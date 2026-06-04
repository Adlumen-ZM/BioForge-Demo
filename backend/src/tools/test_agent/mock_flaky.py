"""
backend/src/tools/test_agent/mock_flaky.py

位置：backend/src/tools/test_agent/
依赖：langchain_core.tools（@tool 装饰器）
职责：前 N 次调用失败、第 N+1 次成功的 mock tool，精确测试 replanner retry 逻辑。
      用模块级 dict 维护各 call_id 的调用计数，不同 step 用不同 call_id 互不干扰。

使用方式：
    在 test_agent plan.yaml 中：tools_required: ["mock_flaky"]
    LLM 调用时：mock_flaky(fail_count=1, call_id="step_02")

    ⚠️ 每次新 run 开始前，必须调用 reset_flaky_counters() 清空计数器，
       否则跨 run 会继承上一次的计数状态导致行为不符合预期。
       agent_runner.py 的 run_sync / run_streaming 会自动调用此函数。
"""

from __future__ import annotations

from langchain_core.tools import tool

# ─────────────────────────────────────────────
# 模块级计数器（测试专用，跨调用持久）
# ─────────────────────────────────────────────

_CALL_COUNTERS: dict[str, int] = {}
"""call_id → 已调用次数。
key 为 call_id 参数，value 为累计调用次数（含当前次）。
模块级存储，在同一 Python 进程内跨 tool 调用持久。
必须通过 reset_flaky_counters() 手动清零，否则跨 run 会积累。
"""


@tool
def mock_flaky(fail_count: int = 2, call_id: str = "default") -> dict:
    """前 fail_count 次调用返回失败，第 fail_count+1 次起返回成功。

    用于精确测试 replanner 的 retry 逻辑：
      - fail_count=1：第 1 次失败，第 2 次成功（min retry 场景）
      - fail_count=2：第 1、2 次失败，第 3 次成功（max_retries=2 的边界）

    用 call_id 区分不同 step 各自的计数器，同一 plan 中多个 step 用不同 call_id 互不干扰。

    Args:
        fail_count: 前多少次调用返回失败（之后永远成功），默认 2。
        call_id: 区分不同 step 的计数器 key，默认 "default"。
                 建议按 step_id 命名，如 "step_02_retry"。

    Returns:
        dict，前 fail_count 次包含 {"status": "failed", ...}，
              之后包含 {"status": "success", ...}。
    """
    # 递增当前 call_id 的计数
    _CALL_COUNTERS[call_id] = _CALL_COUNTERS.get(call_id, 0) + 1
    current_count = _CALL_COUNTERS[call_id]

    if current_count <= fail_count:
        # 前 fail_count 次：返回失败
        return {
            "status": "failed",
            "error": f"模拟第 {current_count} 次失败（共需失败 {fail_count} 次）",
            "call_count": current_count,
            "call_id": call_id,
        }
    else:
        # fail_count+1 次起：返回成功
        return {
            "status": "success",
            "result": f"第 {current_count} 次调用终于成功",
            "call_count": current_count,
            "call_id": call_id,
        }


def reset_flaky_counters(call_id: str | None = None) -> None:
    """重置 mock_flaky 的调用计数器。

    每次新 run 开始前调用此函数，防止跨 run 计数污染。
    此函数不加 @tool 装饰器，由调试工具（agent_runner.py）直接调用。

    Args:
        call_id: 若提供，只清除该 call_id 的计数；
                 若为 None（默认），清除所有 call_id 的计数。
    """
    if call_id is None:
        _CALL_COUNTERS.clear()
    else:
        _CALL_COUNTERS.pop(call_id, None)


def get_call_count(call_id: str = "default") -> int:
    """返回指定 call_id 的当前调用次数（测试断言用）。

    Args:
        call_id: 要查询的计数器 key。

    Returns:
        int，当前调用次数（未调用过则返回 0）。
    """
    return _CALL_COUNTERS.get(call_id, 0)
