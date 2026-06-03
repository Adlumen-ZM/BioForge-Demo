# Trace 数据库说明

BioForge Trace MVP 使用单张 append-only 表 `agent_trace_events` 记录所有运行轨迹，
覆盖 AgentTemplate 层（step 级别）和 Pipeline 层（node 级别）两种事件。

---

## 表结构

```sql
CREATE TABLE agent_trace_events (
    id           BIGSERIAL        PRIMARY KEY,
    run_id       VARCHAR(64)      NOT NULL,    -- pipeline 级别 run_id
    agent_run_id VARCHAR(64),                  -- agent 级别 run_id（"run_<12hex>"）
    stage        VARCHAR(128)     NOT NULL,    -- 如 "search_agent" / "search_node" / "pipeline"
    event_type   VARCHAR(64)      NOT NULL,    -- 见下方事件类型说明
    step_id      VARCHAR(128),                 -- step_start/step_end 事件填写
    status       VARCHAR(32),                  -- success / failed / skipped / running
    duration_ms  DOUBLE PRECISION,             -- step_end / plan_end / node_end 事件填写
    payload      JSONB,                        -- 结构化事件载荷
    created_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);
```

DDL 文件：`db/trace/schema.sql`（同内容也内联在 `db/init/02_trace.sql`）

---

## 事件类型（event_type）

| 类型 | 来源 | 说明 |
|------|------|------|
| `plan_start` | TraceHook | agent plan 开始执行 |
| `step_start` | TraceHook | 某个 step 开始 |
| `step_end` | TraceHook | 某个 step 结束（含 duration_ms） |
| `plan_end` | TraceHook | agent plan 执行完毕 |
| `pipeline_start` | PipelineTraceHook | 整个 pipeline 开始（graph invoke 前） |
| `node_start` | PipelineTraceHook | 某个 graph node 开始（如 search_node） |
| `node_end` | PipelineTraceHook | 某个 graph node 结束 |
| `pipeline_end` | PipelineTraceHook | 整个 pipeline 结束 |

---

## 两级 run_id 设计

```
pipeline run_id ("pipe_<hex>")
    ├─ search_node → agent_run_id ("run_<hex>") → step events
    ├─ screen_node → agent_run_id ("run_<hex>") → step events
    └─ extract_node → agent_run_id ("run_<hex>") → step events
```

- 独立调试（不走 pipeline）时，`run_id` = `agent_run_id`（自动 fallback）
- 有 pipeline 时，`run_id` 由 graph 层生成并传入所有 agent

---

## 初始化方式

### Docker 首次启动（自动）

`db/init/02_trace.sql` 会在 Docker 首次启动时自动执行（与 `01_init.sql` 顺序执行）。

### 手动建表

```bash
docker exec -i <db_container> psql -U bioforge -d bioforge < db/trace/schema.sql
```

---

## 代码入口

| 模块 | 用途 |
|------|------|
| `backend/src/agents/agent_template/hooks.py` | `TraceEvent` / `TraceBackend` / `NullBackend` / `TraceHook` |
| `backend/src/db_access/trace/postgres_backend.py` | `PostgresBackend`（写入）、`get_trace_engine()` |
| `backend/src/db_access/trace/reader.py` | `get_run_events()` / `get_run_summary()` / `get_recent_failed_steps()` |
| `backend/src/db_access/trace/pipeline_hook.py` | `PipelineTraceHook`（graph 层使用） |

---

## 查询示例

```sql
-- 查看某次 pipeline run 的完整轨迹
SELECT stage, event_type, step_id, status, duration_ms, created_at
FROM agent_trace_events
WHERE run_id = 'pipe_smoke_0001'
ORDER BY created_at;

-- 统计各 stage 总耗时
SELECT stage, SUM(duration_ms) as total_ms
FROM agent_trace_events
WHERE run_id = 'pipe_smoke_0001' AND duration_ms IS NOT NULL
GROUP BY stage;

-- 查找最近失败的 step
SELECT run_id, stage, step_id, payload->>'error_message' as error, created_at
FROM agent_trace_events
WHERE status = 'failed' AND event_type = 'step_end'
ORDER BY created_at DESC
LIMIT 20;
```

---

## 环境变量

```env
# 与 LANGGRAPH_CHECKPOINT_DB_URL 同实例同库
TRACE_DB_URL=postgresql://bioforge:your_password_here@localhost:5432/bioforge
```

若未设置 `TRACE_DB_URL`，`PostgresBackend` 自动退回为 `NullBackend`（只 print，不写 DB）。
