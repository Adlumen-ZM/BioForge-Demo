# backend/src/tools/rag_paper/template_contract.py
"""
RAG 工具模板合约加载器

读取 schema.yaml，生成 RAG 工具可识别的 CSV 表结构合约。
直接复用 db_access.business.reader.get_rag_extraction_contract() 的解析逻辑。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
_SCHEMA_DIR   = _PROJECT_ROOT / "docs" / "schema_templates"


def load_extraction_contract(
    template_id: str = "hap_peptide_v1",
    schema_template_path: str | None = None,
) -> dict[str, Any]:
    """
    读取 schema.yaml，返回 RAG 工具所需的 CSV 表结构合约。

    Args:
        template_id:          模板 ID，用于定位 schema.yaml。
        schema_template_path: 显式指定 schema.yaml 路径；None 时自动推导。

    Returns:
        {
          template_id,
          csv_tables: {
            table_name: {
              filename, primary_key,
              fields, required_fields,
              enum_fields: {field: [allowed_values]},
              field_types: {field: type_str},
            }
          },
          enum_groups: {group_name: [values]},
        }
    """
    try:
        from backend.src.db_access.business.reader import get_rag_extraction_contract
        return get_rag_extraction_contract(template_id=template_id)
    except ImportError:
        pass

    # 兜底：直接解析 YAML（当 db_access 层不可用时）
    import yaml

    path = Path(schema_template_path) if schema_template_path else (
        _SCHEMA_DIR / template_id / "schema.yaml"
    )
    if not path.exists():
        raise FileNotFoundError(f"schema.yaml 未找到：{path}")

    with path.open(encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    enum_groups:    dict = schema.get("enum_groups", {})
    logical_tables: dict = schema.get("logical_tables", {})

    csv_tables: dict[str, Any] = {}
    for table_name, table_def in logical_tables.items():
        fields_def: dict = table_def.get("fields", {})
        pk = table_def.get("primary_key", f"{table_name}_id")

        field_names      = list(fields_def.keys())
        required_fields  = [f for f, d in fields_def.items() if d.get("required") is True]
        enum_fields: dict[str, list] = {}
        field_types: dict[str, str]  = {}

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
