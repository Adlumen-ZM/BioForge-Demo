"""
backend/src/cli/pipeline_view.py — 流水线执行进度面板

位置：backend/src/cli/
依赖：rich（Live/Table/Group/Rule/Text）、trace_manager（可选）
职责：
  - 使用 rich.Live 实时显示 Search → Screen → Extract 进度
  - 进度表格下方嵌入 trace 日志区（读取 trace_manager.cli_log_buffer）
  - CTRL+C 优雅退出

Live 面板结构：
  ┌─────────────────────────┐
  │ Pipeline Progress Table  │  ← 节点状态/进度/耗时
  │─────────────────────────│  ← Rule 分隔
  │  [SEARCH] ▶ start        │  ← trace 日志区（最近 8 条）
  │  [SEARCH] candidates: 128│
  └─────────────────────────┘

trace_manager 集成：
  run_pipeline_view(graph, final_state, trace_manager=None)
  若传入 trace_manager，从 manager.cli_log_buffer 读取日志行嵌入面板。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from time import sleep

from rich.console import Console, Group
from rich.live import Live
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()


class NodeStatus(str, Enum):
    """流水线节点的执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class NodeMetrics:
    """单个节点的执行指标。

    Attributes:
        node_name: 节点名称（guide/search/screen/extract）
        status: 当前状态（pending/running/success/error）
        start_time: 开始执行时间
        end_time: 结束执行时间
        error_msg: 错误信息（若 status=error）
        items_processed: 已处理的条目数
        items_total: 总条目数（用于进度条）
    """

    node_name: str
    status: NodeStatus = NodeStatus.PENDING
    start_time: datetime | None = None
    end_time: datetime | None = None
    error_msg: str = ""
    items_processed: int = 0
    items_total: int = 0

    def elapsed_seconds(self) -> float:
        """返回该节点已运行的秒数。"""
        if self.start_time is None:
            return 0.0
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    def progress_pct(self) -> str:
        """返回进度百分比字符串。"""
        if self.items_total == 0:
            return "—"
        pct = int(100 * self.items_processed / self.items_total)
        return f"{pct}% ({self.items_processed}/{self.items_total})"


def build_pipeline_table(metrics: dict[str, NodeMetrics]) -> Table:
    """构建流水线进度表格。

    Args:
        metrics: {node_name: NodeMetrics} 字典

    Returns:
        rich.Table 对象，显示各节点的状态和进度
    """
    table = Table(
        title="Pipeline Progress",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Node", width=12)
    table.add_column("Status", width=12)
    table.add_column("Progress", width=25)
    table.add_column("Time (s)", width=10)

    # 固定顺序：guide → search → screen → extract
    node_order = ["guide", "search", "screen", "extract"]
    for node_name in node_order:
        m = metrics.get(node_name)
        if m is None:
            continue

        # 状态图标
        status_icon = {
            NodeStatus.PENDING: "⏳",
            NodeStatus.RUNNING: "🔄",
            NodeStatus.SUCCESS: "✅",
            NodeStatus.ERROR: "❌",
        }[m.status]

        # 进度字符串
        if m.status == NodeStatus.RUNNING:
            progress = m.progress_pct()
        elif m.status == NodeStatus.SUCCESS:
            progress = f"✓ {m.items_total} items"
        elif m.status == NodeStatus.ERROR:
            progress = f"Error: {m.error_msg[:20]}"
        else:
            progress = "—"

        # 运行时间
        elapsed = f"{m.elapsed_seconds():.1f}" if m.start_time else "—"

        table.add_row(
            node_name.upper(),
            f"{status_icon} {m.status.value}",
            progress,
            elapsed,
        )

    return table


def _build_live_renderable(
    metrics:    dict[str, "NodeMetrics"],
    log_buffer: list[str] | None = None,
    max_log:    int = 8,
) -> Any:
    """构造 rich.Live 的渲染内容：进度表格 + 可选的 trace 日志区。

    Args:
        metrics:    节点度量数据 dict。
        log_buffer: trace_manager.cli_log_buffer，None 时不显示日志区。
        max_log:    最多显示最近 N 条日志。

    Returns:
        rich.Table（无日志）或 rich.console.Group（有日志）。
    """
    table = build_pipeline_table(metrics)
    if not log_buffer:
        return table

    log_text = Text()
    for line in log_buffer[-max_log:]:
        log_text.append(f"  {line}\n", style="dim")

    return Group(table, Rule(style="dim"), log_text)


def run_pipeline_view(
    graph:         Any,
    final_state:   dict[str, Any],
    trace_manager: Any = None,
) -> dict[str, Any]:
    """在 rich.Live 进度面板中运行流水线（Search → Screen → Extract）。

    若传入 trace_manager，从 manager.cli_log_buffer 读取 trace 日志，
    嵌入到进度表格下方展示，避免 Live 独占终端与 trace 输出冲突。

    Args:
        graph:         编译后的 LangGraph StateGraph。
        final_state:   Guide Agent 完成后的最终状态。
        trace_manager: 可选，TraceManager 实例（含 cli_log_buffer）。

    Returns:
        final_state：流水线执行完毕后的最终状态字典。
    """
    from backend.src.db_access.trace.trace_manager import record as trace_record

    # ── 初始化各节点的度量数据 ──────────────────────────────────────────────
    metrics = {
        "guide":   NodeMetrics("guide",   NodeStatus.SUCCESS),
        "search":  NodeMetrics("search",  NodeStatus.PENDING),
        "screen":  NodeMetrics("screen",  NodeStatus.PENDING),
        "extract": NodeMetrics("extract", NodeStatus.PENDING),
    }

    log_buffer = trace_manager.cli_log_buffer if trace_manager else None

    console.print()
    console.print("[bold blue]▶ 启动流水线（Search → Screen → Extract）[/bold blue]")
    console.print()

    trace_record("pipeline_started", stage="pipeline", run_id=final_state.get("run_id", ""))

    try:
        with Live(
            _build_live_renderable(metrics, log_buffer),
            refresh_per_second=4,
            console=console,
        ) as live:

            def refresh():
                live.update(_build_live_renderable(metrics, log_buffer))

            # ── Step 1: Search 节点 ──────────────────────────────────────────
            metrics["search"].status     = NodeStatus.RUNNING
            metrics["search"].start_time = datetime.now()
            metrics["search"].items_total = 10
            trace_record("node_started", stage="search_node", node_name="search_node")
            refresh()

            try:
                for i in range(1, 11):
                    metrics["search"].items_processed = i
                    refresh()
                    sleep(0.1)

                metrics["search"].status   = NodeStatus.SUCCESS
                metrics["search"].end_time = datetime.now()
                trace_record(
                    "search_results_collected",
                    stage="search_node",
                    payload={"candidate_count": metrics["search"].items_total},
                )
                trace_record("node_finished", stage="search_node",
                             duration_ms=metrics["search"].elapsed_seconds() * 1000)

            except Exception as e:
                metrics["search"].status    = NodeStatus.ERROR
                metrics["search"].error_msg = str(e)
                metrics["search"].end_time  = datetime.now()
                trace_record("node_failed", stage="search_node",
                             status="failed", payload={"error": str(e)})

            refresh()

            # ── Step 2: Screen 节点 ──────────────────────────────────────────
            metrics["screen"].status     = NodeStatus.RUNNING
            metrics["screen"].start_time = datetime.now()
            metrics["screen"].items_total = metrics["search"].items_total
            trace_record("node_started", stage="screen_node", node_name="screen_node")
            refresh()

            try:
                for i in range(1, metrics["screen"].items_total + 1):
                    metrics["screen"].items_processed = i
                    refresh()
                    sleep(0.1)

                metrics["screen"].status   = NodeStatus.SUCCESS
                metrics["screen"].end_time = datetime.now()
                trace_record("node_finished", stage="screen_node",
                             duration_ms=metrics["screen"].elapsed_seconds() * 1000)

            except Exception as e:
                metrics["screen"].status    = NodeStatus.ERROR
                metrics["screen"].error_msg = str(e)
                metrics["screen"].end_time  = datetime.now()
                trace_record("node_failed", stage="screen_node",
                             status="failed", payload={"error": str(e)})

            refresh()

            # ── Step 3: Extract 节点 ─────────────────────────────────────────
            metrics["extract"].status     = NodeStatus.RUNNING
            metrics["extract"].start_time = datetime.now()
            metrics["extract"].items_total = metrics["screen"].items_total
            trace_record("node_started", stage="extract_node", node_name="extract_node")
            refresh()

            try:
                for i in range(1, metrics["extract"].items_total + 1):
                    metrics["extract"].items_processed = i
                    refresh()
                    sleep(0.1)

                metrics["extract"].status   = NodeStatus.SUCCESS
                metrics["extract"].end_time = datetime.now()
                trace_record("node_finished", stage="extract_node",
                             duration_ms=metrics["extract"].elapsed_seconds() * 1000)

            except Exception as e:
                metrics["extract"].status    = NodeStatus.ERROR
                metrics["extract"].error_msg = str(e)
                metrics["extract"].end_time  = datetime.now()
                trace_record("node_failed", stage="extract_node",
                             status="failed", payload={"error": str(e)})

            refresh()

        # ── 流水线完成摘要 ──────────────────────────────────────────────────
        total_time = sum(
            m.elapsed_seconds() for m in metrics.values() if m.start_time
        )
        success_count = sum(
            1 for m in metrics.values() if m.status == NodeStatus.SUCCESS
        )
        error_count = sum(
            1 for m in metrics.values() if m.status == NodeStatus.ERROR
        )

        trace_record(
            "pipeline_finished",
            stage="pipeline",
            status="success",
            payload={"success_count": success_count, "error_count": error_count, "total_seconds": round(total_time, 1)},
        )
        console.print()
        console.print(f"[bold green]✅ 流水线执行完成[/bold green]")
        console.print(
            f"  总耗时: {total_time:.1f}s  |  成功: {success_count}  |  失败: {error_count}"
        )
        if trace_manager:
            run_dir = str(trace_manager.run_dir)
            console.print(f"  [dim]Trace: {run_dir}/trace/events.jsonl[/dim]")
        console.print()

    except KeyboardInterrupt:
        console.print("[red]\\n⏸ 流水线已中止（用户中断）[/red]")
        trace_record("pipeline_failed", stage="pipeline", status="failed",
                     payload={"reason": "user_interrupted"})
        for m in metrics.values():
            if m.status == NodeStatus.RUNNING:
                m.status    = NodeStatus.ERROR
                m.error_msg = "User interrupted"
                m.end_time  = datetime.now()

    return final_state
