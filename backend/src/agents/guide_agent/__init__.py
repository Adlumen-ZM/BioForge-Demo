"""
backend/src/agents/guide_agent/__init__.py

guide_agent 包的公开接口。
导出 DemoGuideAgent、RealGuideAgent 和 build_guide_node，
供 graph/nodes.py 使用。
"""

from .agent import DemoGuideAgent, RealGuideAgent, build_guide_node

__all__ = ["DemoGuideAgent", "RealGuideAgent", "build_guide_node"]
