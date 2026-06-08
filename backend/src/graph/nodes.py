"""
nodes.py — BioForge LangGraph 节点定义

位置：backend/src/graph/
职责：将各 agent 包装为 LangGraph 节点函数，供 pipeline.py 注册到 StateGraph。

节点顺序：guide → search → screen → extract

guide  节点：通过 LangGraph interrupt() 三步对话产出三件核心物，需要 checkpointer
search 节点：调用 SearchAgent 检索 PubMed
screen 节点：调用 ScreenAgent 相关性筛选
extract节点：调用 ExtractAgent 结构化抽取
"""

from __future__ import annotations

import os
from typing import Any

from backend.src.agents.guide_agent.agent import build_guide_node
from .factory import create_agent, get_agent_mode
from .state import PipelineState


# ── Guide 节点（interrupt 机制，不走 AgentTemplate）────────────────────────
# GRAPH_AGENT_MODE=demo 时使用 DemoGuideAgent（正常调用 LLM）
# GRAPH_AGENT_MODE=real 时使用 RealGuideAgent（任意任务模式，v0.1 暂降级到 demo）
guide_node = build_guide_node(
    mode=os.getenv("GRAPH_AGENT_MODE", "demo"),
    model=os.getenv("DEFAULT_LLM_MODEL"),
)


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


def search_node(state: PipelineState) -> dict[str, Any]:
    agent = create_agent("search_agent", _mode(state))
    output = agent.run(
        {
            "run_id": state.get("run_id"),
            "query": state.get("query") or state.get("user_query"),
            "user_query": state.get("user_query") or state.get("query"),
            "pdf_path": state.get("pdf_path"),
            "pdf_name": state.get("pdf_name"),
        }
    )

    ok = _is_ok(output)
    updates: dict[str, Any] = {
        "current_stage": "screen",
        "ok": ok,
        "message": output.get("message") or output.get("search_summary") or output.get("search_agent_summary"),
        "candidate_paper_ids": list(output.get("candidate_paper_ids") or []),
        "candidates": list(output.get("candidates") or []),
        "search_summary": output.get("search_summary") or output.get("search_agent_summary") or "",
    }
    if "run_metadata" in output:
        updates["run_metadata"] = output["run_metadata"]
    if not ok:
        updates["current_stage"] = "error"
        updates["errors"] = _existing_errors(state) + [
            _error("search_agent", updates["message"] or "search_agent failed")
        ]
    return updates


def screen_node(state: PipelineState) -> dict[str, Any]:
    agent = create_agent("screen_agent", _mode(state))
    output = agent.run(
        {
            "run_id": state.get("run_id"),
            "query": state.get("query") or state.get("user_query"),
            "candidate_paper_ids": state.get("candidate_paper_ids") or [],
            "candidates": state.get("candidates") or [],
            "search_summary": state.get("search_summary"),
        }
    )

    ok = _is_ok(output)
    updates: dict[str, Any] = {
        "current_stage": "extract",
        "ok": ok,
        "message": output.get("message") or output.get("screen_summary") or output.get("screen_agent_summary"),
        "screened_paper_ids": list(output.get("screened_paper_ids") or []),
        "selected_paper": output.get("selected_paper"),
        "screen_summary": output.get("screen_summary") or output.get("screen_agent_summary") or "",
    }
    if "run_metadata" in output:
        updates["run_metadata"] = output["run_metadata"]
    if not ok:
        updates["current_stage"] = "error"
        updates["errors"] = _existing_errors(state) + [
            _error("screen_agent", updates["message"] or "screen_agent failed")
        ]
    return updates


def extract_node(state: PipelineState) -> dict[str, Any]:
    agent = create_agent("extract_agent", _mode(state))
    output = agent.run(
        {
            "run_id": state.get("run_id"),
            "pdf_path": state.get("pdf_path"),
            "pdf_name": state.get("pdf_name"),
            "screened_paper_ids": state.get("screened_paper_ids") or [],
            "selected_paper": state.get("selected_paper"),
            "screen_summary": state.get("screen_summary"),
        }
    )

    ok = _is_ok(output)
    extraction = output.get("extraction")
    updates: dict[str, Any] = {
        "current_stage": "done" if ok else "error",
        "ok": ok,
        "message": output.get("message") or output.get("extract_summary") or output.get("extract_agent_summary"),
        "extracted_record_ids": list(output.get("extracted_record_ids") or []),
        "extract_summary": output.get("extract_summary") or output.get("extract_agent_summary") or "",
        "extraction": extraction,
        "result": extraction if ok else None,
    }
    if "run_metadata" in output:
        updates["run_metadata"] = output["run_metadata"]
    if not ok:
        updates["errors"] = _existing_errors(state) + [
            _error("extract_agent", updates["message"] or "extract_agent failed")
        ]
    return updates


__all__ = ["extract_node", "screen_node", "search_node"]
