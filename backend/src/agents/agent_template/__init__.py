"""
agent_template — 通用 Agent 模板层

对外唯一公开接口：AgentTemplate 类。
各 agent（search/screen/extract）通过配置注入复用，不通过继承。

注意：本模块采用「组合/配置注入」而非「继承」模式。
各 agent 只需提供 plan.yaml / identity.yaml / skills/ / tools 列表，
实例化 AgentTemplate(config) 后调用 run() 即可，无需修改 template 内部代码。

使用方式（search_agent/agent.py 示例）：
    from backend.src.agents.agent_template import AgentTemplate
    from backend.src.agents.agent_template.config import AgentTemplateConfig
    from pathlib import Path

    config = AgentTemplateConfig(
        agent_name="search_agent",
        plan_path=Path(__file__).parent / "plan.yaml",
        identity_path=Path(__file__).parent / "identity.yaml",
        skills_dir=Path(__file__).parent / "skills",
        model="minimax/MiniMax-M2.7-highspeed",
        tools=["pubmed_search"],
    )
    patch = AgentTemplate(config).run()
"""

from .template_agent import AgentTemplate

__all__ = ["AgentTemplate"]
