"""
backend/src/tools/test_agent/mock_rich_output.py

位置：backend/src/tools/test_agent/
依赖：langchain_core.tools（@tool 装饰器）
职责：返回深层嵌套 dict 的 mock tool，专门测试以下框架行为：
      - output_adapter 对复杂嵌套数据的解析健壮性
      - StepSummary._build_summary 对大/复杂 output 的截断处理
      - context_builder 将上一 step 的大 output 注入下游时的行为
      - plan_runner 对含列表/嵌套 dict 的 step output 的序列化/反序列化

使用方式：
    在 test_agent plan.yaml 中：tools_required: ["mock_rich_output"]
    LLM 调用时：mock_rich_output()（无参数，固定返回复杂结构）
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def mock_rich_output() -> dict:
    """返回 3 层嵌套的复杂 dict，测试框架对复杂输出的处理健壮性。

    结构设计：
      - 顶层：必须字段（result、metadata、items、statistics）
      - 第 2 层：metadata（含多个 kv）、items（含对象列表）、statistics（含嵌套聚合）
      - 第 3 层：每个 item 对象含自身的 attributes dict

    用途：
      validator.validate_step 需能在嵌套结构中找到 required_fields。
      context_builder 注入大 output 时不应崩溃或截断关键信息。

    Returns:
        dict，3 层嵌套结构，含列表、嵌套 dict、多种数据类型。
    """
    return {
        # ── 顶层基本字段 ──
        "result": "ok",
        "total_processed": 15,

        # ── 第 2 层：元数据 ──
        "metadata": {
            "source": "mock_rich_output",
            "version": "1.0",
            "generated_at": "2026-01-01T00:00:00Z",
            "flags": ["test", "mock", "rich"],
        },

        # ── 第 2 层：条目列表（第 3 层含嵌套 dict）──
        "items": [
            {
                "id": f"ITEM{i:03d}",
                "name": f"测试条目 {i}",
                "score": round(0.5 + i * 0.05, 2),
                "attributes": {
                    "category": "mock",
                    "priority": i % 3,
                    "tags": [f"tag_{i}", "test"],
                },
            }
            for i in range(1, 6)  # 5 个条目，保持测试数据量可控
        ],

        # ── 第 2 层：统计聚合（含嵌套子聚合）──
        "statistics": {
            "total": 15,
            "success": 12,
            "failed": 3,
            "breakdown": {
                "by_category": {"mock": 15},
                "by_priority": {"0": 5, "1": 5, "2": 5},
            },
        },
    }
