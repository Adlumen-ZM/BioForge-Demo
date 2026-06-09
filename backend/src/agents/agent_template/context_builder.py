"""
context_builder.py — Executor 输入上下文组装器

位置：依赖 schemas.py（PlanStep）、config.py（AgentTemplateConfig）、errors.py（ContextBuildError）。
职责：将 identity/skills/已完成 step 摘要/当前 step 指令组合为 executor 可用的 prompt dict。

Context Engineering 三层（本模块负责层 B）：
  层 A：step 内 ReAct messages — 由 create_react_agent 自管，本模块不涉及。
  层 B（本模块）：step 间上下文 — 读取已完成 step 的 StepResult.summary，
                  拼入下一 step 的 system prompt；不传完整 messages 历史。
  层 C：agent 间上下文 — output_adapter 生成 search_summary 写入 PipelineState，
                          传入侧 upstream_context 由 AgentTemplate.run() 可选接收。

Memory 接口（v0.1 不接线）：
  memory_refs 参数恒为 None。
  未来：从 db_access/memory/ 的 PostgresStore 按 namespace 读取历史记忆注入 system prompt。

扩展点：
  - 需要动态 skill 选择（根据 step 类型加载不同 skill）时，
    修改 _load_skills() 增加过滤逻辑。
  - 需要 upstream_context（来自上游 agent 的 PipelineState 片段）注入时，
    在 build_context() 增加 upstream_context 参数并追加到 system prompt 尾部。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .config import AgentTemplateConfig
from .errors import ContextBuildError
from .schemas import PlanStep


def build_context(
    config: AgentTemplateConfig,
    identity: dict,
    step: PlanStep,
    completed_summaries: list[dict],
    upstream_context: Optional[dict] = None,
    memory_refs: Optional[list[str]] = None,  # v0.1 未接线，保留接口
) -> dict[str, str]:
    """组装单个 step 的执行上下文。

    Args:
        config: AgentTemplateConfig，含 skills_dir 等路径信息。
        identity: 从 identity.yaml 加载的 dict（agent_name/role/objective 等）。
        step: 当前要执行的 PlanStep。
        completed_summaries: 已完成 step 的摘要列表（来自 TemplateAgentState.completed_summaries()）。
        upstream_context: 来自上游 agent 的 PipelineState 片段（可选，v0.1 可传 None）。
        memory_refs: 跨 run 记忆引用（v0.1 固定为 None，不接线）。

    Returns:
        dict，包含 'system_prompt'（str）和 'user_prompt'（str）两个 key，
        executor 将其直接传给 create_react_agent。

    Raises:
        ContextBuildError: skills_dir 不存在或 identity 格式错误时抛出。
    """
    # v0.1：memory_refs 固定不使用
    # 未来扩展点：从 db_access/memory/ 读取 memory_refs 对应的记忆条目注入 system prompt
    if memory_refs is not None:
        pass  # TODO(memory): 接入 PostgresStore 读取逻辑

    system_parts: list[str] = []

    # ── 层 1：Identity（agent 身份/职责/约束）────────────────────
    system_parts.append(_build_identity_section(identity))

    # ── 层 2：Skills（自然语言操作指南）──────────────────────────
    skills_text = _load_skills(config.skills_dir)
    if skills_text:
        system_parts.append("## 操作技能指南\n\n" + skills_text)

    # ── 层 3：已完成 step 摘要（层 B 上下文压缩）────────────────
    if completed_summaries:
        system_parts.append(_build_history_section(completed_summaries))

    # ── 层 4：上游 agent 上下文（层 C，可选）────────────────────
    if upstream_context:
        system_parts.append(_build_upstream_section(upstream_context))

    # ── 层 5：当前 step 指令 ──────────────────────────────────────
    system_parts.append(f"## 当前任务\n\n{step.instruction}")

    system_prompt = "\n\n".join(system_parts)
    user_prompt = f"请执行以上「当前任务」，step_id={step.step_id}，step_name={step.name}。"

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


def _build_identity_section(identity: dict) -> str:
    """将 identity.yaml 内容格式化为 system prompt 头部段落。"""
    lines = [
        f"# 角色身份：{identity.get('role', '未指定')}",
        f"\n**Agent 名称**：{identity.get('agent_name', '未知')}",
        f"\n**目标**：{identity.get('objective', '')}",
    ]

    responsibilities = identity.get("responsibilities", [])
    if responsibilities:
        lines.append("\n**职责**：")
        lines.extend(f"  - {r}" for r in responsibilities)

    constraints = identity.get("constraints", [])
    if constraints:
        lines.append("\n**约束**：")
        lines.extend(f"  - {c}" for c in constraints)

    output_contract = identity.get("output_contract", {})
    if output_contract:
        lines.append("\n**输出契约**（必须满足）：")
        for field_name, desc in output_contract.items():
            lines.append(f"  - `{field_name}`：{desc}")

    return "\n".join(lines)


def _load_skills(skills_dir: Path) -> str:
    """加载 skills/ 目录下所有 .md 文件，拼成一段 system prompt 文本。

    文件按文件名字母序排列，每个文件以 '### <文件名>' 为标题。
    如果 skills_dir 不存在或为空，返回空字符串（不报错，skills 是可选的）。
    """
    if not skills_dir.exists():
        return ""

    skill_files = sorted(skills_dir.glob("*.md"))
    if not skill_files:
        return ""

    parts = []
    for skill_file in skill_files:
        content = skill_file.read_text(encoding="utf-8").strip()
        if content:
            skill_name = skill_file.stem.replace("_", " ").title()
            parts.append(f"### {skill_name}\n\n{content}")

    return "\n\n".join(parts)


def _build_history_section(completed_summaries: list[dict]) -> str:
    """将已完成 step 的摘要格式化为「执行历史」段落，注入下一 step 上下文。

    传 summary + 实际 output 数据，让后续 step 能直接引用前序数据（如 dedup_filter 使用 raw_candidates）。
    大列表截断至 200 条以控制 token 消耗。
    """
    lines = ["## 已完成步骤摘要及输出数据（供参考）"]
    for s in completed_summaries:
        step_id = s.get("step_id", "unknown")
        summary: dict[str, Any] = s.get("summary", {})
        output: dict[str, Any] = s.get("output", {})

        lines.append(f"\n### step_id: {step_id}")
        lines.append(f"- 执行内容：{summary.get('what_was_done', '—')}")

        key_numbers = summary.get("key_numbers", {})
        if key_numbers:
            kn_str = "、".join(f"{k}={v}" for k, v in key_numbers.items())
            lines.append(f"- 关键数据：{kn_str}")

        issues = summary.get("issues_encountered")
        if issues:
            lines.append(f"- 遇到问题：{issues}")

        if output:
            lines.append(f"- 输出数据：\n```json\n{_truncate_output(output)}\n```")

    return "\n".join(lines)


def _truncate_output(output: dict[str, Any], max_list_items: int = 200) -> str:
    """将 output dict 序列化为 JSON，大列表截断至 max_list_items 条。"""
    import json
    truncated: dict[str, Any] = {}
    for k, v in output.items():
        if isinstance(v, list) and len(v) > max_list_items:
            truncated[k] = v[:max_list_items]
            truncated[f"_{k}_note"] = f"已截断，原始共 {len(v)} 条"
        else:
            truncated[k] = v
    return json.dumps(truncated, ensure_ascii=False, indent=2)


def _build_upstream_section(upstream_context: dict) -> str:
    """将上游 agent 的 PipelineState 片段格式化为「上游结果」段落。

    v0.1：graph 层传入什么就格式化什么，不做深层解析。
    """
    lines = ["## 上游 Agent 输出（供参考）"]
    for key, value in upstream_context.items():
        lines.append(f"- **{key}**：{value}")
    return "\n".join(lines)
