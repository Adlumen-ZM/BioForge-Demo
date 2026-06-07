# -*- coding: utf-8 -*-
"""
tools/rag_paper/schemas.py — 工具输入参数的 Pydantic 模型
=========================================================

LangChain @tool 通过 args_schema 参数读取这些模型，
自动完成入参校验和类型转换，无需在工具函数内手写 if 判断。

每个 Schema 对应一个工具：
    RunBioPaperPipelineInput  ->  run_bio_paper_extraction_pipeline
    ParsePDFInput             ->  parse_pdf_with_ragflow
    RetrieveEvidenceInput     ->  retrieve_pdf_evidence
"""

from pydantic import BaseModel, Field


class RunBioPaperPipelineInput(BaseModel):
    """run_bio_paper_extraction_pipeline 工具的输入参数。"""

    pdf_path: str = Field(
        ...,
        description=(
            "本地 PDF 文件的绝对路径，例如 /data/papers/example.pdf。"
            "文件必须存在且可读，否则抛出 FileNotFoundError。"
        ),
    )


class ParsePDFInput(BaseModel):
    """parse_pdf_with_ragflow 工具的输入参数。"""

    pdf_path: str = Field(
        ...,
        description=(
            "本地 PDF 文件的绝对路径，例如 /data/papers/example.pdf。"
            "解析结果会缓存到临时目录，后续可用 retrieve_pdf_evidence 检索。"
        ),
    )


class RetrieveEvidenceInput(BaseModel):
    """retrieve_pdf_evidence 工具的输入参数。"""

    parse_id: str = Field(
        ...,
        description=(
            "parse_pdf_with_ragflow 返回的 parse_id（32 位 md5 字符串）。"
            "必须先调用 parse_pdf_with_ragflow 才能获得此值。"
        ),
    )
    query: str = Field(
        ...,
        description=(
            "检索问题，例如实体名（HAp nanoparticles）、"
            "实验方法（XRD crystallinity）或表格字段名（particle size）。"
            "问题越具体，检索精度越高。"
        ),
    )
    top_k: int = Field(
        default=8,
        ge=1,
        le=20,
        description="最多返回的证据段落数，范围 1~20，默认 8。",
    )
