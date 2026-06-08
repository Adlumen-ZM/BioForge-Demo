"""
backend/src/agents/guide_agent/__init__.py

guide_agent 包的公开接口。
导出 MockGuideAgent、RealGuideAgent 和 build_guide_node，
供 graph/factory.py 和 graph/nodes.py 使用。
"""

from .agent import MockGuideAgent, RealGuideAgent, build_guide_node

__all__ = ["MockGuideAgent", "RealGuideAgent", "build_guide_node"]
