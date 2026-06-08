"""
backend/src/cli/__init__.py

对话式 CLI 包的公开接口。
入口：python -m backend.src.cli
主函数：app.main()
"""

from .app import main

__all__ = ["main"]
