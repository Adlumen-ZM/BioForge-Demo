"""
output_adapter.py — AgentRunResult → PipelineState patch 适配器

位置：依赖 schemas.py（AgentRunResult, SummaryMode）、config.py（AgentTemplateConfig）、
     errors.py（OutputAdapterError）。
职责：将 AgentRunResult 转换为可 merge 进 graph 层 PipelineState 的 dict patch。

双模式摘要生成：
  TEMPLATE（默认）：纯函数从 step_results 拼接摘要字符串，不调 LLM，速度快。
  LLM：调 LiteLLM 生成自然语言摘要，语义更流畅但多一次 API 调用。
  由 AgentTemplateConfig.summary_mode 控制，各 agent 可按需选择。

PipelineState 集成：
  output_adapter 返回 dict patch，调用方（template_agent.run()）merge 进 PipelineState。
  当前支持的 patch key 由 graph/state.py 的 PipelineState 定义决定：
    - candidate_paper_ids（search_agent 产出）
    - search_summary / screen_summary / extract_summary（各 agent 摘要）
    - run_metadata（运行元数据，调试用）
  不同 agent 产出不同字段，未在 final_output 中的字段不会出现在 patch 中。

扩展点：
  - 新 agent 类型需要写入新的 PipelineState 字段时，直接在 _build_patch() 中增加映射即可。
  - 需要自定义摘要格式时，在 agent.py 中传入 summary_mode=SummaryMode.LLM 并
    在 identity.yaml 的 output_contract 中定义摘要要求。
"""

from __future__ import annotations

import json
from typing import Any

import litellm

from .config import AgentTemplateConfig
from .errors import OutputAdapterError
from .schemas import AgentRunResult, SummaryMode


def adapt(
    run_result: AgentRunResult,
    config: AgentTemplateConfig,
) -> dict[str, Any]:
    """将 AgentRunResult 转换为 PipelineState patch dict。

    Args:
        run_result: plan_runner 返回的完整运行结果。
        config: AgentTemplateConfig（含 summary_mode / model 等）。

    Returns:
        可直接 merge 进 PipelineState 的 dict，
        例如 {'candidate_paper_ids': [...], 'search_summary': '...', 'run_metadata': {...}}。

    Raises:
        OutputAdapterError: 适配过程中发生不可恢复错误。
    """
    try:
        # ── 1. 生成摘要文本（双模式）────────────────────────────────────────
        if config.summary_mode == SummaryMode.LLM:
            summary_text = _generate_llm_summary(run_result, config.model)
        else:
            summary_text = _generate_template_summary(run_result)

        # ── 2. 构造 PipelineState patch ──────────────────────────────────────
        patch = _build_patch(run_result, summary_text, config.agent_name)

        return patch

    except OutputAdapterError:
        raise
    except Exception as e:
        raise OutputAdapterError(f"output_adapter 适配失败：{e}") from e


def _generate_template_summary(run_result: AgentRunResult) -> str:
    """纯函数生成摘要文本（不调 LLM）。

    从每个成功 step 的 StepSummary 拼接人类可读的摘要段落。
    """
    lines = [f"Agent '{run_result.agent_name}' 运行结果：{run_result.status}"]
    lines.append(f"共 {len(run_result.step_results)} 个 step。")

    for r in run_result.step_results:
        if r.status == "success":
            s = r.summary
            line = f"- [{r.step_id}] {s.what_was_done}；{s.what_was_produced}"
            if s.key_numbers:
                kn = ", ".join(f"{k}={v}" for k, v in s.key_numbers.items())
                line += f"（{kn}）"
            lines.append(line)
        else:
            lines.append(f"- [{r.step_id}] 失败：{r.error_message or '未知错误'}")

    # 附加 final_output 关键字段
    final_keys = list(run_result.final_output.keys())
    if final_keys:
        lines.append(f"最终输出字段：{final_keys}")

    return "\n".join(lines)


def _generate_llm_summary(run_result: AgentRunResult, model: str) -> str:
    """调用 LiteLLM 生成自然语言摘要（TEMPLATE mode 的替代方案）。

    Raises:
        OutputAdapterError: LiteLLM 调用失败时抛出。
    """
    step_summaries = [
        {
            "step_id": r.step_id,
            "status": r.status,
            "summary": r.summary.model_dump(),
        }
        for r in run_result.step_results
    ]

    prompt = (
        f"请将以下 Agent 运行结果总结为一段不超过 150 字的中文摘要，"
        f"重点说明完成了什么、产出了哪些数据、有无问题。\n\n"
        f"Agent: {run_result.agent_name}\n"
        f"状态: {run_result.status}\n"
        f"Step 摘要: {json.dumps(step_summaries, ensure_ascii=False)}\n"
        f"最终输出键: {list(run_result.final_output.keys())}"
    )

    try:
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=300,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        raise OutputAdapterError(f"LLM 摘要生成失败：{e}") from e


def _build_patch(
    run_result: AgentRunResult,
    summary_text: str,
    agent_name: str,
) -> dict[str, Any]:
    """根据 agent_name 和 final_output 构造 PipelineState patch dict。

    字段映射规则（基于 graph/state.py 的 PipelineState 定义）：
      search_agent  → candidate_paper_ids + search_summary
      screen_agent  → candidate_paper_ids（过滤后）+ screen_summary
      extract_agent → extract_summary
      其他 agent    → 写入 agent_name_summary

    run_metadata 始终写入，供调试和 trace 关联使用。
    """
    patch: dict[str, Any] = {}

    # 通用：将 final_output 中已知的 PipelineState 字段直接映射
    final = run_result.final_output

    if "candidate_paper_ids" in final:
        patch["candidate_paper_ids"] = final["candidate_paper_ids"]

    # agent 特定摘要字段（去掉 _agent 后缀，与 PipelineState 字段名对齐）
    # "search_agent" → "search_summary" ✅  "test_agent" → "test_summary" ✅
    stage_name = agent_name.lower().replace("_agent", "").replace(" ", "_")
    summary_key = f"{stage_name}_summary"
    patch[summary_key] = summary_text

    # 运行元数据（调试用）
    patch["run_metadata"] = {
        "run_id": run_result.run_id,
        "agent_name": run_result.agent_name,
        "status": run_result.status,
        "step_count": len(run_result.step_results),
    }

    return patch
