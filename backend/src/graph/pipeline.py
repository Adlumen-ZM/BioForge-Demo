"""
pipeline.py — BioForge LangGraph 流水线编排

位置：backend/src/graph/
依赖：graph/state.py（PipelineState）、graph/nodes.py（各 agent node）
职责：用 LangGraph StateGraph 将节点串联成完整流水线。

节点顺序：
  START → guide → search → screen →
  prepare_extraction_context → extract → write_rag_csv_to_db → finalize → END

条件边（短路到 finalize）：
  search  → finalize：candidate_paper_ids 为空
  screen  → finalize：pdf_path 为空 / 下载状态非 downloaded|already_exists
  extract → finalize：rag_csv_files 不完整（缺少 5 张表任一）

Checkpointer 说明：
  guide 节点使用 LangGraph interrupt() 暂停等待用户输入，
  必须传入 checkpointer 才能 resume。Demo 使用 MemorySaver，
  生产环境可换 PostgresSaver。
"""

from __future__ import annotations

import os
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from .nodes import (
    extract_node,
    finalize_node,
    guide_node,
    prepare_extraction_context_node,
    screen_node,
    search_node,
    write_db_node,
)
from .state import PipelineState


# ── 路由函数 ──────────────────────────────────────────────────────────────────

def _route_after_search(state: PipelineState) -> str:
    """没有候选文献时直接进入 finalize。"""
    return "finalize" if not state.get("candidate_paper_ids") else "screen"


def _route_after_screen(state: PipelineState) -> str:
    """没有成功下载的 PDF 时直接进入 finalize。"""
    pdf_path  = state.get("pdf_path")
    dl_status = state.get("download_status")
    if not pdf_path or dl_status not in ("downloaded", "already_exists"):
        return "finalize"
    return "prepare_extraction_context"


def _route_after_extract(state: PipelineState) -> str:
    """RAG CSV 不完整时直接进入 finalize。"""
    rag_csv_files = state.get("rag_csv_files") or {}
    required = {
        "paper", "paper_entity_record", "entity_component",
        "record_function", "function_assay_evidence",
    }
    if not state.get("rag_csv_dir") or not required.issubset(rag_csv_files.keys()):
        return "finalize"
    return "write_rag_csv_to_db"


# ── _with_defaults ────────────────────────────────────────────────────────────

def _with_defaults(node, mode: str):
    """为 node 函数注入默认字段（agent_mode / run_id / trace_dir / artifacts_dir 等）。"""
    def wrapped(state: PipelineState) -> dict:
        next_state: PipelineState = dict(state)
        next_state.setdefault("agent_mode", mode)
        next_state.setdefault("run_id", f"pipe_{uuid4().hex[:12]}")
        next_state.setdefault("current_stage", "init")
        next_state.setdefault("ok", True)
        next_state.setdefault("errors", [])
        run_id    = next_state["run_id"]
        data_root = os.getenv("DATA_ROOT", "data")
        next_state.setdefault("trace_dir",     f"{data_root}/runs/{run_id}/trace")
        next_state.setdefault("artifacts_dir", f"{data_root}/runs/{run_id}/artifacts")
        updates = node(next_state)
        updates.setdefault("agent_mode",    next_state["agent_mode"])
        updates.setdefault("run_id",        next_state["run_id"])
        updates.setdefault("errors",        next_state["errors"])
        updates.setdefault("trace_dir",     next_state["trace_dir"])
        updates.setdefault("artifacts_dir", next_state["artifacts_dir"])
        return updates
    return wrapped


# ── build_graph ───────────────────────────────────────────────────────────────

def build_graph(
    mode: str = "mock",
    checkpointer=None,
):
    """构建并编译 BioForge 流水线图。

    Args:
        mode:         agent 运行模式（"mock" / "demo" / "real"）。
        checkpointer: LangGraph checkpointer 实例（如 MemorySaver）。
                      guide 节点的 interrupt() 需要 checkpointer 才能 resume。

    Returns:
        编译后的 CompiledGraph。
    """
    builder = StateGraph(PipelineState)

    # guide 不经过 _with_defaults（interrupt 语义不同，mode 在 build_guide_node 已注入）
    builder.add_node("guide",                      guide_node)
    builder.add_node("search",                     _with_defaults(search_node,                     mode))
    builder.add_node("screen",                     _with_defaults(screen_node,                     mode))
    builder.add_node("prepare_extraction_context", _with_defaults(prepare_extraction_context_node,  mode))
    builder.add_node("extract",                    _with_defaults(extract_node,                    mode))
    builder.add_node("write_rag_csv_to_db",        _with_defaults(write_db_node,                   mode))
    builder.add_node("finalize",                   _with_defaults(finalize_node,                   mode))

    # 线性边
    builder.add_edge(START,   "guide")
    builder.add_edge("guide", "search")

    # 条件边：search / screen / extract 可短路到 finalize
    builder.add_conditional_edges(
        "search",
        _route_after_search,
        {"screen": "screen", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "screen",
        _route_after_screen,
        {"prepare_extraction_context": "prepare_extraction_context", "finalize": "finalize"},
    )
    builder.add_edge("prepare_extraction_context", "extract")
    builder.add_conditional_edges(
        "extract",
        _route_after_extract,
        {"write_rag_csv_to_db": "write_rag_csv_to_db", "finalize": "finalize"},
    )
    builder.add_edge("write_rag_csv_to_db", "finalize")
    builder.add_edge("finalize", END)

    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()


# 模块级默认 graph（向后兼容，不传 checkpointer；不支持 interrupt/resume）
graph = build_graph()

__all__ = ["build_graph", "graph"]
