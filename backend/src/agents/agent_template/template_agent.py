"""
template_agent.py — AgentTemplate 主类（对外唯一入口）

位置：依赖 agent_template/ 下所有模块。
职责：封装 plan 加载、identity 加载、TraceHook 构造、PlanRunner 调用、output_adapter 适配，
     对外暴露单一 run() 方法。

使用方式（各 agent 的 agent.py 中）：
    from backend.src.agents.agent_template import AgentTemplate
    from backend.src.agents.agent_template.config import AgentTemplateConfig
    from pathlib import Path

    config = AgentTemplateConfig(
        agent_name="search_agent",
        plan_path=Path(__file__).parent / "plan.yaml",
        identity_path=Path(__file__).parent / "identity.yaml",
        skills_dir=Path(__file__).parent / "skills",
        model="minimax/MiniMax-M2.7-highspeed",   # 或任意 LiteLLM 兼容字符串
        tools=["pubmed_search"],
    )
    agent = AgentTemplate(config)
    state_patch = agent.run(pipeline_state={})

设计原则：
  - 组合注入，非继承：各 agent 通过配置注入复用，不改 template 代码。
  - run() 每次创建新的 TemplateAgentState（无跨 run 状态）。
  - TraceHook 在初始化时构造（NullBackend），各 agent 可在构造后替换 backend。

扩展点：
  - 替换 trace backend：agent.hook.backend = PostgresBackend(session)
  - 注入上游 context：agent.run(pipeline_state, upstream_context={...})
  - 自定义 _build_summary：在 executor.py 级别 monkey-patch 或子类化
"""

from __future__ import annotations

from typing import Any, Optional

from .config import AgentTemplateConfig
from .hooks import NullBackend, TraceHook
from .output_adapter import adapt
from .plan_runner import PlanRunner
from .planner import load_identity, load_plan
from .schemas import AgentRunResult


class AgentTemplate:
    """通用 Agent 模板，供 search/screen/extract 三个 agent 通过配置注入复用。

    不使用继承——各 agent 只需实例化此类并传入自己的 config。
    个性化通过 plan.yaml / identity.yaml / skills/ / tools 列表表达。
    """

    def __init__(self, config: AgentTemplateConfig):
        """初始化 AgentTemplate：加载 plan 和 identity，构造 TraceHook。

        Args:
            config: AgentTemplateConfig，由各 agent 的 agent.py 构造并传入。

        Raises:
            PlanLoadError: plan.yaml 或 identity.yaml 加载失败时抛出。
        """
        self.config = config

        # ── 加载 plan 和 identity（失败时早失败，避免运行时才发现配置错误）
        self.plan = load_plan(config.plan_path)
        self.identity = load_identity(config.identity_path)

        # ── 构造 TraceHook（默认 NullBackend，可在外部替换 hook.backend）──
        # run_id 在每次 run() 中由 PlanRunner 生成，此处先用占位符
        self.hook = TraceHook(
            run_id="__unset__",  # 每次 run() 前由 PlanRunner 更新
            agent_name=config.agent_name,
            backend=NullBackend(),
            enabled=config.enable_trace,
        )

        # ── 构造 PlanRunner（持有 config / identity / hook 引用）──────────
        self._runner = PlanRunner(
            config=config,
            identity=self.identity,
            hook=self.hook,
        )

    def run(
        self,
        pipeline_state: Optional[dict[str, Any]] = None,
        upstream_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """执行完整 agent run，返回可 merge 进 PipelineState 的 patch dict。

        Args:
            pipeline_state: 当前 PipelineState（供读取上游字段，v0.1 可传 None 或 {}）。
            upstream_context: 可选，上游 agent 的输出片段（直接注入 context_builder）。
                              若 None 且 pipeline_state 非空，此方法不自动从中提取
                              （graph 层负责决定传哪些字段给各 agent）。

        Returns:
            dict patch，供调用方 merge 进 PipelineState。
            示例：{'candidate_paper_ids': [...], 'search_summary': '...', 'run_metadata': {...}}
        """
        # 每次 run 使用 plan 的内存副本（防止多次 run 之间的状态污染）
        import copy
        plan_copy = copy.deepcopy(self.plan)

        # PlanRunner 负责生成 run_id 并同步到 hook
        run_result: AgentRunResult = self._runner.run(
            plan=plan_copy,
            upstream_context=upstream_context,
        )

        # 将 AgentRunResult 适配为 PipelineState patch
        state_patch = adapt(run_result, self.config)

        return state_patch

    @property
    def last_run_id(self) -> str:
        """返回最近一次 run 的 run_id（从 hook 中读取，调试用）。"""
        return self.hook.run_id
