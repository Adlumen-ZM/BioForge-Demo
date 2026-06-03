"""
hooks.py — Trace 事件 Sink 系统（旧 SQLite trace 的完全替换）

位置：依赖 schemas.py（Plan, PlanStep, StepResult, AgentRunResult）。
职责：定义 TraceEvent / TraceBackend / NullBackend / TraceHook，
     由 plan_runner 在 4 个固定位置调用，记录运行轨迹。

⚠️  本模块是对旧版 trace_logger.py（SQLite + extraction_runs/trace_steps 表）
    的完全替换。新设计是事件流 + Sink 后端，旧表结构作废。

Sink 模式架构：
  plan_runner → TraceHook → TraceBackend（抽象）
                                ├─ NullBackend（当前默认：只 print，不写入，不报错）
                                └─ PostgresBackend（backend/src/db_access/trace/postgres_backend.py）

两级 run_id 设计：
  TraceEvent.run_id       — pipeline 级别 ID（由 graph 层传入）
  TraceEvent.agent_run_id — agent 级别 ID（TemplateAgentState.run_id，格式 "run_<12hex>"）
  独立调试时（无 pipeline），两者相同（均等于 agent run_id）。

安全原则：
  TraceHook._write() 必须 try/except 包裹，trace 失败绝不传播给 plan_runner。
  TraceError 由 _write() 内部捕获后 print，不向上抛。

与 LangGraph checkpoint 的关系：
  TraceBackend 是业务可观测性（trace DB），与 LangGraph 的 PostgresSaver checkpointer
  （LANGGRAPH_CHECKPOINT_DB_URL，管理 graph 运行态恢复）是两回事，互不干扰。

扩展点：
  1. 接入自建 trace DB：backend/src/db_access/trace/postgres_backend.py 已实现
     PostgresBackend，在 template_agent.py 把 NullBackend() 换成 PostgresBackend()
     即可，其余代码零改动（从 TRACE_DB_URL 环境变量读取连接串）。
  2. 接入 Langfuse（自建部署）：实现 LangfuseBackend，同上替换即可。
  3. 同时写多个后端：实现 MultiBackend(backends=[...])，在 write() 中逐一调用。
  4. Pipeline 级别 trace：使用 backend/src/db_access/trace/pipeline_hook.py 的
     PipelineTraceHook，写入同一张 agent_trace_events 表。

==============================================================================
Memory Hook（v0.1 不实现，仅注释占位）
==============================================================================

未来 MemoryHook 的接入位置与签名草图：

class MemoryHook:
    '''在 plan run 结束后，将有价值的「记忆」写入 PostgresStore。

    接入点：plan_runner.run() 的 hook.on_plan_end() 之后调用 memory_hook.on_run_end()。
    存储：db_access/memory/writer.py（目前为 TODO）。
    namespace 设计：见 db/memory/namespace_design.md。
    '''

    def on_run_end(self, run_result: AgentRunResult, stage: str) -> None:
        # 从 run_result 提取有价值的记忆条目（如成功的检索式）
        # 调用 memory_writer.write(namespace=stage, key=..., value=...)
        pass

plan_runner 中对应位置（已留 TODO 注释）：
    # TODO(memory): hook.on_plan_end() 之后调用 memory_hook.on_run_end()
    # 当前 enable_memory=False，此处不调用
==============================================================================
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .schemas import AgentRunResult, Plan, PlanStep, StepResult


# ─────────────────────────────────────────────
# TraceEvent — 单条 trace 记录
# ─────────────────────────────────────────────

@dataclass
class TraceEvent:
    """单条 trace 事件，由 TraceHook / PipelineTraceHook 生成，由 TraceBackend 持久化。

    event_type 在 AgentTemplate 层固定为四种（plan_start/step_start/step_end/plan_end）；
    Pipeline 层（PipelineTraceHook）使用四种额外类型（pipeline_start/node_start/node_end/pipeline_end）。
    全部写入同一张 agent_trace_events 表，通过 event_type + stage 区分。

    两级 run_id：
      run_id       — pipeline 级别（由 graph 层生成并传入），独立调试时与 agent_run_id 相同
      agent_run_id — agent 级别（TemplateAgentState.run_id，格式 "run_<12hex>"），仅 AgentTemplate 层填写
    """

    run_id: str
    """pipeline 级别 run_id；独立调试时等于 agent_run_id。"""

    stage: str
    """产生此事件的逻辑阶段名，如 'search_agent'、'search_node'、'pipeline'。
    对应 DB 中的 stage 列，用于按 agent/节点聚合查询。
    （注：此字段在旧版本中名为 agent_name，Trace MVP 起统一改为 stage。）
    """

    event_type: str
    """事件类型，VARCHAR（不用 Literal 枚举，便于 PipelineTraceHook 扩展）。
    AgentTemplate 层：'plan_start' / 'step_start' / 'step_end' / 'plan_end'
    Pipeline 层：'pipeline_start' / 'node_start' / 'node_end' / 'pipeline_end'
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    step_id: Optional[str] = None
    """step_start / step_end 事件填写对应 step_id，plan / pipeline 级事件为 None。"""

    payload: dict[str, Any] = field(default_factory=dict)
    """事件携带的结构化信息，内容因 event_type 而异（见 TraceHook 各方法注释）。"""

    status: Optional[str] = None
    """step_end / plan_end / node_end / pipeline_end 事件填写最终状态，其余为 None。
    合法值：'success' / 'failed' / 'skipped' / 'running'（VARCHAR，不强制 Literal）。
    """

    duration_ms: Optional[float] = None
    """step_end / plan_end 事件填写耗时（ms），其余为 None。"""

    agent_run_id: Optional[str] = None
    """agent 级别 run_id（TemplateAgentState.run_id，格式 "run_<12hex>"）。
    仅 AgentTemplate 层的 TraceHook 填写；PipelineTraceHook 在 node_end 时可选填写。
    独立调试时（无 pipeline），此值与 run_id 相同。
    """

    def to_dict(self) -> dict[str, Any]:
        """序列化为可打印/可存储的 dict（对应 agent_trace_events 表字段）。"""
        return {
            "run_id": self.run_id,
            "agent_run_id": self.agent_run_id,
            "stage": self.stage,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "step_id": self.step_id,
            "payload": self.payload,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }


# ─────────────────────────────────────────────
# TraceBackend — 抽象后端
# ─────────────────────────────────────────────

class TraceBackend(ABC):
    """Trace 写入后端抽象类。

    实现此类可接入任意存储（Postgres、文件、Langfuse 等），
    替换 NullBackend 时 template 核心代码零改动。
    """

    @abstractmethod
    def write(self, event: TraceEvent) -> None:
        """将 trace 事件持久化。实现类需保证此方法不抛异常（内部处理错误）。"""


class NullBackend(TraceBackend):
    """默认 Trace 后端：只打印，不写入任何存储，不报错。

    v0.1 使用此后端进行「空跑」，便于通过控制台观察运行轨迹。

    替换为真实后端示例（在 template_agent.py 或 search_agent/agent.py 中）：
        from backend.src.db_access.trace.postgres_backend import PostgresBackend
        hook = TraceHook(backend=PostgresBackend(session=db_session))
    """

    def write(self, event: TraceEvent) -> None:
        print(f"[TRACE] {event.event_type} | stage={event.stage} | run={event.run_id} | "
              f"agent_run={event.agent_run_id} | step={event.step_id} | "
              f"status={event.status} | duration_ms={event.duration_ms} | "
              f"payload={event.payload}")


# ─────────────────────────────────────────────
# TraceHook — plan_runner 调用入口
# ─────────────────────────────────────────────

class TraceHook:
    """plan_runner 直接调用的 trace 接口，封装事件构造和后端写入。

    四个固定调用点（plan_runner.run() 中）：
      1. on_plan_start(plan)            — plan 开始时
      2. on_step_start(step)            — 每个 step 开始时
      3. on_step_end(step, result, start_time_ms) — 每个 step 结束时（自动计算 duration_ms）
      4. on_plan_end(run_result)        — plan 结束时

    安全保证：_write() 用 try/except 包裹，trace 失败绝不影响主流程。
    """

    def __init__(
        self,
        run_id: str,
        stage: str,
        backend: Optional[TraceBackend] = None,
        enabled: bool = True,
    ):
        """
        Args:
            run_id: pipeline 级别 run_id（独立调试时与 agent_run_id 相同）。
                    由 PlanRunner.run() 在生成 TemplateAgentState.run_id 后同步更新。
            stage: 产生事件的逻辑阶段名，通常为 AgentTemplateConfig.agent_name。
                   对应 TraceEvent.stage 和 DB 中的 stage 列。
                   （注：v0.1 此参数名为 agent_name，Trace MVP 起统一改为 stage。）
            backend: TraceBackend 实例，默认 NullBackend（只 print，不写 DB）。
                     接入 Postgres：hook.backend = PostgresBackend()
            enabled: False 时所有方法立即返回（disable trace 的快速路径）。
        """
        self.run_id = run_id
        self.stage = stage
        self.agent_run_id: Optional[str] = None
        """agent 级别 run_id，由 PlanRunner.run() 在创建 TemplateAgentState 后写入。
        独立调试时（无 pipeline），此值与 run_id 相同。
        """
        self.backend: TraceBackend = backend if backend is not None else NullBackend()
        self.enabled = enabled

        # 内部计时：记录每个 step 的 start_time_ms，供 on_step_end 计算 duration
        self._step_start_times: dict[str, float] = {}
        self._plan_start_time_ms: float = 0.0

    def on_plan_start(self, plan: Plan) -> None:
        """plan 开始时调用。payload 包含 plan 元数据。"""
        if not self.enabled:
            return
        self._plan_start_time_ms = _now_ms()
        event = TraceEvent(
            run_id=self.run_id,
            agent_run_id=self.agent_run_id,
            stage=self.stage,
            event_type="plan_start",
            status="running",
            payload={
                "plan_id": plan.plan_id,
                "plan_version": plan.version,
                "total_steps": len(plan.steps),
                "step_ids": [s.step_id for s in plan.steps],
            },
        )
        self._write(event)

    def on_step_start(self, step: PlanStep) -> None:
        """每个 step 开始时调用。记录 step 元数据，并存入开始时间供 duration 计算。"""
        if not self.enabled:
            return
        self._step_start_times[step.step_id] = _now_ms()
        event = TraceEvent(
            run_id=self.run_id,
            agent_run_id=self.agent_run_id,
            stage=self.stage,
            event_type="step_start",
            step_id=step.step_id,
            status="running",
            payload={
                "step_name": step.name,
                "tools_required": step.tools_required,
                "max_retries": step.max_retries,
            },
        )
        self._write(event)

    def on_step_end(self, step: PlanStep, result: StepResult, retry_count: int = 0) -> None:
        """每个 step 结束时调用。自动计算 duration_ms。

        Args:
            step: 刚执行完的 PlanStep。
            result: StepResult（status 可能是 success/failed/skipped）。
            retry_count: 该 step 的重试次数。
        """
        if not self.enabled:
            return
        start_ms = self._step_start_times.pop(step.step_id, _now_ms())
        duration_ms = _now_ms() - start_ms
        event = TraceEvent(
            run_id=self.run_id,
            agent_run_id=self.agent_run_id,
            stage=self.stage,
            event_type="step_end",
            step_id=step.step_id,
            status=result.status,
            duration_ms=round(duration_ms, 2),
            payload={
                "step_name": step.name,
                "retry_count": retry_count,
                "error_message": result.error_message,
                "output_keys": list(result.output.keys()),
                "summary": result.summary.model_dump(),
            },
        )
        self._write(event)

    def on_plan_end(self, run_result: AgentRunResult) -> None:
        """plan 结束时调用。记录整体运行结果摘要。"""
        if not self.enabled:
            return
        duration_ms = _now_ms() - self._plan_start_time_ms
        event = TraceEvent(
            run_id=self.run_id,
            agent_run_id=self.agent_run_id,
            stage=self.stage,
            event_type="plan_end",
            status=run_result.status,
            duration_ms=round(duration_ms, 2),
            payload={
                "total_steps": len(run_result.step_results),
                "successful_steps": sum(1 for r in run_result.step_results if r.status == "success"),
                "failed_steps": sum(1 for r in run_result.step_results if r.status == "failed"),
                "final_output_keys": list(run_result.final_output.keys()),
            },
        )
        self._write(event)

    def _write(self, event: TraceEvent) -> None:
        """将事件写入后端。try/except 保证 trace 失败绝不影响主流程。"""
        try:
            self.backend.write(event)
        except Exception as e:
            # TraceError 只在此处打印，不向上传播
            print(f"[TraceError] 写入 trace 失败（event_type={event.event_type}）：{e}")


def _now_ms() -> float:
    """返回当前时间的毫秒时间戳（monotonic clock，用于 duration 计算）。"""
    return time.monotonic() * 1000
