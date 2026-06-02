"""
search_agent — 文献检索 Agent

对外暴露工厂函数 create_search_agent，返回配置好的 AgentTemplate 实例。
"""

from .agent import create_search_agent

__all__ = ["create_search_agent"]
