-- 02_trace.sql — Trace MVP 表初始化
--
-- Docker 首次启动（docker-compose up）时，PostgreSQL 会按文件名顺序执行
-- /docker-entrypoint-initdb.d/ 下的 .sql 文件，本文件紧接 01_init.sql 执行。
--
-- 内联 DDL（而非 \i 引用）以确保跨平台兼容性（Windows/Linux Docker 路径差异）。
-- 如需手动重建 trace 表，也可直接执行 db/trace/schema.sql：
--   docker exec -i <db_container> psql -U bioforge -d bioforge < db/trace/schema.sql

-- agent_trace_events — BioForge Trace MVP 主表
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

CREATE INDEX IF NOT EXISTS idx_trace_run_id    ON agent_trace_events(run_id);
CREATE INDEX IF NOT EXISTS idx_trace_agent_run ON agent_trace_events(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_trace_stage_ts  ON agent_trace_events(stage, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trace_type      ON agent_trace_events(event_type);
CREATE INDEX IF NOT EXISTS idx_trace_status    ON agent_trace_events(status) WHERE status IS NOT NULL;
