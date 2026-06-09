# -*- coding: utf-8 -*-
"""
nodes.py — BioForge LangGraph 节点定义

位置：backend/src/graph/
职责：将各 agent 包装为 LangGraph 节点函数，供 pipeline.py 注册到 StateGraph。

节点顺序（主 pipeline）：
  guide → init_business_db → search → screen → extract → write_rag_csv_to_db → finalize

重试策略：
  search_node  — agent 调用抛出异常时重试最多 3 次（指数退避）；空结果不重试（正常语义）
  screen_node  — 全部 PDF 下载失败时重试最多 3 次；部分失败则继续使用已下载文件
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from backend.src.agents.guide_agent.agent import build_guide_node
from backend.src.db_access.business import (
    ensure_business_db,
    get_rag_extraction_contract,
    write_rag_csv_to_business_db,
)
from .factory import create_agent, get_agent_mode
from .state import PipelineState


# ── Guide 节点（interrupt 机制，不走 AgentTemplate）────────────────────────
# GRAPH_AGENT_MODE 在模块导入时读取；run_demo_pipeline.py 需在 import nodes 前设置该变量
guide_node = build_guide_node(
    mode=os.getenv("GRAPH_AGENT_MODE", "demo"),
    model=os.getenv("DEFAULT_LLM_MODEL"),
)


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _mode(state: PipelineState) -> str:
    return get_agent_mode(state.get("agent_mode"))


def _existing_errors(state: PipelineState) -> list[dict[str, Any]]:
    return list(state.get("errors") or [])


def _error(agent_name: str, message: str) -> dict[str, Any]:
    return {"agent": agent_name, "message": message}


def _is_ok(output: dict[str, Any]) -> bool:
    if "ok" in output:
        return bool(output["ok"])
    metadata = output.get("run_metadata") or {}
    return metadata.get("status") in {None, "success"}


def _save_artifact(artifacts_dir: str | None, filename: str, data: Any) -> str | None:
    """将 data 序列化为 JSON 并写入 artifacts_dir/{filename}，返回路径。"""
    if not artifacts_dir:
        return None
    try:
        Path(artifacts_dir).mkdir(parents=True, exist_ok=True)
        path = str(Path(artifacts_dir) / filename)
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path
    except Exception:
        return None


def _trace_safe(event_type: str, **kwargs: Any) -> None:
    """静默调用 trace_manager.record()；失败时不影响主流程。"""
    try:
        from backend.src.db_access.trace.trace_manager import record
        record(event_type, **kwargs)
    except Exception:
        pass


# ── init_db_node（保留向后兼容，不再注册到主 pipeline）─────────────────────

def init_db_node(state: PipelineState) -> dict[str, Any]:
    """初始化业务 SQLite 数据库（旧接口，保留向后兼容；主 pipeline 使用 prepare_extraction_context_node）。"""
    template_id        = state.get("template_id") or os.getenv("EXTRACTION_PROFILE", "hap_peptide_v1")
    extraction_profile = state.get("extraction_profile") or template_id
    db_path            = state.get("biz_db_path")

    result = ensure_business_db(
        template_id=template_id,
        extraction_profile=extraction_profile,
        db_path=db_path,
    )

    updates: dict[str, Any] = {
        "current_stage":      "search",
        "biz_db_init_result": result,
        "template_id":        template_id,
        "extraction_profile": extraction_profile,
    }
    if result.get("status") == "ok":
        updates["biz_db_path"] = result["db_path"]
        updates["ok"] = True
    else:
        updates["ok"] = False
        updates["current_stage"] = "error"
        updates["errors"] = _existing_errors(state) + [
            _error("init_db", result.get("error") or "业务数据库初始化失败")
        ]
    return updates


# ── prepare_extraction_context_node（主 pipeline 的 init_business_db 节点）──

def prepare_extraction_context_node(state: PipelineState) -> dict[str, Any]:
    """
    流水线初始化节点（在 guide 之后、search 之前执行）：
      1. 初始化业务 SQLite 数据库（幂等，已存在则跳过建表）
      2. 加载 RAG extraction contract（供 extract_node 使用）
      3. 推导 schema_template_path / field_mapping_path
    """
    template_id        = state.get("template_id") or os.getenv("EXTRACTION_PROFILE", "hap_peptide_v1")
    extraction_profile = state.get("extraction_profile") or template_id

    # 1. 初始化业务 DB
    db_result = ensure_business_db(
        template_id=template_id,
        extraction_profile=extraction_profile,
        db_path=state.get("biz_db_path"),
    )
    _trace_safe(
        "business_db_initialized",
        stage="init_business_db",
        payload={"status": db_result.get("status"), "db_path": db_result.get("db_path")},
    )

    # 2. 加载 RAG extraction contract
    contract: dict[str, Any] = {}
    try:
        contract = get_rag_extraction_contract(template_id=template_id)
        _trace_safe("rag_extraction_contract_loaded", stage="init_business_db",
                    payload={"template_id": template_id})
    except Exception:
        pass  # contract 为空时 extract_node 内部工具会重新尝试加载

    # 3. 推导模板文件路径
    project_root = Path(__file__).resolve().parents[4]
    schema_template_path = (
        state.get("schema_template_path")
        or os.getenv("SCHEMA_TEMPLATE_PATH")
        or str(project_root / "docs" / "schema_templates" / template_id / "schema.yaml")
    )
    field_mapping_path = (
        os.getenv("FIELD_MAPPING_PATH")
        or str(project_root / "docs" / "schema_templates" / template_id / "field_mapping.yaml")
    )

    ok = db_result.get("status") == "ok"
    updates: dict[str, Any] = {
        "current_stage":           "search",
        "biz_db_path":             db_result.get("db_path"),
        "biz_db_init_result":      db_result,
        "rag_extraction_contract": contract,
        "schema_template_path":    schema_template_path,
        "field_mapping_path":      field_mapping_path,
        "template_id":             template_id,
        "extraction_profile":      extraction_profile,
    }
    if not ok:
        updates["ok"] = False
        updates["errors"] = _existing_errors(state) + [
            _error("init_business_db", db_result.get("error") or "业务数据库初始化失败")
        ]
    return updates


# ── write_db_node（CSV → SQLite，保留原名和别名）────────────────────────────

def write_db_node(state: PipelineState) -> dict[str, Any]:
    """将 RAG 输出的多表 CSV 写入业务 SQLite 数据库。"""
    csv_dir            = state.get("rag_csv_dir")
    db_path            = state.get("biz_db_path")
    template_id        = state.get("template_id") or os.getenv("EXTRACTION_PROFILE", "hap_peptide_v1")
    extraction_profile = state.get("extraction_profile") or template_id
    run_id             = state.get("run_id")
    paper_key          = state.get("paper_key")

    if not csv_dir:
        return {
            "current_stage": "done",
            "ok": True,
            "db_write_result": {"status": "skipped", "reason": "rag_csv_dir 未设置"},
        }

    _trace_safe("rag_csv_write_started", stage="write_rag_csv_to_db",
                payload={"csv_dir": csv_dir, "db_path": db_path})

    result = write_rag_csv_to_business_db(
        csv_dir=csv_dir,
        db_path=db_path,
        template_id=template_id,
        extraction_profile=extraction_profile,
        run_id=run_id,
        paper_key=paper_key,
    )

    ok = result.get("status") == "ok"
    _trace_safe(
        "rag_csv_written_to_db" if ok else "db_persist_failed",
        stage="write_rag_csv_to_db",
        status="success" if ok else "failed",
        payload=result,
    )

    updates: dict[str, Any] = {
        "current_stage": "done" if ok else "error",
        "ok":            ok,
        "db_write_result": result,
    }
    if not ok:
        updates["errors"] = _existing_errors(state) + [
            _error("write_db", result.get("error") or "CSV 写库失败")
        ]
    return updates


# write_rag_csv_to_db_node 是 write_db_node 的别名（与 pipeline.py 节点名对齐）
write_rag_csv_to_db_node = write_db_node


# ── finalize_node ─────────────────────────────────────────────────────────────

def finalize_node(state: PipelineState) -> dict[str, Any]:
    """
    流水线收尾节点：
      1. 根据 state 推导最终 status
      2. 写 trace/summary.json
      3. 写 trace/timeline.md
    """
    run_id    = state.get("run_id", "unknown")
    data_root = os.getenv("DATA_ROOT", "data")
    trace_dir = state.get("trace_dir") or f"{data_root}/runs/{run_id}/trace"
    Path(trace_dir).mkdir(parents=True, exist_ok=True)

    # 推导最终状态
    candidate_ids   = state.get("candidate_paper_ids") or []
    download_results = state.get("download_results") or []
    successful_dl   = [
        r for r in download_results
        if r.get("download_status") in ("downloaded", "already_exists")
    ]
    pdf_path        = state.get("pdf_path") or (successful_dl[0].get("pdf_path") if successful_dl else None)
    rag_csv_dir     = state.get("rag_csv_dir")
    db_write_result = state.get("db_write_result") or {}

    if not candidate_ids:
        final_status = "no_candidates"
    elif not pdf_path and not successful_dl:
        final_status = "no_pdf_downloaded"
    elif not rag_csv_dir:
        final_status = "extraction_failed"
    elif db_write_result.get("status") not in (None, "ok", "skipped"):
        final_status = "db_write_failed"
    elif state.get("errors"):
        final_status = "error"
    else:
        final_status = "success"

    # summary.json
    summary: dict[str, Any] = {
        "run_id":           run_id,
        "status":           final_status,
        "profile":          state.get("extraction_profile"),
        "template_id":      state.get("template_id"),
        "candidate_count":  len(candidate_ids),
        "query_strings":    state.get("query_strings") or [],
        "search_summary":   state.get("search_summary"),
        "screen_summary":   state.get("screen_summary"),
        "extract_summary":  state.get("extract_summary"),
        "paper_key":        state.get("paper_key"),
        "pdf_path":         pdf_path,
        "rag_csv_dir":      rag_csv_dir,
        "rag_csv_files":    state.get("rag_csv_files"),
        "biz_db_path":      state.get("biz_db_path"),
        "db_write_result":  db_write_result,
        "errors":           state.get("errors") or [],
        "search_artifact_path":  state.get("search_artifact_path"),
        "download_report_path":  state.get("download_report_path"),
    }
    summary_path = str(Path(trace_dir) / "summary.json")
    Path(summary_path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # timeline.md
    timeline_path = str(Path(trace_dir) / "timeline.md")
    lines = [
        f"# Run {run_id} Timeline\n\n",
        f"- **status**: `{final_status}`\n",
        f"- **profile**: {state.get('extraction_profile', '-')}\n",
    ]
    if state.get("query_strings"):
        qs = ", ".join(f'"{q}"' for q in state["query_strings"][:3])
        lines.append(f"- **queries**: {qs}\n")
    if state.get("search_summary"):
        lines.append(f"- **search**: {state['search_summary']}\n")
    if state.get("screen_summary"):
        lines.append(f"- **screen**: {state['screen_summary']}\n")
    if pdf_path:
        lines.append(f"- **pdf**: {pdf_path}\n")
    if state.get("extract_summary"):
        lines.append(f"- **extract**: {state['extract_summary']}\n")
    if db_write_result:
        lines.append(f"- **db_write**: {db_write_result.get('status', '-')}\n")
    if state.get("biz_db_path"):
        lines.append(f"- **db_path**: {state['biz_db_path']}\n")
    Path(timeline_path).write_text("".join(lines), encoding="utf-8")

    return {
        "status":        final_status,
        "current_stage": "done",
        "summary_path":  summary_path,
        "timeline_path": timeline_path,
    }


# ── search_node ───────────────────────────────────────────────────────────────

_SEARCH_MAX_RETRIES = 3   # 网络异常最多重试次数
_SCREEN_MAX_RETRIES = 3   # 全部下载失败最多重试次数


def search_node(state: PipelineState) -> dict[str, Any]:
    """调用 SearchAgent，执行 PubMed 多轮检索并保存 artifact。

    重试策略：agent.run() 抛出异常（网络/超时）时最多重试 3 次，指数退避 1/2/4 秒。
    空结果（无候选文献）不重试，视为正常检索结果。
    """
    _trace_safe("search_started", stage="search",
                payload={"query": state.get("query") or state.get("user_query")})

    agent = create_agent("search_agent", _mode(state))
    input_data = {
        "run_id":                     state.get("run_id"),
        "query":                      state.get("query") or state.get("user_query") or state.get("user_input"),
        "user_query":                 state.get("user_query") or state.get("query") or state.get("user_input"),
        "user_input":                 state.get("user_input") or state.get("raw_user_prompt"),
        "refined_task_prompt":        state.get("refined_task_prompt"),
        "refined_screening_criteria": state.get("refined_screening_criteria"),
        "template_id":                state.get("template_id"),
    }

    output: dict[str, Any] = {}
    last_exc: Exception | None = None

    for attempt in range(_SEARCH_MAX_RETRIES):
        try:
            output = agent.run(input_data)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if attempt < _SEARCH_MAX_RETRIES - 1:
                wait = 2 ** attempt  # 1, 2 秒
                _trace_safe("search_started", stage="search",
                            payload={"retry_attempt": attempt + 1, "error": str(exc), "wait_s": wait})
                time.sleep(wait)

    if last_exc is not None:
        return {
            "current_stage": "error",
            "ok":            False,
            "candidate_paper_ids": [],
            "candidates":          [],
            "errors": _existing_errors(state) + [
                _error("search_agent", f"连接失败（重试 {_SEARCH_MAX_RETRIES} 次）: {last_exc}")
            ],
        }

    ok            = _is_ok(output)
    candidate_ids = list(output.get("candidate_paper_ids") or [])
    candidates    = list(output.get("candidates") or [])

    # 兜底层 1：dedup_filter 成功输出 candidate_paper_ids，但 candidates 为空
    # → 从 raw_candidates（executor 重建的完整元数据列表）匹配补全
    if candidate_ids and not candidates:
        raw_cands = list(output.get("raw_candidates") or [])
        id_set = set(candidate_ids)
        candidates = [c for c in raw_cands if str(c.get("pmid") or "").strip() in id_set]

    # 兜底层 2：dedup_filter 未能输出 candidate_paper_ids
    # → 从 raw_candidates 或 raw_candidate_ids 提取
    if not candidate_ids:
        raw_cands = list(output.get("raw_candidates") or [])
        raw_ids   = list(output.get("raw_candidate_ids") or [])

        if raw_cands:
            seen: set[str] = set()
            for c in raw_cands:
                pid = str(c.get("pmid") or "").strip()
                if pid and pid not in seen:
                    candidate_ids.append(pid)
                    candidates.append(c)
                    seen.add(pid)
        elif raw_ids:
            seen_ids: set[str] = set()
            for pid in raw_ids:
                pid = str(pid).strip()
                if pid and pid not in seen_ids:
                    candidate_ids.append(pid)
                    seen_ids.add(pid)

        if candidate_ids:
            _trace_safe("search_fallback_extract", stage="search",
                        payload={"fallback_count": len(candidate_ids),
                                 "note": "从 raw_candidates/raw_candidate_ids 兜底提取"})
            ok = True
    queries       = output.get("queries") or []
    query_strings = [q.get("query_string", "") for q in queries if q.get("query_string")]

    # 保存 search_candidates artifact
    artifact_path = _save_artifact(
        state.get("artifacts_dir"),
        "search_candidates.json",
        {
            "queries":              queries,
            "candidate_paper_ids":  candidate_ids,
            "candidates":           candidates,
            "search_stats":         output.get("search_stats") or {},
        },
    )

    _trace_safe("search_finished", stage="search",
                payload={"candidate_count": len(candidate_ids), "query_count": len(queries)})

    updates: dict[str, Any] = {
        "current_stage":       "screen",
        "ok":                  ok,
        "message":             output.get("message") or output.get("search_summary") or "",
        "candidate_paper_ids": candidate_ids,
        "candidates":          candidates,
        "queries":             queries,
        "query_strings":       query_strings,
        "search_summary":      output.get("search_summary") or output.get("search_agent_summary") or "",
        "search_artifact_path": artifact_path,
    }
    if "run_metadata" in output:
        updates["run_metadata"] = output["run_metadata"]
    if not ok:
        updates["current_stage"] = "error"
        updates["errors"] = _existing_errors(state) + [
            _error("search_agent", updates["message"] or "search_agent failed")
        ]
    return updates


# ── screen_node ───────────────────────────────────────────────────────────────

def screen_node(state: PipelineState) -> dict[str, Any]:
    """调用 ScreenAgent，执行相关性筛选 + PDF 下载，并保存 artifact。

    重试策略：全部 PDF 下载失败时最多重试 3 次；部分失败则使用已下载的文件继续。
    """
    _trace_safe("screen_started", stage="screen",
                payload={"candidate_count": len(state.get("candidate_paper_ids") or [])})

    agent = create_agent("screen_agent", _mode(state))
    input_data = {
        "run_id":                     state.get("run_id"),
        "query":                      state.get("query") or state.get("user_query"),
        "candidate_paper_ids":        state.get("candidate_paper_ids") or [],
        "candidates":                 state.get("candidates") or [],
        "search_summary":             state.get("search_summary"),
        "refined_screening_criteria": state.get("refined_screening_criteria"),
        "extraction_profile":         state.get("extraction_profile"),
        "template_id":                state.get("template_id"),
    }

    output: dict[str, Any] = {}
    last_exc: Exception | None = None

    for attempt in range(_SCREEN_MAX_RETRIES):
        try:
            output = agent.run(input_data)
            download_results = output.get("download_results") or []
            successful = [
                r for r in download_results
                if r.get("download_status") in ("downloaded", "already_exists")
            ]
            # 有成功下载 → 不重试
            if successful or not download_results:
                last_exc = None
                break
            # 全部失败且还有重试机会
            if attempt < _SCREEN_MAX_RETRIES - 1:
                wait = 2 ** attempt
                _trace_safe("screen_started", stage="screen",
                            payload={"retry_attempt": attempt + 1,
                                     "reason": "all_downloads_failed", "wait_s": wait})
                time.sleep(wait)
        except Exception as exc:
            last_exc = exc
            if attempt < _SCREEN_MAX_RETRIES - 1:
                wait = 2 ** attempt
                time.sleep(wait)

    if last_exc is not None and not output:
        return {
            "current_stage": "error",
            "ok":            False,
            "errors": _existing_errors(state) + [
                _error("screen_agent", f"连接失败（重试 {_SCREEN_MAX_RETRIES} 次）: {last_exc}")
            ],
        }

    ok               = _is_ok(output)
    download_results = output.get("download_results") or []

    # 提取第一个成功下载的 PDF 作为 primary
    successful = [
        r for r in download_results
        if r.get("download_status") in ("downloaded", "already_exists")
    ]
    first = successful[0] if successful else None

    paper_key   = output.get("paper_key")     or (first.get("paper_key")     if first else None)
    pdf_path    = output.get("pdf_path")      or (first.get("pdf_path")      if first else None)
    dl_status   = output.get("download_status") or (first.get("download_status") if first else "failed")
    file_sha256 = output.get("file_sha256")   or (first.get("file_sha256")   if first else None)

    # 保存 download_report artifact
    download_report_path = _save_artifact(
        state.get("artifacts_dir"),
        "download_report.json",
        {
            "download_results": download_results,
            "successful_count": len(successful),
            "paper_key":        paper_key,
            "pdf_path":         pdf_path,
            "download_status":  dl_status,
        },
    )
    if download_report_path:
        _trace_safe(
            "download_report_saved",
            stage="screen",
            payload={
                "download_report_path": download_report_path,
                "success_count": len(successful),
                "failed_count": len(download_results) - len(successful),
            },
        )

    _trace_safe("screen_finished", stage="screen",
                payload={
                    "screened_count":    len(output.get("screened_paper_ids") or []),
                    "downloaded_count":  len(successful),
                    "total_attempted":   len(download_results),
                })

    updates: dict[str, Any] = {
        "current_stage":       "extract",
        "ok":                  ok,
        "message":             output.get("message") or output.get("screen_summary") or "",
        "screened_paper_ids":  list(output.get("screened_paper_ids") or []),
        "selected_paper":      output.get("selected_paper"),
        "screen_summary":      output.get("screen_summary") or output.get("screen_agent_summary") or "",
        "paper_key":           paper_key,
        "pdf_path":            pdf_path,
        "download_status":     dl_status,
        "file_sha256":         file_sha256,
        "download_results":    download_results,
        "download_report_path": download_report_path,
    }
    if "run_metadata" in output:
        updates["run_metadata"] = output["run_metadata"]
    if not ok:
        updates["current_stage"] = "error"
        updates["errors"] = _existing_errors(state) + [
            _error("screen_agent", updates["message"] or "screen_agent failed")
        ]
    return updates


# ── extract_node ──────────────────────────────────────────────────────────────

def extract_node(state: PipelineState) -> dict[str, Any]:
    """调用 ExtractAgent，执行 RAG CSV 生成。"""
    paper_key          = state.get("paper_key")
    extraction_profile = state.get("extraction_profile") or os.getenv("EXTRACTION_PROFILE", "hap_peptide_v1")
    template_id        = state.get("template_id") or extraction_profile
    pdf_path           = state.get("pdf_path")

    # 构造 output_dir
    data_root  = os.getenv("DATA_ROOT", "data")
    output_dir = f"{data_root}/projects/{extraction_profile}/papers/{paper_key or 'unknown'}/outputs/rag_csv"

    _trace_safe("rag_extraction_started", stage="extract",
                payload={"pdf_path": pdf_path, "template_id": template_id})

    agent = create_agent("extract_agent", _mode(state))
    output = agent.run(
        {
            "run_id":                  state.get("run_id"),
            "pdf_path":                pdf_path,
            "pdf_name":                state.get("pdf_name"),
            "paper_key":               paper_key,
            "extraction_profile":      extraction_profile,
            "template_id":             template_id,
            "output_dir":              output_dir,
            "schema_template_path":    state.get("schema_template_path"),
            "rag_extraction_contract": state.get("rag_extraction_contract"),
            "screened_paper_ids":      state.get("screened_paper_ids") or [],
            "selected_paper":          state.get("selected_paper"),
            "screen_summary":          state.get("screen_summary"),
        }
    )

    ok            = _is_ok(output)
    rag_csv_dir   = output.get("rag_csv_dir") or output.get("output_dir")
    rag_csv_files = output.get("rag_csv_files") or output.get("csv_files")

    csv_quality = output.get("csv_quality_status") or ("pass" if ok and rag_csv_files else "unknown")

    _trace_safe(
        "extract_finished",
        stage="extract",
        status="success" if ok else "failed",
        payload={
            "rag_csv_dir":       rag_csv_dir,
            "csv_table_count":   len(rag_csv_files) if rag_csv_files else 0,
            "csv_quality_status": csv_quality,
        },
    )

    updates: dict[str, Any] = {
        "current_stage":        "done" if ok else "error",
        "ok":                   ok,
        "message":              output.get("message") or output.get("extract_summary") or "",
        "extracted_record_ids": list(output.get("extracted_record_ids") or []),
        "extract_summary":      output.get("extract_summary") or output.get("extract_agent_summary") or "",
        "extraction":           output.get("extraction"),
        "result":               output.get("extraction") if ok else None,
        "rag_csv_dir":          rag_csv_dir,
        "rag_csv_files":        rag_csv_files,
        "ragflow_ref":          output.get("ragflow_ref"),
        "csv_quality_status":   csv_quality,
        "csv_quality_issues":   output.get("csv_quality_issues") or [],
    }
    if "run_metadata" in output:
        updates["run_metadata"] = output["run_metadata"]
    if not ok:
        updates["errors"] = _existing_errors(state) + [
            _error("extract_agent", updates["message"] or "extract_agent failed")
        ]
    return updates


__all__ = [
    "extract_node",
    "finalize_node",
    "guide_node",
    "init_db_node",
    "prepare_extraction_context_node",
    "screen_node",
    "search_node",
    "write_db_node",
    "write_rag_csv_to_db_node",
]
