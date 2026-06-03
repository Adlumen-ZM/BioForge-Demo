"""
postgres_backend.py — Trace PostgreSQL 写入后端

位置：backend/src/db_access/trace/postgres_backend.py
职责：实现 TraceBackend.write()，将 TraceEvent 持久化到 agent_trace_events 表。

安全性原则：
  write() 永不抛异常——try/except 包裹整体，失败只 print 警告，保证主流程不受影响。

依赖：
  - sqlalchemy>=2.0（Core，不用 ORM）
  - psycopg[binary]>=3.1 或 psycopg2-binary（通过 TRACE_DB_URL 连接串区分，由环境变量提供）

环境变量：
  TRACE_DB_URL — PostgreSQL 连接串，与 LANGGRAPH_CHECKPOINT_DB_URL 同实例同库：
    格式：postgresql+psycopg://user:password@host:port/dbname   （psycopg3）
       或 postgresql://user:password@host:port/dbname            （psycopg2，sqlalchemy 2.x 默认驱动）
  若未设置，write() 静默跳过（不写入，不报错）。

使用方式（在 template_agent.py 或各 agent 的 agent.py 中）：
    from backend.src.db_access.trace.postgres_backend import PostgresBackend
    # 方式 1：在 AgentTemplate 构造后直接替换 backend
    agent = AgentTemplate(config)
    agent.hook.backend = PostgresBackend()

    # 方式 2：在 run_minimal_agent.py 中条件切换
    import os
    backend = PostgresBackend() if os.getenv("TRACE_DB_URL") else NullBackend()
    agent.hook.backend = backend

前提：agent_trace_events 表已存在（由 db/trace/schema.sql 或 db/init/02_trace.sql 创建）。

扩展点：
  - 批量写入：改为 buffer 模式，积累到 N 条再 executemany（高吞吐场景）。
  - 异步写入：改用 create_async_engine + asyncpg，在异步 pipeline 中使用。
  - 连接池调整：get_trace_engine() 中增加 pool_size / max_overflow 参数。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# TraceBackend 和 TraceEvent 来自 agent_template/hooks.py
# 避免循环依赖：db_access → agents（单向依赖，不会循环）
from backend.src.agents.agent_template.hooks import TraceBackend, TraceEvent


# ─────────────────────────────────────────────
# Engine 工厂（模块级缓存，避免重复建连接池）
# ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_trace_engine() -> Optional[Engine]:
    """获取（或创建）指向 trace DB 的 SQLAlchemy Engine。

    从 TRACE_DB_URL 环境变量读取连接串。
    使用 @lru_cache 保证整个进程内只创建一次连接池。

    Returns:
        Engine 实例；若 TRACE_DB_URL 未设置则返回 None（静默跳过）。
    """
    url = os.getenv("TRACE_DB_URL")
    if not url:
        print("[PostgresBackend] ⚠️ TRACE_DB_URL 未设置，trace 写入已禁用（退回 NullBackend 行为）。")
        return None
    try:
        engine = create_engine(
            url,
            pool_pre_ping=True,   # 每次获取连接前 ping，自动处理断连
            pool_size=3,          # 小连接池，trace 写入非高频
            max_overflow=5,
        )
        return engine
    except Exception as exc:
        print(f"[PostgresBackend] ⚠️ 创建 Engine 失败，trace 写入已禁用：{exc}")
        return None


# ─────────────────────────────────────────────
# PostgresBackend — TraceBackend 实现
# ─────────────────────────────────────────────

class PostgresBackend(TraceBackend):
    """将 TraceEvent 写入 PostgreSQL 的 agent_trace_events 表。

    使用 SQLAlchemy Core text() + named params，禁止字符串拼接（防 SQL 注入）。
    write() 永不抛异常，trace 失败只 print 警告，主流程不受影响。

    示例：
        backend = PostgresBackend()
        agent.hook.backend = backend

    注意：需提前建表（db/trace/schema.sql 或 db/init/02_trace.sql）。
    """

    _INSERT_SQL = text("""
        INSERT INTO agent_trace_events
            (run_id, agent_run_id, stage, event_type, step_id,
             status, duration_ms, payload, created_at)
        VALUES
            (:run_id, :agent_run_id, :stage, :event_type, :step_id,
             :status, :duration_ms, :payload, :created_at)
    """)

    def write(self, event: TraceEvent) -> None:
        """将单条 TraceEvent 持久化到 agent_trace_events 表。

        Args:
            event: 待写入的 TraceEvent。

        安全保证：
            任何异常（DB 连接失败、表不存在、字段类型错误等）均被捕获，
            只 print 警告行，不向调用方传播。
        """
        try:
            engine = get_trace_engine()
            if engine is None:
                # TRACE_DB_URL 未设置，静默跳过（已在 get_trace_engine 中打印一次警告）
                return

            # 将 payload dict 序列化为 JSON 字符串（Postgres JSONB 列）
            payload_json: Optional[str] = None
            if event.payload:
                payload_json = json.dumps(event.payload, ensure_ascii=False, default=str)

            with engine.begin() as conn:
                conn.execute(
                    self._INSERT_SQL,
                    {
                        "run_id": event.run_id,
                        "agent_run_id": event.agent_run_id,
                        "stage": event.stage,
                        "event_type": event.event_type,
                        "step_id": event.step_id,
                        "status": event.status,
                        "duration_ms": event.duration_ms,
                        "payload": payload_json,
                        "created_at": event.timestamp,
                    },
                )
        except Exception as exc:
            # trace 写入失败，只 print 警告，绝不向上传播
            print(
                f"[PostgresBackend] ⚠️ write 失败，已跳过"
                f"（event_type={event.event_type}, stage={event.stage}）：{exc}"
            )
