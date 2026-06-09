# Trace 日志 README

## 定位

Trace 记录 Agent 的运行过程，回答“结果怎么来的”。

## 文件

```text
backend/src/db_access/trace/trace_manager.py
backend/src/db_access/trace/file_backend.py
backend/src/db_access/trace/postgres_backend.py
backend/src/agents/agent_template/hooks.py
db/trace/schema.sql
```

## 输出

```text
data/runs/YYYYMMDD/run_xxx/trace/events.jsonl
data/runs/YYYYMMDD/run_xxx/operator_debug/*.jsonl
```

## 事件字段

```python
run_id, agent_run_id, stage, event_type, step_id, status, duration_ms, payload, created_at
```

## 典型事件

`plan_start/step_start/step_end/step_replanned/plan_end/node_started/node_finished/tool_call`。

## PostgreSQL

配置 `TRACE_DB_URL=postgresql+psycopg://...` 后可写入 `agent_trace_events`。
