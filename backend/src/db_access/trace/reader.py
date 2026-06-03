"""
reader.py — Trace 数据读取层

位置：backend/src/db_access/trace/reader.py
职责：提供三个只读查询函数，供调试、监控和回放使用。

与 postgres_backend.py 的区别：
  写入（write）：永不抛异常，trace 失败静默降级。
  读取（read）：允许抛异常——读操作发生在主动 debug 上下文中，失败应显式告知调用方。

依赖：
  - sqlalchemy>=2.0（Core，不用 ORM）
  - 已初始化的 Engine（通过 get_trace_engine() 获取，或调用方自行传入）

典型使用场景：
  1. 排查某次 pipeline run 的完整轨迹（get_run_events）
  2. 快速查看某次 run 的成功/失败统计（get_run_summary）
  3. 监控最近哪些 step 失败了（get_recent_failed_steps）

使用方式：
    from backend.src.db_access.trace.postgres_backend import get_trace_engine
    from backend.src.db_access.trace.reader import get_run_events, get_run_summary

    engine = get_trace_engine()
    events = get_run_events(engine, run_id="pipe_smoke_0001")
    for e in events:
        print(e["event_type"], e["stage"], e["status"], e["duration_ms"])

    summary = get_run_summary(engine, run_id="pipe_smoke_0001")
    print(summary)

注意：调用方需自行处理 engine 为 None 的情况（TRACE_DB_URL 未设置时）。
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine


# ─────────────────────────────────────────────
# 公共查询函数
# ─────────────────────────────────────────────

def get_run_events(engine: Engine, run_id: str) -> list[dict[str, Any]]:
    """获取一次 pipeline run 的全部 trace 事件（按 created_at 升序排列）。

    Args:
        engine: SQLAlchemy Engine（指向 bioforge DB）。
        run_id: pipeline 级别 run_id（对应 agent_trace_events.run_id 列）。

    Returns:
        list of dict，每个 dict 对应一行 trace 记录（不含 id 列）。
        若无匹配记录，返回空列表。

    Raises:
        sqlalchemy.exc.* — DB 连接或查询失败时向上传播（调用方处理）。
    """
    sql = text("""
        SELECT
            run_id,
            agent_run_id,
            stage,
            event_type,
            step_id,
            status,
            duration_ms,
            payload,
            created_at
        FROM agent_trace_events
        WHERE run_id = :run_id
        ORDER BY created_at ASC
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    return [dict(row) for row in rows]


def get_run_summary(engine: Engine, run_id: str) -> dict[str, Any]:
    """聚合统计一次 pipeline run 的整体情况。

    返回信息：
      - 各 event_type 的事件数量
      - 各 stage 的总 duration_ms
      - 各 status 的出现次数
      - 总事件数

    Args:
        engine: SQLAlchemy Engine。
        run_id: pipeline 级别 run_id。

    Returns:
        dict，格式：
        {
            "run_id": str,
            "total_events": int,
            "event_type_counts": {"plan_start": N, "step_start": N, ...},
            "stage_duration_ms": {"search_agent": float, ...},
            "status_counts": {"success": N, "failed": N, ...},
        }

    Raises:
        sqlalchemy.exc.* — DB 连接或查询失败时向上传播。
    """
    # 按 event_type 统计
    sql_type_count = text("""
        SELECT event_type, COUNT(*) AS cnt
        FROM agent_trace_events
        WHERE run_id = :run_id
        GROUP BY event_type
    """)
    # 按 stage 统计总 duration
    sql_stage_dur = text("""
        SELECT stage, SUM(duration_ms) AS total_dur
        FROM agent_trace_events
        WHERE run_id = :run_id AND duration_ms IS NOT NULL
        GROUP BY stage
    """)
    # 按 status 统计
    sql_status = text("""
        SELECT status, COUNT(*) AS cnt
        FROM agent_trace_events
        WHERE run_id = :run_id AND status IS NOT NULL
        GROUP BY status
    """)
    # 总事件数
    sql_total = text("""
        SELECT COUNT(*) AS total FROM agent_trace_events WHERE run_id = :run_id
    """)

    with engine.connect() as conn:
        params = {"run_id": run_id}
        type_rows = conn.execute(sql_type_count, params).mappings().all()
        stage_rows = conn.execute(sql_stage_dur, params).mappings().all()
        status_rows = conn.execute(sql_status, params).mappings().all()
        total = conn.execute(sql_total, params).scalar() or 0

    return {
        "run_id": run_id,
        "total_events": int(total),
        "event_type_counts": {row["event_type"]: int(row["cnt"]) for row in type_rows},
        "stage_duration_ms": {
            row["stage"]: float(row["total_dur"]) if row["total_dur"] is not None else 0.0
            for row in stage_rows
        },
        "status_counts": {row["status"]: int(row["cnt"]) for row in status_rows},
    }


def get_recent_failed_steps(
    engine: Engine,
    stage: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """获取最近 N 条 status='failed' 的 step 事件（排除 plan/pipeline 级事件）。

    用于监控：快速定位哪些 step 在最近频繁失败。

    Args:
        engine: SQLAlchemy Engine。
        stage: 可选，按 stage（如 'search_agent'）过滤；为 None 时返回所有 stage。
        limit: 返回最多 N 条记录，默认 20，上限 500。

    Returns:
        list of dict，按 created_at 降序（最新的在前），每条包含：
        run_id, agent_run_id, stage, event_type, step_id, status, duration_ms, payload, created_at

    Raises:
        ValueError: limit 超出范围时抛出。
        sqlalchemy.exc.* — DB 连接或查询失败时向上传播。
    """
    if not 1 <= limit <= 500:
        raise ValueError(f"limit 必须在 1-500 范围内，当前值：{limit}")

    if stage is not None:
        sql = text("""
            SELECT
                run_id, agent_run_id, stage, event_type, step_id,
                status, duration_ms, payload, created_at
            FROM agent_trace_events
            WHERE status = 'failed'
              AND stage = :stage
              AND event_type IN ('step_end', 'plan_end', 'node_end', 'pipeline_end')
            ORDER BY created_at DESC
            LIMIT :limit
        """)
        params: dict[str, Any] = {"stage": stage, "limit": limit}
    else:
        sql = text("""
            SELECT
                run_id, agent_run_id, stage, event_type, step_id,
                status, duration_ms, payload, created_at
            FROM agent_trace_events
            WHERE status = 'failed'
              AND event_type IN ('step_end', 'plan_end', 'node_end', 'pipeline_end')
            ORDER BY created_at DESC
            LIMIT :limit
        """)
        params = {"limit": limit}

    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    return [dict(row) for row in rows]
