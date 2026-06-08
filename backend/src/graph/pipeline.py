"""
pipeline.py — BioForge LangGraph 流水线编排

位置：backend/src/graph/
依赖：graph/state.py（PipelineState）、graph/nodes.py（各 agent node）
职责：用 LangGraph StateGraph 将四个 agent 节点串联成完整流水线。

节点顺序：
  START → guide → search → screen → extract → END

Checkpointer 说明：
  guide 节点使用 LangGraph interrupt() 暂停等待用户输入，
  必须传入 checkpointer 才能 resume。Demo 使用 MemorySaver，
  生产环境可换 PostgresSaver。
"""

from __future__ import annotations

from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from .nodes import extract_node, guide_node, screen_node, search_node
from .state import PipelineState


def _with_defaults(node, mode: str):
    """为 node 函数注入默认字段（agent_mode / run_id / errors 等）。"""
    def wrapped(state: PipelineState) -> dict:
        """包装后的 node：注入缺省字段后调用原 node，并确保关键字段传递。"""
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


def build_graph(
    mode: str = "mock",
    checkpointer=None,
):
    """构建并编译 BioForge 流水线图。

    Args:
        mode:         agent 运行模式（"mock" / "real"）。
        checkpointer: LangGraph checkpointer 实例（如 MemorySaver）。
                      guide 节点的 interrupt() 需要 checkpointer 才能 resume。

    Returns:
        编译后的 CompiledGraph。
    """
    builder = StateGraph(PipelineState)

    # guide 节点不经过 _with_defaults（interrupt 语义不同，mode 在 build_guide_node 已注入）
    builder.add_node("guide",   guide_node)
    builder.add_node("search",  _with_defaults(search_node,  mode))
    builder.add_node("screen",  _with_defaults(screen_node,  mode))
    builder.add_node("extract", _with_defaults(extract_node, mode))

    builder.add_edge(START,     "guide")
    builder.add_edge("guide",   "search")
    builder.add_edge("search",  "screen")
    builder.add_edge("screen",  "extract")
    builder.add_edge("extract", END)

    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()


# 模块级默认 graph（向后兼容，不传 checkpointer）
graph = build_graph()

__all__ = ["build_graph", "graph"]
