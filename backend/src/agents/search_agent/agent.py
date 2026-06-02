"""
search_agent/agent.py — SearchAgent 封装

位置：依赖 agent_template（AgentTemplate / AgentTemplateConfig）。
职责：实例化 AgentTemplate，注入 search_agent 专属配置（plan/identity/skills/tools/model）。

使用方式：
    from backend.src.agents.search_agent.agent import create_search_agent
    agent = create_search_agent(model="minimax/MiniMax-M2.7-highspeed")
    patch = agent.run()

扩展点：
  - 替换 trace backend：
      agent.hook.backend = PostgresBackend(session=db_session)
  - 调整模型或参数：通过 model / temperature 参数传入。
  - 真实 PubMed 工具接入：在 tools/registry.py 注册真实 pubmed_search 后，
    此文件和 template 代码零改动。
"""

from __future__ import annotations

from pathlib import Path

from backend.src.agents.agent_template import AgentTemplate
from backend.src.agents.agent_template.config import AgentTemplateConfig
from backend.src.agents.agent_template.schemas import SummaryMode

# search_agent 包目录（plan/identity/skills 文件相对此文件所在目录）
_AGENT_DIR = Path(__file__).parent


def create_search_agent(
    model: str = "minimax/MiniMax-M2.7-highspeed",
    temperature: float = 0.0,
    summary_mode: SummaryMode = SummaryMode.TEMPLATE,
) -> AgentTemplate:
    """工厂函数：创建配置好的 SearchAgent 实例。

    Args:
        model: LiteLLM 兼容的模型字符串（provider-agnostic）。
               默认使用 MiniMax，可改为任意 LiteLLM 支持的模型。
        temperature: LLM 采样温度，默认 0.0（确定性输出）。
        summary_mode: 摘要生成模式，默认 TEMPLATE（不调 LLM）。

    Returns:
        已初始化的 AgentTemplate 实例（plan 和 identity 已加载）。
    """
    config = AgentTemplateConfig(
        agent_name="search_agent",
        plan_path=_AGENT_DIR / "plan.yaml",
        identity_path=_AGENT_DIR / "identity.yaml",
        skills_dir=_AGENT_DIR / "skills",
        model=model,
        temperature=temperature,
        tools=["pubmed_search"],  # search_agent 可用的工具白名单
        max_step_retries=2,
        max_plan_retries=1,
        summary_mode=summary_mode,
        enable_trace=True,
        enable_memory=False,
    )

    return AgentTemplate(config)
