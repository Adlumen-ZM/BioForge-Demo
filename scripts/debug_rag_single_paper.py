#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run the agent RAG extraction tool against one PDF and inspect CSV output.

Example:
    python scripts/debug_rag_single_paper.py ^
        --pdf data/projects/hap_peptide_v1/papers/example/raw/source.pdf ^
        --schema-template docs/schema_templates/hap_peptide_v1/schema.yaml ^
        --overwrite
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_ID = "hap_peptide_v1"


def _load_env(env_file: Path) -> None:
    """Load .env without making python-dotenv a hard dependency for --help."""
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
        return
    except ImportError:
        pass

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _resolve_path(value: str | None, *, must_exist: bool = False) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if must_exist and not path.exists():
        raise FileNotFoundError(str(path))
    return path


def _default_schema_path(template_id: str) -> Path:
    return PROJECT_ROOT / "docs" / "schema_templates" / template_id / "schema.yaml"


def _default_field_mapping_path(template_id: str) -> Path:
    return PROJECT_ROOT / "docs" / "schema_templates" / template_id / "field_mapping.yaml"


def _paper_key(pdf_path: Path) -> str:
    seed = str(pdf_path.resolve()).encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:16]


def _default_output_dir(template_id: str, pdf_path: Path) -> Path:
    return (
        PROJECT_ROOT
        / "data"
        / "debug_rag"
        / template_id
        / _paper_key(pdf_path)
        / "rag_csv"
    )


def _csv_row_count(path: Path) -> int | None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        return max(len(rows) - 1, 0)
    except Exception:
        return None


def _summarize_csv_files(result: dict[str, Any]) -> list[dict[str, Any]]:
    csv_files = result.get("csv_files") or {}
    summary: list[dict[str, Any]] = []
    if isinstance(csv_files, dict):
        items = csv_files.items()
    else:
        items = []

    for table_name, raw_path in items:
        if not raw_path:
            summary.append({"table": table_name, "path": None, "exists": False, "rows": None})
            continue
        path = Path(str(raw_path))
        summary.append(
            {
                "table": table_name,
                "path": str(path),
                "exists": path.exists(),
                "rows": _csv_row_count(path) if path.exists() else None,
            }
        )
    return summary


def _print_json(title: str, data: Any) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Debug one-paper RAG extraction through the agent tool "
            "run_bio_paper_extraction_pipeline."
        )
    )
    parser.add_argument("--pdf", required=True, help="Path to the input PDF.")
    parser.add_argument(
        "--template-id",
        default=os.environ.get("EXTRACTION_PROFILE") or DEFAULT_TEMPLATE_ID,
        help="Schema template id. Defaults to EXTRACTION_PROFILE or hap_peptide_v1.",
    )
    parser.add_argument(
        "--schema-template",
        default=os.environ.get("SCHEMA_TEMPLATE_PATH") or None,
        help="Path to schema.yaml. Defaults to docs/schema_templates/<template-id>/schema.yaml.",
    )
    parser.add_argument(
        "--field-mapping",
        default=os.environ.get("FIELD_MAPPING_PATH") or None,
        help=(
            "Path to field_mapping.yaml. The current RAG tool does not consume this "
            "directly yet; this script validates and records it for debugging."
        ),
    )
    parser.add_argument(
        "--output-dir",
        help="CSV output directory. Defaults to data/debug_rag/<template-id>/<paper-key>/rag_csv.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing CSV files.")
    parser.add_argument(
        "--env-file",
        default=str(PROJECT_ROOT / ".env"),
        help="Optional env file to load before creating the RAG service.",
    )
    parser.add_argument(
        "--result-json",
        help="Optional path to write the full tool result JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _load_env(Path(args.env_file))

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    pdf_path = _resolve_path(args.pdf, must_exist=True)
    assert pdf_path is not None
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"--pdf must point to a PDF file: {pdf_path}")

    schema_template = _resolve_path(args.schema_template) or _default_schema_path(args.template_id)
    if not schema_template.exists():
        raise FileNotFoundError(f"schema template not found: {schema_template}")

    field_mapping = _resolve_path(args.field_mapping) or _default_field_mapping_path(args.template_id)
    field_mapping_exists = field_mapping.exists()

    output_dir = _resolve_path(args.output_dir) or _default_output_dir(args.template_id, pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_config = {
        "pdf_path": str(pdf_path),
        "template_id": args.template_id,
        "schema_template_path": str(schema_template),
        "field_mapping_path": str(field_mapping),
        "field_mapping_exists": field_mapping_exists,
        "output_dir": str(output_dir),
        "overwrite": bool(args.overwrite),
    }
    _print_json("Run Config", run_config)

    from backend.src.tools.rag_paper.tools import run_bio_paper_extraction_pipeline

    result = run_bio_paper_extraction_pipeline.invoke(
        {
            "pdf_path": str(pdf_path),
            "output_dir": str(output_dir),
            "template_id": args.template_id,
            "schema_template_path": str(schema_template),
            "overwrite": bool(args.overwrite),
        }
    )

    if not isinstance(result, dict):
        result = {"status": "error", "raw_result": result}

    _print_json("Tool Result", result)
    _print_json("CSV Summary", _summarize_csv_files(result))

    if args.result_json:
        result_json = _resolve_path(args.result_json)
        assert result_json is not None
        result_json.parent.mkdir(parents=True, exist_ok=True)
        result_json.write_text(
            json.dumps(
                {
                    "run_config": run_config,
                    "tool_result": result,
                    "csv_summary": _summarize_csv_files(result),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"\nWrote result JSON: {result_json}")

    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
