# db_access/trace — Trace 层说明

BioForge Trace MVP 实现，将 AgentTemplate 和 Pipeline 两层的运行轨迹持久化到 PostgreSQL。

---

## 模块结构

```
backend/src/db_access/trace/
├── postgres_backend.py   ← PostgresBackend（写入，永不抛异常）
├── reader.py             ← 3 个只读查询函数（调试用，可抛异常）
└── pipeline_hook.py      ← PipelineTraceHook（graph 层节点 trace）
```

核心数据结构（TraceEvent / TraceBackend / NullBackend / TraceHook）位于：
`backend/src/agents/agent_template/hooks.py`

---

## 快速接入

### 1. AgentTemplate 层：切换为 PostgresBackend

```python
from backend.src.db_access.trace.postgres_backend import PostgresBackend

agent = create_search_agent(...)
agent.hook.backend = PostgresBackend()  # 替换默认的 NullBackend
state_patch = agent.run(pipeline_state={}, run_id="pipe_001")
```

### 2. Pipeline 层：使用 PipelineTraceHook（编排负责人）

```python
from backend.src.db_access.trace.pipeline_hook import PipelineTraceHook
from backend.src.db_access.trace.postgres_backend import PostgresBackend

hook = PipelineTraceHook(run_id="pipe_001", backend=PostgresBackend())
hook.on_pipeline_start()

hook.on_node_start("search_node")
state_patch = search_agent.run(pipeline_state=state, run_id=hook.run_id)
hook.on_node_end("search_node", status="success", agent_run_id=search_agent.last_run_id)

hook.on_pipeline_end(status="success")
```

### 3. 读取 trace 数据（调试）

```python
from backend.src.db_access.trace.postgres_backend import get_trace_engine
from backend.src.db_access.trace.reader import get_run_events, get_run_summary

engine = get_trace_engine()
events = get_run_events(engine, run_id="pipe_001")
summary = get_run_summary(engine, run_id="pipe_001")
```

---

## 环境变量

```env
TRACE_DB_URL=postgresql://bioforge:password@localhost:5432/bioforge
```

`TRACE_DB_URL` 与 `LANGGRAPH_CHECKPOINT_DB_URL` 同实例同库。
若未设置，`PostgresBackend` 自动退回 NullBackend（只 print，不写 DB）。

---

## 表结构

见 `db/trace/README.md` 或 `db/trace/schema.sql`。

---

## ⚠️ 旧版 trace（已废弃）

`trace_logger.py` 和 `init_trace_db.py` 已标注 DEPRECATED，不再使用。
新 trace 系统通过 `hooks.py` Sink 模式实现，与旧 SQLite trace 完全独立。
