"""
screen_agent/agent.py — ScreenAgent 封装

提供两套 screen_agent 实现：
  - MockScreenAgent / RealScreenAgent：轻量 mock/占位类（供 graph 层快速集成测试）
  - create_screen_agent()：基于 AgentTemplate 的正式实现（Plan-and-Execute + ReAct）

使用方式：
    # Mock（无需 LLM）
    from backend.src.agents.screen_agent.agent import MockScreenAgent
    agent = MockScreenAgent()
    result = agent.run({"candidate_paper_ids": ["34265844"]})

    # 正式实现（需要 LLM + tools）
    from backend.src.agents.screen_agent.agent import create_screen_agent
    agent = create_screen_agent(model="minimax/MiniMax-M2.7-highspeed")
    patch = agent.run(pipeline_state=state, run_id=state["run_id"])
"""

from __future__ import annotations

import os
from pathlib import Path

from backend.src.agents.agent_template import AgentTemplate
from backend.src.agents.agent_template.config import AgentTemplateConfig
from backend.src.agents.agent_template.schemas import SummaryMode

# screen_agent 包目录（plan/identity/skills 文件相对此文件所在目录）
_AGENT_DIR = Path(__file__).parent


# ═══════════════════════════════════════════════════════════════════
# Mock / Placeholder（供 graph 层快速集成测试）
# ═══════════════════════════════════════════════════════════════════


class MockScreenAgent:
    """Offline screen agent that keeps the first candidate."""

    def run(self, input_data: dict) -> dict:
        candidate_ids = list(input_data.get("candidate_paper_ids") or [])
        candidates = list(input_data.get("candidates") or [])

        selected_id = candidate_ids[0] if candidate_ids else None
        selected_paper = candidates[0] if candidates else None

        return {
            "ok": selected_id is not None or selected_paper is not None,
            "message": "mock screen success" if candidate_ids or candidates else "no candidates to screen",
            "screened_paper_ids": [selected_id] if selected_id else [],
            "selected_paper": selected_paper,
            "rejected_count": max(len(candidate_ids or candidates) - 1, 0),
            "screen_summary": "Mock screen kept 1 paper." if candidate_ids or candidates else "Mock screen found no papers.",
        }


class RealScreenAgent:
    """Placeholder for the future real screening agent."""

    def run(self, input_data: dict) -> dict:
        return {
            "ok": False,
            "message": "real screen_agent is not implemented",
            "screened_paper_ids": [],
            "selected_paper": None,
            "screen_summary": "Real screen agent is not implemented.",
        }


# ═══════════════════════════════════════════════════════════════════
# AgentTemplate 正式实现
# ═══════════════════════════════════════════════════════════════════


def create_screen_agent(
    model: str = None,
    temperature: float = 0.0,
    summary_mode: SummaryMode = SummaryMode.TEMPLATE,
) -> AgentTemplate:
    """工厂函数：创建配置好的 ScreenAgent 实例。

    Args:
        model: LiteLLM 兼容的模型字符串（provider-agnostic）。
               默认使用 MiniMax，可改为任意 LiteLLM 支持的模型。
        temperature: LLM 采样温度，默认 0.0（确定性输出）。
        summary_mode: 摘要生成模式，默认 TEMPLATE（不调 LLM，纯函数拼装）。

    Returns:
        已初始化的 AgentTemplate 实例（plan 和 identity 已加载）。
    """
    model = model or os.getenv("DEFAULT_LLM_MODEL", "deepseek/deepseek-chat")
    config = AgentTemplateConfig(
        agent_name="screen_agent",
        plan_path=_AGENT_DIR / "plan.yaml",
        identity_path=_AGENT_DIR / "identity.yaml",
        skills_dir=_AGENT_DIR / "skills",
        model=model,
        temperature=temperature,
        tools=[
            "screen_paper",
            "download_paper",
        ],
        max_step_retries=2,
        max_plan_retries=1,
        summary_mode=summary_mode,
        enable_trace=True,
        enable_memory=False,
    )

    return AgentTemplate(config)


__all__ = ["MockScreenAgent", "RealScreenAgent", "create_screen_agent"]
