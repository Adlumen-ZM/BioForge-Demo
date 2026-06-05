"""
scripts/debugger/components/trace_reader.py — Streamlit 版 trace 查询封装

位置：scripts/debugger/components/
依赖：backend/src/db_access/trace/reader.py（零改动，只 import）
      backend/src/db_access/trace/postgres_backend.py（get_trace_engine）
      streamlit（st.cache_resource / st.cache_data）
职责：封装 reader.py 的三个查询函数，加 Streamlit 缓存层（TTL=30s）；
      提供 list_recent_runs() 等专为 UI 设计的便捷查询。

使用方式（Streamlit 页面中）：
    from components.trace_reader import (
        get_engine,
        cached_get_run_events,
        cached_get_run_summary,
        list_recent_runs,
    )

    engine = get_engine()
    events = cached_get_run_events("run_abc123")
    summary = cached_get_run_summary("run_abc123")
    runs = list_recent_runs(stage="search_agent", limit=20)

注意：
  - get_engine() 使用 @st.cache_resource（跨 session 共享连接池）
  - 查询函数使用 @st.cache_data(ttl=30)（30s 内不重复查 DB）
  - 若 TRACE_DB_URL 未配置，get_engine() 返回 None，所有查询返回空结果
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st


# ─────────────────────────────────────────────
# Engine 连接（缓存，跨 session 共享）
# ─────────────────────────────────────────────

@st.cache_resource(show_spinner="连接 trace DB...")
def get_engine():
    """获取 SQLAlchemy Engine（跨 session 共享连接池）。

    根据 TRACE_DB_URL 前缀自动选择后端：
      - sqlite:///...   → SQLiteBackend（本地开发，无需 Docker）
      - postgresql://...→ PostgresBackend（生产/CI）
      - 未配置          → None（只打印，不落盘）

    Returns:
        SQLAlchemy Engine 实例，或 None（TRACE_DB_URL 未配置时）。
    """
    url = os.getenv("TRACE_DB_URL", "")
    if not url:
        return None
    try:
        if url.startswith("sqlite"):
            from components.sqlite_backend import get_sqlite_engine
            return get_sqlite_engine()
        else:
            from backend.src.db_access.trace.postgres_backend import get_trace_engine
            return get_trace_engine()
    except Exception as e:
        st.warning(f"连接 trace DB 失败：{e}。请检查 TRACE_DB_URL 配置。")
        return None


# ─────────────────────────────────────────────
# 带缓存的查询函数（TTL=30s）
# ─────────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def cached_get_run_events(run_id: str) -> list[dict[str, Any]]:
    """获取指定 run_id 的全部 trace 事件（按 created_at 升序）。

    Args:
        run_id: pipeline 级别 run_id。

    Returns:
        list[dict]，每个 dict 对应一行 agent_trace_events 记录。
        TRACE_DB_URL 未配置时返回 []。
    """
    engine = get_engine()
    if engine is None:
        return []
    try:
        from backend.src.db_access.trace.reader import get_run_events
        return get_run_events(engine, run_id)
    except Exception as e:
        st.warning(f"查询 run_events 失败：{e}")
        return []


@st.cache_data(ttl=30, show_spinner=False)
def cached_get_run_summary(run_id: str) -> dict[str, Any]:
    """获取指定 run_id 的聚合统计摘要。

    Args:
        run_id: pipeline 级别 run_id。

    Returns:
        dict，包含 event_type_counts / stage_duration_ms / status_counts / total_events。
        TRACE_DB_URL 未配置时返回空 dict。
    """
    engine = get_engine()
    if engine is None:
        return {}
    try:
        from backend.src.db_access.trace.reader import get_run_summary
        return get_run_summary(engine, run_id)
    except Exception as e:
        st.warning(f"查询 run_summary 失败：{e}")
        return {}


@st.cache_data(ttl=30, show_spinner=False)
def cached_get_recent_failed_steps(
    stage: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """获取最近 N 条失败的 step 事件。

    Args:
        stage: 可选 stage 过滤（如 "search_agent"）。None 表示全部 stage。
        limit: 最大返回条数（默认 20）。

    Returns:
        list[dict]，按 created_at 降序排列。TRACE_DB_URL 未配置时返回 []。
    """
    engine = get_engine()
    if engine is None:
        return []
    try:
        from backend.src.db_access.trace.reader import get_recent_failed_steps
        return get_recent_failed_steps(engine, stage=stage, limit=limit)
    except Exception as e:
        st.warning(f"查询 failed_steps 失败：{e}")
        return []


# ─────────────────────────────────────────────
# UI 专用便捷查询
# ─────────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def list_recent_runs(
    stage: str | None = None,
    status_filter: str | None = None,
    time_range_hours: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """查询最近的完整 run 列表（用于 01_runs.py 运行历史页面）。

    每条记录来自一个 plan_end 事件（代表一次完整的 agent run）。

    Args:
        stage: 按 stage 过滤（如 "search_agent"、"test_agent"）。None 不过滤。
        status_filter: 按状态过滤（"success"、"failed"、"partial"）。None 不过滤。
        time_range_hours: 只查最近 N 小时内的运行。None 不过滤。
        limit: 最大返回条数（默认 50）。

    Returns:
        list[dict]，每个 dict 包含：
            run_id / agent_run_id / stage / status / duration_ms / created_at
        按 created_at 降序排列。
    """
    engine = get_engine()
    if engine is None:
        return []

    try:
        from sqlalchemy import text as sa_text

        # 动态构建 WHERE 子句
        conditions = ["event_type = 'plan_end'"]
        params: dict[str, Any] = {"limit": limit}

        if stage:
            conditions.append("stage = :stage")
            params["stage"] = stage

        if status_filter:
            conditions.append("status = :status")
            params["status"] = status_filter

        if time_range_hours:
            _url = os.getenv("TRACE_DB_URL", "")
            if _url.startswith("sqlite"):
                # SQLite 方言：datetime() 函数，hours 是受控整数，无注入风险
                conditions.append(f"created_at >= datetime('now', '-{int(time_range_hours)} hours')")
            else:
                # PostgreSQL 方言：用命名参数避免字符串拼接
                conditions.append("created_at >= NOW() - :hours * INTERVAL '1 hour'")
                params["hours"] = time_range_hours

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT run_id, agent_run_id, stage, status, duration_ms, created_at
            FROM agent_trace_events
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit
        """

        with engine.connect() as conn:
            rows = conn.execute(sa_text(sql), params).fetchall()

        return [
            {
                "run_id": row[0],
                "agent_run_id": row[1],
                "stage": row[2],
                "status": row[3],
                "duration_ms": row[4],
                "created_at": str(row[5]),
            }
            for row in rows
        ]
    except Exception as e:
        st.warning(f"查询运行历史失败：{e}")
        return []


def get_step_events_for_run(run_id: str) -> list[dict[str, Any]]:
    """获取指定 run 的所有 step_end 事件（用于 step 级别详情显示）。

    Args:
        run_id: pipeline 级别 run_id。

    Returns:
        list[dict]，只包含 step_end 事件，按 created_at 升序。
    """
    all_events = cached_get_run_events(run_id)
    return [ev for ev in all_events if ev.get("event_type") == "step_end"]
