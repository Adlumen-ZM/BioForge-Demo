"""
3.2 向量索引与双路混合拦截层

Dense 路：BGE-M3 稠密向量，余弦相似度（L2 归一化后点积）
Sparse 路：BGE-M3 词法权重（Lexical Weights），应对无语义硬核肽段编号（如 HAp-2）
混合得分：alpha * dense + beta * sparse，默认 alpha=0.4, beta=0.6
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)


def _load_bge_model(model_dir: str, use_fp16: bool):
    """懒加载 BGEM3FlagModel，避免未安装时顶层 import 崩溃。
    添加全局缓存，避免反复加载 4.5GB 模型。
    """
    cache_key = f"{model_dir}_{use_fp16}"
    if cache_key in _BGE_MODEL_CACHE:
        logger.debug("使用缓存的 BGE-M3 模型: %s", model_dir)
        return _BGE_MODEL_CACHE[cache_key]

    try:
        from FlagEmbedding import BGEM3FlagModel  # noqa: PLC0415
    except ImportError as e:
        raise ImportError(
            "请先安装 FlagEmbedding：pip install FlagEmbedding"
        ) from e
    model = BGEM3FlagModel(model_dir, use_fp16=use_fp16)
    _BGE_MODEL_CACHE[cache_key] = model
    logger.info("BGE-M3 模型加载完成: %s", model_dir)
    return model


# 全局模型缓存（跨 BGEHybridRetriever 实例共享）
_BGE_MODEL_CACHE = {}


class BGEHybridRetriever:
    """
    单 PDF 生命周期内的混合检索器。
    典型用法：
        retriever = BGEHybridRetriever(model_dir="BAAI/bge-m3")
        retriever.build_index(chunks_with_trace)
        context_str = retriever.retrieve(query, threshold=0.4, top_k=8)
    """

    def __init__(
        self,
        model_dir: str = "BAAI/bge-m3",
        use_fp16: bool = True,
        alpha: float = 0.4,   # dense 权重
        beta: float = 0.6,    # sparse 权重
    ) -> None:
        logger.info("加载 BGE-M3 模型: %s", model_dir)
        self.model = _load_bge_model(model_dir, use_fp16)
        self.alpha = alpha
        self.beta = beta

        # 索引存储（build_index 后填充）
        self._chunks: List[Dict] = []
        self._dense_matrix: np.ndarray | None = None   # shape: (N, D)，已 L2 归一化
        self._sparse_list: List[Dict[int, float]] = []  # 每个 chunk 的词法权重 dict

    # ------------------------------------------------------------------
    # 建库
    # ------------------------------------------------------------------

    def build_index(self, chunks: List[Dict]) -> None:
        """
        对 chunk 列表做批量编码，建立内存索引。

        chunks 格式：
            [{"chunk_id": "doc_p1_b0_table", "text": "..."}, ...]
        """
        if not chunks:
            # [R3] 改为 warning + 提前返回，避免与 O2 联动形成崩溃链
            logger.warning("build_index() 收到空 chunk 列表，跳过建库")
            return

        texts = [c["text"] for c in chunks]
        logger.info("编码 %d 个 chunk ...", len(texts))

        output = self.model.encode(
            texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
            batch_size=32,
        )

        dense_vecs = np.array(output["dense_vecs"], dtype=np.float32)
        # BGE-M3 输出已 L2 归一化，保险起见再归一化一次
        norms = np.linalg.norm(dense_vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        self._dense_matrix = dense_vecs / norms

        self._sparse_list = output["lexical_weights"]  # list of {token_id: weight}
        self._chunks = chunks
        logger.info("索引建立完成，共 %d 条", len(chunks))

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        threshold: float = 0.1,   # 实验使用值；技术方案中同步记录为 0.1
        top_k: int = 8,
    ) -> str:
        """
        双路混合检索，返回拼装了 Trace ID 的上下文字符串。

        - 低于 threshold 的 chunk 全部丢弃（防幻觉底线）
        - 最多保留 top_k 条（防超载容量）
        - 每条前缀物理装订 Trace ID 标签
        """
        if self._dense_matrix is None:
            raise RuntimeError("请先调用 build_index() 建立索引")

        q_output = self.model.encode(
            [query],
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )

        # Dense 路：余弦相似度（点积，因为已归一化）
        q_dense = np.array(q_output["dense_vecs"][0], dtype=np.float32)
        # [R2] 与 build_index 保持一致的归一化兜底写法
        q_norm = np.linalg.norm(q_dense)
        q_norm = q_norm if q_norm > 0 else 1.0
        q_dense /= q_norm
        dense_scores = self._dense_matrix @ q_dense  # shape: (N,)

        # Sparse 路：词法权重稀疏点积
        q_sparse = q_output["lexical_weights"][0]
        sparse_scores = np.array(
            [self._sparse_dot(q_sparse, doc_sp) for doc_sp in self._sparse_list],
            dtype=np.float32,
        )

        # 混合得分
        hybrid_scores = self.alpha * dense_scores + self.beta * sparse_scores

        # Top-K 截断（降序排列后取前 top_k）
        ranked_idx = np.argsort(hybrid_scores)[::-1][:top_k]

        # 阈值拦截 + Trace ID 装订
        valid_blocks: List[str] = []
        for idx in ranked_idx:
            score = float(hybrid_scores[idx])
            if score < threshold:
                break  # 已降序，后续不可能过阈值
            chunk = self._chunks[idx]
            trace_id = chunk.get("chunk_id", "unknown")
            block = f"--- [源区块 ID: {trace_id}] ---\n{chunk['text']}\n"
            valid_blocks.append(block)
            logger.debug("chunk %s 命中，混合分=%.4f", trace_id, score)

        if not valid_blocks:
            logger.info("query='%s' 无 chunk 过阈值 %.2f，跳过 LLM", query, threshold)
            return ""

        return "\n".join(valid_blocks)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _sparse_dot(q_weights: Dict[int, float], doc_weights: Dict[int, float]) -> float:
        """稀疏词法权重点积：仅遍历 query 侧的非零 token。"""
        score = 0.0
        for token_id, q_w in q_weights.items():
            if token_id in doc_weights:
                score += q_w * doc_weights[token_id]
        return score
