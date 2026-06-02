"""
plan_runner.py — Plan-and-Execute 核心 Runtime

位置：依赖 state / schemas / executor / validator / replanner / hooks / errors / context_builder。
职责：持有 TemplateAgentState，驱动整个 plan 的 step 循环，
     在固定位置调用 TraceHook，条件触发 replanner。

控制流（纯 Python while 循环，不套 LangGraph subgraph）：
  on_plan_start → for each step → on_step_start → executor → validate_step
                → [失败] replanner.decide → retry / abort
                → [成功] on_step_end → 继续下一 step
  所有 step 完成 → validate_plan（LLM）→ on_plan_end → 返回 AgentRunResult

DB 写入（非本模块范围）：
  本模块在 step 成功后留有 TODO 注释，标注 graph 层写库的扩展点。
  template 本身不调用任何 db_writer，业务数据写入由编排层（graph/pipeline.py）负责。

Memory（v0.1 不接线）：
  on_plan_end 之后留有 TODO 注释，标注未来 MemoryHook 接入位置。

final_output 合并策略：
  取所有成功 step 的 output 做浅合并（后面的 step 覆盖同名 key）。
  各 agent 可在 output_adapter 层做更精细的字段选择。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import context_builder as ctx_builder
from .config import AgentTemplateConfig
from .errors import AgentTemplateError
from .hooks import TraceHook
from .replanner import decide, decide_plan_failure
from .schemas import AgentRunResult, Plan, ReplanAction, StepResult
from .state import TemplateAgentState
from .validator import validate_plan, validate_step
from . import executor as exec_module


class PlanRunner:
    """Plan-and-Execute 运行时，plan_runner 的唯一入口类。

    由 AgentTemplate 实例化，每次 run() 调用创建新的 TemplateAgentState。
    """

    def __init__(
        self,
        config: AgentTemplateConfig,
        identity: dict,
        hook: TraceHook,
    ):
        """
        Args:
            config: AgentTemplateConfig，含模型/工具/路径/重试等配置。
            identity: 从 identity.yaml 加载的 dict，含 output_contract 等。
            hook: TraceHook 实例（NullBackend 或真实后端），由 AgentTemplate 构造并传入。
        """
        self.config = config
        self.identity = identity
        self.hook = hook

    def run(
        self,
        plan: Plan,
        upstream_context: Optional[dict[str, Any]] = None,
    ) -> AgentRunResult:
        """执行完整 plan，返回 AgentRunResult。

        Args:
            plan: 由 planner.load_plan() 加载的 Plan 对象（内存中可修改）。
            upstream_context: 来自上游 agent 的 PipelineState 片段（可选）。

        Returns:
            AgentRunResult，status 为 'success' / 'failed' / 'partial'。
        """
        # ── 初始化运行时状态 ─────────────────────────────────────────────────
        state = TemplateAgentState(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            agent_name=self.config.agent_name,
            plan=plan,
        )

        # ── trace 固定位置 1：plan_start ─────────────────────────────────────
        self.hook.run_id = state.run_id  # 将生成的 run_id 同步给 hook
        self.hook.on_plan_start(plan)

        aborted = False
        abort_reason: str = ""

        # ── 主循环：逐 step 执行 ──────────────────────────────────────────────
        step_index = 0
        while step_index < len(plan.steps):
            step = plan.steps[step_index]

            # trace 固定位置 2：step_start
            self.hook.on_step_start(step)

            # 组装本 step 的执行上下文
            context = ctx_builder.build_context(
                config=self.config,
                identity=self.identity,
                step=step,
                completed_summaries=state.completed_summaries(),
                upstream_context=upstream_context,
            )

            # 执行 step（executor 内部处理 LLM 调用异常，返回 status='failed' 的 StepResult）
            result: StepResult = exec_module.run_step(step, context, self.config)

            # 验证 step 结果（纯规则，不调 LLM）
            ok, validation_msg = validate_step(result, step)

            if ok:
                # ── step 成功路径 ──────────────────────────────────────────
                state.record_result(result)

                # trace 固定位置 3：step_end（成功）
                self.hook.on_step_end(step, result, state.get_retry_count(step.step_id))

                # TODO(graph层扩展点): 若 step.db_write_policy == "after_step"，
                # 未来由 graph 层在此位置调用 DB writer，将 result.output 写入业务库。
                # template 本身不负责业务库写入，写库策略由编排层决定。
                # 示例（graph 层伪代码）：
                #   if step.db_write_policy == "after_step" and step.db_write_target:
                #       db_writer.write(step.db_write_target, result.output,
                #                       run_id=state.run_id, step_id=step.step_id)

                step_index += 1

            else:
                # ── step 失败路径：交给 replanner 决策 ────────────────────
                current_retry = state.get_retry_count(step.step_id)
                decision = decide(step, result, current_retry, self.config)

                if decision.action == ReplanAction.RETRY:
                    # 重试：更新 step 定义（如有），增加重试计数，不推进 step_index
                    state.increment_retry(step.step_id)
                    if decision.updated_step is not None:
                        # MODIFY_STEP 路径（v0.1 纯规则下不会走到此处）
                        plan.steps[step_index] = decision.updated_step

                    # 记录失败结果（用于 trace 和上下文感知）
                    state.step_results.append(result)

                    # trace 固定位置 3：step_end（失败，将重试）
                    self.hook.on_step_end(step, result, state.get_retry_count(step.step_id))

                    # 继续循环（step_index 不变，下次循环重试同一 step）

                elif decision.action == ReplanAction.INSERT_STEP:
                    # v0.1 未实现，降级为 ABORT（v0.2 在此处插入补救 step）
                    state.step_results.append(result)
                    self.hook.on_step_end(step, result, state.get_retry_count(step.step_id))
                    aborted = True
                    abort_reason = f"INSERT_STEP v0.1 未实现，降级为 ABORT：{decision.reason}"
                    break

                else:
                    # ABORT：终止整个 run
                    state.step_results.append(result)
                    self.hook.on_step_end(step, result, state.get_retry_count(step.step_id))
                    aborted = True
                    abort_reason = decision.reason
                    break

        # ── 构造最终输出 ──────────────────────────────────────────────────────
        final_output = _merge_step_outputs(state.step_results)

        if aborted:
            run_result = AgentRunResult(
                agent_name=self.config.agent_name,
                run_id=state.run_id,
                status="failed",
                step_results=state.step_results,
                final_output=final_output,
            )
        else:
            # 所有 step 完成，执行 plan 级 LLM 校验
            output_contract = self.identity.get("output_contract", {})
            plan_ok, plan_msg = validate_plan(
                AgentRunResult(
                    agent_name=self.config.agent_name,
                    run_id=state.run_id,
                    status="success",
                    step_results=state.step_results,
                    final_output=final_output,
                ),
                output_contract,
                self.config.model,
            )

            if not plan_ok:
                plan_decision = decide_plan_failure(plan_msg)
                overall_status = "failed"
            else:
                overall_status = "success"

            # 判断是否有部分失败的 step
            has_failed = any(r.status == "failed" for r in state.step_results)
            if overall_status == "success" and has_failed:
                overall_status = "partial"

            run_result = AgentRunResult(
                agent_name=self.config.agent_name,
                run_id=state.run_id,
                status=overall_status,
                step_results=state.step_results,
                final_output=final_output,
            )

        # trace 固定位置 4：plan_end
        self.hook.on_plan_end(run_result)

        # TODO(memory): v0.1 不接线 MemoryHook
        # 未来扩展：if config.enable_memory: memory_hook.on_run_end(run_result, config.agent_name)
        # 见 hooks.py 末尾的 MemoryHook 接口草图

        return run_result


def _merge_step_outputs(step_results: list[StepResult]) -> dict[str, Any]:
    """将所有成功 step 的 output 做浅合并，后面的 step 覆盖同名 key。

    跳过 failed/skipped 的 step（其 output 通常为 {}）。
    """
    merged: dict[str, Any] = {}
    for result in step_results:
        if result.status == "success":
            merged.update(result.output)
    return merged
