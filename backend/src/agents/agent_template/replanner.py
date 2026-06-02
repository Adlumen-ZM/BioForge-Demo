"""
replanner.py — 失败时的重规划决策器

位置：依赖 schemas.py（PlanStep, StepResult, ReplanDecision, ReplanAction）、
     config.py（AgentTemplateConfig）、errors.py（ReplanError）。
职责：step 失败或 validate_plan 失败后，决定下一步动作（retry / abort）。

v0.1 策略（纯规则，不调 LLM）：
  - 重试次数 < max_retries → RETRY（不修改 step 定义）。
  - 重试次数 ≥ max_retries → ABORT。

触发条件（由 plan_runner 决定何时调用）：
  - validate_step 返回 False，且尚有重试余量。
  - validate_plan 返回 False（整个 plan 级失败，目前直接 ABORT）。

重要：Replanner 只修改内存中的 Plan 对象，plan_runner 持有此对象，
     不回写 YAML 文件（YAML = 设计时意图，内存 Plan = 运行时状态）。

扩展点（v0.1 未实现，注释标出）：
  - MODIFY_STEP：v0.2 可接入 LLM 生成修改后的 step.instruction，
    并通过 PlanStep(updated_step) 返回给 plan_runner 替换当前 step 定义。
  - INSERT_STEP：v0.2 可在当前位置插入补救 step（如「重新构造检索式」）。
  - LLM 决策模式：将 step_result.error_message + step.instruction 传给 LLM，
    让模型判断应 retry / modify / abort，而非固定规则。
"""

from __future__ import annotations

from .config import AgentTemplateConfig
from .errors import ReplanError
from .schemas import PlanStep, ReplanAction, ReplanDecision, StepResult


def decide(
    step: PlanStep,
    result: StepResult,
    current_retry_count: int,
    config: AgentTemplateConfig,
) -> ReplanDecision:
    """根据 step 失败信息和当前重试次数，决定重规划动作。

    Args:
        step: 失败的 PlanStep。
        result: StepResult（status=='failed'）。
        current_retry_count: 该 step 已经重试的次数（不含首次执行）。
        config: AgentTemplateConfig（包含 max_step_retries）。

    Returns:
        ReplanDecision，plan_runner 据此决定 retry 或 abort。

    Raises:
        ReplanError: replanner 自身逻辑出错（区别于正常的 abort 决策）。
    """
    # 取 step 级和 config 级 max_retries 的较小值，给 step 级设置更宽松或更严格的上限
    effective_max_retries = min(step.max_retries, config.max_step_retries)

    error_info = result.error_message or "未知错误"

    if current_retry_count < effective_max_retries:
        # 尚有重试余量 → RETRY
        return ReplanDecision(
            action=ReplanAction.RETRY,
            target_step_id=step.step_id,
            updated_step=None,  # RETRY 不修改 step 定义
            reason=(
                f"step '{step.step_id}' 第 {current_retry_count + 1} 次失败，"
                f"已重试 {current_retry_count}/{effective_max_retries} 次，继续重试。"
                f"错误信息：{error_info}"
            ),
        )
    else:
        # 达到重试上限 → ABORT
        return ReplanDecision(
            action=ReplanAction.ABORT,
            target_step_id=step.step_id,
            updated_step=None,
            reason=(
                f"step '{step.step_id}' 已重试 {current_retry_count}/{effective_max_retries} 次，"
                f"达到上限，终止本次 run。最后错误：{error_info}"
            ),
        )


def decide_plan_failure(reason: str) -> ReplanDecision:
    """validate_plan 失败后的决策（v0.1：直接 ABORT）。

    Args:
        reason: validate_plan 返回的失败理由。

    Returns:
        ReplanDecision(action=ABORT)。

    扩展点：
      v0.2 可在此检查失败理由，若属于「可补救型」（如某字段为空），
      则 INSERT_STEP 在 plan 末尾追加修复步骤后重跑 validate_plan。
    """
    return ReplanDecision(
        action=ReplanAction.ABORT,
        target_step_id="plan_validation",
        updated_step=None,
        reason=f"validate_plan 失败，终止 run。原因：{reason}",
    )
