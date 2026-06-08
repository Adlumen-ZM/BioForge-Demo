"""
factory.py — BioForge Agent 工厂（mock/real 模式切换）

位置：backend/src/graph/
依赖：各 agent 的工厂函数或 Agent 类
职责：根据运行模式（mock/real）返回对应的 Agent 实例或工厂函数，
     供 nodes.py 的各 node wrapper 按需调用。

mock 模式：不调用真实 LLM，使用 mock tools，适合本地开发和 CI 测试。
real 模式：调用真实 LLM 和工具，适合生产运行。

注意：guide_agent 不走 AgentTemplate（无 plan.yaml，无多步 executor），
     因此这里存储的是 Agent 类而非 AgentTemplateConfig。
     search/screen/extract 存储工厂函数（返回 AgentTemplate 实例）。
"""

from __future__ import annotations

# ── Guide Agent 导入（不走 AgentTemplate，见 guide_agent/agent.py 顶部说明）────
# 引导员不走 Plan-and-Execute 模板，直接 litellm.completion + interrupt()
from backend.src.agents.guide_agent.agent import MockGuideAgent, RealGuideAgent

# ── Search Agent 导入 ─────────────────────────────────────────────────────────
try:
    from backend.src.agents.search_agent.agent import create_search_agent
    _SEARCH_AVAILABLE = True
except ImportError:
    print("[factory] ⚠️ search_agent 导入失败")
    create_search_agent = None  # type: ignore
    _SEARCH_AVAILABLE = False


# ── Agent 注册表 ──────────────────────────────────────────────────────────────
# 结构：{mode: {agent_name: agent_class_or_factory}}
# guide_agent：存 Agent 类（Mock/Real），由 build_guide_node 内部实例化
#              不走 AgentTemplate，见 guide_agent/agent.py 顶部说明
# search/screen/extract：存工厂函数，返回 AgentTemplate 实例
_AGENTS: dict[str, dict[str, object]] = {
    "mock": {
        "guide_agent":   MockGuideAgent,      # 引导员 mock：固定三步 payload，不调 LLM
        "search_agent":  create_search_agent, # 检索 mock：stub pubmed_search，不连真实 API
        "screen_agent":  None,                # TODO v0.2
        "extract_agent": None,                # TODO v0.2
    },
    "real": {
        "guide_agent":   RealGuideAgent,      # 引导员 real：真实 LLM 调用
        "search_agent":  create_search_agent, # 检索 real：连接真实 PubMed API
        "screen_agent":  None,                # TODO v0.2
        "extract_agent": None,                # TODO v0.2
    },
}


def get_agent(mode: str, agent_name: str):
    """根据运行模式获取对应的 Agent 类或工厂函数。

    Args:
        mode: 运行模式，"mock" 或 "real"。
        agent_name: agent 名称，如 "guide_agent"、"search_agent"。

    Returns:
        Agent 类（guide_agent）或工厂函数（search/screen/extract），
        若不存在返回 None。
    """
    mode_agents = _AGENTS.get(mode, _AGENTS["mock"])
    agent = mode_agents.get(agent_name)
    if agent is None:
        print(f"[factory] ⚠️ {agent_name} 在 {mode} 模式下未实现，返回 None")
    return agent
