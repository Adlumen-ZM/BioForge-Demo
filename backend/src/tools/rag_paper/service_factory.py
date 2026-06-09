"""Factory for creating the singleton BioPaperRAGService."""

from __future__ import annotations

import os
from typing import Optional

from rag.service import BioPaperRAGService

_SERVICE_INSTANCE: Optional[BioPaperRAGService] = None


def _first_env(*names: str, default: str | None = None) -> str | None:
    """Return the first non-empty environment variable value."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _normalize_openai_model_name(model: str | None) -> str:
    """Convert LiteLLM-style provider/model names into OpenAI client model ids."""
    if not model:
        return "gpt-4o"

    normalized = model.strip()
    for prefix in ("openai/", "azure/", "litellm/"):
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def get_rag_service() -> BioPaperRAGService:
    """Return a singleton RAG service reusing the app's existing LLM env vars."""
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is not None:
        return _SERVICE_INSTANCE

    ragflow_base_url = _first_env("RAGFLOW_API_BASE_URL")
    ragflow_api_key = _first_env("RAGFLOW_API_KEY")
    llm_api_key = _first_env("LLM_API_KEY", "OPENAI_API_KEY")

    missing = [
        name
        for name, value in {
            "RAGFLOW_API_BASE_URL": ragflow_base_url,
            "RAGFLOW_API_KEY": ragflow_api_key,
            "LLM_API_KEY|OPENAI_API_KEY": llm_api_key,
        }.items()
        if not value
    ]
    if missing:
        raise EnvironmentError(
            f"RAG 工具缺少必填环境变量：{missing}。请在 .env 中配置后重启服务。"
        )

    llm_base_url = _first_env("LLM_BASE_URL", "OPENAI_API_BASE")
    llm_model = _normalize_openai_model_name(
        _first_env("LLM_MODEL", "DEFAULT_LLM_MODEL", default="gpt-4o")
    )

    _SERVICE_INSTANCE = BioPaperRAGService(
        ragflow_base_url=ragflow_base_url,
        ragflow_api_key=ragflow_api_key,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        bge_model_dir=_first_env("BGE_MODEL_DIR", "EMBEDDING_MODEL", default="BAAI/bge-m3"),
        bge_use_fp16=os.environ.get("BGE_USE_FP16", "false").lower() == "true",
        retrieval_top_k=int(os.environ.get("RETRIEVAL_TOP_K", "8")),
        retrieval_threshold=float(os.environ.get("RETRIEVAL_THRESHOLD", "0.1")),
        ragflow_chunk_method=os.environ.get("RAGFLOW_CHUNK_METHOD", "paper"),
    )
    return _SERVICE_INSTANCE
