# -*- coding: utf-8 -*-
"""
tools/rag_paper/service_factory.py — BioPaperRAGService 工厂函数
================================================================

build_rag_service() 是 tools 层与 rag 能力层之间的唯一连接点。

设计意图
--------
- 工具函数（tools.py）不直接持有服务实例，每次调用时通过工厂函数获取。
- 工厂函数从环境变量读取配置，便于在不同部署环境中切换参数，
  无需修改任何业务代码。
- 未来如需换用其他 RAG 后端，只需修改本文件，tools.py 无需改动。

所需环境变量（在 .env 中配置）
------------------------------
必填：
    RAGFLOW_API_BASE_URL    RAGFlow 服务地址
    RAGFLOW_API_KEY         RAGFlow API Key
    LLM_API_KEY             LLM 服务 API Key

选填（有默认值）：
    LLM_BASE_URL            LLM 服务 Base URL（默认使用 OpenAI 官方端点）
    LLM_MODEL               LLM 模型名（默认 gpt-4o）
    BGE_MODEL_DIR           BGE-M3 模型路径（默认 BAAI/bge-m3）
    BGE_USE_FP16            是否用 FP16 加载 BGE（默认 false）
    RETRIEVAL_TOP_K         检索返回条数（默认 8）
    RETRIEVAL_THRESHOLD     检索分数阈值（默认 0.1）
"""

from __future__ import annotations

import os

from rag.service import BioPaperRAGService  # 从 rag/ 能力层导入门面类


def build_rag_service() -> BioPaperRAGService:
    """
    从环境变量构造并返回 BioPaperRAGService 实例。

    Returns
    -------
    BioPaperRAGService
        配置完整的服务实例，可直接调用 run_pipeline / parse_pdf / retrieve_evidence。

    Raises
    ------
    KeyError
        如果 RAGFLOW_API_BASE_URL、RAGFLOW_API_KEY 或 LLM_API_KEY 未在环境中设置。
    """
    return BioPaperRAGService(
        ragflow_base_url=os.environ["RAGFLOW_API_BASE_URL"],    # 必填
        ragflow_api_key=os.environ["RAGFLOW_API_KEY"],          # 必填
        llm_api_key=os.environ["LLM_API_KEY"],                  # 必填
        llm_base_url=os.environ.get("LLM_BASE_URL") or None,   # 选填
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o"),        # 默认 gpt-4o
        bge_model_dir=os.environ.get("BGE_MODEL_DIR", "BAAI/bge-m3"),
        bge_use_fp16=os.environ.get("BGE_USE_FP16", "false").lower() == "true",
        retrieval_top_k=int(os.environ.get("RETRIEVAL_TOP_K", "8")),
        retrieval_threshold=float(os.environ.get("RETRIEVAL_THRESHOLD", "0.1")),
    )
