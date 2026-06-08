"""
backend/src/db_access/trace/__init__.py — Trace 包公开接口

外部模块使用：
  from backend.src.db_access.trace import record, get_manager, set_manager, TraceManager
"""

from .trace_manager import TraceManager, get_manager, record, set_manager
from .event_types import TraceEventType

__all__ = [
    "TraceManager",
    "TraceEventType",
    "get_manager",
    "set_manager",
    "record",
]
