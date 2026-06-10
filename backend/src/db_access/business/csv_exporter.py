# backend/src/db_access/business/csv_exporter.py
"""
SQLite -> CSV export helpers for the business database.

This module is the inverse of csv_writer.py: it exports the current contents of
the standard business tables back into the contract-defined multi-table CSV
layout consumed and produced by the RAG extraction pipeline.
"""

from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .reader import get_rag_extraction_contract

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

_MAIN_TABLES = [
    "paper",
    "paper_entity_record",
    "entity_component",
    "record_function",
    "function_assay_evidence",
]


def _resolve_db_path(db_path: str | None, extraction_profile: str) -> Path:
    if db_path:
        return Path(db_path).expanduser()

    env_path = os.getenv("BIZ_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()

    root = Path(os.getenv("DATA_ROOT") or (_PROJECT_ROOT / "data"))
    return root / "projects" / extraction_profile / "db" / "business.sqlite"


def _default_output_dir(db_path: Path) -> Path:
    db_name = db_path.stem or "business-db"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return _PROJECT_ROOT / "output" / f"{db_name}-{timestamp}"


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    return [row[1] for row in rows]


def _select_rows(
    conn: sqlite3.Connection,
    table_name: str,
    fields: list[str],
    primary_key: str | None,
) -> list[dict[str, Any]]:
    db_columns = set(_get_table_columns(conn, table_name))
    select_exprs = [
        _quote_identifier(field) if field in db_columns else f"NULL AS {_quote_identifier(field)}"
        for field in fields
    ]

    order_by = "rowid"
    if primary_key and primary_key in db_columns:
        order_by = _quote_identifier(primary_key)

    sql = (
        f"SELECT {', '.join(select_exprs)} "
        f"FROM {_quote_identifier(table_name)} "
        f"ORDER BY {order_by}"
    )
    rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def _write_csv(csv_path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def export_business_db_to_csv(
    db_path: str | None = None,
    output_dir: str | None = None,
    template_id: str = "hap_peptide_v1",
    extraction_profile: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Export the business SQLite database to the standard multi-table CSV layout.

    Args:
        db_path: SQLite database path. Defaults to BIZ_DB_PATH, then the profile
            default under data/projects/<profile>/db/business.sqlite.
        output_dir: Destination directory. Defaults to
            output/<db-name>-<YYYYMMDD-HHMMSS> under the repository root.
        template_id: Schema template used to determine CSV fields and filenames.
        extraction_profile: Optional profile used only for default DB path lookup.
        overwrite: Whether to allow writing into an existing non-empty directory.

    Returns:
        A structured export summary suitable for CLI rendering.
    """
    profile = extraction_profile or template_id
    resolved_db = _resolve_db_path(db_path, profile)
    resolved_output = Path(output_dir).expanduser() if output_dir else _default_output_dir(resolved_db)

    if not resolved_db.exists():
        return {
            "status": "error",
            "db_path": str(resolved_db),
            "output_dir": str(resolved_output),
            "error": f"Database file not found: {resolved_db}",
        }

    if resolved_output.exists() and any(resolved_output.iterdir()) and not overwrite:
        return {
            "status": "error",
            "db_path": str(resolved_db),
            "output_dir": str(resolved_output),
            "error": f"Output directory is not empty: {resolved_output}",
        }

    contract = get_rag_extraction_contract(template_id=template_id)
    csv_tables = contract.get("csv_tables", {})

    exported_tables: dict[str, int] = {}
    csv_files: dict[str, str] = {}
    missing_tables: list[str] = []
    errors: list[str] = []

    try:
        resolved_output.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(resolved_db) as conn:
            conn.row_factory = sqlite3.Row

            for table_name in _MAIN_TABLES:
                table_contract = csv_tables.get(table_name, {})
                fields = list(table_contract.get("fields") or [])
                if not fields:
                    errors.append(f"{table_name}: no CSV fields found in schema contract")
                    continue

                filename = table_contract.get("filename") or f"{table_name}.csv"
                csv_path = resolved_output / filename
                primary_key = table_contract.get("primary_key")

                if not _table_exists(conn, table_name):
                    missing_tables.append(table_name)
                    _write_csv(csv_path, fields, [])
                    exported_tables[table_name] = 0
                    csv_files[table_name] = str(csv_path)
                    continue

                rows = _select_rows(conn, table_name, fields, primary_key)
                _write_csv(csv_path, fields, rows)
                exported_tables[table_name] = len(rows)
                csv_files[table_name] = str(csv_path)

    except Exception as exc:
        return {
            "status": "error",
            "db_path": str(resolved_db),
            "output_dir": str(resolved_output),
            "tables_exported": exported_tables,
            "csv_files": csv_files,
            "missing_tables": missing_tables,
            "errors": errors,
            "error": str(exc),
        }

    return {
        "status": "ok" if not errors else "partial",
        "db_path": str(resolved_db),
        "output_dir": str(resolved_output),
        "tables_exported": exported_tables,
        "csv_files": csv_files,
        "missing_tables": missing_tables,
        "errors": errors,
    }
