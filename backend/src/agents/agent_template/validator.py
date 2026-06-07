"""
validator.py — 两层验证器

位置：依赖 schemas.py（StepResult, PlanStep, AgentRunResult）、errors.py（ValidationError）。
职责：
  - validate_step()：纯规则校验（不调 LLM），判断单个 step 是否通过。
  - validate_plan()：LLM 校验，判断整个 run 的最终输出是否满足 output_contract。

设计原则：
  两个函数完全独立，分别可被单独测试和替换。
  validate_step 不调 LLM，保证校验速度和确定性；
  validate_plan 调 LLM，允许语义层面的灵活判断。

success_criteria 支持的规则类型（validate_step 的规则执行器）：
  required_fields: list[str]  — output 中必须存在且非空的 key。
  min_count: dict[str, int]   — output 中某 key（list 类型）的最小元素数量。
  不认识的规则 key 会被跳过并记录在 warning 里（向后兼容）。

扩展点：
  - 增加新规则类型：在 _check_criteria() 中添加对应的 elif 分支即可。
  - validate_plan 的 LLM prompt 可按 agent 定制：
    在 identity.yaml 的 output_contract 中补充期望格式，
    validate_plan 将 output_contract 完整传入 prompt。
"""

from __future__ import annotations

import json
from typing import Any

import litellm

from .errors import ValidationError
from .schemas import AgentRunResult, PlanStep, StepResult


def validate_step(result: StepResult, step: PlanStep) -> tuple[bool, str]:
    """纯规则校验单个 step 的执行结果。不调 LLM。

    Args:
        result: executor 返回的 StepResult。
        step: 对应的 PlanStep（含 success_criteria）。

    Returns:
        (True, "") 表示通过；(False, 错误描述) 表示不通过。
    """
    # 基础状态检查
    if result.status == "failed":
        reason = result.error_message or "step 状态为 failed"
        return False, f"step 执行失败：{reason}"

    if result.status == "skipped":
        # skipped 视为通过，不再做 criteria 检查
        return True, ""

    # success_criteria 规则校验
    ok, msg = _check_criteria(result.output, step.success_criteria)
    if not ok:
        return False, f"success_criteria 未满足：{msg}"

    return True, ""


def validate_plan(
    run_result: AgentRunResult,
    output_contract: dict[str, Any],
    model: str,
) -> tuple[bool, str]:
    """LLM 校验整个 run 的最终输出是否满足 output_contract。

    调用 LiteLLM（provider-agnostic），prompt 包含 output_contract 定义
    和 run_result.final_output 的 JSON 序列化。

    Args:
        run_result: plan_runner 完成后的 AgentRunResult。
        output_contract: identity.yaml 中定义的输出契约 dict，
                         如 {'candidate_paper_ids': '至少1篇，list[str]', 'search_summary': '...'}。
        model: LiteLLM 兼容的模型字符串（与 AgentTemplateConfig.model 一致）。

    Returns:
        (True, "") 表示通过；(False, 判断理由) 表示不通过。

    Raises:
        ValidationError: LiteLLM API 调用本身失败（非 LLM 返回 no 的情形）。
    """
    if not output_contract:
        # 没有 output_contract，直接通过（搜索型 agent 可能不定义）
        return True, ""

    prompt = _build_validate_plan_prompt(run_result.final_output, output_contract)

    try:
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=256,
        )
        answer = response.choices[0].message.content.strip().lower()
    except Exception as e:
        raise ValidationError(f"validate_plan LLM 调用失败：{e}") from e

    # 解析 LLM 回答：兼容英文 yes/no 及中文模型常见回答格式
    # 中文模型（如 deepseek）可能回答「是的」「满足」「否，因为...」等，
    # 不能只检查 startswith("yes")
    _YES = ("yes", "是的", "是,", "是。", "是 ", "满足", "通过", "符合", "✅")
    _NO  = ("no", "否", "不满足", "不符合", "未满足", "不通过", "❌")

    answer_head = answer[:60]  # 只看开头，避免理由中的关键词干扰
    is_yes = any(answer_head.startswith(s) for s in _YES)
    is_no  = any(answer_head.startswith(s) for s in _NO)

    if is_yes and not is_no:
        return True, ""
    elif is_no:
        # 提取 LLM 给出的理由（去掉前缀词）
        reason = answer
        for prefix in _NO:
            if reason.startswith(prefix):
                reason = reason[len(prefix):].lstrip("，,：:。. \n")
                break
        return False, reason or "LLM 判断输出不满足 output_contract"
    else:
        # 回答格式不符合预期（未以 yes/no 类词开头），在全文中搜索信号
        if any(s in answer for s in _YES):
            return True, ""
        return False, f"LLM 回答格式异常（期望 yes/no 开头）：{answer[:100]}"


def _check_criteria(output: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, str]:
    """执行 success_criteria 中的每条规则。

    返回 (True, "") 或 (False, 第一条失败规则的错误描述)。
    """
    for rule_key, rule_value in criteria.items():
        if rule_key == "required_fields":
            # 检查 output 中必须存在且非空的 key
            for field in rule_value:
                if field not in output:
                    return False, f"required_fields: 缺少字段 '{field}'"
                val = output[field]
                if val is None or val == "" or val == [] or val == {}:
                    return False, f"required_fields: 字段 '{field}' 为空"

        elif rule_key == "min_count":
            # 检查 list 类型字段的最小元素数量
            for field, min_n in rule_value.items():
                if field not in output:
                    return False, f"min_count: 缺少字段 '{field}'"
                val = output[field]
                if not isinstance(val, list):
                    return False, f"min_count: 字段 '{field}' 不是 list 类型（实际 {type(val).__name__}）"
                if len(val) < min_n:
                    return False, f"min_count: 字段 '{field}' 数量 {len(val)} < 要求的 {min_n}"

        else:
            # 未知规则类型，跳过（向后兼容，不报错）
            pass

    return True, ""


def _build_validate_plan_prompt(final_output: dict[str, Any], output_contract: dict[str, Any]) -> str:
    """构造 validate_plan 的 LLM prompt。

    期望 LLM 回答 "yes" 或 "no，<理由>" 格式，便于解析。
    """
    contract_json = json.dumps(output_contract, ensure_ascii=False, indent=2)
    output_json = json.dumps(final_output, ensure_ascii=False, indent=2)

    return f"""你是一个输出质量检查助手。判断「实际输出」是否包含「输出契约」要求的全部字段，且字段值非空。

## 输出契约（要求的字段及说明）
```json
{contract_json}
```

## 实际输出
```json
{output_json}
```

判断规则：实际输出中是否存在契约要求的所有字段（key），且值不为 null/空字符串/空列表。不校验值的具体内容，只看字段是否存在。

请用以下格式回答（第一个词必须是 yes 或 no，英文小写）：
- 满足：yes
- 不满足：no，<缺少或为空的字段名>

不要输出其他内容。"""
