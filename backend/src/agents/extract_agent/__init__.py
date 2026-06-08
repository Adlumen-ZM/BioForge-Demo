"""extract_agent 包：生物医学文献信息提取 Agent 模块。

对外暴露的主入口：
    create_extract_agent : 创建 extract_agent 实例（基于 AgentTemplate）

子模块职责：
    agent.py            : AgentTemplate 入口函数
    plan.yaml           : 执行计划定义
    identity.yaml       : 身份配置
    skills/             : 技能指南

遗留模块（v0.1 旧版）：
    text_agent.py       : 旧版 TextAgent（10 阶段流程），保留用于兼容
    pdf_extractor.py    : PDF 文本提取
    prompt_builder.py   : Prompt 构建
    llm_client.py       : LLM 调用
    response_parser.py  : 响应解析
    id_generator.py     : ID 生成
    field_dict_prompt.json : 字段字典
"""

from backend.src.agents.extract_agent.agent import create_extract_agent

__all__ = ['create_extract_agent']
