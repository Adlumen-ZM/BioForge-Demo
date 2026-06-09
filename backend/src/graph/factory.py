"""
factory.py — BioForge Agent 工厂（mock/real 模式切换）

位置：backend/src/graph/
职责：根据运行模式（mock/real/demo）返回对应的 Agent 实例，
     供 nodes.py 的各 node wrapper 按需调用。

注意：guide_agent 不在此工厂中（它不走 AgentTemplate 模式），
     guide_node 直接由 build_guide_node() 构造，见 nodes.py。
"""

import os
from typing import Any

from backend.src.agents.screen_agent.agent import MockScreenAgent, RealScreenAgent
from backend.src.agents.search_agent.agent import create_search_agent


DEFAULT_AGENT_MODE = "mock"


# ── Search 适配器（无 Mock/Real 类，统一用工厂函数 + wrapper） ──────────────

def _wrap_search(mode: str):
    """将 create_search_agent 工厂适配为与 Mock/Real 类相同的调用方式。"""
    class _SearchWrapper:
        def __init__(self):
            self._agent = create_search_agent()

        def run(self, input_data: dict) -> dict:
            return self._agent.run(
                pipeline_state=input_data,
                run_id=input_data.get("run_id"),
            )

    return _SearchWrapper


# ── Extract 适配器 ─────────────────────────────────────────────────────────

class _MockExtractAgent:
    """mock 模式下的 ExtractAgent：直接返回成功占位结果。"""

    def run(self, input_data: dict) -> dict:
        return {
            "ok": True,
            "rag_csv_dir": None,
            "rag_csv_files": None,
            "ragflow_ref": None,
            "extract_summary": "mock extract（跳过真实 RAG）",
            "run_metadata": {"status": "success"},
        }


def _wrap_extract(mode: str):
    """将 create_extract_agent 工厂适配为统一调用方式。"""
    class _ExtractWrapper:
        def __init__(self):
            from backend.src.agents.extract_agent.agent import create_extract_agent
            self._agent = create_extract_agent()

        def run(self, input_data: dict) -> dict:
            # 将 RAG 工具调用所需的关键字段显式注入 upstream_context，
            # 避免 LLM 在未看到真实值时退回到 schema/example 中的占位路径。
            _UPSTREAM_KEYS = (
                "run_id",
                "pdf_path",
                "pdf_name",
                "paper_key",
                "extraction_profile",
                "template_id",
                "output_dir",
                "schema_template_path",
                "screen_summary",
            )
            upstream = {
                k: v for k, v in input_data.items()
                if k in _UPSTREAM_KEYS and v is not None and v != [] and v != ""
            }
            return self._agent.run(
                pipeline_state=input_data,
                upstream_context=upstream if upstream else None,
                run_id=input_data.get("run_id"),
            )

    return _ExtractWrapper


# ── Screen 适配器（demo/real 模式使用真实 AgentTemplate）────────────────────

def _wrap_screen(mode: str):
    """将 create_screen_agent 工厂适配为统一调用方式。"""
    class _ScreenWrapper:
        def __init__(self):
            from backend.src.agents.screen_agent.agent import create_screen_agent
            self._agent = create_screen_agent()

        def run(self, input_data: dict) -> dict:
            # 将关键输入字段注入 upstream_context，使 LLM 能在 system prompt 中看到它们
            _UPSTREAM_KEYS = (
                "run_id", "candidate_paper_ids", "query",
                "refined_screening_criteria", "search_summary",
                "template_id", "extraction_profile",
            )
            upstream = {
                k: v for k, v in input_data.items()
                if k in _UPSTREAM_KEYS and v is not None and v != [] and v != ""
            }
            return self._agent.run(
                pipeline_state=input_data,
                upstream_context=upstream if upstream else None,
                run_id=input_data.get("run_id"),
            )

    return _ScreenWrapper


# ── Agent 注册表 ────────────────────────────────────────────────────────────

_AGENTS: dict[str, dict[str, Any]] = {
    # mock 模式：全部 Agent 使用轻量 mock，供单元测试（无需 LLM）
    "mock": {
        "search_agent":  _wrap_search("mock"),
        "screen_agent":  MockScreenAgent,
        "extract_agent": _MockExtractAgent,
    },
    # demo 模式：guide 正常调用 LLM；search/screen/extract 全部使用真实 AgentTemplate
    "demo": {
        "search_agent":  _wrap_search("demo"),
        "screen_agent":  _wrap_screen("demo"),
        "extract_agent": _wrap_extract("demo"),
    },
    # real 模式：全链路真实 LLM + tools
    "real": {
        "search_agent":  _wrap_search("real"),
        "screen_agent":  _wrap_screen("real"),
        "extract_agent": _wrap_extract("real"),
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
