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
        # ⭐ 新增：LLM 修改指令判断
        # 触发条件：策略为 llm_on_exhaustion 且已用掉 replan_threshold 次重试
        # 仍处于 < effective_max_retries 分支内，保证至少还有一次重试机会
        should_llm_modify = (
            config.replan_strategy == "llm_on_exhaustion"
            and current_retry_count >= config.replan_threshold
        )
        if should_llm_modify:
            try:
                # 调 LLM 修改 step.instruction，返回 MODIFY_STEP 决策
                return _llm_modify_step(step, result, config)
            except Exception as e:
                # LLM 修改失败：降级为普通 RETRY，绝不影响主流程
                print(f"[Replanner] ⚠️ LLM modify 失败，降级为 RETRY：{e}")
                return ReplanDecision(
                    action=ReplanAction.RETRY,
                    target_step_id=step.step_id,
                    updated_step=None,
                    reason=(
                        f"LLM modify 失败（{e}），降级普通重试。"
                        f"step '{step.step_id}' 第 {current_retry_count + 1} 次，错误：{error_info}"
                    ),
                )

        # 尚有重试余量 → 普通 RETRY（原逻辑不变）
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


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ 新增：LLM MODIFY_STEP 相关私有函数（v0.2）
# ─────────────────────────────────────────────────────────────────────────────


def _llm_modify_step(
    step: PlanStep,
    result: StepResult,
    config: AgentTemplateConfig,
) -> ReplanDecision:
    """调用 LLM，根据失败信息生成修改后的 step instruction。

    触发条件（由 decide() 保证）：
      - config.replan_strategy == "llm_on_exhaustion"
      - current_retry_count >= config.replan_threshold
      - current_retry_count < effective_max_retries（还有重试机会）

    输入：失败的 PlanStep、对应的 StepResult（含 error_message）、运行配置。
    输出：ReplanDecision(action=MODIFY_STEP, updated_step=<新 PlanStep>)。

    降级行为：本函数内部不捕获异常，调用方 decide() 的 try/except 负责降级为 RETRY。
    """
    import copy
    import json

    import litellm

    # 构造发给 LLM 的 prompt
    prompt = _build_modify_prompt(step, result)

    # 调用 LLM（使用与主流程相同的模型，temperature=0 保证确定性）
    response = litellm.completion(
        model=config.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=512,
    )
    raw = response.choices[0].message.content.strip()

    # 解析 LLM 返回（三层 fallback，永不抛异常）
    parsed = _parse_modify_response(raw)

    # 构造修改后的 step（deepcopy 原 step，只替换 instruction）
    updated_step = copy.deepcopy(step)
    updated_step.instruction = parsed["new_instruction"]

    return ReplanDecision(
        action=ReplanAction.MODIFY_STEP,
        target_step_id=step.step_id,
        updated_step=updated_step,
        reason=parsed.get("reason", "LLM 根据失败信息修改了指令"),
    )


def _build_modify_prompt(step: PlanStep, result: StepResult) -> str:
    """构造 LLM 修改指令的 prompt。

    包含：step 名称、原始指令、失败原因、success_criteria（JSON 格式）。
    要求 LLM 输出严格 JSON：{"new_instruction": "...", "reason": "..."}。
    """
    import json

    criteria_str = json.dumps(step.success_criteria, ensure_ascii=False)
    error_msg = result.error_message or "未知错误"

    return f"""你是一个 AI Agent 的任务规划助手。
某个执行步骤失败了，请根据失败信息，改写执行指令以避免同样的错误。

## 失败的步骤
名称：{step.name}
原始指令：
{step.instruction}

## 失败原因
{error_msg}

## 该步骤需要满足的条件
{criteria_str}

## 要求
请输出改写后的指令，使其更清晰、更易于执行、能避免上述错误。
仅输出 JSON，格式如下（不要输出其他内容）：
{{
  "new_instruction": "改写后的完整指令文本",
  "reason": "为什么这样改（一句话）"
}}"""


def _parse_modify_response(raw: str) -> dict:
    """解析 LLM 返回的 JSON，三层 fallback 保健壮性。

    Layer 1：提取 ```json ... ``` 代码块。
    Layer 2：直接 json.loads（适用于 LLM 直接输出纯 JSON 的情况）。
    Layer 3：原文作为 new_instruction，标注格式异常。

    永不抛异常——调用方无需 try/except。
    """
    import json
    import re

    # Layer 1：提取 ```json 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass

    # Layer 2：直接解析（LLM 输出纯 JSON 时）
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except Exception:
            pass

    # Layer 3：fallback — 将原文作为 new_instruction
    return {
        "new_instruction": raw,
        "reason": "LLM 返回格式异常，原文使用",
    }
