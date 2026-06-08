import os
from typing import Any

from backend.src.agents.extract_agent.agent import MockExtractAgent, RealExtractAgent
from backend.src.agents.screen_agent.agent import MockScreenAgent, RealScreenAgent
from backend.src.agents.search_agent.agent import MockSearchAgent, RealSearchAgent


DEFAULT_AGENT_MODE = "mock"

_AGENTS = {
    "mock": {
        "search_agent": MockSearchAgent,
        "screen_agent": MockScreenAgent,
        "extract_agent": MockExtractAgent,
    },
    "real": {
        "search_agent": RealSearchAgent,
        "screen_agent": RealScreenAgent,
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
