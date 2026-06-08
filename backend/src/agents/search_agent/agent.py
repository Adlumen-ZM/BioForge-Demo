from pathlib import Path
from backend.src.agents.agent_template import AgentTemplate
from backend.src.agents.agent_template.config import AgentTemplateConfig

_AGENT_DIR = Path(__file__).parent

def create_search_agent(model: str = None) -> AgentTemplate:
    import os
    model = model or os.getenv("DEFAULT_LLM_MODEL", "deepseek/deepseek-chat")
    config = AgentTemplateConfig(
        agent_name="search_agent",
        plan_path=_AGENT_DIR / "plan.yaml",
        identity_path=_AGENT_DIR / "identity.yaml",
        skills_dir=_AGENT_DIR / "skills",
        model=model,
        tools=["pubmed_search"],
        max_step_retries=2,
        enable_trace=True,
    )
    return AgentTemplate(config)