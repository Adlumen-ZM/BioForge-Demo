"""
backend/src/agents/test_agent/__init__.py

位置：backend/src/agents/test_agent/
职责：test_agent 包入口，导出工厂函数供外部调用。

test_agent 定位：
  - 专用于验证 AgentTemplate 框架本身的行为（控制流/retry/abort/context传递/trace记录）
  - 不连接任何真实外部 API，所有 tool 调用结果可预测
  - 四个预设 plan 覆盖框架的所有主要分支

使用方式：
    from backend.src.agents.test_agent import create_test_agent
    agent = create_test_agent(plan_name="plan_retry_scenario")
    result = agent.run()
"""

from .agent import create_test_agent

__all__ = ["create_test_agent"]
