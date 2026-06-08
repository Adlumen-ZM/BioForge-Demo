"""
backend/src/cli/system_check.py — 启动时环境检测

位置：backend/src/cli/
依赖：os（环境变量）、pathlib（文件系统检测）
      backend.src.db_access.trace.postgres_backend（get_trace_engine 探测 TraceDB）
职责：在 CLI 启动时检测关键组件的可用性，结果用于 banner 的状态显示。

检测项（共5项，任何失败都不崩溃）：
  LLM        — 检查 API Key 环境变量（MINIMAX/OPENAI/ANTHROPIC 等）
  TraceDB    — 调用 get_trace_engine() 探测 Trace 数据库连接
  BizDB      — 检查业务数据库配置（DATABASE_URL 或 BIZ_DB_PATH）
  Mode       — 读取 GRAPH_AGENT_MODE 环境变量（不判断对错，只显示当前值）
  Checkpoint — 检查 data/ 目录是否存在且可写（interrupt resume 的 checkpointer 依赖）

与 banner 的关系：
  run_system_check() 返回 list[dict]，每项 {name, status, detail}，
  app.print_banner() 读取结果并用 rich 渲染对应颜色的状态行。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def run_system_check() -> list[dict[str, Any]]:
    """运行所有环境检测项，返回结果列表。

    任何单项检测的异常都被捕获为 warn（不影响其他项的检测，不崩溃）。

    Returns:
        list[dict]，每项包含：
          name   — 检测项名称（如 "LLM"）
          status — "ok" / "warn" / "error"
          detail — 简短说明（如 key 名 + 前6位掩码、版本信息等）
    """
    results = []

    # ── 1. LLM API Key 检测 ──────────────────────────────────────────────────
    # 检查常见 LLM 供应商的 API Key 环境变量，任一非空即为 ok
    try:
        llm_keys = {
            "MINIMAX_API_KEY":    os.getenv("MINIMAX_API_KEY"),
            "OPENAI_API_KEY":     os.getenv("OPENAI_API_KEY"),
            "ANTHROPIC_API_KEY":  os.getenv("ANTHROPIC_API_KEY"),
        }
        found_keys = {k: v for k, v in llm_keys.items() if v}

        if found_keys:
            # 找到至少一个 key，显示 key 名和前6位（不暴露完整 key）
            key_name, key_val = next(iter(found_keys.items()))
            masked = f"{key_val[:6]}***" if len(key_val) > 6 else "***"
            # 同时读取 DEFAULT_LLM_MODEL 显示当前默认模型
            default_model = os.getenv("DEFAULT_LLM_MODEL", "未配置")
            detail = f"{key_name}={masked}  ·  模型={default_model}"
            results.append({"name": "LLM", "status": "ok", "detail": detail})
        else:
            results.append({
                "name":   "LLM",
                "status": "warn",
                "detail": "未找到 API Key（MINIMAX/OPENAI/ANTHROPIC），LLM 调用将失败",
            })
    except Exception as e:
        # LLM 检测异常不崩溃
        results.append({"name": "LLM", "status": "warn", "detail": f"检测异常：{e}"})

    # ── 2. Trace DB 检测 ─────────────────────────────────────────────────────
    # 调用 get_trace_engine() 探测，非 None 表示连接配置正常
    try:
        from backend.src.db_access.trace.postgres_backend import get_trace_engine
        engine = get_trace_engine()
        if engine is not None:
            trace_url = os.getenv("TRACE_DB_URL", "")
            # 从 URL 里提取 DB 类型（sqlite/postgresql 等），不显示完整连接串
            db_type = trace_url.split("://")[0] if "://" in trace_url else "unknown"
            results.append({
                "name":   "TraceDB",
                "status": "ok",
                "detail": f"{db_type}  (TRACE_DB_URL)",
            })
        else:
            results.append({
                "name":   "TraceDB",
                "status": "warn",
                "detail": "TRACE_DB_URL 未配置，运行历史不会落库",
            })
    except Exception as e:
        results.append({"name": "TraceDB", "status": "warn", "detail": f"检测异常：{e}"})

    # ── 3. 业务 DB 检测 ──────────────────────────────────────────────────────
    # DATABASE_URL 或 BIZ_DB_PATH 任一存在即为 ok
    try:
        db_url  = os.getenv("DATABASE_URL")
        biz_path = os.getenv("BIZ_DB_PATH")

        if db_url:
            db_type = db_url.split("://")[0] if "://" in db_url else "unknown"
            results.append({
                "name":   "BizDB",
                "status": "ok",
                "detail": f"{db_type}  (DATABASE_URL)",
            })
        elif biz_path:
            # 检查文件是否存在
            exists = Path(biz_path).exists()
            results.append({
                "name":   "BizDB",
                "status": "ok" if exists else "warn",
                "detail": f"SQLite  {biz_path}{'（文件存在）' if exists else '（文件未找到）'}",
            })
        else:
            results.append({
                "name":   "BizDB",
                "status": "warn",
                "detail": "DATABASE_URL 和 BIZ_DB_PATH 均未配置，业务数据无法持久化",
            })
    except Exception as e:
        results.append({"name": "BizDB", "status": "warn", "detail": f"检测异常：{e}"})

    # ── 4. 运行模式检测 ──────────────────────────────────────────────────────
    # 读取 GRAPH_AGENT_MODE，只显示值，不判断对错（任何值都是 ok）
    try:
        mode = os.getenv("GRAPH_AGENT_MODE", "mock")
        results.append({
            "name":   "Mode",
            "status": "ok",
            "detail": f"{mode}  (GRAPH_AGENT_MODE)",
        })
    except Exception as e:
        results.append({"name": "Mode", "status": "warn", "detail": f"检测异常：{e}"})

    # ── 5. Checkpointer 目录检测 ─────────────────────────────────────────────
    # data/ 目录存在且可写，checkpointer（SqliteSaver）才能正常工作
    try:
        data_dir = Path("data")
        if data_dir.exists() and data_dir.is_dir():
            # 尝试写入一个临时文件验证可写性
            test_file = data_dir / ".write_test"
            try:
                test_file.write_text("ok")
                test_file.unlink()  # 立即删除测试文件
                results.append({
                    "name":   "Checkpoint",
                    "status": "ok",
                    "detail": f"data/  (可写，SqliteSaver 可用)",
                })
            except OSError:
                results.append({
                    "name":   "Checkpoint",
                    "status": "warn",
                    "detail": "data/ 目录存在但不可写，interrupt resume 功能受限",
                })
        else:
            # data/ 目录不存在，尝试创建
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
                results.append({
                    "name":   "Checkpoint",
                    "status": "ok",
                    "detail": "data/  (已自动创建，SqliteSaver 可用)",
                })
            except OSError:
                results.append({
                    "name":   "Checkpoint",
                    "status": "warn",
                    "detail": "data/ 目录不存在且无法创建，interrupt resume 功能不可用",
                })
    except Exception as e:
        results.append({"name": "Checkpoint", "status": "warn", "detail": f"检测异常：{e}"})

    return results
