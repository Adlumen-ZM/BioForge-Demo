"""
executor.py — 单 Step 执行器

位置：依赖 schemas.py / config.py / stopping.py / errors.py + 外部 tools.registry。
职责：封装 create_react_agent 调用，执行单个 PlanStep，返回 StepResult。

LLM 接入（provider-agnostic）：
  统一使用 LiteLLM 作为后端，通过 ChatLiteLLM 桥接给 create_react_agent。
  model 字符串由 AgentTemplateConfig.model 注入（如 "openai/gpt-4o" 或
  "minimax/MiniMax-M2.7-highspeed"），API key 由 .env 环境变量提供，
  executor 层完全不感知供应商细节。

create_react_agent API（LangGraph 0.3+）：
  create_react_agent(model, tools, prompt=system_message)
  调用 agent.invoke({"messages": [HumanMessage(content=user_prompt)]},
                    config={"recursion_limit": N})
  最后一条 AIMessage 的 content 作为 step 输出文本，
  executor 将其解析为结构化 output dict。

StepSummary 生成（方案 C，不调 LLM）：
  _build_summary(output) 是纯函数，从 output dict 推导摘要，
  各 agent 可在自己的 executor 子模块中 override 此函数。

扩展点：
  - 需要严格结构化输出时，在 _extract_output() 后接入 instructor 库进行
    schema binding（当前版本跳过此步）。
  - 需要 streaming 输出时，换用 agent.stream() 并在此处聚合。
  - 自定义停止函数（如检测到特定 token 停止）：在 StoppingConfig 增加字段，
    在 create_react_agent 的 should_continue 参数处接入。
"""

from __future__ import annotations

import json
import re
from typing import Any

try:
    # langchain-community>=0.3.0 将 ChatLiteLLM 迁移至 langchain-litellm 包
    from langchain_litellm import ChatLiteLLM
except ImportError:
    # 向后兼容 langchain-community 0.2.x
    from langchain_community.chat_models import ChatLiteLLM  # type: ignore[no-redef]
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from .config import AgentTemplateConfig
from .errors import StepExecutionError
from .schemas import PlanStep, StepResult, StepSummary


def run_step(
    step: PlanStep,
    context: dict[str, str],
    config: AgentTemplateConfig,
) -> StepResult:
    """执行单个 PlanStep，返回 StepResult。

    Args:
        step: 当前要执行的 PlanStep（含 instruction / tools_required / success_criteria）。
        context: context_builder.build_context() 返回的 dict，
                 包含 'system_prompt' 和 'user_prompt' 两个 key。
        config: AgentTemplateConfig，含 model / temperature / stopping 等配置。

    Returns:
        StepResult，status 为 'success' 或 'failed'。

    Raises:
        StepExecutionError: create_react_agent 调用过程中发生不可恢复错误时抛出。
    """
    try:
        # ── 1. 从 registry 获取工具列表（按本 step 的 tools_required 过滤）───
        tools = _get_filtered_tools(step.tools_required, config.tools)

        # ── 2. 构造 LiteLLM 模型（provider-agnostic）────────────────────────
        model = ChatLiteLLM(
            model=config.model,
            temperature=config.temperature,
        )

        # ── 3. 构造 ReAct agent（LangGraph prebuilt）────────────────────────
        # LangGraph 0.3+ 使用 prompt 参数（取代已废弃的 state_modifier）
        system_message = SystemMessage(content=context["system_prompt"])
        agent = create_react_agent(
            model=model,
            tools=tools,
            prompt=system_message,
        )

        # ── 4. 执行 agent（单次 step 的完整 ReAct 循环）────────────────────
        invoke_config = {"recursion_limit": config.stopping.recursion_limit}
        result = agent.invoke(
            {"messages": [HumanMessage(content=context["user_prompt"])]},
            config=invoke_config,
        )

        # ── 5. 提取输出文本（最后一条 AIMessage）───────────────────────────
        output_text = _extract_final_message(result)

        # ── 6. 将文本解析为结构化 output dict──────────────────────────────
        output = _extract_output(output_text, step)

        # ── 7. 生成 StepSummary（纯函数，不调 LLM）─────────────────────────
        summary = _build_summary(output, step)

        return StepResult(
            step_id=step.step_id,
            status="success",
            output=output,
            summary=summary,
        )

    except StepExecutionError:
        raise  # 已是目标异常类型，直接上抛

    except Exception as e:
        # 将所有其他异常包装为 StepExecutionError，统一由 plan_runner 处理
        error_msg = f"{type(e).__name__}: {e}"
        summary = StepSummary(
            what_was_done=f"尝试执行 step {step.step_id}",
            what_was_produced="执行失败，无产出",
            issues_encountered=error_msg,
        )
        return StepResult(
            step_id=step.step_id,
            status="failed",
            output={},
            summary=summary,
            error_message=error_msg,
        )


def _get_filtered_tools(step_tool_names: list[str], agent_tool_names: list[str]) -> list:
    """从 registry 加载工具，按本 step 的 tools_required 过滤。

    过滤逻辑：取 step_tool_names 与 agent_tool_names 的交集，
    确保 step 不能越权使用 agent 未声明的工具。
    """
    # 延迟导入，避免循环依赖；tools.registry 由 tools 负责人维护
    from backend.src.tools.registry import get_tools  # type: ignore[import]

    # 取交集：step 声明 AND agent 授权
    allowed = [n for n in step_tool_names if n in agent_tool_names]
    return get_tools(allowed)


def _extract_final_message(invoke_result: dict) -> str:
    """从 create_react_agent 的 invoke 结果中提取最后一条 AI 消息文本。

    LangGraph create_react_agent 返回 {'messages': [...]},
    最后一条消息应为 AIMessage，其 content 即最终回答。

    兼容性说明：
      LangChain 1.x+ 在多模态或部分 LLM provider（如 GLM、Kimi 等）下，
      AIMessage.content 可能返回 list（形如 [{"type": "text", "text": "..."}]）
      而非 str。此处做统一归一化，确保始终返回字符串。
    """
    messages = invoke_result.get("messages", [])
    if not messages:
        raise StepExecutionError("unknown", "create_react_agent 返回空 messages 列表")

    last_msg = messages[-1]
    content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    # ── 归一化：list → str（新版 LangChain 多模态 content 格式兼容）────────
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                # {"type": "text", "text": "..."} 格式
                text_parts.append(block.get("text", ""))
            else:
                text_parts.append(str(block))
        content = "\n".join(part for part in text_parts if part)

    return content if isinstance(content, str) else str(content)


def _extract_output(text: str, step: PlanStep) -> dict[str, Any]:
    """将 agent 输出文本解析为结构化 dict。

    解析策略（三层 fallback）：
      1. 尝试提取 ```json ... ``` 代码块并解析。
      2. 尝试直接 JSON 解析（整个 text）。
      3. Fallback：将文本整体存入 {'raw_output': text}，让 validator 决定是否通过。

    扩展点：
      - 需要严格结构化输出时，可在此接入 instructor 库，
        使用 step.success_criteria 中的 schema 进行 schema binding。
    """
    # 策略 1：提取 ```json 代码块
    json_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if json_block:
        try:
            return json.loads(json_block.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 策略 2：直接 JSON 解析
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # 策略 3：从文本中提取第一个 { 到最后一个 } 之间的内容（处理 LLM 在正文中夹杂 JSON 的情况）
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # 策略 4：Fallback — 原文存储，由 validator 的 required_fields 规则捕获失败
    return {"raw_output": text}


def _build_summary(output: dict[str, Any], step: PlanStep) -> StepSummary:
    """从 output dict 推导 StepSummary（纯函数，不调 LLM）。

    默认实现：提取 output 的 key 列表和可量化字段作为摘要。
    各 agent 可在自己的 executor 封装中 override 此函数，提供更具体的摘要逻辑。

    key_numbers 提取规则：output 中值为 int/float/list（取 len）的字段。
    """
    key_numbers: dict[str, Any] = {}
    for k, v in output.items():
        if isinstance(v, (int, float)):
            key_numbers[k] = v
        elif isinstance(v, list):
            key_numbers[f"{k}_count"] = len(v)

    produced_keys = list(output.keys())
    what_was_produced = (
        f"输出字段：{produced_keys}" if produced_keys else "无结构化输出（见 raw_output）"
    )

    return StepSummary(
        what_was_done=f"执行 step '{step.name}'（{step.step_id}）",
        what_was_produced=what_was_produced,
        key_numbers=key_numbers,
    )
