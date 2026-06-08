"""
factory.py — BioForge Agent 工厂（mock/real 模式切换）

位置：backend/src/graph/
职责：根据运行模式（mock/real）返回对应的 Agent 实例，
     供 nodes.py 的各 node wrapper 按需调用。

注意：guide_agent 不在此工厂中（它不走 AgentTemplate 模式），
     guide_node 直接由 build_guide_node() 构造，见 nodes.py。
"""

import os
from typing import Any

from backend.src.agents.extract_agent.agent import MockExtractAgent, RealExtractAgent
from backend.src.agents.screen_agent.agent import MockScreenAgent, RealScreenAgent
from backend.src.agents.search_agent.agent import create_search_agent


DEFAULT_AGENT_MODE = "mock"


def _wrap_search(mode: str):
    """将 create_search_agent 工厂适配为与 Mock/Real 类相同的调用方式。"""
    class _SearchWrapper:
        def __init__(self):
            self._agent = create_search_agent()

        def run(self, input_data: dict) -> dict:
            run_id     = input_data.get("run_id")
            state_dict = input_data
            return self._agent.run(pipeline_state=state_dict, run_id=run_id)

    return _SearchWrapper


_AGENTS = {
    "mock": {
        "search_agent":  _wrap_search("mock"),
        "screen_agent":  MockScreenAgent,
        "extract_agent": MockExtractAgent,
    },
    "real": {
        "search_agent":  _wrap_search("real"),
        "screen_agent":  RealScreenAgent,
        "extract_agent": RealExtractAgent,
    },
}


def get_agent_mode(mode: str | None = None) -> str:
    return mode or os.getenv("GRAPH_AGENT_MODE") or DEFAULT_AGENT_MODE


def create_agent(agent_name: str, mode: str | None = None) -> Any:
    selected_mode = get_agent_mode(mode)

    if selected_mode not in _AGENTS:
        raise ValueError(
            f"unknown agent mode '{selected_mode}', expected one of {sorted(_AGENTS)}"
        )

    agents_for_mode = _AGENTS[selected_mode]
    if agent_name not in agents_for_mode:
        raise ValueError(
            f"unknown agent '{agent_name}', expected one of {sorted(agents_for_mode)}"
        )

    return agents_for_mode[agent_name]()


__all__ = ["DEFAULT_AGENT_MODE", "create_agent", "get_agent_mode"]
