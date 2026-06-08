"""
pipeline.py — BioForge LangGraph 流水线编排

位置：backend/src/graph/
依赖：graph/state.py（PipelineState）、graph/nodes.py（各 agent node）
职责：用 LangGraph StateGraph 将四个 agent 节点串联成完整流水线。

节点顺序：
  START → guide → search → screen → extract → END

  guide:   引导节点，通过 LangGraph interrupt() 与用户三步对话，
           产出任务描述/字段模板/准入标准（三件核心物）
  search:  检索节点，调用 SearchAgent 检索 PubMed
  screen:  筛选节点，调用 ScreenAgent 相关性筛选（v0.1 TODO）
  extract: 抽取节点，调用 ExtractAgent 结构化抽取（v0.1 TODO）

Checkpointer 说明：
  guide 节点使用 LangGraph interrupt() 暂停等待用户输入，
  必须传入 checkpointer 才能 resume（从断点继续执行）。
  Demo 模式使用 SqliteSaver，生产环境换 PostgresSaver。
  不传 checkpointer（默认 None）时 interrupt 功能不可用，
  仅能在纯 mock 模式下跳过 guide 节点直接运行后续节点。
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph

from .state import PipelineState


def _with_defaults(node_fn, mode: str):
    """为 node 函数注入默认字段（run_id 等），返回包装后的 node。

    每个 node 运行时，若 state 中缺少 run_id，自动生成一个 pipeline 级 run_id，
    确保同一 pipeline run 的所有 trace 事件共享同一 ID。
    """
    def _wrapped_node(state: PipelineState) -> dict[str, Any]:
        """包装后的 node：确保 run_id 已初始化再调用原 node。"""
        # 若 run_id 未设置，生成 pipeline 级 run_id
        if not state.get("run_id"):
            # 用 PipelineState update 注入 run_id（LangGraph 会 merge 进 state）
            state = dict(state)
            state["run_id"] = f"pipe_{uuid.uuid4().hex[:12]}"
        return node_fn(state)
    return _wrapped_node


def build_graph(
    mode: str = "mock",
    checkpointer=None,
):
    """构建并编译 BioForge 流水线图。

    Args:
        mode: agent 运行模式，"mock"（使用 mock agent，不调真实 LLM）
              或 "real"（使用真实 agent）。
        checkpointer: LangGraph checkpointer 实例（如 SqliteSaver）。
                      guide 节点的 interrupt() 需要 checkpointer 才能 resume。
                      传 None 则 interrupt 功能不可用（仅 mock 模式无 guide 时可用）。

    Returns:
        编译后的 CompiledGraph，可调用 .stream() / .invoke() 执行。
    """
    # ── 延迟导入 nodes，避免模块加载时就触发 agent 初始化 ─────────────────
    from .nodes import (  # noqa: F401（各 node 函数）
        extract_node,
        guide_node,
        screen_node,
        search_node,
    )

    # ── 构建 StateGraph ────────────────────────────────────────────────────
    builder = StateGraph(PipelineState)

    # 添加四个节点（guide → search → screen → extract）
    # _with_defaults 确保 run_id 在第一个节点已初始化
    builder.add_node("guide",   _with_defaults(guide_node,   mode))
    builder.add_node("search",  _with_defaults(search_node,  mode))
    builder.add_node("screen",  _with_defaults(screen_node,  mode))
    builder.add_node("extract", _with_defaults(extract_node, mode))

    # 添加边：START → guide → search → screen → extract → END
    # guide 节点通过 interrupt() 与用户对话，需要 checkpointer 才能 resume
    builder.add_edge(START,     "guide")
    builder.add_edge("guide",   "search")
    builder.add_edge("search",  "screen")
    builder.add_edge("screen",  "extract")
    builder.add_edge("extract", END)

    # ── 编译图（若有 checkpointer 则传入，支持 interrupt/resume）────────────
    if checkpointer is not None:
        # 有 checkpointer：支持 guide 节点的 interrupt() 暂停和恢复
        return builder.compile(checkpointer=checkpointer)
    else:
        # 无 checkpointer：interrupt 功能不可用，适合纯 mock 批量运行
        return builder.compile()


# ── 模块级默认 graph（向后兼容，不传 checkpointer）────────────────────────
# 仅用于快速导入测试，生产/CLI 使用时请调用 build_graph(mode, checkpointer=...)
graph = build_graph()
