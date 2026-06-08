from __future__ import annotations

from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from .nodes import extract_node, screen_node, search_node
from .state import PipelineState


def _with_defaults(node, mode: str):
    def wrapped(state: PipelineState) -> dict:
        next_state: PipelineState = dict(state)
        next_state.setdefault("agent_mode", mode)
        next_state.setdefault("run_id", f"pipe_{uuid4().hex[:12]}")
        next_state.setdefault("current_stage", "init")
        next_state.setdefault("ok", True)
        next_state.setdefault("errors", [])
        updates = node(next_state)
        updates.setdefault("agent_mode", next_state["agent_mode"])
        updates.setdefault("run_id", next_state["run_id"])
        updates.setdefault("errors", next_state["errors"])
        return updates

    return wrapped


def build_graph(mode: str = "mock"):
    builder = StateGraph(PipelineState)

    builder.add_node("search", _with_defaults(search_node, mode))
    builder.add_node("screen", _with_defaults(screen_node, mode))
    builder.add_node("extract", _with_defaults(extract_node, mode))

    builder.add_edge(START, "search")
    builder.add_edge("search", "screen")
    builder.add_edge("screen", "extract")
    builder.add_edge("extract", END)

    return builder.compile()


graph = build_graph()

__all__ = ["build_graph", "graph"]
