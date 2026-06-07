# -*- coding: utf-8 -*-
"""
tools/rag_paper/service_factory.py — BioPaperRAGService 工厂函数
================================================================

get_rag_service() 是 tools 层与 rag 能力层之间的唯一连接点。

设计意图
--------
- 工具函数（tools.py）不直接持有服务实例，通过本函数获取。
- 模块级单例（_SERVICE_INSTANCE）确保 BGE-M3 模型只加载一次：
  第一次调用 get_rag_service() 时初始化并缓存，后续调用直接返回同一实例。
- 配置从环境变量读取，无需修改任何业务代码即可切换部署参数。
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
from typing import Optional

# 导入门面类（rag/ 在项目根，sys.path 包含项目根时可直接导入）
from rag.service import BioPaperRAGService

# ── 模块级单例：首次调用 get_rag_service() 时初始化，后续调用复用 ──────────────
# 好处：BGE-M3 模型（30-60s 加载）只初始化一次，同一进程内所有工具调用共享同一实例。
_SERVICE_INSTANCE: Optional[BioPaperRAGService] = None


def get_rag_service() -> BioPaperRAGService:
    """
    返回 BioPaperRAGService 的单例实例（首次调用时从环境变量构造）。

    Returns
    -------
    BioPaperRAGService
        配置完整的服务实例，可直接调用 run_pipeline / parse_pdf / retrieve_evidence。

    Raises
    ------
    EnvironmentError
        如果必填环境变量（RAGFLOW_API_BASE_URL / RAGFLOW_API_KEY / LLM_API_KEY）未配置。
    """
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is not None:
        return _SERVICE_INSTANCE

    # ── 校验必填环境变量，给出明确错误信息 ──────────────────────────────────
    _required = {
        "RAGFLOW_API_BASE_URL": os.environ.get("RAGFLOW_API_BASE_URL"),
        "RAGFLOW_API_KEY":      os.environ.get("RAGFLOW_API_KEY"),
        "LLM_API_KEY":          os.environ.get("LLM_API_KEY"),
    }
    missing = [k for k, v in _required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"RAG 工具缺少必填环境变量：{missing}。"
            "请在 .env 中配置后重启服务。"
        )

    _SERVICE_INSTANCE = BioPaperRAGService(
        ragflow_base_url=_required["RAGFLOW_API_BASE_URL"],
        ragflow_api_key=_required["RAGFLOW_API_KEY"],
        llm_api_key=_required["LLM_API_KEY"],
        llm_base_url=os.environ.get("LLM_BASE_URL") or None,
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o"),
        bge_model_dir=os.environ.get("BGE_MODEL_DIR", "BAAI/bge-m3"),
        bge_use_fp16=os.environ.get("BGE_USE_FP16", "false").lower() == "true",
        retrieval_top_k=int(os.environ.get("RETRIEVAL_TOP_K", "8")),
        retrieval_threshold=float(os.environ.get("RETRIEVAL_THRESHOLD", "0.1")),
    )
    return _SERVICE_INSTANCE
