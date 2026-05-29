"""text_agent 包：HAp 肽数据库 Text Agent 模块。

对外暴露的主入口：
    TextAgent : 论文 PDF → 结构化数据库记录的全流程编排器

子模块职责：
    text_agent.py       : TextAgent 主类，10 阶段流程编排
    pdf_extractor.py    : PyMuPDF PDF 文本提取
    prompt_builder.py   : System/User Prompt 构建
    llm_client.py       : MiniMax-M2.5 LLM API 调用（OpenAI 兼容接口）
    response_parser.py  : LLM 原始输出解析（JSON 提取 + reasoning 分离）
    id_generator.py     : paper_id / record_id / fae_id 生成与 DOI 查重
    field_dict_prompt.json : 嵌入 System Prompt 的 v0.1 字段字典（供 prompt_builder 加载）
"""

from text_agent.text_agent import TextAgent

__all__ = ['TextAgent']
