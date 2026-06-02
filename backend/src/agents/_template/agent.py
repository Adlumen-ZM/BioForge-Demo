"""
_template/agent.py — 新 agent 骨架（复制后修改）

步骤：
  1. 将文件中所有 "my_agent" 替换为你的 agent 名称
  2. 更新 model、tools、max_step_retries 等参数
  3. 实现 identity.yaml / plan.yaml / skills/
"""

from __future__ import annotations

from pathlib import Path

from backend.src.agents.agent_template import AgentTemplate
from backend.src.agents.agent_template.config import AgentTemplateConfig

_AGENT_DIR = Path(__file__).parent


def create_my_agent(
    model: str = "minimax/MiniMax-M2.7-highspeed",
    temperature: float = 0.0,
) -> AgentTemplate:
    """工厂函数：创建 MyAgent 实例（替换 my_agent 为实际名称）。"""
    config = AgentTemplateConfig(
        agent_name="my_agent",              # ← 修改为实际 agent 名称
        plan_path=_AGENT_DIR / "plan.yaml",
        identity_path=_AGENT_DIR / "identity.yaml",
        skills_dir=_AGENT_DIR / "skills",
        model=model,
        temperature=temperature,
        tools=[],                           # ← 填写本 agent 可用的 tool 名称列表
        max_step_retries=2,
        enable_trace=True,
        enable_memory=False,
    )
    return AgentTemplate(config)
