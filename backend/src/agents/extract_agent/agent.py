from pathlib import Path
from backend.src.agents.agent_template import AgentTemplate
from backend.src.agents.agent_template.config import AgentTemplateConfig

_AGENT_DIR = Path(__file__).parent


def create_extract_agent(model: str = "minimax/MiniMax-M2.7-highspeed") -> AgentTemplate:
    """创建 extract_agent 实例。

    ExtractAgent 负责从论文 PDF 文本中通过 LLM 抽取结构化信息。

    Args:
        model: LLM 模型名称，默认使用 MiniMax-M2.7-highspeed

    Returns:
        AgentTemplate 实例，可通过 run() 方法执行抽取流程

    Example:
        agent = create_extract_agent()
        result = agent.run(pipeline_state={"paper_texts": [...]})
    """
    config = AgentTemplateConfig(
        agent_name="extract_agent",
        plan_path=_AGENT_DIR / "plan.yaml",
        identity_path=_AGENT_DIR / "identity.yaml",
        skills_dir=_AGENT_DIR / "skills",
        model=model,
        tools=[
            "chunk_document",    # 文档切块
            "build_rag_index",  # Embedding 与建索引
            "retrieve_chunks",  # RAG 召回
        ],
        max_step_retries=2,
        enable_trace=True,
    )
    return AgentTemplate(config)
