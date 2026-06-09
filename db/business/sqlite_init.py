# db/business/sqlite_init.py
"""
SQLite 业务数据库初始化模块

根据 docs/schema_templates/{template_id}/schema.yaml 动态生成并创建：
  - controlled_vocabulary  枚举值表
  - paper                  论文主表
  - paper_entity_record    对象记录表
  - entity_component       组成模块表
  - record_function        功能结论表
  - function_assay_evidence 证据表
  - document_asset         文件资产追踪表（辅助）
  - rag_document_reference RAGFlow 引用表（辅助）
  - workflow_extraction_call 抽取任务记录表（辅助）
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# 项目根目录：db/business/sqlite_init.py → db/business → db → 项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_DIR   = _PROJECT_ROOT / "docs" / "schema_templates"


# ─────────────────────────────────────────────────────────────────────────────
# SQLite 类型映射
# ─────────────────────────────────────────────────────────────────────────────

_TYPE_MAP: dict[str, str] = {
    "string":       "TEXT",
    "text":         "TEXT",
    "enum":         "TEXT",
    "list[string]": "TEXT",   # JSON 编码存储
    "json":         "TEXT",   # JSON 编码存储
    "integer":      "INTEGER",
    "boolean":      "INTEGER",  # 0/1
    "float":        "REAL",
}


# ─────────────────────────────────────────────────────────────────────────────
# 辅助表 DDL（不在 schema.yaml 中，手动维护）
# ─────────────────────────────────────────────────────────────────────────────

_AUX_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS document_asset (
    asset_id         TEXT PRIMARY KEY,
    paper_key        TEXT NOT NULL,
    extraction_profile TEXT,
    pdf_path         TEXT,
    file_sha256      TEXT,
    file_size_bytes  INTEGER,
    source_url       TEXT,
    download_status  TEXT,
    downloaded_at    TEXT,
    run_id           TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rag_document_reference (
    rag_ref_id       TEXT PRIMARY KEY,
    paper_key        TEXT NOT NULL,
    document_id      TEXT,
    knowledge_base_id TEXT,
    ragflow_status   TEXT,
    chunk_count      INTEGER,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workflow_extraction_call (
    call_id          TEXT PRIMARY KEY,
    run_id           TEXT,
    paper_key        TEXT,
    template_id      TEXT,
    csv_dir          TEXT,
    status           TEXT,
    tables_written   TEXT,   -- JSON 编码
    error_message    TEXT,
    called_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ─────────────────────────────────────────────────────────────────────────────
# schema.yaml 解析
# ─────────────────────────────────────────────────────────────────────────────

def _load_schema(template_id: str) -> dict[str, Any]:
    """加载指定模板的 schema.yaml。"""
    schema_path = _SCHEMA_DIR / template_id / "schema.yaml"
    if not schema_path.exists():
        raise FileNotFoundError(f"schema.yaml 未找到：{schema_path}")
    with schema_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _sqlite_type(field_def: dict) -> str:
    return _TYPE_MAP.get(field_def.get("type", "string"), "TEXT")


def _build_table_ddl(table_name: str, table_def: dict, pk: str) -> str:
    """将逻辑表定义转换为 SQLite CREATE TABLE 语句。"""
    cols: list[str] = []
    fields: dict = table_def.get("fields", {})

    for col_name, field in fields.items():
        sqlite_type = _sqlite_type(field)
        col_def     = f"    {col_name} {sqlite_type}"
        if col_name == pk:
            col_def += " PRIMARY KEY"
        if field.get("required") and col_name != pk:
            col_def += " NOT NULL"
        cols.append(col_def)

    # 所有主表加时间戳列
    cols.append("    created_at TEXT NOT NULL DEFAULT (datetime('now'))")
    cols.append("    updated_at TEXT")

    cols_str = ",\n".join(cols)
    return f"CREATE TABLE IF NOT EXISTS {table_name} (\n{cols_str}\n);"


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

def init_sqlite_business_db(
    template_id: str = "hap_peptide_v1",
    db_path: str | None = None,
    data_root: str | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    """
    根据 schema.yaml 初始化 SQLite 业务数据库。

    Args:
        template_id:  提取模板 ID，决定加载哪个 schema.yaml（默认 hap_peptide_v1）。
        db_path:      数据库文件路径；None 时自动推导为
                      {data_root}/projects/{template_id}/db/business.sqlite。
        data_root:    数据根目录；None 时取环境变量 DATA_ROOT 或项目根的 data/。
        reset:        True 时删除已有数据库文件重建。

    Returns:
        {
          status:          "ok" / "error",
          db_path:         实际数据库路径,
          template_id:     使用的模板 ID,
          tables_created:  创建的表名列表,
          vocab_count:     写入枚举值条数,
          already_existed: 数据库文件在 reset=False 时是否已存在,
        }
    """
    import os

    # ── 1. 确定数据库路径 ────────────────────────────────────────────────────
    if db_path is None:
        root = data_root or os.getenv("DATA_ROOT") or str(_PROJECT_ROOT / "data")
        db_path = str(Path(root) / "projects" / template_id / "db" / "business.sqlite")

    db_file = Path(db_path)
    already_existed = db_file.exists()

    if reset and already_existed:
        db_file.unlink()
        already_existed = False

    db_file.parent.mkdir(parents=True, exist_ok=True)

    # ── 2. 加载 schema ───────────────────────────────────────────────────────
    try:
        schema = _load_schema(template_id)
    except Exception as e:
        return {"status": "error", "error": str(e), "db_path": db_path}

    enum_groups:    dict = schema.get("enum_groups", {})
    logical_tables: dict = schema.get("logical_tables", {})

    # ── 3. 建表 ──────────────────────────────────────────────────────────────
    tables_created: list[str] = []
    vocab_count    = 0

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

        # controlled_vocabulary
        conn.execute("""
CREATE TABLE IF NOT EXISTS controlled_vocabulary (
    cv_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL,
    value      TEXT NOT NULL,
    UNIQUE(group_name, value)
);""")
        tables_created.append("controlled_vocabulary")

        # 写入枚举值（INSERT OR IGNORE 幂等）
        for group_name, values in enum_groups.items():
            for v in (values or []):
                conn.execute(
                    "INSERT OR IGNORE INTO controlled_vocabulary(group_name, value) VALUES(?,?)",
                    (group_name, str(v)),
                )
                vocab_count += 1

        # 5 张逻辑主表
        for table_name, table_def in logical_tables.items():
            pk  = table_def.get("primary_key", f"{table_name}_id")
            ddl = _build_table_ddl(table_name, table_def, pk)
            conn.execute(ddl)
            tables_created.append(table_name)

        # 3 张辅助表
        conn.executescript(_AUX_TABLES_DDL)
        tables_created += ["document_asset", "rag_document_reference", "workflow_extraction_call"]

        conn.commit()

    return {
        "status":         "ok",
        "db_path":        db_path,
        "template_id":    template_id,
        "tables_created": tables_created,
        "vocab_count":    vocab_count,
        "already_existed": already_existed,
    }
