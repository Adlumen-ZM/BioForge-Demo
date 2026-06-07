# -*- coding: utf-8 -*-
"""
tools/rag_paper/tools.py — LangChain @tool 注册
===============================================

本文件将 BioPaperRAGService 的三个核心方法包装为 LangChain 工具，
供 Agent 框架（LangGraph / ReAct / ToolCallingAgent 等）直接调用。

工具设计原则
------------
1. 职责单一：每个工具只做一件事，Agent 自行决定调用顺序。
2. 无状态：工具函数本身不持有状态，每次调用从工厂函数获取服务实例。
3. 错误透明：异常不被吞掉，直接抛出让 Agent 感知并重试或报错。

三个工具的关系
--------------
方案 A（一步到位）：
    直接调用 run_bio_paper_extraction_pipeline，完成全流程抽取。

方案 B（两步，适合需要多次检索不同字段的场景）：
    1. parse_pdf_with_ragflow       -> 获得 parse_id
    2. retrieve_pdf_evidence * N    -> 用不同 query 多次检索
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from tools.rag_paper.schemas import (
    ParsePDFInput,
    RetrieveEvidenceInput,
    RunBioPaperPipelineInput,
)
from tools.rag_paper.service_factory import build_rag_service


@tool(
    "run_bio_paper_extraction_pipeline",
    args_schema=RunBioPaperPipelineInput,
)
def run_bio_paper_extraction_pipeline(pdf_path: str) -> dict:
    """
    对单篇生物矿化 / HAp 领域 PDF 执行端到端结构化抽取。

    内部自动完成：
      RAGFlow 视觉解析 -> 盲盒实体发现（Scout）-> BGE-M3 混合检索（Strike）-> LLM 字段抽取

    返回值包含：
      - paper_meta : 论文元数据（标题、作者、DOI、期刊、年份）
      - entities   : 结构化实体列表，每项含实体类型、字段值、证据 chunk 引用

    适用场景：extract_agent 在不需要手动拆解步骤时直接调用（黑盒一键抽取）。
    """
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")
    service = build_rag_service()
    return service.run_pipeline(pdf_path)


@tool(
    "parse_pdf_with_ragflow",
    args_schema=ParsePDFInput,
)
def parse_pdf_with_ragflow(pdf_path: str) -> dict:
    """
    使用 RAGFlow deepdoc 视觉引擎解析 PDF，完成版式识别、表格保护与文本切片。

    返回值包含：
      - parse_id    : PDF 路径的 md5 哈希（后续 retrieve_pdf_evidence 的必填参数）
      - chunk_count : 切分产生的 chunk 数量

    解析结果会自动缓存到本地临时目录，同一 PDF 重复调用不会触发重新解析。

    适用场景：screen_agent 或 extract_agent 在需要"先解析、后多次检索"时调用。
    """
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")
    service = build_rag_service()
    return service.parse_pdf(pdf_path)


@tool(
    "retrieve_pdf_evidence",
    args_schema=RetrieveEvidenceInput,
)
def retrieve_pdf_evidence(parse_id: str, query: str, top_k: int = 8) -> dict:
    """
    基于已解析的 PDF（由 parse_pdf_with_ragflow 产生的 parse_id）执行 BGE-M3 混合检索。

    检索策略：稀疏（BM25）+ 稠密（向量相似度）加权融合，权重由 .env 配置。

    返回值包含：
      - evidence : 列表，每项含 chunk_id（段落定位标识）和 text（原文片段）

    适用场景：review_agent 验证某字段的文献依据；或 extract_agent 需要
    定向检索特定实体 / 字段证据时调用（可用不同 query 多次检索同一 PDF）。
    """
    service = build_rag_service()
    return service.retrieve_evidence(parse_id=parse_id, query=query, top_k=top_k)
