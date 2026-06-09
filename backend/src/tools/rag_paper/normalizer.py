# backend/src/tools/rag_paper/normalizer.py
"""
RAG 原始输出 → hap_peptide_v1 五表 rows 转换器

把 PipelineOrchestrator.process_pdf() 返回的 {paper_meta, entities}
转换为 db_access 层可直接写入的五表行字典列表。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any


# ─── 枚举归一化 ───────────────────────────────────────────────────────────────

def _normalize_enum(value: str | None, allowed: list[str]) -> str | None:
    """
    将枚举值归一化到 schema 定义的合法值集。

    策略：
      1. 精确匹配 → 直接返回
      2. 忽略大小写匹配 → 返回 schema 中的规范写法
      3. 匹配失败 → 返回 None（由上层填 not_reported/unclear）
    """
    if not value or not allowed:
        return value
    if value in allowed:
        return value
    value_lower = value.lower()
    for canonical in allowed:
        if canonical.lower() == value_lower:
            return canonical
    return None


def _fill_required(val: Any, field_type: str) -> Any:
    """必填字段缺失时的默认填充值。"""
    if val is not None and val != "":
        return val
    if field_type == "enum":
        return "not_reported"
    return "not_reported"


# ─── 稳定 ID 生成 ─────────────────────────────────────────────────────────────

def _stable_id(prefix: str, *parts: str) -> str:
    """基于内容哈希生成稳定 ID（前缀 + sha256[:12]）。"""
    content = "|".join(str(p) for p in parts)
    suffix  = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"{prefix}_{suffix}"


# ─── 主转换函数 ───────────────────────────────────────────────────────────────

def normalize_to_five_tables(
    raw_output: dict[str, Any],
    contract: dict[str, Any],
    paper_key: str | None = None,
) -> dict[str, list[dict]]:
    """
    将 service.run_pipeline() 的原始输出转换为五张逻辑表的行列表。

    Args:
        raw_output: {paper_meta: {...}, entities: [...]}
        contract:   load_extraction_contract() 的返回值
        paper_key:  文献 paper_key（用于生成稳定 ID）

    Returns:
        {
          paper: [...],
          paper_entity_record: [...],
          entity_component: [...],
          record_function: [...],
          function_assay_evidence: [...],
        }
    """
    csv_tables  = contract.get("csv_tables", {})
    enum_groups = contract.get("enum_groups", {})

    paper_meta = raw_output.get("paper_meta") or {}
    entities   = raw_output.get("entities")   or []

    # ── 1. paper 表 ───────────────────────────────────────────────────────────
    paper_tbl  = csv_tables.get("paper", {})
    paper_enums = paper_tbl.get("enum_fields", {})
    paper_pk   = paper_tbl.get("primary_key", "paper_id")
    paper_id   = paper_key or _stable_id("P", paper_meta.get("doi", ""), paper_meta.get("title", ""))

    paper_row: dict[str, Any] = {paper_pk: paper_id}
    for field in paper_tbl.get("fields", []):
        if field == paper_pk:
            continue
        raw_val = paper_meta.get(field)
        if field in paper_enums:
            raw_val = _normalize_enum(raw_val, paper_enums[field])
        paper_row[field] = raw_val

    # 保证必填字段不为空
    for req in paper_tbl.get("required_fields", []):
        if req != paper_pk and not paper_row.get(req):
            paper_row[req] = _fill_required(None, paper_tbl.get("field_types", {}).get(req, "string"))

    papers = [paper_row]

    # ── 2~5. 实体相关四表 ─────────────────────────────────────────────────────
    records:   list[dict] = []
    components:list[dict] = []
    functions: list[dict] = []
    evidences: list[dict] = []

    rec_tbl  = csv_tables.get("paper_entity_record", {})
    comp_tbl = csv_tables.get("entity_component", {})
    func_tbl = csv_tables.get("record_function", {})
    evid_tbl = csv_tables.get("function_assay_evidence", {})

    rec_pk   = rec_tbl.get("primary_key",  "record_id")
    comp_pk  = comp_tbl.get("primary_key", "component_id")
    func_pk  = func_tbl.get("primary_key", "function_id")
    evid_pk  = evid_tbl.get("primary_key", "evidence_id")

    for entity in entities:
        # paper_entity_record
        rec_id = _stable_id("R", paper_id, entity.get("entity_name_raw", ""), str(uuid.uuid4())[:8])
        rec_row: dict[str, Any] = {rec_pk: rec_id, "paper_id": paper_id}
        for field in rec_tbl.get("fields", []):
            if field in (rec_pk, "paper_id"):
                continue
            raw_val = entity.get(field)
            if field in rec_tbl.get("enum_fields", {}):
                raw_val = _normalize_enum(raw_val, rec_tbl["enum_fields"][field])
            rec_row[field] = raw_val
        for req in rec_tbl.get("required_fields", []):
            if req not in (rec_pk, "paper_id") and not rec_row.get(req):
                rec_row[req] = _fill_required(None, rec_tbl.get("field_types", {}).get(req, "string"))
        records.append(rec_row)

        # entity_component（从 entity.components 或 sequence 提取）
        comps_raw = entity.get("components") or []
        if not comps_raw and entity.get("sequence"):
            comps_raw = [{"sequence": entity["sequence"], "component_order": 1}]
        for idx, comp in enumerate(comps_raw):
            comp_id  = _stable_id("C", rec_id, str(idx))
            comp_row: dict[str, Any] = {comp_pk: comp_id, "record_id": rec_id}
            for field in comp_tbl.get("fields", []):
                if field in (comp_pk, "record_id"):
                    continue
                raw_val = comp.get(field)
                if field in comp_tbl.get("enum_fields", {}):
                    raw_val = _normalize_enum(raw_val, comp_tbl["enum_fields"][field])
                comp_row[field] = raw_val
            components.append(comp_row)

        # record_function（从 entity.functions 提取）
        funcs_raw = entity.get("functions") or []
        for fidx, func in enumerate(funcs_raw):
            func_id  = _stable_id("F", rec_id, str(fidx))
            func_row: dict[str, Any] = {func_pk: func_id, "record_id": rec_id}
            for field in func_tbl.get("fields", []):
                if field in (func_pk, "record_id"):
                    continue
                raw_val = func.get(field)
                if field in func_tbl.get("enum_fields", {}):
                    raw_val = _normalize_enum(raw_val, func_tbl["enum_fields"][field])
                func_row[field] = raw_val
            functions.append(func_row)

            # function_assay_evidence（从 func.evidence 提取）
            evids_raw = func.get("evidence") or []
            for eidx, evid in enumerate(evids_raw):
                evid_id  = _stable_id("E", func_id, str(eidx))
                evid_row: dict[str, Any] = {evid_pk: evid_id, "function_id": func_id}
                for field in evid_tbl.get("fields", []):
                    if field in (evid_pk, "function_id"):
                        continue
                    raw_val = evid.get(field)
                    if field in evid_tbl.get("enum_fields", {}):
                        raw_val = _normalize_enum(raw_val, evid_tbl["enum_fields"][field])
                    evid_row[field] = raw_val
                evidences.append(evid_row)

    return {
        "paper":                  papers,
        "paper_entity_record":    records,
        "entity_component":       components,
        "record_function":        functions,
        "function_assay_evidence": evidences,
    }
