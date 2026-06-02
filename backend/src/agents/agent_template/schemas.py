"""
schemas.py — AgentTemplate 全部数据契约定义

位置：最底层，无任何内部依赖，所有其他模块都可从此导入。
职责：定义 Plan 层、执行层、Replanner 层、OutputAdapter 层的 Pydantic v2 数据模型。

扩展点：
  - 新增字段时直接在对应模型加，Pydantic v2 默认值机制保证向后兼容。
  - success_criteria 目前是结构化 dict（validator.py 负责解释），
    未来如需更复杂规则可换成 Union 类型，但 validator.py 需同步修改。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# 辅助：Step 摘要（纯函数从 output 推导，不调 LLM）
# ─────────────────────────────────────────────

class StepSummary(BaseModel):
    """单个 step 的压缩摘要，用于下一个 step 的上下文注入。

    由 executor._build_summary(output) 纯函数生成，不额外调 LLM（方案 C）。
    各 agent 可在自己的 executor 子类中 override _build_summary。
    """

    what_was_done: str
    """本 step 执行了什么动作。"""

    what_was_produced: str
    """产出了哪些数据/结果。"""

    key_numbers: dict[str, Any] = Field(default_factory=dict)
    """关键数量指标，如 {'retrieved_count': 42, 'filtered_count': 10}。"""

    issues_encountered: Optional[str] = None
    """遇到的问题或异常，无则为 None。"""


# ─────────────────────────────────────────────
# Plan 层：从 YAML 加载，planner.py 负责解析
# ─────────────────────────────────────────────

class PlanStep(BaseModel):
    """Plan 中的单个 step 定义，从 plan.yaml 加载。

    重要：tools_required 限定本 step 可用的工具，executor 按此列表过滤。
    success_criteria 是结构化 dict，validator.validate_step 负责逐规则执行，
    目前支持 required_fields、min_count 两类规则，可在 validator.py 扩展。

    db_write_policy / db_write_target：
      声明式写库策略，plan_runner 读取后在固定位置触发（不经 LLM 决策）。
      v0.1 中 plan_runner 仅留 TODO 注释，实际写库由 graph 层负责。
    """

    step_id: str
    """step 唯一标识，用于 trace / replanner / 上下文引用。"""

    name: str
    """人类可读的 step 名称。"""

    instruction: str
    """注入 executor system prompt 的执行指令。"""

    tools_required: list[str] = Field(default_factory=list)
    """本 step 允许调用的 tool 名称列表；executor 按此从 registry 过滤。"""

    success_criteria: dict[str, Any] = Field(default_factory=dict)
    """结构化验收规则，validator.validate_step 可直接执行。
    示例：{'required_fields': ['candidate_ids'], 'min_count': {'candidate_ids': 1}}
    """

    max_retries: int = 2
    """本 step 最大重试次数，超出则 replanner 决定 abort 或跳过。"""

    db_write_policy: Literal["none", "after_step"] = "none"
    """写库触发策略：none=不触发；after_step=本 step 成功后触发（由 graph 层处理）。"""

    db_write_target: Optional[str] = None
    """写入目标表/集合名，db_write_policy=='after_step' 时由 graph 层读取。"""


class Plan(BaseModel):
    """一个 agent 的完整 plan，从 plan.yaml 加载后在内存中可被 replanner 修改。

    Replanner 只修改内存中的 Plan 对象，不回写 YAML 文件。
    """

    plan_id: str
    """plan 唯一标识，YAML 不填则 planner.py 自动生成 UUID。"""

    agent_name: str
    """所属 agent 名称，与 identity.yaml 的 agent_name 一致。"""

    version: str = "0.1"
    """plan 版本号，用于 trace 记录。"""

    steps: list[PlanStep]
    """有序 step 列表，plan_runner 按顺序执行。"""


# ─────────────────────────────────────────────
# 执行层：运行时产生的结果对象
# ─────────────────────────────────────────────

class StepResult(BaseModel):
    """单个 step 的执行结果，由 executor 返回，写入 TemplateAgentState.step_results。

    summary 字段由纯函数生成，是下游 step 的上下文压缩来源，
    不向下游传递完整 ReAct messages 历史（Context Engineering 层 B）。
    """

    step_id: str
    """对应 PlanStep.step_id。"""

    status: Literal["success", "failed", "skipped"]
    """执行状态。"""

    output: dict[str, Any] = Field(default_factory=dict)
    """结构化输出，内容由各 agent step 约定（如 {'candidate_ids': [...]}）。"""

    summary: StepSummary
    """压缩摘要，由 _build_summary(output) 生成，供后续 step context_builder 使用。"""

    error_message: Optional[str] = None
    """失败时的错误描述，成功时为 None。"""

    retry_count: int = 0
    """本 step 实际重试次数。"""


class AgentRunResult(BaseModel):
    """一次完整 agent run 的结果，由 plan_runner 返回给 template_agent。

    output_adapter 将此对象转换为 PipelineState patch。
    """

    agent_name: str
    run_id: str
    status: Literal["success", "failed", "partial"]
    step_results: list[StepResult]
    final_output: dict[str, Any] = Field(default_factory=dict)
    """整合所有 step output 的最终结构化输出，供 output_adapter 消费。"""


# ─────────────────────────────────────────────
# Replanner 层
# ─────────────────────────────────────────────

class ReplanAction(str, Enum):
    """Replanner 可采取的动作类型。

    v0.1 只实现 RETRY 和 ABORT；MODIFY_STEP / INSERT_STEP 为未来扩展预留。
    """

    RETRY = "retry"
    """重试当前 step（不修改 step 定义）。"""

    MODIFY_STEP = "modify_step"
    """修改当前 step 的 instruction / tools_required 后重试。（v0.1 未实现）"""

    INSERT_STEP = "insert_step"
    """在当前位置插入新 step。（v0.1 未实现）"""

    ABORT = "abort"
    """放弃整个 plan run，返回 failed 状态。"""


class ReplanDecision(BaseModel):
    """Replanner 的决策结果，plan_runner 据此更新内存 Plan。"""

    action: ReplanAction
    target_step_id: str
    """决策针对的 step_id。"""

    updated_step: Optional[PlanStep] = None
    """action==MODIFY_STEP 时提供修改后的 step 定义；其他情况为 None。"""

    reason: str
    """决策理由，写入 trace 事件 payload。"""


# ─────────────────────────────────────────────
# OutputAdapter 层
# ─────────────────────────────────────────────

class SummaryMode(str, Enum):
    """output_adapter 生成摘要的模式。

    TEMPLATE：纯函数拼接，不调 LLM，速度快、成本低。
    LLM：调 LiteLLM 生成摘要，质量更高但多一次 API 调用。
    由 AgentTemplateConfig.summary_mode 配置，可按 agent 级别切换。
    """

    TEMPLATE = "template"
    LLM = "llm"
