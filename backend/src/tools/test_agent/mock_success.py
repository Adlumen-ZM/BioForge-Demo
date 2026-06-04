"""
backend/src/tools/test_agent/mock_success.py

位置：backend/src/tools/test_agent/
依赖：langchain_core.tools（@tool 装饰器）
职责：永远返回成功的 mock tool，供 test_agent 测试正常流程。
      通过 output_template 参数控制返回数据形态，覆盖 template 框架的各种 success_criteria 断言。

使用方式：
    在 test_agent plan.yaml 中：tools_required: ["mock_success"]
    LLM 调用时：mock_success(output_template="with_ids")
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def mock_success(output_template: str = "default") -> dict:
    """永远返回成功结果。

    通过 output_template 选择返回数据的形态：
      default     → {"result": "ok", "value": 42}
      with_ids    → {"candidate_ids": ["P001","P002","P003"], "total": 3}
      with_counts → {"count": 10, "processed": 10, "skipped": 0}
      complex     → 带嵌套的成功结果（供验证 output_adapter 解析）

    Args:
        output_template: 数据形态模板名称，不认识的名称退回 default。

    Returns:
        dict，结构由 output_template 决定，不含 "_stub" 污染字段。
    """
    # 各种预设模板——对应不同的 success_criteria.required_fields 断言
    templates: dict[str, dict] = {
        "default": {
            "result": "ok",
            "value": 42,
        },
        "with_ids": {
            # 模拟 search_agent 返回候选文献 ID 列表
            "candidate_ids": ["P001", "P002", "P003"],
            "total": 3,
        },
        "with_counts": {
            # 模拟 screen_agent 返回统计数据
            "count": 10,
            "processed": 10,
            "skipped": 0,
        },
        "complex": {
            # 嵌套结构，测试 output_adapter 对多层 dict 的处理
            "result": "ok",
            "metadata": {
                "source": "mock",
                "version": "1.0",
            },
            "items": ["item_01", "item_02"],
        },
    }

    # 未知模板名退回 default，保证 tool 永不失败
    return templates.get(output_template, templates["default"])
