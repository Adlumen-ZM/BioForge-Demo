"""
trace_manager.py — Trace 统一管理器

位置：backend/src/db_access/trace/
职责：
  - 提供模块级单例（set_manager / get_manager / record）
  - TraceManager：构建 trace event，分发到所有 sink
  - 封装 run_dir 计算（data/runs/YYYYMMDD/{run_id}/）
  - 保证 trace 失败不影响主流程

与现有 TraceHook 的关系（Option B）：
  hooks.py 的 TraceHook._write() 将同时路由到 trace_manager.record()，
  实现框架级事件（plan_start/step_end 等）也进入新 Trace 系统。
  两者字段名有差异，在路由时做字段映射。

使用方式：
  # app.py 中初始化
  from backend.src.db_access.trace.trace_manager import TraceManager, set_manager
  manager = TraceManager.create(run_id=session.run_id)
  set_manager(manager)

  # 任意模块中记录
  from backend.src.db_access.trace.trace_manager import record
  record("search_query_built", stage="search_node", payload={"query": q})

  # pipeline_view 中读取 CLI 日志
  manager.cli_log_buffer  # list[str]，Live panel 读此 buffer
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .event_types import GUIDE_ONLY_EVENTS

# ─────────────────────────────────────────────────────────────────────────────
# 模块级单例
# ─────────────────────────────────────────────────────────────────────────────

_manager: "TraceManager | None" = None


def get_manager() -> "TraceManager | None":
    """获取当前 TraceManager 单例（未初始化时返回 None）。"""
    return _manager


def set_manager(manager: "TraceManager") -> None:
    """设置当前 TraceManager 单例，由 app.py 在 session 初始化后调用。"""
    global _manager
    _manager = manager


def record(event_type: str, **kwargs) -> None:
    """便捷函数：向当前 manager 发送事件。manager 未初始化时静默跳过。"""
    if _manager is not None:
        _manager.record(event_type, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# run_dir 计算
# ─────────────────────────────────────────────────────────────────────────────

def make_run_dir(run_id: str, data_root: str | None = None) -> Path:
    """构造 trace 存储目录：{data_root}/YYYYMMDD/{run_id}/

    run_id 格式保持 run_{hex8}（与 CLISession 一致）。
    目录路径带日期前缀，便于按日期归档查看。

    Args:
        run_id:    CLISession 生成的 run_id（格式 "run_{hex8}"）。
        data_root: trace 根目录，默认读取 TRACE_DATA_ROOT 环境变量或 data/runs。

    Returns:
        Path，trace 存储目录（未创建）。
    """
    if data_root is None:
        data_root = os.getenv("TRACE_DATA_ROOT", "data/runs")
    date_str = date.today().strftime("%Y%m%d")
    return Path(data_root) / date_str / run_id


# ─────────────────────────────────────────────────────────────────────────────
# TraceManager
# ─────────────────────────────────────────────────────────────────────────────

class TraceManager:
    """Trace 统一管理器，负责构建事件并分发到各 sink。

    Attributes:
        run_id:          当前 pipeline run_id（格式 "run_{hex8}"）。
        run_dir:         trace 文件存储目录（data/runs/YYYYMMDD/{run_id}/）。
        project_id:      项目标识（默认 "hap_peptide"）。
        extraction_profile: 抽取配置（默认 "hap_peptide_v1"）。
        cli_log_buffer:  共享 buffer，pipeline_view 的 rich.Live 从此读取日志行。
    """

    def __init__(
        self,
        run_id:             str,
        run_dir:            Path,
        project_id:         str = "hap_peptide",
        extraction_profile: str = "hap_peptide_v1",
    ):
        self.run_id             = run_id
        self.run_dir            = run_dir
        self.project_id         = project_id
        self.extraction_profile = extraction_profile
        self._started_at        = datetime.now(timezone.utc)
        self._sinks: list       = []

        # 共享 buffer，供 pipeline_view 的 rich.Live 读取日志行（最近 N 条）
        self.cli_log_buffer: list[str] = []

    @classmethod
    def create(
        cls,
        run_id:             str,
        project_id:         str = "hap_peptide",
        extraction_profile: str = "hap_peptide_v1",
        data_root:          str | None = None,
        cli_level:          str = "normal",
    ) -> "TraceManager":
        """工厂方法：创建 TraceManager 并自动附加标准 sink。

        自动根据环境变量决定开启哪些 sink：
          TRACE_FILE_ENABLED=true  → FileJsonlSink
          TRACE_CLI_ENABLED=true   → CLIConsoleSink（写到 manager.cli_log_buffer）
          TRACE_ENABLED=false      → 所有 sink 禁用，返回空 manager

        Args:
            run_id:             CLISession 生成的 run_id。
            project_id:         项目标识。
            extraction_profile: 抽取配置 ID。
            data_root:          trace 根目录，None 时读 TRACE_DATA_ROOT。
            cli_level:          CLI 日志级别（quiet/normal/debug）。

        Returns:
            已配置好 sink 的 TraceManager 实例。
        """
        run_dir = make_run_dir(run_id, data_root)
        manager = cls(run_id, run_dir, project_id, extraction_profile)

        trace_enabled = os.getenv("TRACE_ENABLED", "true").lower() != "false"
        if not trace_enabled:
            return manager

        # ── FileJsonlSink ───────────────────────────────────────────────────
        if os.getenv("TRACE_FILE_ENABLED", "true").lower() != "false":
            try:
                from .file_backend import FileJsonlSink
                max_chars = int(os.getenv("TRACE_MAX_PAYLOAD_CHARS", "4000"))
                manager.add_sink(FileJsonlSink(run_dir, max_payload_chars=max_chars))
            except Exception as e:
                print(f"[TraceManager] ⚠️ FileJsonlSink 初始化失败：{e}")

        # ── CLIConsoleSink ───────────────────────────────────────────────────
        if os.getenv("TRACE_CLI_ENABLED", "true").lower() != "false":
            try:
                from .console_backend import CLIConsoleSink
                level = os.getenv("TRACE_CLI_LEVEL", cli_level)
                manager.add_sink(CLIConsoleSink(manager.cli_log_buffer, level=level))
            except Exception as e:
                print(f"[TraceManager] ⚠️ CLIConsoleSink 初始化失败：{e}")

        return manager

    def add_sink(self, sink: Any) -> None:
        """添加一个 sink（FileJsonlSink / CLIConsoleSink / OperatorDebugSink）。"""
        self._sinks.append(sink)

    def record(
        self,
        event_type:   str,
        stage:        str        = "",
        status:       str        = "success",
        payload:      dict | None = None,
        duration_ms:  float | None = None,
        agent_name:   str        = "",
        step_id:      str        = "",
        node_name:    str        = "",
        artifact_refs: list | None = None,
        thread_id:    str        = "",
        **extra,
    ) -> None:
        """记录一个 trace 事件，分发到所有 sink。

        任何 sink 失败时打印警告，不影响主流程。

        Args:
            event_type:    事件类型（见 TraceEventType 常量）。
            stage:         所属阶段（如 "search_node"、"guide_node"）。
            status:        事件状态（success / warning / failed / running）。
            payload:       结构化摘要 dict（不应超过 TRACE_MAX_PAYLOAD_CHARS）。
            duration_ms:   耗时（毫秒），调用方负责计时。
            agent_name:    产生事件的 Agent 名称。
            step_id:       若来自 AgentTemplate step，记录 step_id。
            node_name:     若来自 LangGraph node，记录 node 名称。
            artifact_refs: 指向本地文件的路径引用列表。
            thread_id:     LangGraph thread_id，用于 interrupt/resume 关联。
        """
        event = {
            "event_id":           uuid.uuid4().hex[:16],
            "run_id":             self.run_id,
            "thread_id":          thread_id,
            "project_id":         self.project_id,
            "extraction_profile": self.extraction_profile,
            "stage":              stage,
            "event_type":         event_type,
            "status":             status,
            "timestamp":          datetime.now(timezone.utc).isoformat(),
            "duration_ms":        duration_ms,
            "agent_name":         agent_name,
            "step_id":            step_id,
            "node_name":          node_name,
            "payload":            payload or {},
            "artifact_refs":      artifact_refs or [],
        }

        for sink in self._sinks:
            try:
                sink.write(event)
            except Exception as e:
                print(f"[TraceManager] ⚠️ sink 写入失败（{type(sink).__name__}）：{e}")

    def close(self) -> None:
        """关闭所有 sink（写完 events.jsonl 后调用）。"""
        for sink in self._sinks:
            try:
                if hasattr(sink, "close"):
                    sink.close()
            except Exception:
                pass
