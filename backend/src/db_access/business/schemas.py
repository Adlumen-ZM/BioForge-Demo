# backend/src/db_access/business/schemas.py
"""
业务数据库接口层 Pydantic 数据契约

定义业务库三类操作（初始化/读取/写入）的输入输出结构。
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class DbInitResult(BaseModel):
    """ensure_business_db 的返回结构。"""

    status: str
    """ok / error"""
    db_path: str
    template_id: str
    tables_created: list[str] = Field(default_factory=list)
    vocab_count: int = 0
    already_existed: bool = False
    error: str | None = None


class CsvWriteResult(BaseModel):
    """write_rag_csv_to_business_db 的返回结构。"""

    status: str
    """ok / error"""
    db_path: str = ""
    tables_written: dict[str, int] = Field(default_factory=dict)
    """各表写入行数 {table_name: row_count}。"""
    skipped_tables: list[str] = Field(default_factory=list)
    """CSV 文件不存在而跳过的表名。"""
    errors: list[str] = Field(default_factory=list)
    error: str | None = None


class RagExtractionContract(BaseModel):
    """get_rag_extraction_contract 的返回结构。"""

    template_id: str
    csv_tables: dict[str, Any] = Field(default_factory=dict)
    """
    {
      table_name: {
        filename, primary_key,
        fields, required_fields,
        enum_fields, field_types
      }
    }
    """
    enum_groups: dict[str, list] = Field(default_factory=dict)


class PaperContext(BaseModel):
    """get_paper_context 的返回结构。"""

    exists: bool
    paper_id: str | None = None
    paper_key: str | None = None
    has_pdf: bool = False
    has_rag_csv: bool = False
    has_extraction: bool = False
    record_count: int = 0
    last_extraction_run: str | None = None
    reason: str | None = None
    db_path: str | None = None
