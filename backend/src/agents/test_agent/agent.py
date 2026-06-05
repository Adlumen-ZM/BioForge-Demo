"""
backend/src/agents/test_agent/agent.py — TestAgent 工厂函数

位置：backend/src/agents/test_agent/
依赖：backend/src/agents/agent_template（AgentTemplate, AgentTemplateConfig, SummaryMode）
职责：实例化 AgentTemplate，注入 test_agent 专属配置（plan/identity/skills/tools/model）。

test_agent 定位：
  - 专用于验证 AgentTemplate 框架本身行为（非业务 agent）
  - 四个预设 plan：happy_path / retry_scenario / abort_scenario / full_coverage
  - 所有 tools 均为 mock（不连接任何真实外部 API）
  - 算子调优工具通过 overrides dict 覆盖 config 参数

使用方式：
    from backend.src.agents.test_agent.agent import create_test_agent

    # 基本用法（使用默认 plan）
    agent = create_test_agent()
    patch = agent.run()

    # 指定 plan
    agent = create_test_agent(plan_name="plan_retry_scenario")

    # 算子调优工具覆盖参数
    agent = create_test_agent(overrides={"model": "openai/gpt-4o-mini"})

扩展点：
  - 替换 trace backend：
      agent.hook.backend = PostgresBackend()
  - 调整 plan：通过 plan_name 参数选择预设 plan，或通过 overrides["plan_path"] 指定自定义路径
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.src.agents.agent_template import AgentTemplate
from backend.src.agents.agent_template.config import AgentTemplateConfig
from backend.src.agents.agent_template.schemas import SummaryMode

# test_agent 包目录（plan / identity / skills 文件相对此文件所在目录）
_AGENT_DIR = Path(__file__).parent

# 可选的 plan 名称 → 文件名映射（不含.yaml后缀）
_PLAN_NAMES = {
    "happy_path": "plan_happy_path",
    "retry_scenario": "plan_retry_scenario",
    "abort_scenario": "plan_abort_scenario",
    "full_coverage": "plan_full_coverage",
    "deep_analysis": "plan_deep_analysis",
    # 支持直接传带前缀的完整名称
    "plan_happy_path": "plan_happy_path",
    "plan_retry_scenario": "plan_retry_scenario",
    "plan_abort_scenario": "plan_abort_scenario",
    "plan_full_coverage": "plan_full_coverage",
    "plan_deep_analysis": "plan_deep_analysis",
}

# test_agent 专属的 mock tools 白名单（物理隔离，禁止真实 agent 使用）
_TEST_TOOLS = [
    "mock_success",
    "mock_fail",
    "mock_slow",
    "mock_flaky",
    "mock_rich_output",
    # plan_deep_analysis 专属（多轮轮询 + validate_plan 失败路径测试）
    "mock_literature_search",
    "mock_fetch_details",
    "mock_binding_analysis",
    "mock_generate_report",
]


def create_test_agent(
    plan_name: str = "plan_happy_path",
    model: str | None = None,
    temperature: float = 0.0,
    summary_mode: SummaryMode = SummaryMode.TEMPLATE,
    overrides: dict[str, Any] | None = None,
) -> AgentTemplate:
    """工厂函数：创建配置好的 TestAgent 实例。

    Args:
        plan_name: 预设 plan 名称（不含 .yaml 后缀）。
                   可选值：happy_path / retry_scenario / abort_scenario / full_coverage。
                   也接受带前缀的完整文件名（如 "plan_retry_scenario"）。
                   默认："plan_happy_path"。
        model: LiteLLM 兼容的模型字符串。
               默认从环境变量 DEFAULT_LLM_MODEL 读取，
               若未设置则使用 "minimax/MiniMax-M2.7-highspeed"。
        temperature: LLM 采样温度，默认 0.0（确定性输出）。
        summary_mode: 摘要生成模式，默认 TEMPLATE（不调 LLM，适合快速测试）。
        overrides: 算子调优工具传入的覆盖参数 dict，可覆盖：
                   - "model": str — 覆盖模型字符串
                   - "plan_path": str | Path — 直接指定 plan 文件路径（优先于 plan_name）
                   - "temperature": float — 覆盖温度
                   - "summary_mode": SummaryMode — 覆盖摘要模式

    Returns:
        已初始化的 AgentTemplate 实例（plan 和 identity 已加载）。

    Raises:
        ValueError: plan_name 不在已知列表且 overrides 中也没有 plan_path 时。
        PlanLoadError: plan.yaml 文件不存在或格式错误时。
    """
    overrides = overrides or {}

    # ── 解析模型 ─────────────────────────────────────────────────────────────
    resolved_model = (
        overrides.get("model")
        or model
        or os.getenv("DEFAULT_LLM_MODEL", "minimax/MiniMax-M2.7-highspeed")
    )

    # ── 解析 plan 路径 ────────────────────────────────────────────────────────
    if "plan_path" in overrides:
        # overrides 直接指定路径（算子调优工具用）
        plan_path = Path(overrides["plan_path"])
    else:
        # 从 plan_name 解析到 plans/ 子目录下的文件
        canonical_name = _PLAN_NAMES.get(plan_name)
        if canonical_name is None:
            raise ValueError(
                f"未知 plan_name: '{plan_name}'。"
                f"可选值：{list(_PLAN_NAMES.keys())}，"
                f"或通过 overrides['plan_path'] 直接指定文件路径。"
            )
        plan_path = _AGENT_DIR / "plans" / f"{canonical_name}.yaml"

    # ── 解析其他覆盖参数 ───────────────────────────────────────────────────────
    resolved_temperature = overrides.get("temperature", temperature)
    resolved_summary_mode = overrides.get("summary_mode", summary_mode)

    # ── 构建 AgentTemplateConfig ───────────────────────────────────────────────
    config = AgentTemplateConfig(
        agent_name="test_agent",
        plan_path=plan_path,
        identity_path=_AGENT_DIR / "identity.yaml",
        skills_dir=_AGENT_DIR / "skills",
        model=resolved_model,
        temperature=resolved_temperature,
        tools=_TEST_TOOLS,           # 只给 test_agent 用的 mock tools
        max_step_retries=2,          # 允许最多 2 次 retry（覆盖 abort_scenario 边界）
        max_plan_retries=1,
        summary_mode=resolved_summary_mode,
        enable_trace=True,
        enable_memory=False,         # v0.1 不接线 memory
    )

    return AgentTemplate(config)
