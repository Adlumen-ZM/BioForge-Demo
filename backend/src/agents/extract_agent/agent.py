"""
backend/src/agents/extract_agent/agent.py
ExtractAgent 入口函数 - 基于 AgentTemplate 架构
"""

from pathlib import Path
import os

from backend.src.agents.agent_template import AgentTemplate
from backend.src.agents.agent_template.config import AgentTemplateConfig

_AGENT_DIR = Path(__file__).parent


def create_extract_agent(model: str = None) -> AgentTemplate:
    """创建 extract_agent 实例。

    ExtractAgent 负责从论文 PDF 文本中通过 LLM 抽取结构化信息。

    Args:
        model: LLM 模型名称，默认从环境变量 DEFAULT_LLM_MODEL 读取，
               回退到 deepseek/deepseek-chat。

    Returns:
        AgentTemplate 实例，可通过 run() 方法执行抽取流程

    Example:
        agent = create_extract_agent()
        result = agent.run(pipeline_state={"paper_texts": [...]})

    """
    model = model or os.getenv("DEFAULT_LLM_MODEL", "deepseek/deepseek-chat")
    config = AgentTemplateConfig(
        agent_name="extract_agent",
        plan_path=_AGENT_DIR / "plan.yaml",
        identity_path=_AGENT_DIR / "identity.yaml",
        skills_dir=_AGENT_DIR / "skills",
        model=model,
        tools=[
            "run_bio_paper_extraction_pipeline",
        ],
        max_step_retries=2,
        enable_trace=True,
    )
    return AgentTemplate(config)
