"""
⚠️  DEPRECATED — 此文件已废弃，不应在新代码中 import。

旧实现：初始化 SQLite hap_trace.db，创建 extraction_runs / trace_steps 双表。

新实现：Trace 基于 Sink 模式事件流，见 backend/src/agents/agent_template/hooks.py。
新设计不依赖 SQLite，当前使用 NullBackend（只 print 不写入）；
未来接 Postgres 时，在 db_access/trace/ 下新建 postgres_backend.py 实现 TraceBackend 接口。
"""

import os
import sqlite3

# Trace 数据库路径，优先读取环境变量，默认写入 data/ 目录
TRACE_DB_PATH = os.getenv('TRACE_DB_PATH', 'data/hap_trace.db')


def init_trace_database():
    """一键初始化 Trace 数据库 hap_trace.db。

    包含建表和建索引全部操作，使用 CREATE TABLE IF NOT EXISTS，
    可重复执行而不会破坏已有数据。
    与业务数据库的初始化脚本（init_biz_db.py）分开，两者独立执行。
    """
    os.makedirs(os.path.dirname(TRACE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(TRACE_DB_PATH)
    # 开启外键约束（SQLite 默认关闭）
    conn.execute('PRAGMA foreign_keys = ON;')
    # WAL 模式：提升并发读写性能，减少 Trace 高频写入对数据库的锁竞争
    conn.execute('PRAGMA journal_mode = WAL;')
    _create_tables(conn)
    _create_indexes(conn)
    conn.commit()
    conn.close()
    print(f'Trace 数据库已初始化：{TRACE_DB_PATH}')


def _create_tables(conn):
    """创建 Trace 数据库的两张核心表。

    表一 extraction_runs：任务级表，每篇论文一条记录，记录整体执行结果与 token 汇总。
    表二 trace_steps    ：步骤级表，每次 LLM API 调用一条记录，v0.1 正常情况下一个 run
                          对应一条，v0.2 引入 repair / 分块后一个 run 可能对应多条。
    """
    # ── 表一：extraction_runs ───────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS extraction_runs (
            run_id                  TEXT PRIMARY KEY,  -- 任务唯一标识，格式 run_YYYYMMDD_HHMMSS_xxxxxx
            paper_id                TEXT NOT NULL,     -- 关联业务库 paper_record.paper_id
            model_name              TEXT NOT NULL,     -- 本次任务实际调用的模型名称
            prompt_version          TEXT NOT NULL,     -- System Prompt 版本号
            schema_version          TEXT NOT NULL,     -- 字段字典版本号
            started_at              TEXT,              -- 任务开始时间，ISO 8601 UTC
            finished_at             TEXT,              -- 任务结束时间，finalize() 时写入
            total_input_tokens      INTEGER DEFAULT 0, -- 本 run 所有 steps 的 input_tokens 之和
            total_output_tokens     INTEGER DEFAULT 0, -- 本 run 所有 steps 的 output_tokens 之和
            total_tokens            INTEGER DEFAULT 0, -- total_input + total_output，用于核算成本
            records_extracted       INTEGER DEFAULT 0, -- LLM 输出并通过 Schema 校验的 record 数
            records_inserted        INTEGER DEFAULT 0, -- 实际成功写入业务数据库的 record 数
            integrity_check_status  TEXT,              -- 业务写入后反向校验的结果
            integrity_check_detail  TEXT,              -- 完整性检查失败时的具体原因
            run_status              TEXT NOT NULL DEFAULT 'running', -- 任务整体状态，枚举值
            error_message           TEXT,              -- run 级别顶层错误信息
            created_at              TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── 表二：trace_steps ───────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trace_steps (
            step_id             TEXT PRIMARY KEY,  -- 单次 API 调用唯一标识，格式 run_xxx_step_01
            run_id              TEXT NOT NULL,     -- 关联 extraction_runs.run_id，外键
            step_index          INTEGER NOT NULL,  -- 同一 run 内的步骤序号，从 1 开始
            step_type           TEXT DEFAULT 'extraction', -- 调用类型：extraction / repair
            prompt_system       TEXT,              -- System Prompt 完整内容，不截断
            prompt_user         TEXT,              -- User Prompt 完整内容（含论文全文），不截断
            input_tokens        INTEGER,           -- 本次调用输入 token 数
            raw_response        TEXT,              -- LLM 原始输出，无论解析成功与否都保存
            output_tokens       INTEGER,           -- 本次调用输出 token 数
            parsed_output       TEXT,              -- 解析成功后的结构化输出，JSON 字符串
            llm_reasoning       TEXT,              -- LLM 对核心枚举字段的判断理由，JSON 字符串
            called_at           TEXT,              -- API 调用发起时间，ISO 8601 UTC
            response_at         TEXT,              -- 收到 LLM 响应的时间，ISO 8601 UTC
            response_time_ms    INTEGER,           -- LLM 纯响应时间（毫秒），排除 DB/解析耗时
            model_name          TEXT NOT NULL,     -- 本次 API 调用实际使用的模型名称
            http_status_code    INTEGER,           -- API 返回的 HTTP 状态码
            step_status         TEXT NOT NULL DEFAULT 'processing', -- 步骤状态，枚举值
            error_detail        TEXT,              -- step 级别错误详情，比 run 粒度更细
            created_at          TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (run_id)
                REFERENCES extraction_runs(run_id)
                ON DELETE CASCADE   -- 删除 run 时对应 step 自动级联删除
        )
    """)


def _create_indexes(conn):
    """创建查询优化索引。

    idx_er_paper_id：支持按 paper_id 查找该论文的历史抽取任务。
    idx_ts_run_id  ：支持按 run_id 快速聚合该 run 下的所有 step（finalize 聚合 token 时使用）。
    """
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_er_paper_id ON extraction_runs(paper_id)'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_ts_run_id ON trace_steps(run_id)'
    )


if __name__ == '__main__':
    init_trace_database()
