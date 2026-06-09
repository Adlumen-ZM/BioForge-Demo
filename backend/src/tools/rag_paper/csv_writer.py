# backend/src/tools/rag_paper/csv_writer.py
"""
五表 CSV 写出器（rag_paper 模块内部使用）

按 contract 定义的字段顺序将 normalize_to_five_tables() 的输出写为 CSV。
每张表都会生成文件：无数据时也写表头，保证文件存在。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


_TABLE_ORDER = [
    "paper",
    "paper_entity_record",
    "entity_component",
    "record_function",
    "function_assay_evidence",
]


def write_tables_to_csv(
    tables: dict[str, list[dict]],
    contract: dict[str, Any],
    output_dir: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    按 contract 字段顺序将五表数据写入 CSV 文件。

    Args:
        tables:     normalize_to_five_tables() 的输出。
        contract:   load_extraction_contract() 的返回值。
        output_dir: 输出目录（不存在时自动创建）。
        overwrite:  False 时若文件已存在则跳过；True 时覆盖。

    Returns:
        {
          csv_files: {table_name: absolute_path},
          tables:    {table_name: {rows: n}},
          skipped:   [table_name, ...]
        }
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    csv_tables = contract.get("csv_tables", {})

    csv_files: dict[str, str] = {}
    table_stats: dict[str, Any] = {}
    skipped: list[str] = []

    for table_name in _TABLE_ORDER:
        table_def = csv_tables.get(table_name, {})
        fields    = table_def.get("fields", [])
        filename  = table_def.get("filename") or f"{table_name}.csv"
        dest      = out_path / filename

        if dest.exists() and not overwrite:
            skipped.append(table_name)
            csv_files[table_name]  = str(dest)
            table_stats[table_name] = {"rows": _count_rows(dest)}
            continue

        rows = tables.get(table_name) or []

        # 确保字段列表非空：若 contract 没有该表定义，从数据推导
        if not fields and rows:
            fields = list(rows[0].keys())

        with dest.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        csv_files[table_name]  = str(dest)
        table_stats[table_name] = {"rows": len(rows)}

    return {
        "csv_files": csv_files,
        "tables":    table_stats,
        "skipped":   skipped,
    }


def _count_rows(path: Path) -> int:
    """计算已有 CSV 文件的数据行数（不含表头）。"""
    try:
        with path.open(encoding="utf-8", newline="") as f:
            return sum(1 for _ in f) - 1
    except Exception:
        return 0
