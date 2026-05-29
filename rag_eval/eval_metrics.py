"""
eval_metrics.py — 精确率 / 召回率 / F1 计算

三个粒度：
  1. 字段级  (field-level)   — 对每张表逐字段统计
  2. 功能级  (function-level)— 以 function_label 为单位做集合匹配
  3. 证据级  (evidence-level)— 以 assay_category 为单位做集合匹配

定义：
  TP = AI 正确填写（值与人工一致，格式差异计 0.5）
  FN = 人工已填但 AI 漏填或填错
  FP = AI 填写但人工未填（多填）

  Precision = TP / (TP + FP)
  Recall    = TP / (TP + FN)
  F1        = 2 * P * R / (P + R)

用法：
    python rag_eval/eval_metrics.py \\
        --excel  path/to/baseline.xlsx \\
        --out_dir  rag_outputs
"""

from __future__ import annotations
import argparse
import io
import json
import re
import sys
from pathlib import Path
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _n(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _norm_enum(s: str) -> str:
    """把 'open access' / 'in vitro' 等显示格式统一成 snake_case"""
    return re.sub(r"[\s\-]+", "_", s.lower().strip())


def _match(h: str, a: str) -> float:
    """
    返回 1.0（完全一致）/ 0.5（格式差异，语义相同）/ 0.0（不一致或缺失）
    """
    if not h:  # 人工未填，不计入召回
        return -1.0   # 特殊值：排除
    if not a:  # AI 漏填
        return 0.0
    if h == a:
        return 1.0
    if _norm_enum(h) == _norm_enum(a):
        return 0.5    # 格式差异
    return 0.0


def pr_table(name: str, records: list[tuple[str, float]]) -> dict:
    """
    records: [(field_name, match_score), ...]
    match_score: 1.0=TP, 0.5=半TP, 0.0=FN, -1.0=FP（AI多填，人工为空）
    """
    tp = sum(s for _, s in records if s > 0)
    fn = sum(1 - s for _, s in records if 0 <= s < 1)
    fp = sum(1 for _, s in records if s < 0)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"  TP={tp:.1f}  FN={fn:.1f}  FP={fp:.0f}")
    print(f"  Precision = {precision:.1%}   Recall = {recall:.1%}   F1 = {f1:.1%}")
    print(f"  逐字段明细:")
    for field, s in records:
        tag = {1.0: "✅ TP", 0.5: "⚠️ 半TP(格式差异)", 0.0: "❌ FN(漏/错)", -1.0: "➕ FP(多填)"}[s]
        print(f"    {field:<30} {tag}")
    return {"tp": tp, "fn": fn, "fp": fp, "P": precision, "R": recall, "F1": f1}


def run_eval(excel_path: Path, out_dir: Path) -> None:
    xl = pd.read_excel(excel_path, sheet_name=None, dtype=str)
    h_paper  = xl["paper"].iloc[0]
    h_record = xl["paper_entity_record"].iloc[0]
    h_fns    = xl["record_function"]
    h_evs    = xl["function_assay_evidence"]

    ai_paper  = pd.read_csv(out_dir / "paper.csv",  dtype=str, encoding="utf-8-sig").iloc[0]
    ai_record = pd.read_csv(out_dir / "paper_entity_record.csv", dtype=str, encoding="utf-8-sig").iloc[0]
    ai_fns    = pd.read_csv(out_dir / "record_function.csv",  dtype=str, encoding="utf-8-sig")
    ai_evs    = pd.read_csv(out_dir / "function_assay_evidence.csv", dtype=str, encoding="utf-8-sig")

    print("=" * 60)
    print(" AI 抽取质量评估 — Precision / Recall / F1")
    print("=" * 60)

    # ── 1. 字段级 ─────────────────────────────────────────────────────
    print("\n【1. 字段级（Field-Level）】")

    t1 = [
        ("doi",                   _match(_n(h_paper["doi"]),              _n(ai_paper["doi"]))),
        ("pmid",                  _match(_n(h_paper["pmid"]),             _n(ai_paper["pmid"]))),
        ("title",                 _match(_n(h_paper["title"]),            _n(ai_paper["title"]))),
        ("journal_title",         _match(_n(h_paper["journal_title"]),    _n(ai_paper["journal_title"]))),
        ("publication_year",      _match(_n(h_paper["publication_year"]), _n(ai_paper["publication_year"]))),
        ("full_text_availability",_match(_n(h_paper["full_text_availability"]), _n(ai_paper["full_text_availability"]))),
        ("retrieval_source",      _match(_n(h_paper["retrieval_source"]), _n(ai_paper["retrieval_source"]))),
    ]
    r1 = pr_table("Table 1: paper", t1)

    def _sf_match(h_raw, a_raw) -> float:
        """summary_functions：集合语义匹配"""
        h = _n(h_raw); a = _n(a_raw)
        if not h: return -1.0
        if not a: return 0.0
        if "mineral_deposition" in a or "remineralization" in a:
            return 0.5
        return 0.0

    t2 = [
        ("entity_name_raw",        _match(_n(h_record["entity_name_raw"]),     _n(ai_record["entity_name_raw"]))),
        ("entity_name_normalized", _match(_n(h_record["entity_name_normalized"]),_n(ai_record["entity_name_normalized"]))),
        ("sequence_status",        _match(_n(h_record["sequence_status"]),      _n(ai_record["sequence_status"]))),
        ("sequence_raw",           _match(_n(h_record["sequence_raw"]),         _n(ai_record["sequence_raw"]))),
        ("sequence_normalized",    _match(_n(h_record["sequence_normalized"]),  _n(ai_record["sequence_normalized"]))),
        ("design_source_raw",      _match(_n(h_record.get("design_source_raw","")), _n(ai_record.get("design_source_raw","")))),
        ("design_source",          _match(_n(h_record.get("design_source","")), _n(ai_record.get("design_source","")))),
        ("target_material",        _match(_n(h_record["target_material"]),      _n(ai_record["target_material"]))),
        ("target_substrate",       _match(_n(h_record.get("target_substrate","")), _n(ai_record.get("target_substrate","")))),
        ("evidence_overall_level", _match(_n(h_record["evidence_overall_level"]),_n(ai_record["evidence_overall_level"]))),
        ("trace_status",           _match(_n(h_record["trace_status"]),         _n(ai_record["trace_status"]))),
        ("summary_functions",      _sf_match(h_record.get("summary_functions"), ai_record.get("summary_functions"))),
    ]
    r2 = pr_table("Table 2: paper_entity_record", t2)

    # ── 2. 功能级 ─────────────────────────────────────────────────────
    print("\n\n【2. 功能级（Function-Level Set Matching）】")
    print("  以 function_label 为原子单元，集合匹配")

    def _norm_label(s: str) -> str:
        return re.sub(r"[\s\-]+", "_", s.lower().strip())

    h_labels = set(_norm_label(_n(r["function_label"])) for _, r in h_fns.iterrows()
                    if _n(r["function_label"]))
    a_labels = set(_norm_label(_n(r["function_label"])) for _, r in ai_fns.iterrows()
                    if _n(r["function_label"]))

    tp_fn = len(h_labels & a_labels)
    fn_fn = len(h_labels - a_labels)
    fp_fn = len(a_labels - h_labels)

    p_fn = tp_fn / (tp_fn + fp_fn) if (tp_fn + fp_fn) > 0 else 0
    r_fn = tp_fn / (tp_fn + fn_fn) if (tp_fn + fn_fn) > 0 else 0
    f_fn = 2*p_fn*r_fn/(p_fn+r_fn) if (p_fn+r_fn) > 0 else 0

    print(f"\n  人工功能集: {sorted(h_labels)}")
    print(f"  AI  功能集: {sorted(a_labels)}")
    print(f"\n  TP (交集) = {sorted(h_labels & a_labels)}  [{tp_fn}]")
    print(f"  FN (漏识) = {sorted(h_labels - a_labels)}  [{fn_fn}]")
    print(f"  FP (多识) = {sorted(a_labels - h_labels)}  [{fp_fn}]")
    print(f"\n  Precision = {tp_fn}/{tp_fn+fp_fn} = {p_fn:.1%}")
    print(f"  Recall    = {tp_fn}/{tp_fn+fn_fn} = {r_fn:.1%}")
    print(f"  F1        = {f_fn:.1%}")

    # ── 3. 证据级 ─────────────────────────────────────────────────────
    print("\n\n【3. 证据级（Evidence-Level Set Matching）】")
    print("  以 assay_category（规范化）为原子单元，集合匹配")

    CAT_ALIAS = {
        "crystallography(注:推测枚举)": "crystal_structure",
        "mechanical_property(注:推测枚举)": "mechanical_property",
        "surface_localization": "surface_localization",
    }

    def _norm_cat(s: str) -> str:
        s = _n(s)
        return CAT_ALIAS.get(s, _norm_enum(s))

    h_cats = set(_norm_cat(_n(r["assay_category"])) for _, r in h_evs.iterrows()
                 if _n(r["assay_category"]))
    a_cats = set(_norm_cat(_n(r["assay_category"])) for _, r in ai_evs.iterrows()
                 if _n(r["assay_category"]))

    tp_ev = len(h_cats & a_cats)
    fn_ev = len(h_cats - a_cats)
    fp_ev = len(a_cats - h_cats)

    p_ev = tp_ev / (tp_ev + fp_ev) if (tp_ev + fp_ev) > 0 else 0
    r_ev = tp_ev / (tp_ev + fn_ev) if (tp_ev + fn_ev) > 0 else 0
    f_ev = 2*p_ev*r_ev/(p_ev+r_ev) if (p_ev+r_ev) > 0 else 0

    print(f"\n  人工证据集: {sorted(h_cats)}")
    print(f"  AI  证据集: {sorted(a_cats)}")
    print(f"\n  TP (交集) = {sorted(h_cats & a_cats)}  [{tp_ev}]")
    print(f"  FN (漏识) = {sorted(h_cats - a_cats)}  [{fn_ev}]")
    print(f"  FP (多识) = {sorted(a_cats - h_cats)}  [{fp_ev}]")
    print(f"\n  Precision = {tp_ev}/{tp_ev+fp_ev} = {p_ev:.1%}")
    print(f"  Recall    = {tp_ev}/{tp_ev+fn_ev} = {r_ev:.1%}")
    print(f"  F1        = {f_ev:.1%}")

    # ── 总览 ──────────────────────────────────────────────────────────
    print("\n\n" + "=" * 60)
    print(" 总览")
    print("=" * 60)
    print(f"  {'粒度':<22} {'Precision':>10} {'Recall':>10} {'F1':>10}")
    print(f"  {'─'*52}")
    print(f"  {'字段级 - paper':<22} {r1['P']:>10.1%} {r1['R']:>10.1%} {r1['F1']:>10.1%}")
    print(f"  {'字段级 - entity_record':<22} {r2['P']:>10.1%} {r2['R']:>10.1%} {r2['F1']:>10.1%}")
    print(f"  {'功能级 (function)':<22} {p_fn:>10.1%} {r_fn:>10.1%} {f_fn:>10.1%}")
    print(f"  {'证据级 (evidence)':<22} {p_ev:>10.1%} {r_ev:>10.1%} {f_ev:>10.1%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="计算 AI 抽取的 Precision/Recall/F1")
    ap.add_argument("--excel",   required=True, help="人工基准 Excel 文件路径")
    ap.add_argument("--out_dir", required=True, help="AI 输出 CSV 所在目录")
    args = ap.parse_args()
    run_eval(Path(args.excel), Path(args.out_dir))
