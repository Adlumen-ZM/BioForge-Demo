# -*- coding: utf-8 -*-
"""
tools/rag_paper/ — PepClaw RAG 工具注册层
==========================================

本包将 rag.service.BioPaperRAGService 的三个核心能力
包装为 LangChain @tool，供 Agent 框架直接调用。

对外暴露的工具
--------------
- run_bio_paper_extraction_pipeline : 端到端抽取（Scout + Strike 全流程）
- parse_pdf_with_ragflow            : 仅解析 PDF（获取 parse_id）
- retrieve_pdf_evidence             : 基于 parse_id 进行定向检索

在 Agent 构建时引入::

    from tools.rag_paper.tools import (
        run_bio_paper_extraction_pipeline,
        parse_pdf_with_ragflow,
        retrieve_pdf_evidence,
    )
    tools = [run_bio_paper_extraction_pipeline, parse_pdf_with_ragflow, retrieve_pdf_evidence]
"""
from .tools import (  # noqa: F401
    parse_pdf_with_ragflow,
    retrieve_pdf_evidence,
    run_bio_paper_extraction_pipeline,
)

__all__ = [
    "run_bio_paper_extraction_pipeline",
    "parse_pdf_with_ragflow",
    "retrieve_pdf_evidence",
]
