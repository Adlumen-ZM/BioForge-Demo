"""
backend/src/tools/test_agent/mock_slow.py

位置：backend/src/tools/test_agent/
依赖：time（标准库）、langchain_core.tools（@tool 装饰器）
职责：模拟耗时操作的 mock tool，供 test_agent 测试以下场景：
      - StoppingConfig.max_iterations 超时行为
      - 耗时监控（trace 里的 duration_ms 是否合理）
      - Streamlit 流式显示时 step 卡片出现延迟的视觉效果

使用方式：
    在 test_agent plan.yaml 中：tools_required: ["mock_slow"]
    LLM 调用时：mock_slow(delay_seconds=3.0, output_template="default")
"""

from __future__ import annotations

import time

from langchain_core.tools import tool


@tool
def mock_slow(delay_seconds: float = 2.0, output_template: str = "default") -> dict:
    """sleep 指定秒数后返回成功结果。

    Args:
        delay_seconds: 等待时间（秒），默认 2.0s。建议不超过 30s，避免影响测试效率。
        output_template: 完成后返回的数据模板，与 mock_success 保持一致：
                         default / with_ids / with_counts / complex。

    Returns:
        dict，sleep 完成后返回成功结果（格式同 mock_success）。
    """
    # 限制最大延迟，防止测试超时
    actual_delay = min(max(delay_seconds, 0.0), 60.0)
    time.sleep(actual_delay)

    # sleep 完成后复用 mock_success 的模板数据
    templates: dict[str, dict] = {
        "default": {"result": "ok", "value": 42, "elapsed_seconds": actual_delay},
        "with_ids": {"candidate_ids": ["P001", "P002", "P003"], "total": 3},
        "with_counts": {"count": 10, "processed": 10, "skipped": 0},
        "complex": {
            "result": "ok",
            "metadata": {"source": "mock_slow", "delay_seconds": actual_delay},
        },
    }

    return templates.get(output_template, templates["default"])
