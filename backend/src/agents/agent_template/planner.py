"""
planner.py — Plan 加载器

位置：依赖 schemas.py（Plan, PlanStep）、errors.py（PlanLoadError）。
职责：从 YAML 文件加载并校验 Plan 对象，供 template_agent.py 在初始化时调用。

关键设计决策：
  - Replanner 只修改内存中的 Plan 对象（plan_runner 持有），不回写 YAML。
    这使得 YAML 始终是「设计时意图」，内存 Plan 是「运行时状态」。
  - plan_id 若 YAML 不填，自动生成 UUID，保证 trace 记录唯一性。

依赖：需要 pyyaml（requirements.txt 已添加）。

扩展点：
  - 未来支持多模板 plan（如 A/B 测试不同策略），可在此增加 load_plan_by_variant() 函数。
  - 需要 plan 版本校验时，在此增加 SUPPORTED_VERSIONS 列表和版本检查逻辑。
"""

import uuid
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from .errors import PlanLoadError
from .schemas import Plan


def load_plan(path: Path) -> Plan:
    """从 YAML 文件加载并校验 Plan 对象。

    Args:
        path: plan.yaml 的文件路径（绝对路径或相对于 cwd）。

    Returns:
        校验通过的 Plan 对象（内存中可修改，不影响原文件）。

    Raises:
        PlanLoadError: 文件不存在、YAML 语法错误、Pydantic 校验失败时抛出。
    """
    if not path.exists():
        raise PlanLoadError(f"plan.yaml 文件不存在：{path}")

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PlanLoadError(f"plan.yaml YAML 解析失败：{e}") from e

    if not isinstance(raw, dict):
        raise PlanLoadError(f"plan.yaml 根级别应为 mapping，实际为 {type(raw).__name__}")

    # plan_id 若 YAML 未填，自动生成 UUID（保证 trace 记录唯一）
    if not raw.get("plan_id"):
        raw["plan_id"] = f"plan_{uuid.uuid4().hex[:8]}"

    try:
        plan = Plan.model_validate(raw)
    except PydanticValidationError as e:
        raise PlanLoadError(f"plan.yaml 结构校验失败：\n{e}") from e

    if not plan.steps:
        raise PlanLoadError(f"plan.yaml 的 steps 列表为空，agent_name={plan.agent_name}")

    return plan


def load_identity(path: Path) -> dict:
    """从 identity.yaml 加载 agent 身份配置，返回原始 dict（context_builder 消费）。

    Args:
        path: identity.yaml 的文件路径。

    Returns:
        dict，包含 agent_name/role/objective/responsibilities/constraints/output_contract 等字段。

    Raises:
        PlanLoadError: 文件不存在、YAML 语法错误、缺少必填字段时抛出。
    """
    if not path.exists():
        raise PlanLoadError(f"identity.yaml 文件不存在：{path}")

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PlanLoadError(f"identity.yaml YAML 解析失败：{e}") from e

    if not isinstance(raw, dict):
        raise PlanLoadError(f"identity.yaml 根级别应为 mapping，实际为 {type(raw).__name__}")

    # 校验必填字段
    required_keys = {"agent_name", "role", "objective"}
    missing = required_keys - set(raw.keys())
    if missing:
        raise PlanLoadError(f"identity.yaml 缺少必填字段：{missing}")

    return raw
