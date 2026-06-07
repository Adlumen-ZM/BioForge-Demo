# -*- coding: utf-8 -*-
"""
rag/ — PepClaw RAG 能力层
==========================

本包是 PepClaw 生物矿化文献结构化抽取系统的 RAG 核心能力层。
对外暴露唯一入口：BioPaperRAGService。

使用方式::

    from rag.service import BioPaperRAGService

    svc = BioPaperRAGService(
        ragflow_base_url="https://your-ragflow-host",
        ragflow_api_key="ragflow-xxx",
        llm_api_key="your-llm-key",
    )
    result = svc.run_pipeline("/path/to/paper.pdf")

依赖说明
--------
本包依赖 PepClaw 的内部模块（rag_pipeline.*）。
集成前请确认 PepClaw 已作为 Python 包安装，或将其源码置于本仓库可寻址路径。
"""
from rag.service import BioPaperRAGService  # noqa: F401

__all__ = ["BioPaperRAGService"]
