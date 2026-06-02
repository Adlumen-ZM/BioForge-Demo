"""
stopping.py — ReAct 停止条件配置

位置：底层，无内部依赖。
职责：定义传递给 create_react_agent 的停止/迭代上限参数。

扩展点：
  - 未来如需自定义停止函数（如检测到 "FINAL_ANSWER" 标记即停止），
    可在此增加 stop_fn: Optional[Callable] 字段并在 executor.py 接入。
  - recursion_limit 对应 LangGraph 的 graph.invoke(config={"recursion_limit": N})，
    防止 ReAct 无限循环。
"""

from typing import Literal

from pydantic import BaseModel, Field


class StoppingConfig(BaseModel):
    """控制单个 step 内 ReAct 循环的停止行为。

    executor.py 从此对象读取参数，构造传给 create_react_agent/invoke 的配置。
    """

    max_iterations: int = Field(default=10, ge=1, le=50)
    """单次 step 内 ReAct 最大迭代轮数（think-act-observe 为一轮）。
    超出则强制结束并标记 step 为 failed。
    对应 LangGraph recursion_limit = max_iterations * 3（粗估每轮 3 个节点）。
    """

    early_stopping_method: Literal["force", "generate"] = "force"
    """达到 max_iterations 后的处理方式：
    force   — 立即返回当前状态，不再生成（更安全，避免截断时产生格式错误输出）。
    generate — 强制让模型再生成一次最终答案（可能改善输出质量，但会多一次 API 调用）。
    v0.1 默认 force，与 LangGraph prebuilt 的 force_no_tool 策略对应。
    """

    @property
    def recursion_limit(self) -> int:
        """转换为 LangGraph invoke config 的 recursion_limit 值。

        LangGraph 每个 ReAct 轮次涉及 agent 节点 + tool 节点，
        保守估计每轮 3 个图节点，再加 2 作为缓冲。
        """
        return self.max_iterations * 3 + 2
