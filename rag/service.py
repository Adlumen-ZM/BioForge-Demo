# -*- coding: utf-8 -*-
"""
rag/service.py — BioPaperRAGService 门面类
==========================================

职责
----
将 PepClaw 内部的三大组件（RAGFlow 视觉解析器、BGE-M3 混合检索器、
LLM 字段抽取器）封装为一个简洁的门面（Facade）对象，供上层 Agent 工具调用。

设计原则
--------
- 零侵入：不修改 PepClaw 0531 版本任何源文件；所有集成逻辑写在本文件。
- 延迟加载：三大组件仅在首次调用时初始化，避免启动时加载 GPU 模型造成延迟。
- 缓存机制：解析结果以 PDF 路径的 md5 哈希为 key，写入临时目录 JSON 文件，
  支持 parse -> retrieve 两步流程（无需重复解析同一 PDF）。

依赖前提
--------
运行本文件前，需要本仓库内的 rag/ 本地实现及其三方依赖可用：
    rag.ingestion.vision_parser             (RAGFlowParser)
    rag.retrieval.bge_hybrid_retriever      (BGEHybridRetriever)
    rag.core.orchestrator                   (PipelineOrchestrator)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 块缓存目录：parse_pdf() 把解析结果存这里，retrieve_evidence() 从这里读
_CHUNK_CACHE_DIR = Path(tempfile.gettempdir()) / "pepclaw_chunk_cache"


class _InMemoryCollection:
    """最小化 collection 适配器，供未安装 chromadb 时兜底。"""

    def __init__(self) -> None:
        self.documents: list[str] = []
        self.ids: list[str] = []
        self.metadatas: list[dict[str, Any]] = []

    def add(
        self,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        self.documents.extend(documents)
        self.ids.extend(ids)
        self.metadatas.extend(metadatas)


class _InMemoryChromaClient:
    """兼容 orchestrator 需要的最小 client 接口。"""

    def __init__(self) -> None:
        self._collections: dict[str, _InMemoryCollection] = {}

    def create_collection(self, name: str) -> _InMemoryCollection:
        collection = _InMemoryCollection()
        self._collections[name] = collection
        return collection

    def delete_collection(self, name: str) -> None:
        self._collections.pop(name, None)


class BioPaperRAGService:
    """
    PepClaw RAG 能力的统一门面。

    Parameters
    ----------
    ragflow_base_url : str
        RAGFlow 服务地址，例如 "https://your-ragflow-host"
    ragflow_api_key : str
        RAGFlow API Key（格式：ragflow-xxxxxxxx）
    llm_api_key : str
        LLM 服务的 API Key
    llm_base_url : str | None
        LLM 服务的 Base URL；为 None 时使用 OpenAI 官方端点
    llm_model : str
        LLM 模型名，默认 "gpt-4o"
    bge_model_dir : str
        BGE-M3 模型本地路径或 HuggingFace Hub ID，默认 "BAAI/bge-m3"
    bge_use_fp16 : bool
        是否用 FP16 加载 BGE 模型（GPU 内存受限时启用），默认 False
    retrieval_top_k : int
        检索返回的最大 chunk 数，默认 8
    retrieval_threshold : float
        混合检索分数阈值，低于此值的 chunk 被过滤，默认 0.1
    scout_model : str | None
        Scout 步骤（盲盒实体发现）使用的模型；为 None 时复用 llm_model
    """

    def __init__(
        self,
        ragflow_base_url: str,
        ragflow_api_key: str,
        llm_api_key: str,
        llm_base_url: str | None = None,
        llm_model: str = "gpt-4o",
        bge_model_dir: str = "BAAI/bge-m3",
        bge_use_fp16: bool = False,
        retrieval_top_k: int = 8,
        retrieval_threshold: float = 0.1,
        scout_model: str | None = None,
        ragflow_chunk_method: str = "paper",
    ) -> None:
        # 保存配置；组件延迟初始化（首次调用时才创建，节省启动时间）
        self._ragflow_base_url = ragflow_base_url
        self._ragflow_api_key = ragflow_api_key
        self._llm_api_key = llm_api_key
        self._llm_base_url = llm_base_url
        self._llm_model = llm_model
        self._bge_model_dir = bge_model_dir
        self._bge_use_fp16 = bge_use_fp16
        self._retrieval_top_k = retrieval_top_k
        self._retrieval_threshold = retrieval_threshold
        self._scout_model = scout_model or llm_model
        self._ragflow_chunk_method = ragflow_chunk_method

        # 延迟加载的组件占位符（None = 尚未初始化）
        self._parser = None        # RAGFlowParser
        self._retriever = None     # BGEHybridRetriever
        self._orchestrator = None  # PipelineOrchestrator

        # 确保缓存目录存在
        _CHUNK_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 私有：延迟初始化各组件
    # ------------------------------------------------------------------

    def _get_parser(self):
        """首次调用时初始化 RAGFlowParser（视觉 PDF 解析器）。"""
        if self._parser is None:
            from rag.ingestion.vision_parser import RAGFlowParser  # noqa: PLC0415

            self._parser = RAGFlowParser(
                base_url=self._ragflow_base_url,
                api_key=self._ragflow_api_key,
            )
            logger.info("RAGFlowParser 初始化完成")
        return self._parser

    def _get_orchestrator(self):
        """首次调用时初始化完整 Pipeline（包含 BGE 加载，耗时较长）。"""
        if self._orchestrator is None:
            from rag.core.orchestrator import PipelineOrchestrator  # noqa: PLC0415
            from rag.extraction.llm_extractor import (  # noqa: PLC0415
                EntityExtractor,
                PaperExtractor,
            )
            from rag.retrieval.bge_hybrid_retriever import (  # noqa: PLC0415
                BGEHybridRetriever,
            )

            if os.getenv("RAG_USE_CHROMADB", "false").lower() == "true":
                import chromadb  # noqa: PLC0415

                chroma_client: Any = chromadb.EphemeralClient()
            else:
                logger.info("使用内存 collection 适配器，避免 ChromaDB 默认 embedding 下载")
                chroma_client = _InMemoryChromaClient()

            retriever = BGEHybridRetriever(
                model_dir=self._bge_model_dir,
                use_fp16=self._bge_use_fp16,
            )
            paper_extractor = PaperExtractor(
                model=self._llm_model,
                api_key=self._llm_api_key,
                base_url=self._llm_base_url,
            )
            entity_extractor = EntityExtractor(
                model=self._llm_model,
                api_key=self._llm_api_key,
                base_url=self._llm_base_url,
            )

            self._orchestrator = PipelineOrchestrator(
                retriever=retriever,
                paper_extractor=paper_extractor,
                entity_extractor=entity_extractor,
                chroma_client=chroma_client,
                scout_model=self._scout_model,
                scout_api_key=self._llm_api_key,
                scout_base_url=self._llm_base_url,
            )
            logger.info("PipelineOrchestrator 初始化完成")
        return self._orchestrator

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def _parse_id_for_path(self, pdf_path: str | Path) -> str:
        """用 PDF 绝对路径生成稳定的解析缓存 ID。"""
        abs_path = str(Path(pdf_path).resolve())
        return hashlib.md5(abs_path.encode()).hexdigest()

    def _chunk_cache_file(self, pdf_path: str | Path) -> Path:
        return _CHUNK_CACHE_DIR / f"{self._parse_id_for_path(pdf_path)}.json"

    def _load_or_parse_chunks(self, pdf_path: str | Path) -> list[dict[str, Any]]:
        cache_file = self._chunk_cache_file(pdf_path)
        if cache_file.exists():
            chunks = json.loads(cache_file.read_text(encoding="utf-8"))
            logger.info(
                "parse chunks 命中缓存: %s (%d chunks)",
                cache_file.stem,
                len(chunks),
            )
            return chunks

        parser = self._get_parser()
        chunks = parser.parse(
            str(Path(pdf_path).resolve()),
            chunk_method=self._ragflow_chunk_method,
        )
        cache_file.write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("parse chunks 完成并缓存: %s (%d chunks)", cache_file.stem, len(chunks))
        return chunks

    def run_pipeline(
        self,
        pdf_path: str,
        output_dir: str | None = None,
        template_id: str = "hap_peptide_v1",
        schema_template_path: str | None = None,
        overwrite: bool = True,
        paper_key: str | None = None,
    ) -> dict[str, Any]:
        """
        端到端结构化抽取：解析 → 盲盒发现 → 检索 → 字段抽取 → 五表 CSV 写出。

        Parameters
        ----------
        pdf_path : str
            本地 PDF 文件的绝对路径。
        output_dir : str | None
            CSV 输出目录；None 时只返回 paper_meta + entities，不写 CSV。
        template_id : str
            schema 模板 ID（默认 hap_peptide_v1），用于加载 CSV 字段合约。
        schema_template_path : str | None
            schema.yaml 显式路径；None 时根据 template_id 自动推导。
        overwrite : bool
            True 时覆盖已有 CSV 文件。
        paper_key : str | None
            文献 paper_key，用于生成稳定实体 ID。

        Returns
        -------
        dict
            - status     : "ok" | "error"
            - pdf_path   : 输入路径
            - paper_meta : 论文元数据
            - entities   : 原始实体列表
            - output_dir : CSV 输出目录（仅当 output_dir 不为 None 时存在）
            - csv_files  : {table_name: path}（同上）
            - tables     : {table_name: {rows: n}}（同上）
        """
        try:
            chunks = self._load_or_parse_chunks(pdf_path)
            orchestrator = self._get_orchestrator()
            raw = orchestrator.process_pdf(
                pdf_path,
                chunks,
                retrieval_threshold=self._retrieval_threshold,
                retrieval_top_k=self._retrieval_top_k,
            )

            result: dict[str, Any] = {
                "status":     "ok",
                "pdf_path":   pdf_path,
                "paper_meta": raw.get("paper_meta", {}),
                "entities":   raw.get("entities", []),
            }

            if output_dir is not None:
                # 加载 CSV 字段合约
                from backend.src.tools.rag_paper.template_contract import load_extraction_contract
                from backend.src.tools.rag_paper.normalizer import normalize_to_five_tables
                from backend.src.tools.rag_paper.csv_writer import write_tables_to_csv

                contract = load_extraction_contract(
                    template_id=template_id,
                    schema_template_path=schema_template_path,
                )
                tables = normalize_to_five_tables(raw, contract, paper_key=paper_key)
                csv_result = write_tables_to_csv(
                    tables=tables,
                    contract=contract,
                    output_dir=output_dir,
                    overwrite=overwrite,
                )
                result.update({
                    "output_dir": output_dir,
                    "csv_files":  csv_result["csv_files"],
                    "tables":     csv_result["tables"],
                })

            return result

        except Exception as exc:
            logger.exception("run_pipeline 失败: %s", pdf_path)
            return {"status": "error", "pdf_path": pdf_path, "error": str(exc)}

    def parse_pdf(self, pdf_path: str) -> dict[str, Any]:
        """
        仅执行 RAGFlow 视觉解析（不触发 LLM），结果写入本地缓存。

        适用场景：先解析、后多次检索（避免重复解析浪费时间）。

        Parameters
        ----------
        pdf_path : str
            本地 PDF 文件的绝对路径

        Returns
        -------
        dict
            - status      : "ok" | "error"
            - pdf_path    : 输入路径
            - parse_id    : PDF 路径的 md5 哈希，作为后续检索的凭证
            - chunk_count : 解析产生的 chunk 数量
        """
        try:
            # parse_id = PDF 绝对路径的 md5，保证同一文件幂等
            parse_id = self._parse_id_for_path(pdf_path)
            chunks = self._load_or_parse_chunks(pdf_path)

            return {
                "status": "ok",
                "pdf_path": pdf_path,
                "parse_id": parse_id,
                "chunk_count": len(chunks),
            }
        except Exception as exc:
            logger.exception("parse_pdf 失败: %s", pdf_path)
            return {"status": "error", "pdf_path": pdf_path, "error": str(exc)}

    def retrieve_evidence(
        self, parse_id: str, query: str, top_k: int = 8
    ) -> dict[str, Any]:
        """
        基于已解析的 PDF，用 BGE-M3 混合检索找到与 query 最相关的段落。

        必须先调用 parse_pdf() 获得 parse_id，再调用本方法。

        Parameters
        ----------
        parse_id : str
            parse_pdf() 返回的 parse_id（md5 字符串）
        query : str
            检索问题，例如实体名、实验方法、表格字段名
        top_k : int
            最多返回的 chunk 数，默认 8

        Returns
        -------
        dict
            - status   : "ok" | "error"
            - parse_id : 输入的 parse_id
            - query    : 输入的检索问题
            - evidence : 列表，每项包含 chunk_id 和 text
        """
        try:
            cache_file = _CHUNK_CACHE_DIR / f"{parse_id}.json"
            if not cache_file.exists():
                raise FileNotFoundError(
                    f"parse_id={parse_id} 的缓存不存在，请先调用 parse_pdf()"
                )

            chunks = json.loads(cache_file.read_text(encoding="utf-8"))

            if self._retriever is None:
                from rag.retrieval.bge_hybrid_retriever import (  # noqa: PLC0415
                    BGEHybridRetriever,
                )
                self._retriever = BGEHybridRetriever(
                    model_dir=self._bge_model_dir,
                    use_fp16=self._bge_use_fp16,
                )
                logger.info("BGEHybridRetriever 初始化完成")

            retriever_chunks = [
                {
                    "chunk_id": c.get("trace_id") or c.get("chunk_id") or f"chunk_{i}",
                    "text": c.get("text", ""),
                }
                for i, c in enumerate(chunks)
            ]
            self._retriever.build_index(retriever_chunks)
            raw_context = self._retriever.retrieve(
                query=query,
                threshold=self._retrieval_threshold,
                top_k=top_k,
            )
            evidence = _context_to_evidence(raw_context)
            return {
                "status": "ok",
                "parse_id": parse_id,
                "query": query,
                "evidence": evidence,
            }
        except Exception as exc:
            logger.exception("retrieve_evidence 失败: parse_id=%s", parse_id)
            return {"status": "error", "parse_id": parse_id, "error": str(exc)}


def _context_to_evidence(raw_context: str) -> list[dict[str, str]]:
    """把 Retriever 返回的拼接上下文拆回 evidence 列表。"""
    evidence: list[dict[str, str]] = []
    if not raw_context.strip():
        return evidence

    marker = "--- [源区块 ID:"
    for block in raw_context.split(marker):
        block = block.strip()
        if not block:
            continue

        if "] ---" in block:
            chunk_id, text = block.split("] ---", 1)
            evidence.append(
                {
                    "chunk_id": chunk_id.strip(),
                    "text": text.strip(),
                }
            )

    return evidence
