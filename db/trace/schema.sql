-- agent_trace_events — BioForge Trace MVP DDL
--
-- 单表 append-only，记录 AgentTemplate 和 Pipeline 两层的所有 trace 事件。
-- 通过 event_type 和 stage 区分事件来源：
--   event_type IN ('plan_start','step_start','step_end','plan_end')  → AgentTemplate 层（TraceHook）
--   event_type IN ('pipeline_start','node_start','node_end','pipeline_end') → Pipeline 层（PipelineTraceHook）
--
-- 两级 run_id 设计：
--   run_id       — pipeline 级别 ID（由 graph 层生成），独立调试时与 agent_run_id 相同
--   agent_run_id — agent 级别 ID（TemplateAgentState.run_id，格式 "run_<12hex>"）
--
-- 注意：event_type 使用 VARCHAR 而非 ENUM，便于后续扩展无需 migrate。
--
-- 使用方式：
--   docker exec -i <db_container> psql -U bioforge -d bioforge < db/trace/schema.sql
--   或由 db/init/02_trace.sql 在 Docker 首次启动时自动执行。

CREATE TABLE IF NOT EXISTS agent_trace_events (
    id           BIGSERIAL        PRIMARY KEY,
    run_id       VARCHAR(64)      NOT NULL,
    agent_run_id VARCHAR(64),
    stage        VARCHAR(128)     NOT NULL,
    event_type   VARCHAR(64)      NOT NULL,
    step_id      VARCHAR(128),
    status       VARCHAR(32),
    duration_ms  DOUBLE PRECISION,
    payload      JSONB,
    created_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

-- 按 pipeline run_id 查询全部事件（最常用查询路径）
CREATE INDEX IF NOT EXISTS idx_trace_run_id    ON agent_trace_events(run_id);

-- 按 agent run_id 查询单次 agent 执行的事件（独立调试常用）
CREATE INDEX IF NOT EXISTS idx_trace_agent_run ON agent_trace_events(agent_run_id);

-- 按 stage 分组看时序（监控各 agent/节点的执行情况）
CREATE INDEX IF NOT EXISTS idx_trace_stage_ts  ON agent_trace_events(stage, created_at DESC);

-- 按 event_type 聚合统计（如统计 plan_end 数量）
CREATE INDEX IF NOT EXISTS idx_trace_type      ON agent_trace_events(event_type);

-- 快速定位失败事件（只对有值的行建索引，减少索引大小）
CREATE INDEX IF NOT EXISTS idx_trace_status    ON agent_trace_events(status) WHERE status IS NOT NULL;
