"""
pipeline_hook.py — Pipeline 级别 Trace Hook

位置：backend/src/db_access/trace/pipeline_hook.py
职责：为 LangGraph graph 层各节点（search_node/screen_node/extract_node）
     记录 pipeline_start/node_start/node_end/pipeline_end 事件，
     写入与 TraceHook 相同的 agent_trace_events 表（同一 run_id 下可关联查询）。

与 TraceHook 的关系：
  - 两者复用同一套 TraceEvent + TraceBackend 基础设施（来自 agent_template/hooks.py）
  - TraceHook 由 PlanRunner 调用（step 级别，stage = agent_name，如 "search_agent"）
  - PipelineTraceHook 由 graph 层调用（node/pipeline 级别，stage = node_name 或 "pipeline"）
  - 同一次 pipeline run 中，两层事件共享同一 run_id，可在 DB 中完整关联

注意：
  本类不自动接入 graph/pipeline.py（属编排负责人域）。
  编排负责人根据需要将本 Hook 注入 pipeline.py 中的各 node 函数。

使用方式（编排负责人参考）：
    from backend.src.db_access.trace.pipeline_hook import PipelineTraceHook
    from backend.src.db_access.trace.postgres_backend import PostgresBackend

    # 在 pipeline.py 的 graph node 函数外层创建 hook（或注入为依赖）
    hook = PipelineTraceHook(run_id="pipe_abc123", backend=PostgresBackend())

    # pipeline 入口（如 graph invoke 前）
    hook.on_pipeline_start()

    # 各 node 包装（以 search_node 为例）
    hook.on_node_start("search_node")
    state_patch = search_agent.run(
        pipeline_state=state,
        run_id=hook.run_id,          # ← 将 pipeline run_id 传给 AgentTemplate
    )
    hook.on_node_end(
        "search_node",
        status="success",
        agent_run_id=search_agent.last_run_id,  # ← 记录 agent 内部 run_id
    )

    # pipeline 结束
    hook.on_pipeline_end(status="success")

    # 查询验证
    from backend.src.db_access.trace.reader import get_run_events
    from backend.src.db_access.trace.postgres_backend import get_trace_engine
    events = get_run_events(get_trace_engine(), run_id="pipe_abc123")

扩展点：
  - 自动计时：可在 on_node_start 记录 start_time，on_node_end 自动计算 duration_ms（参考 TraceHook 实现）
  - 异步版本：创建 AsyncPipelineTraceHook，用 async/await 包装 write() 调用
  - 多后端：将 backend 换为 MultiBackend([PostgresBackend(), LangfuseBackend()])
"""

from __future__ import annotations

import time
from typing import Any, Optional

from backend.src.agents.agent_template.hooks import NullBackend, TraceBackend, TraceEvent


class PipelineTraceHook:
    """pipeline 级别的 trace 接口，记录节点级别的 trace 事件。

    写入与 TraceHook 相同的 agent_trace_events 表，通过 event_type 和 stage 区分。
    _write() 同样使用 try/except 包裹，pipeline trace 失败不影响主流程。
    """

    def __init__(
        self,
        run_id: str,
        backend: Optional[TraceBackend] = None,
        enabled: bool = True,
    ):
        """
        Args:
            run_id: pipeline 级别 run_id（通常由调用方在 pipeline 入口生成，
                    如 f"pipe_{uuid.uuid4().hex[:12]}"）。
                    此 run_id 同时传给各 AgentTemplate.run(run_id=...)，
                    确保同一 pipeline run 的所有事件共享同一 run_id。
            backend: TraceBackend 实例，默认 NullBackend（只 print，不写 DB）。
                     接入 Postgres：PipelineTraceHook(run_id=..., backend=PostgresBackend())
            enabled: False 时所有方法立即返回。
        """
        self.run_id = run_id
        self.backend: TraceBackend = backend if backend is not None else NullBackend()
        self.enabled = enabled

        # 内部计时：记录每个 node 的 start_time_ms
        self._node_start_times: dict[str, float] = {}
        self._pipeline_start_time_ms: float = 0.0

    # ─────────────────────────────────────────────
    # 四个固定调用点
    # ─────────────────────────────────────────────

    def on_pipeline_start(self, metadata: Optional[dict[str, Any]] = None) -> None:
        """pipeline 开始时调用（graph invoke 前）。

        Args:
            metadata: 可选，pipeline 元数据（如输入参数摘要）。
        """
        if not self.enabled:
            return
        self._pipeline_start_time_ms = _now_ms()
        event = TraceEvent(
            run_id=self.run_id,
            stage="pipeline",
            event_type="pipeline_start",
            status="running",
            payload=metadata or {},
        )
        self._write(event)

    def on_node_start(
        self,
        node_name: str,
        agent_run_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """某个 graph node 开始执行时调用（如 search_node 开始前）。

        Args:
            node_name: LangGraph node 名称（如 "search_node"），对应 stage 列。
            agent_run_id: 可选，若在 node 开始前已知 agent_run_id 则填写（通常留 None）。
            metadata: 可选，节点启动参数摘要。
        """
        if not self.enabled:
            return
        self._node_start_times[node_name] = _now_ms()
        event = TraceEvent(
            run_id=self.run_id,
            agent_run_id=agent_run_id,
            stage=node_name,
            event_type="node_start",
            status="running",
            payload=metadata or {},
        )
        self._write(event)

    def on_node_end(
        self,
        node_name: str,
        status: str,
        agent_run_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """某个 graph node 执行完成时调用（如 search_node 结束后）。

        自动计算 duration_ms（如果先调用了对应的 on_node_start）。

        Args:
            node_name: LangGraph node 名称，与 on_node_start 对应。
            status: 执行结果，合法值 'success' / 'failed' / 'skipped'。
            agent_run_id: agent 内部 run_id（从 agent.last_run_id 获取），
                          填入后可在 DB 中关联 TraceHook 产生的 agent 级别事件。
            metadata: 可选，节点结束时的附加信息（如输出字段数量）。
        """
        if not self.enabled:
            return
        start_ms = self._node_start_times.pop(node_name, _now_ms())
        duration_ms = round(_now_ms() - start_ms, 2)
        event = TraceEvent(
            run_id=self.run_id,
            agent_run_id=agent_run_id,
            stage=node_name,
            event_type="node_end",
            status=status,
            duration_ms=duration_ms,
            payload=metadata or {},
        )
        self._write(event)

    def on_pipeline_end(
        self,
        status: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """pipeline 完全结束时调用（graph invoke 后）。

        自动计算整体 duration_ms。

        Args:
            status: 整体 pipeline 状态，合法值 'success' / 'failed' / 'partial'。
            metadata: 可选，最终输出摘要（如各阶段产出的文献数量）。
        """
        if not self.enabled:
            return
        duration_ms = round(_now_ms() - self._pipeline_start_time_ms, 2)
        event = TraceEvent(
            run_id=self.run_id,
            stage="pipeline",
            event_type="pipeline_end",
            status=status,
            duration_ms=duration_ms,
            payload=metadata or {},
        )
        self._write(event)

    # ─────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────

    def _write(self, event: TraceEvent) -> None:
        """将事件写入后端。try/except 保证 trace 失败绝不影响主流程。"""
        try:
            self.backend.write(event)
        except Exception as e:
            print(f"[PipelineTraceHook] ⚠️ 写入 trace 失败（event_type={event.event_type}）：{e}")


def _now_ms() -> float:
    """返回当前时间的毫秒时间戳（monotonic clock，用于 duration 计算）。"""
    return time.monotonic() * 1000
