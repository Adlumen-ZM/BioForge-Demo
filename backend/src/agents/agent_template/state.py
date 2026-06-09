"""
state.py — AgentTemplate 运行时内存状态

位置：依赖 schemas.py（Plan, StepResult）、config.py（AgentTemplateConfig）。
职责：定义 TemplateAgentState，plan_runner 在整个 run 期间持有此对象。

生命周期（Context = 缓存语义）：
  AgentTemplate.run() 开始时创建，run() 结束后由 GC 回收。
  批处理流水线下合理——有价值信息已持久化：
    - 业务结果 → graph 层写入 business DB（非本模块范围）
    - 运行轨迹 → TraceHook 通过 TraceBackend 持久化

跨层传递：
  层 A（step 内 ReAct messages）由 create_react_agent 自管，step 结束即丢，不存此处。
  层 B（step 间上下文）通过 step_results 传递：context_builder 读取已完成 step 的
       StepResult.summary + output 关键字段，不传完整 messages 历史。

扩展点（v0.1 未实现，标注位置）：
  - 跨 run 持久化状态（Memory）：未来在 run_id + agent_name 维度写入 PostgresStore，
    context_builder 通过 memory_refs 参数读取，plan_runner 在 run 结束后调 MemoryHook 写入。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .schemas import Plan, StepResult


@dataclass
class TemplateAgentState:
    """plan_runner 持有的运行时内存状态，贯穿整个 plan 执行周期。

    使用 dataclass 而非 Pydantic，因为字段会被频繁原地修改（追加 step_results 等），
    不需要序列化/校验语义。
    """

    # ── 标识 ──────────────────────────────────
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    """唯一运行 ID，格式 run_<12位hex>，写入 trace 事件和（未来）DB 记录。"""

    agent_name: str = ""
    """agent 名称，从 config.agent_name 复制，用于 trace 记录。"""

    # ── Plan ──────────────────────────────────
    plan: Optional[Plan] = None
    """当前执行的 Plan 对象，由 planner 加载后注入。
    replanner 可直接修改此对象（如调整 step 的 instruction），不回写 YAML。
    """

    # ── 执行历史 ──────────────────────────────
    step_results: list[StepResult] = field(default_factory=list)
    """已完成（success/failed/skipped）的 step 结果列表，按执行顺序追加。
    context_builder 从此读取摘要注入下一 step 的上下文。
    """

    current_step_index: int = 0
    """当前正在执行的 step 在 plan.steps 中的索引。"""

    retry_counts: dict[str, int] = field(default_factory=dict)
    """各 step_id 的实际重试次数，key=step_id, value=重试次数（不含首次执行）。"""

    # ── 时间 ──────────────────────────────────
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    """run 开始时间（UTC），用于 trace 的 plan_end 事件计算总耗时。"""

    def record_result(self, result: StepResult) -> None:
        """追加一个 step 结果并推进索引。"""
        self.step_results.append(result)
        self.current_step_index += 1

    def increment_retry(self, step_id: str) -> int:
        """增加指定 step 的重试计数，返回更新后的重试次数。"""
        self.retry_counts[step_id] = self.retry_counts.get(step_id, 0) + 1
        return self.retry_counts[step_id]

    def get_retry_count(self, step_id: str) -> int:
        """获取指定 step 的当前重试次数（0 表示尚未重试）。"""
        return self.retry_counts.get(step_id, 0)

    def completed_summaries(self) -> list[dict]:
        """返回所有已完成 step 的摘要信息，供 context_builder 注入下一 step。

        只返回 status=='success' 的 step，失败/跳过的不提供正向上下文。
        包含实际 output 数据，让后续 step（如 dedup_filter）能看到前序 step 的结果。
        """
        return [
            {
                "step_id": r.step_id,
                "summary": r.summary.model_dump(),
                "output_keys": list(r.output.keys()),
                "output": r.output,
            }
            for r in self.step_results
            if r.status == "success"
        ]
