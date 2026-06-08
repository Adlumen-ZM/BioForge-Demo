"""
backend/src/graph/__init__.py

graph 包的公开接口。
导出 build_graph 供 CLI 和测试代码使用。
"""

from .pipeline import build_graph

__all__ = ["build_graph"]
