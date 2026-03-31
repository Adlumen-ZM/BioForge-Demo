import sqlite3
import os

# 业务数据库路径，优先读取环境变量，默认写入 data/ 目录
BIZ_DB_PATH = os.getenv('BIZ_DB_PATH', 'data/hap_v01.db')


def init_biz_database():
    """一键初始化业务数据库 hap_v01.db。

    包含建表和建索引全部操作，使用 CREATE TABLE IF NOT EXISTS，
    可重复执行而不会破坏已有数据。
    与 Trace 数据库的初始化脚本（init_trace_db.py）分开，两者独立执行。
    """
    os.makedirs(os.path.dirname(BIZ_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(BIZ_DB_PATH)
    # 开启外键约束（SQLite 默认关闭）
    conn.execute('PRAGMA foreign_keys = ON;')
    # WAL 模式：提升并发读写性能，减少锁竞争
    conn.execute('PRAGMA journal_mode = WAL;')
    _create_tables(conn)
    _create_indexes(conn)
    conn.commit()
    conn.close()
    print(f'业务数据库已初始化：{BIZ_DB_PATH}')


def _create_tables(conn):
    """创建业务数据库的两张核心表:

    表一 paper_record_v01_min：论文级主表，每篇论文一条记录。
    表二 function_assay_evidence_v01_min：FAE 子表，每条功能实验证据一条记录，
    通过 record_id 外键关联主表，ON DELETE CASCADE 保证级联删除。
    """
    # ── 主表：paper_record_v01_min ──────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_record_v01_min (
            paper_id                TEXT PRIMARY KEY,   -- 论文唯一标识，格式 P000001
            record_id               TEXT UNIQUE NOT NULL, -- 对象级记录编号，格式 P000001-R01
            extraction_run_id       TEXT NOT NULL,      -- 关联 hap_trace.db extraction_runs.run_id
            doi                     TEXT NOT NULL,      -- 论文 DOI，全局唯一标识符
            pmid                    TEXT,               -- PubMed ID，预印本可能为 null
            title                   TEXT NOT NULL,      -- 论文完整标题，原文字面量
            journal_title           TEXT NOT NULL,      -- 期刊名称，原文字面量
            publication_year        INTEGER NOT NULL,   -- 发表年份，4 位整数
            entity_name_raw         TEXT NOT NULL,      -- 原文对象名，直接从论文抽取，不标准化
            entity_name_normalized  TEXT NOT NULL,      -- 标准化名称，v0.1 采用序列作为标准化名
            sequence_raw            TEXT NOT NULL,      -- 原始氨基酸序列，单字母缩写，原文字面量
            interaction_target      TEXT NOT NULL,      -- 肽段主要作用对象，枚举值
            summary_functions       TEXT NOT NULL,      -- 功能标签集合，分号分隔字符串
            evidence_overall_level  TEXT NOT NULL,      -- 总体证据层级，反映最高层级，枚举值
            model_system_summary    TEXT NOT NULL,      -- 摘要层模型说明，简短描述实验体系
            text_to_sequence        TEXT NOT NULL,      -- 序列来源定位，章节锚点格式
            text_to_function_summary TEXT NOT NULL,     -- 功能来源定位，判断依据出处
            text_to_evidence_summary TEXT NOT NULL,     -- 证据来源定位，可包含多个锚点
            trace_status            TEXT NOT NULL,      -- 溯源状态，枚举值
            curator_note            TEXT,               -- 人工备注，LLM 抽取阶段可为 null
            created_at              TEXT DEFAULT (datetime('now'))  -- 记录创建时间，自动写入
        )
    """)

    # ── 子表：function_assay_evidence_v01_min（FAE）────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS function_assay_evidence_v01_min (
            fae_id              TEXT PRIMARY KEY,  -- 子表记录编号，格式 P000001-R01-FAE01
            record_id           TEXT NOT NULL,     -- 关联主表 record_id，外键
            function_label      TEXT NOT NULL,     -- 本条记录对应的功能标签，枚举值
            evidence_level      TEXT NOT NULL,     -- 本条记录的证据层级，枚举值
            assay_category      TEXT NOT NULL,     -- 一级实验类别，枚举值
            validation_method   TEXT NOT NULL,     -- 标准化方法名称，优先使用白名单
            readout_main        TEXT,              -- 主要测量指标，可为 null
            result_text_summary TEXT NOT NULL,     -- 结果短摘要，1-2 句话描述关键发现
            text_to_evidence    TEXT NOT NULL,     -- 本条证据的来源定位，章节锚点格式
            trace_status        TEXT NOT NULL,     -- 溯源状态，枚举值
            created_at          TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (record_id)
                REFERENCES paper_record_v01_min(record_id)
                ON DELETE CASCADE   -- 删除主表记录时，对应 FAE 子记录自动级联删除
        )
    """)


def _create_indexes(conn):
    """创建查询优化索引

    idx_pr_extraction_run：支持从 run_id 反向查找业务记录（跨库溯源）。
    idx_fae_record_id    ：支持按 record_id 快速聚合 FAE 子记录。
    """
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_pr_extraction_run '
        'ON paper_record_v01_min(extraction_run_id)'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_fae_record_id '
        'ON function_assay_evidence_v01_min(record_id)'
    )


if __name__ == '__main__':
    init_biz_database()
