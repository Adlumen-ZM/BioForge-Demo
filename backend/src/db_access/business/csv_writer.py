# backend/src/db_access/business/csv_writer.py
"""
CSV → SQLite 写入接口

把 RAG 工具输出的多表 CSV 写入业务 SQLite 数据库。
支持幂等 upsert（INSERT OR REPLACE），不因重复运行崩溃。
"""

import csv
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[5]

# 标准 5 张逻辑主表，按外键依赖顺序排列（父表先于子表）
_MAIN_TABLES = [
    "paper",
    "paper_entity_record",
    "entity_component",
    "record_function",
    "function_assay_evidence",
]


def _resolve_db_path(db_path: str | None, extraction_profile: str) -> str:
    """推导数据库文件路径。"""
    if db_path:
        return db_path
    env_path = os.getenv("BIZ_DB_PATH")
    if env_path:
        return env_path
    root = os.getenv("DATA_ROOT") or str(_PROJECT_ROOT / "data")
    return str(Path(root) / "projects" / extraction_profile / "db" / "business.sqlite")


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """查询 SQLite 表的实际列名（不含 rowid）。"""
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1] for row in rows]


def _load_csv(csv_path: Path) -> list[dict]:
    """加载 CSV 文件，返回行字典列表。"""
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _write_table(
    conn: sqlite3.Connection,
    table_name: str,
    rows: list[dict],
    overwrite: bool = False,
) -> tuple[int, list[str]]:
    """
    将 CSV 行写入指定表，只写数据库中已有的列。

    overwrite=False → INSERT OR IGNORE（主键已存在则跳过）
    overwrite=True  → INSERT OR REPLACE（覆盖旧行）

    Returns:
        (写入行数, 错误列表)
    """
    if not rows:
        return 0, []

    db_cols    = set(_get_table_columns(conn, table_name))
    valid_cols = [c for c in rows[0].keys() if c in db_cols]

    if not valid_cols:
        return 0, [f"{table_name}: CSV 列名与数据库列名无交集"]

    placeholders = ", ".join("?" * len(valid_cols))
    col_names    = ", ".join(valid_cols)
    conflict     = "OR REPLACE" if overwrite else "OR IGNORE"
    sql          = f"INSERT {conflict} INTO {table_name} ({col_names}) VALUES ({placeholders})"

    written = 0
    errors: list[str] = []

    for row in rows:
        try:
            values = [row.get(c) or None for c in valid_cols]
            conn.execute(sql, values)
            written += 1
        except Exception as e:
            errors.append(f"{table_name} 行写入失败: {e}")

    return written, errors


def write_rag_csv_to_business_db(
    csv_dir: str,
    db_path: str | None = None,
    template_id: str = "hap_peptide_v1",
    extraction_profile: str | None = None,
    run_id: str | None = None,
    paper_key: str | None = None,
    source_pdf_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    读取 RAG 输出的多表 CSV，写入 SQLite 业务数据库。

    CSV 目录应包含（按需）：
      paper.csv / paper_entity_record.csv / entity_component.csv /
      record_function.csv / function_assay_evidence.csv

    Args:
        csv_dir:           RAG 输出的 CSV 文件夹路径。
        db_path:           数据库路径；None 时自动推导。
        template_id:       模板 ID，用于路径推导。
        extraction_profile: 提取配置名；None 时与 template_id 相同。
        run_id:            当前 pipeline run_id，写入 workflow_extraction_call。
        paper_key:         文献 paper_key，写入 workflow_extraction_call。
        source_pdf_path:   PDF 路径，写入 workflow_extraction_call。
        overwrite:         保留字段，当前 INSERT OR REPLACE 已覆盖旧值。

    Returns:
        {
          status:         "ok" / "error",
          db_path:        数据库路径,
          tables_written: {table_name: row_count},
          skipped_tables: [表名（CSV 不存在时跳过）],
          errors:         [错误信息],
        }
    """
    profile = extraction_profile or template_id
    resolved_db = _resolve_db_path(db_path, profile)

    if not Path(resolved_db).exists():
        return {
            "status": "error",
            "error":  f"数据库文件不存在，请先调用 ensure_business_db(): {resolved_db}",
        }

    csv_dir_path    = Path(csv_dir)
    tables_written: dict[str, int] = {}
    skipped_tables: list[str]      = []
    all_errors:     list[str]      = []

    try:
        with sqlite3.connect(resolved_db) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")

            for table_name in _MAIN_TABLES:
                csv_file = csv_dir_path / f"{table_name}.csv"
                if not csv_file.exists():
                    skipped_tables.append(table_name)
                    continue

                rows = _load_csv(csv_file)
                written, errs = _write_table(conn, table_name, rows, overwrite=overwrite)
                tables_written[table_name] = written
                all_errors.extend(errs)

            # 写入 workflow_extraction_call 追踪记录
            _write_workflow_call(
                conn=conn,
                run_id=run_id,
                paper_key=paper_key,
                template_id=template_id,
                csv_dir=csv_dir,
                tables_written=tables_written,
                errors=all_errors,
            )

            conn.commit()

    except Exception as e:
        return {
            "status": "error",
            "db_path": resolved_db,
            "error":  str(e),
        }

    return {
        "status":         "ok",
        "db_path":        resolved_db,
        "tables_written": tables_written,
        "skipped_tables": skipped_tables,
        "errors":         all_errors,
    }


def _write_workflow_call(
    conn: sqlite3.Connection,
    run_id: str | None,
    paper_key: str | None,
    template_id: str,
    csv_dir: str,
    tables_written: dict,
    errors: list,
) -> None:
    """记录本次写入任务到 workflow_extraction_call 表。"""
    call_id = str(uuid.uuid4())
    status  = "ok" if not errors else "partial"
    try:
        conn.execute(
            """
INSERT INTO workflow_extraction_call
    (call_id, run_id, paper_key, template_id, csv_dir, status, tables_written, error_message)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""",
            (
                call_id,
                run_id or "",
                paper_key or "",
                template_id,
                csv_dir,
                status,
                json.dumps(tables_written, ensure_ascii=False),
                "; ".join(errors) if errors else None,
            ),
        )
    except Exception:
        pass  # 追踪记录写失败不影响主流程
