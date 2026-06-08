"""
nodes.py — BioForge LangGraph 节点定义

位置：backend/src/graph/
依赖：guide_agent/agent.py（build_guide_node）
      search_agent/agent.py（create_search_agent）
      graph/state.py（PipelineState）
职责：将各 agent 包装为 LangGraph 节点函数，供 pipeline.py 注册到 StateGraph。

节点顺序（见 pipeline.py）：
  START → guide → search → screen → extract → END

guide  节点：通过 LangGraph interrupt() 与用户三步对话，
             产出任务描述/字段模板/准入标准（三件核心物）
             此节点使用 interrupt()，需要 checkpointer 才能 resume
search 节点：调用 SearchAgent 检索 PubMed，产出候选文献 ID 列表
screen 节点：调用 ScreenAgent 相关性筛选（v0.1 stub，直通）
extract节点：调用 ExtractAgent 结构化抽取（v0.1 stub，直通）
"""

from __future__ import annotations

import os
from typing import Any

# ── 引导节点：不走 AgentTemplate，见 guide_agent/agent.py 顶部说明 ──────────
from backend.src.agents.guide_agent.agent import build_guide_node

# ── 检索节点：走 AgentTemplate（Plan-and-Execute）────────────────────────────
try:
    from backend.src.agents.search_agent.agent import create_search_agent
    _SEARCH_AVAILABLE = True
except ImportError:
    print("[nodes] ⚠️ search_agent 导入失败，search_node 将使用 stub")
    create_search_agent = None  # type: ignore
    _SEARCH_AVAILABLE = False


# ── 引导节点（guide_node）────────────────────────────────────────────────────
# 使用 LangGraph interrupt() 机制暂停等待用户输入，需要 checkpointer 支持
# mode 和 model 从环境变量读取，允许运行时覆盖
guide_node = build_guide_node(
    mode=os.getenv("GRAPH_AGENT_MODE", "mock"),
    model=os.getenv("DEFAULT_LLM_MODEL"),
)


# ── 检索节点（search_node）────────────────────────────────────────────────────
def search_node(state: Any) -> dict:
    """检索节点：调用 SearchAgent 检索 PubMed，产出候选文献 ID 列表。

    Args:
        state: PipelineState（含 run_id / task_description / query 等）。

    Returns:
        dict patch，含 candidate_paper_ids 和 search_summary。
    """
    if not _SEARCH_AVAILABLE or create_search_agent is None:
        # search_agent 不可用时返回空结果（不崩溃）
        return {
            "candidate_paper_ids": [],
            "search_summary": "search_agent 不可用，跳过检索",
            "ok": False,
        }

    try:
        # 从 state 读取 run_id（用于 trace 关联）
        run_id = state.get("run_id") if hasattr(state, "get") else None
        # 从 state 读取运行模式，决定使用 mock 还是 real agent
        mode   = os.getenv("GRAPH_AGENT_MODE", "mock")
        model  = os.getenv("DEFAULT_LLM_MODEL")

        # 创建 SearchAgent 实例并运行
        agent = create_search_agent(model=model) if model else create_search_agent()
        patch = agent.run(pipeline_state=dict(state), run_id=run_id)
        patch["ok"] = True
        return patch

    except Exception as e:
        # search_agent 运行失败不崩溃，返回失败状态
        print(f"[search_node] ❌ SearchAgent 运行失败：{e}")
        return {
            "candidate_paper_ids": [],
            "search_summary":      f"SearchAgent 运行失败：{e}",
            "ok":                  False,
        }


# ── 筛选节点（screen_node）────────────────────────────────────────────────────
def screen_node(state: Any) -> dict:
    """筛选节点：调用 ScreenAgent 相关性筛选。

    v0.1 状态：ScreenAgent 尚未实现，直通（将所有候选文献视为通过筛选）。

    Args:
        state: PipelineState（含 candidate_paper_ids / inclusion_criteria 等）。

    Returns:
        dict patch，含 screened_paper_ids 和 screen_summary。
    """
    # v0.1 stub：直通，将 candidate_paper_ids 作为 screened_paper_ids 返回
    candidate_ids = (
        state.get("candidate_paper_ids", [])
        if hasattr(state, "get") else []
    )
    return {
        "screened_paper_ids": candidate_ids,
        "screen_summary":     f"screen_agent v0.1 stub：直通 {len(candidate_ids)} 篇",
        "ok":                 True,
    }


# ── 抽取节点（extract_node）──────────────────────────────────────────────────
def extract_node(state: Any) -> dict:
    """抽取节点：调用 ExtractAgent 结构化抽取。

    v0.1 状态：ExtractAgent 尚未实现，直通（不做实际抽取）。

    Args:
        state: PipelineState（含 screened_paper_ids / db_schema 等）。

    Returns:
        dict patch，含 extracted_record_ids 和 extract_summary。
    """
    # v0.1 stub：直通，不做实际抽取
    screened_ids = (
        state.get("screened_paper_ids", [])
        if hasattr(state, "get") else []
    )
    return {
        "extracted_record_ids": [],
        "extract_summary":      f"extract_agent v0.1 stub：待抽取 {len(screened_ids)} 篇，暂未实现",
        "ok":                   True,
    }


# ── 公开接口 ──────────────────────────────────────────────────────────────────
__all__ = ["guide_node", "search_node", "screen_node", "extract_node"]
