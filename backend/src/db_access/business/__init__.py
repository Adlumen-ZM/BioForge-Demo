# backend/src/db_access/business/__init__.py
"""
业务数据库接口层

对外暴露三类操作：
  初始化  — ensure_business_db
  读取    — get_rag_extraction_contract / get_paper_context
  写入    — write_rag_csv_to_business_db
"""

from .init_service import ensure_business_db
from .reader import get_paper_context, get_rag_extraction_contract
from .csv_writer import write_rag_csv_to_business_db

__all__ = [
    "ensure_business_db",
    "get_rag_extraction_contract",
    "get_paper_context",
    "write_rag_csv_to_business_db",
]
