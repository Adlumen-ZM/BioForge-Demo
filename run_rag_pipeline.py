"""
全链路入口脚本 — 盲盒自驱动模式（4 表版）

用法：
    python run_rag_pipeline.py \\
        --pdf_dir  v0_1PDF \\
        --out_dir  rag_outputs

输出（out_dir 下）：
    paper.csv                 — Table 1：论文元数据
    paper_entity_record.csv   — Table 2：实体记录
    record_function.csv       — Table 3：功能记录
    function_assay_evidence.csv — Table 4：实验证据

层级 ID 格式：
    paper_id    : Pnnnnnn        （如 P000001）
    record_id   : {paper_id}-R{nn}
    function_id : {record_id}-F{nn}
    evidence_id : {function_id}-E{nn}

环境变量（从 .env 自动加载）：
    RAGFLOW_API_BASE_URL  RAGFlow 服务地址（不含 /api/v1）
    RAGFLOW_API_KEY       RAGFlow API 密钥
    LLM_API_KEY           OpenAI-compatible API Key
    LLM_BASE_URL          LLM 接口地址（如 https://ark.cn-beijing.volces.com/api/coding/v3）
    LLM_MODEL             模型名称（如 ark-code-latest）
    BGE_MODEL_DIR         BGE-M3 模型路径，默认 BAAI/bge-m3
"""

# ── dotenv 必须在所有业务模块 import 之前加载 ──────────────────────────
from dotenv import load_dotenv
load_dotenv()

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path

import chromadb

from rag_pipeline.core.orchestrator import PipelineOrchestrator
from rag_pipeline.extraction.llm_extractor import EntityExtractor, PaperExtractor
from rag_pipeline.ingestion.vision_parser import RAGFlowParser
from rag_pipeline.retrieval.bge_hybrid_retriever import BGEHybridRetriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── CSV 字段定义 ───────────────────────────────────────────────────────

PAPER_FIELDS = [
    "paper_id", "doi", "pmid", "title", "journal_title", "publication_year",
    "abstract", "keywords", "full_text_availability", "retrieval_source",
    "curator_note", "source_pdf",
]

RECORD_FIELDS = [
    "record_id", "paper_id",
    "entity_name_raw", "entity_name_normalized",
    "sequence_status", "sequence_raw", "sequence_normalized",
    "design_source_raw", "design_source",
    "target_material_raw", "target_material",
    "target_substrate_raw", "target_substrate",
    "summary_functions", "evidence_overall_level",
    "model_system_summary", "text_to_sequence",
    "trace_status", "curator_note",
]

FUNCTION_FIELDS = [
    "function_id", "record_id",
    "function_layer", "function_label",
    "function_source_raw", "evidence_level",
    "text_to_function", "trace_status", "curator_note",
]

EVIDENCE_FIELDS = [
    "evidence_id", "function_id",
    "evidence_level", "assay_category",
    "validation_method_raw", "validation_method",
    "readout_main", "result_text_summary",
    "result_value_raw", "result_value_normalized",
    "source_locations", "text_to_evidence",
    "trace_status", "curator_note",
]

# ── paper_id 计数器（持久化，跨运行连续编号）────────────────────────────

def _get_counter_file(out_dir: Path) -> Path:
    return out_dir / "paper_id_counter.json"


def _load_counter(out_dir: Path) -> int:
    counter_file = _get_counter_file(out_dir)
    if counter_file.exists():
        try:
            return int(json.loads(counter_file.read_text(encoding="utf-8"))["next"])
        except Exception:
            pass
    return 1


def _save_counter(out_dir: Path, next_val: int) -> None:
    counter_file = _get_counter_file(out_dir)
    counter_file.parent.mkdir(parents=True, exist_ok=True)
    counter_file.write_text(
        json.dumps({"next": next_val}, ensure_ascii=False),
        encoding="utf-8",
    )


def _make_paper_id(n: int) -> str:
    return f"P{n:06d}"


# ── 环境变量 ──────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val or val == "请在这里填入":
        raise EnvironmentError(f"环境变量 {name!r} 未配置，请先编辑 .env 文件。")
    return val


def build_components():
    ragflow_base = _require_env("RAGFLOW_API_BASE_URL")
    ragflow_key  = _require_env("RAGFLOW_API_KEY")
    llm_key      = _require_env("LLM_API_KEY")
    llm_base     = os.environ.get("LLM_BASE_URL") or None
    llm_model    = os.environ.get("LLM_MODEL", "gpt-4o")

    parser = RAGFlowParser(api_key=ragflow_key, base_url=ragflow_base)

    retriever = BGEHybridRetriever(
        model_dir=os.environ.get("BGE_MODEL_DIR", "BAAI/bge-m3"),
        use_fp16=True,
    )

    paper_extractor  = PaperExtractor(model=llm_model, api_key=llm_key, base_url=llm_base)
    entity_extractor = EntityExtractor(model=llm_model, api_key=llm_key, base_url=llm_base)

    chroma_client = chromadb.EphemeralClient()

    orchestrator = PipelineOrchestrator(
        retriever=retriever,
        paper_extractor=paper_extractor,
        entity_extractor=entity_extractor,
        chroma_client=chroma_client,
        scout_model=llm_model,
        scout_api_key=llm_key,
        scout_base_url=llm_base,
    )

    return parser, orchestrator


# ── ID 分配与行展开 ────────────────────────────────────────────────────

def _flatten_result(
    pdf_path: str,
    result: dict,
    paper_id: str,
) -> tuple:
    """
    将 process_pdf() 的返回值展开为 4 张表的行列表。

    Returns:
        (paper_rows, record_rows, function_rows, evidence_rows)
    """
    meta = result.get("paper_meta", {})

    # Table 1 — paper
    paper_row = {
        "paper_id":               paper_id,
        "doi":                    meta.get("doi"),
        "pmid":                   meta.get("pmid"),
        "title":                  meta.get("title"),
        "journal_title":          meta.get("journal_title"),
        "publication_year":       meta.get("publication_year"),
        "abstract":               meta.get("abstract"),
        "keywords":               json.dumps(meta.get("keywords"), ensure_ascii=False)
                                  if meta.get("keywords") else None,
        "full_text_availability": meta.get("full_text_availability"),
        "retrieval_source":       meta.get("retrieval_source"),
        "curator_note":           meta.get("curator_note"),
        "source_pdf":             pdf_path,
    }

    record_rows:   list = []
    function_rows: list = []
    evidence_rows: list = []

    for rec_idx, entity in enumerate(result.get("entities", []), start=1):
        record_id = f"{paper_id}-R{rec_idx:02d}"

        # Table 2 — paper_entity_record
        record_row = {
            "record_id":              record_id,
            "paper_id":               paper_id,
            "entity_name_raw":        entity.get("entity_name_raw"),
            "entity_name_normalized": entity.get("entity_name_normalized"),
            "sequence_status":        entity.get("sequence_status"),
            "sequence_raw":           entity.get("sequence_raw"),
            "sequence_normalized":    entity.get("sequence_normalized"),
            "design_source_raw":      entity.get("design_source_raw"),
            "design_source":          entity.get("design_source"),
            "target_material_raw":    entity.get("target_material_raw"),
            "target_material":        entity.get("target_material"),
            "target_substrate_raw":   entity.get("target_substrate_raw"),
            "target_substrate":       entity.get("target_substrate"),
            "summary_functions":      json.dumps(entity.get("summary_functions", []),
                                                 ensure_ascii=False),
            "evidence_overall_level": entity.get("evidence_overall_level"),
            "model_system_summary":   entity.get("model_system_summary"),
            "text_to_sequence":       entity.get("text_to_sequence"),
            "trace_status":           entity.get("trace_status"),
            "curator_note":           entity.get("curator_note"),
        }
        record_rows.append(record_row)

        for fn_idx, fn in enumerate(entity.get("functions", []), start=1):
            function_id = f"{record_id}-F{fn_idx:02d}"

            # Table 3 — record_function
            fn_row = {
                "function_id":       function_id,
                "record_id":         record_id,
                "function_layer":    fn.get("function_layer"),
                "function_label":    fn.get("function_label"),
                "function_source_raw": fn.get("function_source_raw"),
                "evidence_level":    fn.get("evidence_level"),
                "text_to_function":  fn.get("text_to_function"),
                "trace_status":      fn.get("trace_status"),
                "curator_note":      fn.get("curator_note"),
            }
            function_rows.append(fn_row)

            for ev_idx, ev in enumerate(fn.get("evidence_items", []), start=1):
                evidence_id = f"{function_id}-E{ev_idx:02d}"

                # Table 4 — function_assay_evidence
                ev_row = {
                    "evidence_id":             evidence_id,
                    "function_id":             function_id,
                    "evidence_level":          ev.get("evidence_level"),
                    "assay_category":          ev.get("assay_category"),
                    "validation_method_raw":   ev.get("validation_method_raw"),
                    "validation_method":       ev.get("validation_method"),
                    "readout_main":            ev.get("readout_main"),
                    "result_text_summary":     ev.get("result_text_summary"),
                    "result_value_raw":        ev.get("result_value_raw"),
                    "result_value_normalized": json.dumps(ev.get("result_value_normalized"),
                                                          ensure_ascii=False)
                                               if ev.get("result_value_normalized") else None,
                    "source_locations":        json.dumps(ev.get("source_locations"),
                                                          ensure_ascii=False)
                                               if ev.get("source_locations") else None,
                    "text_to_evidence":        ev.get("text_to_evidence"),
                    "trace_status":            ev.get("trace_status"),
                    "curator_note":            ev.get("curator_note"),
                }
                evidence_rows.append(ev_row)

    return [paper_row], record_rows, function_rows, evidence_rows


# ── 主流程 ────────────────────────────────────────────────────────────

def run(pdf_dir: str, out_dir: str) -> None:
    pdf_files = sorted(Path(pdf_dir).glob("*.pdf"))
    if not pdf_files:
        logger.warning("在 %s 下未找到任何 PDF 文件，退出。", pdf_dir)
        return

    logger.info("发现 %d 篇 PDF，开始处理 ...", len(pdf_files))
    parser, orchestrator = build_components()

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    counter = _load_counter(out_path)

    paper_csv    = out_path / "paper.csv"
    record_csv   = out_path / "paper_entity_record.csv"
    function_csv = out_path / "record_function.csv"
    evidence_csv = out_path / "function_assay_evidence.csv"

    # 追加模式（a），文件不存在时自动创建并写表头
    def _open_csv(path: Path, fields: list):
        is_new = not path.exists()
        f = open(path, "a", newline="", encoding="utf-8")
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        return f, writer

    fh_paper,    w_paper    = _open_csv(paper_csv,    PAPER_FIELDS)
    fh_record,   w_record   = _open_csv(record_csv,   RECORD_FIELDS)
    fh_function, w_function = _open_csv(function_csv, FUNCTION_FIELDS)
    fh_evidence, w_evidence = _open_csv(evidence_csv, EVIDENCE_FIELDS)

    try:
        for pdf_path in pdf_files:
            try:
                logger.info(">>> 处理: %s", pdf_path.name)
                chunks = parser.parse(str(pdf_path))
                logger.info("[%s] 解析完成，chunk=%d（table=%d，text=%d）",
                            pdf_path.name, len(chunks),
                            sum(1 for c in chunks if c.get("type") == "table"),
                            sum(1 for c in chunks if c.get("type") == "text"))

                result = orchestrator.process_pdf(str(pdf_path), chunks)

                paper_id = _make_paper_id(counter)
                counter += 1

                p_rows, r_rows, fn_rows, ev_rows = _flatten_result(
                    str(pdf_path), result, paper_id
                )

                w_paper.writerows(p_rows)
                w_record.writerows(r_rows)
                w_function.writerows(fn_rows)
                w_evidence.writerows(ev_rows)

                # 立即刷盘，防止中途崩溃丢失数据
                for fh in (fh_paper, fh_record, fh_function, fh_evidence):
                    fh.flush()

                logger.info(
                    "[%s] paper_id=%s | 实体=%d | 功能=%d | 证据=%d",
                    pdf_path.name, paper_id,
                    len(r_rows), len(fn_rows), len(ev_rows),
                )

            except Exception:
                logger.exception("处理 %s 时发生未预期异常，跳过", pdf_path.name)

    finally:
        _save_counter(out_path, counter)
        for fh in (fh_paper, fh_record, fh_function, fh_evidence):
            fh.close()

    logger.info("完成！输出目录: %s", out_dir)
    logger.info("  paper.csv               : %s", paper_csv)
    logger.info("  paper_entity_record.csv : %s", record_csv)
    logger.info("  record_function.csv     : %s", function_csv)
    logger.info("  function_assay_evidence.csv: %s", evidence_csv)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="PepClaw RAG Pipeline — 4 表关系型抽取流水线")
    ap.add_argument("--pdf_dir", default="v0_1PDF", help="PDF 文件目录（默认: v0_1PDF）")
    ap.add_argument("--out_dir", default="rag_outputs", help="输出目录（默认: rag_outputs）")
    args = ap.parse_args()
    run(args.pdf_dir, args.out_dir)
