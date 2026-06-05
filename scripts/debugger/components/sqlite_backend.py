"""
scripts/debugger/components/sqlite_backend.py — SQLite Trace 写入后端

位置：scripts/debugger/components/
依赖：sqlalchemy>=2.0（已在 requirements.txt）、pathlib（标准库）
      backend/src/agents/agent_template/hooks.py（TraceBackend, TraceEvent）
职责：实现 TraceBackend.write()，将 TraceEvent 写入本地 SQLite 文件。
      首次调用 get_sqlite_engine() 时自动建表，无需提前初始化 schema。

与 PostgresBackend 的主要差异：
  - 不需要 Docker / 独立 DB 服务
  - TRACE_DB_URL 格式：sqlite:///data/traces.db（三斜杠=相对项目根路径）
  - payload 列类型：TEXT（JSON 字符串），无 JSONB
  - created_at 列类型：TEXT（ISO 8601 字符串）
  - 使用 NullPool + check_same_thread=False（SQLite 不支持连接池）

路径解析规则：
  sqlite:///data/traces.db   → 相对项目根目录（三斜杠），自动转绝对路径
  sqlite:////abs/path/db     → 绝对路径（四斜杠），直接使用

使用方式（.env 中配置）：
    TRACE_DB_URL=sqlite:///data/traces.db
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

# ── 路径设置（确保 backend 可被 import）──────────────────────────────────────
_COMPONENTS_DIR = Path(__file__).resolve().parent        # scripts/debugger/components/
_DEBUGGER_DIR   = _COMPONENTS_DIR.parent                 # scripts/debugger/
_SCRIPTS_DIR    = _DEBUGGER_DIR.parent                   # scripts/
_PROJECT_ROOT   = _SCRIPTS_DIR.parent                    # 项目根目录

for _p in [str(_PROJECT_ROOT), str(_SCRIPTS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend.src.agents.agent_template.hooks import TraceBackend, TraceEvent


# ─────────────────────────────────────────────
# 路径解析
# ─────────────────────────────────────────────

def _resolve_sqlite_url(url: str) -> str:
    """sqlite:///相对路径 → sqlite:///绝对路径（相对项目根）。
    sqlite:////绝对路径（四斜杠）直接返回，不修改。
    """
    if url.startswith("sqlite:////"):
        # 已是绝对路径，直接使用
        return url
    # 三斜杠：取后面的相对路径，相对项目根解析
    rel = url[len("sqlite:///"):]
    abs_path = _PROJECT_ROOT / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{abs_path}"


# ─────────────────────────────────────────────
# 建表 DDL（与 schema.sql 逻辑等价，SQLite 方言）
# ─────────────────────────────────────────────

# SQLite 不支持在一次 execute 中执行多条语句，逐条执行
_DDL_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS agent_trace_events (
        id           INTEGER  PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT     NOT NULL,
        agent_run_id TEXT,
        stage        TEXT     NOT NULL,
        event_type   TEXT     NOT NULL,
        step_id      TEXT,
        status       TEXT,
        duration_ms  REAL,
        payload      TEXT,
        created_at   TEXT     NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_run_id    ON agent_trace_events(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_trace_agent_run ON agent_trace_events(agent_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_trace_stage_ts  ON agent_trace_events(stage, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_trace_type      ON agent_trace_events(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_trace_status    ON agent_trace_events(status)",
]


# ─────────────────────────────────────────────
# Engine 工厂（模块级缓存）
# ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_sqlite_engine() -> Optional[Engine]:
    """获取 SQLite Engine，首次调用时自动建表。

    从 TRACE_DB_URL 读取连接串，若前缀不是 sqlite 则返回 None。
    使用 @lru_cache 保证整个进程内只创建一次连接。

    Returns:
        Engine 实例；URL 前缀不是 sqlite 时返回 None。
    """
    url = os.getenv("TRACE_DB_URL", "")
    if not url.startswith("sqlite"):
        return None

    resolved_url = _resolve_sqlite_url(url)
    try:
        engine = create_engine(
            resolved_url,
            connect_args={"check_same_thread": False},  # 允许多线程（Streamlit + 后台线程）
            poolclass=NullPool,                          # SQLite 不支持连接池
        )
        # 建表（幂等，已有表不会重建）
        with engine.begin() as conn:
            for stmt in _DDL_STATEMENTS:
                conn.execute(text(stmt))
        print(f"[SQLiteBackend] ✅ 已连接 SQLite，DB 路径：{resolved_url[len('sqlite:///'):] }")
        return engine
    except Exception as exc:
        print(f"[SQLiteBackend] ⚠️ 创建 Engine 失败，trace 写入已禁用：{exc}")
        return None


# ─────────────────────────────────────────────
# SQLiteBackend — TraceBackend 实现
# ─────────────────────────────────────────────

class SQLiteBackend(TraceBackend):
    """将 TraceEvent 写入本地 SQLite 文件的 agent_trace_events 表。

    接口与 PostgresBackend 完全相同，可无缝替换。
    write() 永不抛异常，失败只 print 警告，主流程不受影响。

    示例：
        backend = SQLiteBackend()
        agent.hook.backend = backend
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

        安全保证：任何异常均被捕获，只 print 警告，不向调用方传播。
        """
        try:
            engine = get_sqlite_engine()
            if engine is None:
                return

            # payload → JSON 字符串（SQLite 无 JSONB 类型）
            payload_json: Optional[str] = None
            if event.payload:
                payload_json = json.dumps(event.payload, ensure_ascii=False, default=str)

            # created_at → ISO 8601 字符串（SQLite 无 TIMESTAMPTZ 类型）
            if event.timestamp is not None:
                created_at_str = event.timestamp.isoformat()
            else:
                created_at_str = datetime.now(tz=timezone.utc).isoformat()

            with engine.begin() as conn:
                conn.execute(self._INSERT_SQL, {
                    "run_id":       event.run_id,
                    "agent_run_id": event.agent_run_id,
                    "stage":        event.stage,
                    "event_type":   event.event_type,
                    "step_id":      event.step_id,
                    "status":       event.status,
                    "duration_ms":  event.duration_ms,
                    "payload":      payload_json,
                    "created_at":   created_at_str,
                })
        except Exception as exc:
            print(
                f"[SQLiteBackend] ⚠️ write 失败，已跳过"
                f"（event_type={event.event_type}, stage={event.stage}）：{exc}"
            )
