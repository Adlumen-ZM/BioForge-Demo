"""
compare_outputs.py — 人工基准 vs AI 自动提取结果 逐字段比对

用法：
    python rag_eval/compare_outputs.py \\
        --excel  path/to/baseline.xlsx \\
        --out_dir  rag_outputs

输入：
    基准  : Excel 文件（4 个 sheet：paper / paper_entity_record / record_function / function_assay_evidence）
    AI输出 : out_dir/*.csv

输出：
    控制台打印比对报告，同时写入 out_dir/comparison_report.txt
"""

from __future__ import annotations
import argparse
import io
import json
import re
import sys
from pathlib import Path
import pandas as pd

# 强制 stdout 使用 UTF-8，避免 Windows GBK 下 emoji 报错
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── 枚举合法值集合（用于校验人工填写是否合规）─────────────────────────
VALID_ENUMS = {
    "full_text_availability": {"open_access", "subscription", "preprint", "unknown"},
    "retrieval_source":       {"pubmed", "crossref", "manual_entry", "agent_crawl"},
    "sequence_status":        {"explicit", "partial", "not_reported", "backtrace_required"},
    "design_source":          {"natural_derived", "rational_design", "phage_display",
                               "computational", "synthetic", "unclear"},
    "target_material":        {"HAP", "collagen", "ACP", "other", "not_reported", "unclear"},
    "target_substrate":       {"enamel", "dentin", "bone", "mineral_surface",
                               "in_vitro_crystal", "other", "not_reported", "unclear"},
    "evidence_overall_level": {"in_vitro", "ex_vivo", "animal_in_vivo", "clinical",
                               "in_silico", "unclear"},
    "trace_status":           {"complete", "partial", "missing", "disputed"},
    "function_layer":         {"binding", "kinetics", "crystallography",
                               "protection", "biology", "other"},
    "function_label":         {"adsorption", "localization", "ion_capture",
                               "nucleation", "mineral_deposition", "crystal_growth_promotion",
                               "phase_stabilization", "phase_transformation_promotion",
                               "crystal_growth_inhibition", "crystal_orientation_modulation",
                               "crystal_morphology_modulation",
                               "anti_demineralization",
                               "antimicrobial", "cell_adhesion_promotion", "other"},
    "evidence_level":         {"in_vitro", "ex_vivo", "animal_in_vivo", "clinical",
                               "in_silico", "unclear"},
    "assay_category":         {"binding_affinity", "surface_localization", "retention_test",
                               "crystal_structure", "mineral_morphology", "elemental_composition",
                               "molecular_composition", "mechanical_property", "mineral_quantity",
                               "lesion_morphology", "biological_response", "in_vivo_efficacy",
                               "simulation", "other"},
    "validation_method":      {"CLSM", "fluorescence_microscopy", "micro-CT", "nanoindentation",
                               "SEM", "TEM", "AFM", "XRD", "FTIR", "EDX", "ICP-OES",
                               "SPR", "ITC", "ELISA", "MTT",
                               "molecular_docking", "MD_simulation", "other", "unclear"},
}

# ── function_layer ↔ function_label 约束 ─────────────────────────────
LAYER_LABEL = {
    "binding":        {"adsorption", "localization", "ion_capture"},
    "kinetics":       {"nucleation", "mineral_deposition", "crystal_growth_promotion"},
    "crystallography":{"phase_stabilization", "phase_transformation_promotion",
                       "crystal_growth_inhibition", "crystal_orientation_modulation",
                       "crystal_morphology_modulation"},
    "protection":     {"anti_demineralization"},
    "biology":        {"antimicrobial", "cell_adhesion_promotion"},
    "other":          {"other"},
}

# ─────────────────────────────────────────────────────────────────────
lines: list[str] = []


def pr(s: str = "") -> None:
    lines.append(s)
    print(s)


def _norm(v) -> str:
    """统一为小写去空格字符串，NaN → ''"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _cmp(field: str, human_val, ai_val, context: str = "") -> str:
    """
    返回:
      ✅ 正确
      ⚠️ 格式差异（值语义相同，枚举写法不一致）
      ❌ 不一致
      ➕ AI 填写但人工为空（AI 多填）
      🔲 人工填写但 AI 为空（AI 漏填）
      🔳 双方均为空
    """
    h = _norm(human_val)
    a = _norm(ai_val)
    if not h and not a:
        return "🔳 双方均为空"
    if not h and a:
        return f"➕ AI 多填: {a!r}"
    if h and not a:
        return f"🔲 AI 漏填 (人工: {h!r})"
    if h.lower() == a.lower():
        return "✅ 正确"
    # 枚举格式差异检测（如 open access vs open_access）
    h_norm = re.sub(r"[\s\-]", "_", h.lower())
    a_norm = re.sub(r"[\s\-]", "_", a.lower())
    if h_norm == a_norm:
        return f"⚠️ 格式差异 (人工: {h!r} / AI: {a!r})"
    return f"❌ 不一致 (人工: {h!r} / AI: {a!r})"


def _enum_warn(field: str, value: str) -> str | None:
    """检查枚举合法性，不合法返回警告字符串"""
    if field in VALID_ENUMS and value and value not in VALID_ENUMS[field]:
        return f"   ⚠️  枚举越界：{field}={value!r}（合法值: {sorted(VALID_ENUMS[field])}）"
    return None


def run_comparison(excel_path: Path, out_dir: Path) -> None:
    report_path = out_dir / "comparison_report.txt"

    xl = pd.read_excel(excel_path, sheet_name=None, dtype=str)
    h_paper  = xl["paper"].iloc[0]
    h_record = xl["paper_entity_record"].iloc[0]
    h_fns    = xl["record_function"]
    h_evs    = xl["function_assay_evidence"]

    ai_paper  = pd.read_csv(out_dir / "paper.csv", dtype=str, encoding="utf-8-sig")
    ai_record = pd.read_csv(out_dir / "paper_entity_record.csv", dtype=str, encoding="utf-8-sig")
    ai_fns    = pd.read_csv(out_dir / "record_function.csv", dtype=str, encoding="utf-8-sig")
    ai_evs    = pd.read_csv(out_dir / "function_assay_evidence.csv", dtype=str, encoding="utf-8-sig")

    has_ai_paper  = len(ai_paper) > 0
    has_ai_record = len(ai_record) > 0

    pr("=" * 70)
    pr(" 人工基准 vs AI 自动提取 — 逐字段比对报告")
    pr("=" * 70)

    # ── TABLE 1：paper ────────────────────────────────────────────────
    pr("\n【Table 1: paper】")
    pr("-" * 60)
    if not has_ai_paper:
        pr("  ❌ AI 未产出任何 paper 行！")
    else:
        ai_p = ai_paper.iloc[0]
        pr(f"  paper_id         : {_cmp('paper_id', h_paper.get('paper_id'), ai_p.get('paper_id'))}")
        for field in ["doi", "pmid", "title", "journal_title", "publication_year"]:
            result = _cmp(field, h_paper.get(field), ai_p.get(field))
            pr(f"  {field:<22}: {result}")
        r = _cmp("full_text_availability",
                 h_paper.get("full_text_availability"), ai_p.get("full_text_availability"))
        pr(f"  {'full_text_availability':<22}: {r}")
        w = _enum_warn("full_text_availability", _norm(h_paper.get("full_text_availability")))
        if w: pr(w)
        pr(f"  {'retrieval_source':<22}: {_cmp('retrieval_source', h_paper.get('retrieval_source'), ai_p.get('retrieval_source'))}")
        pr(f"  {'abstract':<22}: {'(人工保留原文占位，AI空白)' if not _norm(ai_p.get('abstract')) else _cmp('abstract', h_paper.get('abstract'), ai_p.get('abstract'))[:60]}")
        pr(f"  {'keywords':<22}: {_cmp('keywords', h_paper.get('keywords'), ai_p.get('keywords'))}")

    # ── TABLE 2：paper_entity_record ──────────────────────────────────
    pr("\n【Table 2: paper_entity_record】")
    pr("-" * 60)
    if not has_ai_record:
        pr("  ❌ AI 未产出任何 record 行！")
    else:
        ai_r = ai_record.iloc[0]
        pr("  [外键校验]")
        pr(f"    record_id FK paper_id : 人工={h_record.get('paper_id')!r}, "
           f"AI={ai_r.get('paper_id')!r} → {_cmp('paper_id_fk', h_record.get('paper_id'), ai_r.get('paper_id'))}")
        pr()
        for field in ["entity_name_raw", "entity_name_normalized",
                      "sequence_status", "sequence_raw", "sequence_normalized",
                      "design_source_raw", "design_source",
                      "target_material_raw", "target_material",
                      "target_substrate_raw", "target_substrate",
                      "evidence_overall_level", "trace_status"]:
            result = _cmp(field, h_record.get(field), ai_r.get(field))
            pr(f"  {field:<28}: {result}")
            w = _enum_warn(field, _norm(ai_r.get(field)))
            if w: pr(w)

        h_sf = _norm(h_record.get("summary_functions"))
        a_sf = _norm(ai_r.get("summary_functions"))
        pr(f"\n  {'summary_functions':<28}: 人工={h_sf!r}")
        pr(f"  {'':28}  AI  ={a_sf!r}")
        try:
            h_list = json.loads(h_sf.replace("'", '"')) if h_sf.startswith("[") else [h_sf]
        except Exception:
            h_list = [h_sf]
        for v in h_list:
            w = _enum_warn("function_label", v)
            if w: pr(w.replace("function_label", "summary_functions item"))

    # ── TABLE 3：record_function ──────────────────────────────────────
    pr("\n【Table 3: record_function】")
    pr("-" * 60)
    pr(f"  人工行数: {len(h_fns)}  / AI行数: {len(ai_fns)}")

    pr("\n  [外键校验] record_id FK → paper_entity_record")
    h_valid_record_ids = {_norm(h_record.get("record_id"))}
    ai_valid_record_ids = set(ai_record["record_id"].apply(_norm)) if has_ai_record else set()

    for i, row in h_fns.iterrows():
        rid = _norm(row.get("record_id"))
        status = "✅" if rid in h_valid_record_ids else "❌ 外键悬空"
        pr(f"    人工 function_id={row.get('function_id')!r} → record_id={rid!r}: {status}")

    for i, row in ai_fns.iterrows():
        rid = _norm(row.get("record_id"))
        status = "✅" if rid in ai_valid_record_ids else "❌ 外键悬空"
        pr(f"    AI   function_id={row.get('function_id')!r} → record_id={rid!r}: {status}")

    pr("\n  [逐行比对] 按 function_label 配对")
    h_fn_map = {_norm(r["function_label"]): r for _, r in h_fns.iterrows()}
    ai_fn_map = {_norm(r["function_label"]): r for _, r in ai_fns.iterrows()}
    all_labels = sorted(set(h_fn_map) | set(ai_fn_map))

    for label in all_labels:
        in_h = label in h_fn_map
        in_a = label in ai_fn_map
        if in_h and not in_a:
            pr(f"\n  ▸ function_label={label!r}: 🔲 AI 漏填（人工有此功能）")
            continue
        if not in_h and in_a:
            pr(f"\n  ▸ function_label={label!r}: ➕ AI 多填（人工无此功能）")
            continue
        hf = h_fn_map[label]
        af = ai_fn_map[label]
        pr(f"\n  ▸ function_label={label!r}:")
        for field in ["function_layer", "function_label", "evidence_level", "trace_status"]:
            pr(f"      {field:<22}: {_cmp(field, hf.get(field), af.get(field))}")
            w = _enum_warn(field, _norm(af.get(field)))
            if w: pr(w)
        layer = _norm(af.get("function_layer"))
        lbl   = _norm(af.get("function_label"))
        if layer in LAYER_LABEL and lbl not in LAYER_LABEL[layer]:
            pr(f"      ⚠️  AI: function_layer={layer!r} 与 function_label={lbl!r} 不匹配！")

    # ── TABLE 4：function_assay_evidence ──────────────────────────────
    pr("\n【Table 4: function_assay_evidence】")
    pr("-" * 60)
    pr(f"  人工行数: {len(h_evs)}  / AI行数: {len(ai_evs)}")

    pr("\n  [外键校验] function_id FK → record_function")
    h_valid_fn_ids = set(h_fns["function_id"].apply(_norm))
    ai_valid_fn_ids = set(ai_fns["function_id"].apply(_norm)) if len(ai_fns) else set()

    for i, row in h_evs.iterrows():
        fid = _norm(row.get("function_id"))
        status = "✅" if fid in h_valid_fn_ids else "❌ 外键悬空（与人工 function 表不匹配）"
        pr(f"    人工 evidence_id={row.get('evidence_id')!r} → function_id={fid!r}: {status}")

    for i, row in ai_evs.iterrows():
        fid = _norm(row.get("function_id"))
        status = "✅" if fid in ai_valid_fn_ids else "❌ 外键悬空"
        pr(f"    AI   evidence_id={row.get('evidence_id')!r} → function_id={fid!r}: {status}")

    pr("\n  [逐行比对] 按 assay_category 配对")
    h_ev_map = {_norm(r["assay_category"]): r for _, r in h_evs.iterrows()}
    ai_ev_map = {_norm(r["assay_category"]): r for _, r in ai_evs.iterrows()}
    all_cats = sorted(set(h_ev_map) | set(ai_ev_map))

    for cat in all_cats:
        in_h = cat in h_ev_map
        in_a = cat in ai_ev_map
        if in_h and not in_a:
            pr(f"\n  ▸ assay_category={cat!r}: 🔲 AI 漏填")
            continue
        if not in_h and in_a:
            pr(f"\n  ▸ assay_category={cat!r}: ➕ AI 多填")
            continue
        he = h_ev_map[cat]
        ae = ai_ev_map[cat]
        pr(f"\n  ▸ assay_category={cat!r}:")
        for field in ["evidence_level", "assay_category", "validation_method",
                      "result_text_summary", "trace_status"]:
            v = _cmp(field, he.get(field), ae.get(field))
            pr(f"      {field:<24}: {v}")
            for who, row in [("人工", he), ("AI", ae)]:
                w = _enum_warn(field, _norm(row.get(field)))
                if w: pr(f"   {who}{w}")

    # ── 汇总 ──────────────────────────────────────────────────────────
    pr("\n" + "=" * 70)
    pr(" 汇总")
    pr("=" * 70)
    full_text = "\n".join(lines)
    counts = {
        "✅ 正确":   full_text.count("✅"),
        "⚠️ 格式差异/枚举越界": full_text.count("⚠️"),
        "❌ 不一致": full_text.count("❌"),
        "🔲 AI漏填": full_text.count("🔲"),
        "➕ AI多填": full_text.count("➕"),
        "🔳 双方均空": full_text.count("🔳"),
    }
    for k, v in counts.items():
        pr(f"  {k}: {v}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已保存到: {report_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="比对人工基准与 AI 抽取输出")
    ap.add_argument("--excel",   required=True, help="人工基准 Excel 文件路径")
    ap.add_argument("--out_dir", required=True, help="AI 输出 CSV 所在目录")
    args = ap.parse_args()
    run_comparison(Path(args.excel), Path(args.out_dir))
