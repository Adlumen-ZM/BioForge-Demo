"""
RAG 工具接口 — 暴露给 Agent 调用的 @tool 函数

提供三个核心工具：
1. chunk_document    — 文档切块
2. build_rag_index   — 建立向量索引
3. retrieve_chunks   — 召回检索

典型调用流程：
    chunk_document(pdf_path="paper.pdf")
    build_rag_index(chunks=[...])
    retrieve_chunks(query="FAE peptide adsorption mechanism", top_k=5)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from rag.retrieval.bge_hybrid_retriever import BGEHybridRetriever

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 全局 RAG 状态（单 agent 生命周期内共享）
# ─────────────────────────────────────────────────────────────────────────────

_rag_state: Dict[str, Any] = {
    "retriever": None,      # BGEHybridRetriever 实例
    "chunks": [],           # 当前已建索引的 chunks
    "indexed": False,      # 是否已建索引
}


# ─────────────────────────────────────────────────────────────────────────────
# 工具 1：文档切块
# ─────────────────────────────────────────────────────────────────────────────

@tool
def chunk_document(
    pdf_path: str,
    chunk_size: int = 1024,
    overlap: int = 128,
) -> Dict[str, Any]:
    """
    使用 RAGFlow 解析 PDF 并切块。

    Args:
        pdf_path: PDF 文件路径
        chunk_size: 每块最大字符数（传递给 RAGFlow）
        overlap: 块间重叠字符数

    Returns:
        {
            "status": "success" | "error",
            "chunks": [{"chunk_id": str, "text": str, "type": str}, ...],
            "chunk_count": int,
            "error": str | None
        }
    """
    try:
        from rag.ingestion.vision_parser import RAGFlowParser

        parser = RAGFlowParser()
        raw_chunks = parser.parse(pdf_path)

        # 转换为统一格式
        chunks = []
        for i, c in enumerate(raw_chunks):
            chunks.append({
                "chunk_id": c.get("trace_id", f"doc_{i}"),
                "text": c["text"],
                "type": c.get("type", "text"),
                "is_abstract": c.get("is_abstract", False),
            })

        # 存储到全局状态
        _rag_state["chunks"] = chunks
        _rag_state["indexed"] = False

        logger.info("文档切块完成，共 %d 个 chunks", len(chunks))

        return {
            "status": "success",
            "chunks": chunks,
            "chunk_count": len(chunks),
            "error": None,
        }

    except Exception as e:
        logger.error("文档切块失败: %s", str(e))
        return {
            "status": "error",
            "chunks": [],
            "chunk_count": 0,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# 工具 2：建立向量索引
# ─────────────────────────────────────────────────────────────────────────────

@tool
def build_rag_index(
    chunks: Optional[List[Dict[str, Any]]] = None,
    model_dir: str = "BAAI/bge-m3",
    alpha: float = 0.4,
    beta: float = 0.6,
) -> Dict[str, Any]:
    """
    对文档 chunks 建立 BGE-M3 混合向量索引。

    Args:
        chunks: chunks 列表，格式 [{"chunk_id": str, "text": str}, ...]
                如果为 None，使用上次 chunk_document 的结果
        model_dir: BGE-M3 模型路径或模型名称
        alpha: dense 检索权重
        beta: sparse 检索权重

    Returns:
        {
            "status": "success" | "error",
            "indexed_count": int,
            "error": str | None
        }
    """
    try:
        # 如果没有传入 chunks，使用全局状态
        if chunks is None:
            chunks = _rag_state.get("chunks", [])
            if not chunks:
                return {
                    "status": "error",
                    "indexed_count": 0,
                    "error": "无可用 chunks，请先调用 chunk_document 或传入 chunks",
                }

        # 转换为 retriever 需要的格式
        index_chunks = [
            {"chunk_id": c["chunk_id"], "text": c["text"]}
            for c in chunks
        ]

        # 创建 retriever 并建索引
        retriever = BGEHybridRetriever(
            model_dir=model_dir,
            alpha=alpha,
            beta=beta,
        )
        retriever.build_index(index_chunks)

        # 保存到全局状态
        _rag_state["retriever"] = retriever
        _rag_state["chunks"] = chunks
        _rag_state["indexed"] = True

        logger.info("向量索引建立完成，共 %d 个 chunks", len(index_chunks))

        return {
            "status": "success",
            "indexed_count": len(index_chunks),
            "error": None,
        }

    except Exception as e:
        logger.error("建立向量索引失败: %s", str(e))
        return {
            "status": "error",
            "indexed_count": 0,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# 工具 3：召回检索
# ─────────────────────────────────────────────────────────────────────────────

@tool
def retrieve_chunks(
    query: str,
    top_k: int = 8,
    threshold: float = 0.1,
) -> Dict[str, Any]:
    """
    根据 query 召回最相关的文档 chunks。

    Args:
        query: 检索查询文本
        top_k: 最多返回的 chunk 数量
        threshold: 相似度阈值，低于此值的 chunk 会被过滤

    Returns:
        {
            "status": "success" | "error",
            "query": str,
            "retrieved_chunks": [
                {
                    "chunk_id": str,
                    "text": str,
                    "score": float
                }, ...
            ],
            "retrieved_count": int,
            "context_summary": str,  # 用于回填的上下文摘要
            "error": str | None
        }
    """
    try:
        # 检查是否已建索引
        if not _rag_state.get("indexed") or _rag_state.get("retriever") is None:
            return {
                "status": "error",
                "query": query,
                "retrieved_chunks": [],
                "retrieved_count": 0,
                "context_summary": "",
                "error": "请先调用 build_rag_index 建立索引",
            }

        retriever = _rag_state["retriever"]

        # 执行检索
        context_str = retriever.retrieve(
            query=query,
            threshold=threshold,
            top_k=top_k,
        )

        # 解析返回的 context_str，还原为结构化 chunks
        # context_str 格式：--- [源区块 ID: xxx] ---\ntext\n--- ...
        retrieved_chunks = []
        blocks = context_str.split("--- [源区块 ID:")
        for block in blocks[1:]:  # 跳过第一个空块
            parts = block.split("] ---\n", 1)
            if len(parts) == 2:
                chunk_id = parts[0].strip()
                text = parts[1].strip()
                retrieved_chunks.append({
                    "chunk_id": chunk_id,
                    "text": text,
                    "score": 1.0,  # retriever 不返回分数，我们设为 1.0
                })

        # 生成上下文摘要用于回填
        context_summary = f"【检索结果：{len(retrieved_chunks)} 条相关片段】\n\n{context_str}"

        logger.info("召回检索完成，query='%s', 命中 %d 条", query, len(retrieved_chunks))

        return {
            "status": "success",
            "query": query,
            "retrieved_chunks": retrieved_chunks,
            "retrieved_count": len(retrieved_chunks),
            "context_summary": context_summary,
            "error": None,
        }

    except Exception as e:
        logger.error("召回检索失败: %s", str(e))
        return {
            "status": "error",
            "query": query,
            "retrieved_chunks": [],
            "retrieved_count": 0,
            "context_summary": "",
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# 工具 4：重置 RAG 状态（可选，用于清理）
# ─────────────────────────────────────────────────────────────────────────────

@tool
def reset_rag_state() -> Dict[str, str]:
    """
    重置 RAG 全局状态，释放内存。
    """
    global _rag_state
    _rag_state = {
        "retriever": None,
        "chunks": [],
        "indexed": False,
    }
    return {"status": "success", "message": "RAG 状态已重置"}