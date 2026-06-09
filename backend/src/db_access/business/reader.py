# backend/src/db_access/business/reader.py
"""
业务数据库读取接口

提供两类读取能力：
  1. get_rag_extraction_contract() — 给 RAG 工具 / 抽取 Agent 使用的表结构合约
  2. get_paper_context()           — 查询文献在业务库中的当前状态
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
_SCHEMA_DIR   = _PROJECT_ROOT / "docs" / "schema_templates"


# ─────────────────────────────────────────────────────────────────────────────
# RAG 工具 / 抽取 Agent 需要的合约
# ─────────────────────────────────────────────────────────────────────────────

def get_rag_extraction_contract(
    template_id: str = "hap_peptide_v1",
) -> dict[str, Any]:
    """
    解析 schema.yaml，返回 RAG 工具可识别的 CSV 表结构合约。

    RAG 工具凭此合约知道：
      - 要输出哪些 CSV 文件（csv_tables）
      - 每个 CSV 的字段名
      - 哪些字段为必填
      - 哪些字段是枚举、枚举值有哪些
      - 每个字段的类型

    Returns:
        {
          template_id,
          csv_tables: {
            table_name: {
              filename,
              primary_key,
              fields: [str, ...],
              required_fields: [str, ...],
              enum_fields: {field: [values]},
              field_types: {field: type_str},
            }
          },
          enum_groups: {group_name: [values]},
        }
    """
    import yaml

    schema_path = _SCHEMA_DIR / template_id / "schema.yaml"
    if not schema_path.exists():
        raise FileNotFoundError(f"schema.yaml 未找到：{schema_path}")

    with schema_path.open(encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    enum_groups:    dict = schema.get("enum_groups", {})
    logical_tables: dict = schema.get("logical_tables", {})

    csv_tables: dict[str, Any] = {}

    for table_name, table_def in logical_tables.items():
        fields_def: dict = table_def.get("fields", {})
        pk = table_def.get("primary_key", f"{table_name}_id")

        field_names:    list[str]       = list(fields_def.keys())
        required_fields: list[str]      = [
            f for f, d in fields_def.items()
            if d.get("required") is True
        ]
        enum_fields: dict[str, list]    = {}
        field_types:  dict[str, str]    = {}

        for fname, fdef in fields_def.items():
            ftype = fdef.get("type", "string")
            field_types[fname] = ftype
            if ftype == "enum":
                group_key = fdef.get("enum", fname)
                enum_fields[fname] = enum_groups.get(group_key, [])

        csv_tables[table_name] = {
            "filename":       f"{table_name}.csv",
            "primary_key":    pk,
            "fields":         field_names,
            "required_fields": required_fields,
            "enum_fields":    enum_fields,
            "field_types":    field_types,
        }

    return {
        "template_id": template_id,
        "csv_tables":  csv_tables,
        "enum_groups": enum_groups,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 文献上下文查询
# ─────────────────────────────────────────────────────────────────────────────

def get_paper_context(
    paper_key: str | None = None,
    doi: str | None = None,
    pmid: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    查询文献在业务库中的当前状态（是否已存在、是否已抽取等）。

    用途：node 判断是否跳过重复抽取。

    Returns:
        {
          exists:           文献主记录是否存在,
          paper_id:         paper_id（如存在）,
          paper_key:        paper_key（如存在）,
          has_pdf:          document_asset 中是否有已下载 PDF,
          has_rag_csv:      rag_document_reference 中是否有 RAG 记录,
          has_extraction:   paper_entity_record 中是否有抽取记录,
          record_count:     paper_entity_record 行数,
          last_extraction_run: 最近抽取的 run_id,
        }
    """
    resolved_path = db_path or os.getenv("BIZ_DB_PATH") or ""
    if not resolved_path or not Path(resolved_path).exists():
        return {"exists": False, "reason": "数据库文件不存在", "db_path": resolved_path}

    conn = sqlite3.connect(resolved_path)
    conn.row_factory = sqlite3.Row

    try:
        paper_id = None

        # 根据 doi / pmid 查 paper_id
        if doi:
            row = conn.execute(
                "SELECT paper_id FROM paper WHERE doi = ? LIMIT 1", (doi,)
            ).fetchone()
            if row:
                paper_id = row["paper_id"]

        if not paper_id and pmid:
            row = conn.execute(
                "SELECT paper_id FROM paper WHERE pmid = ? LIMIT 1", (pmid,)
            ).fetchone()
            if row:
                paper_id = row["paper_id"]

        if not paper_id:
            return {
                "exists":            False,
                "paper_id":          None,
                "paper_key":         paper_key,
                "has_pdf":           False,
                "has_rag_csv":       False,
                "has_extraction":    False,
                "record_count":      0,
                "last_extraction_run": None,
            }

        # 查 PDF 资产
        has_pdf_row = conn.execute(
            "SELECT 1 FROM document_asset WHERE paper_key = ? AND download_status = 'downloaded' LIMIT 1",
            (paper_key or "",),
        ).fetchone()

        # 查 RAG 引用
        has_rag_row = conn.execute(
            "SELECT 1 FROM rag_document_reference WHERE paper_key = ? LIMIT 1",
            (paper_key or "",),
        ).fetchone()

        # 查抽取记录
        record_count = conn.execute(
            "SELECT COUNT(*) FROM paper_entity_record WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()[0]

        # 最近抽取任务
        last_run_row = conn.execute(
            "SELECT run_id FROM workflow_extraction_call WHERE paper_key = ? ORDER BY called_at DESC LIMIT 1",
            (paper_key or "",),
        ).fetchone()

        return {
            "exists":            True,
            "paper_id":          paper_id,
            "paper_key":         paper_key,
            "has_pdf":           has_pdf_row is not None,
            "has_rag_csv":       has_rag_row is not None,
            "has_extraction":    record_count > 0,
            "record_count":      record_count,
            "last_extraction_run": last_run_row["run_id"] if last_run_row else None,
        }

    finally:
        conn.close()
