"""
backend/src/tools/test_agent/mock_fail.py

位置：backend/src/tools/test_agent/
依赖：langchain_core.tools（@tool 装饰器）
职责：永远返回失败状态的 mock tool，供 test_agent 测试 abort 路径。
      validator.validate_step 会读取 result.output 里的 "status": "failed" 并判断失败。
      搭配 plan_abort_scenario.yaml（max_retries=2）可精确测试 replanner abort 逻辑。

使用方式：
    在 test_agent plan.yaml 中：tools_required: ["mock_fail"]
    LLM 调用时：mock_fail(error_message="自定义错误信息")
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def mock_fail(error_message: str = "模拟失败：工具调用返回错误状态") -> dict:
    """永远返回失败状态。

    返回的 dict 包含 status="failed"，供 executor 将此 step 标记为 failed。
    error_message 可自定义，便于在 trace 中区分不同失败场景。

    Args:
        error_message: 失败原因描述，写入 trace payload 的 error_message 字段。

    Returns:
        dict，永远包含 {"status": "failed", "error": error_message}。
        注意：tool 本身不抛异常（遵守 AgentTemplate tool 约定），
              框架通过检查 output["status"] 判断失败。
    """
    return {
        "status": "failed",
        "error": error_message,
    }
