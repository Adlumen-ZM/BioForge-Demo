"""
backend/src/cli/pipeline_view.py — 流水线执行进度面板

职责：使用 rich.Live 实时显示 Search → Screen → Extract 三阶段的执行进度：
  - 实时更新每个 node 的状态（running / success / error / timeout）
  - 显示当前执行时间、已处理条目数等指标
  - 处理 CTRL+C 优雅退出（取消当前 step）

当前版本：骨架 + 占位实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.table import Table

console = Console()


class NodeStatus(str, Enum):
    """流水线节点的执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class NodeMetrics:
    """单个节点的执行指标。"""

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


def build_pipeline_table(metrics: dict[str, NodeMetrics]) -> Table:
    """构建流水线进度表格。

    Args:
        metrics: {node_name: NodeMetrics} 字典

    Returns:
        rich.Table 对象
    """
    table = Table(title="Pipeline Progress", show_header=True, header_style="bold cyan")
    table.add_column("Node", width=15)
    table.add_column("Status", width=12)
    table.add_column("Progress", width=20)
    table.add_column("Elapsed (s)", width=12)

    # 固定顺序：guide → search → screen → extract
    node_order = ["guide", "search", "screen", "extract"]
    for node_name in node_order:
        m = metrics.get(node_name)
        if m is None:
            continue

        status_icon = {
            NodeStatus.PENDING: "⏳",
            NodeStatus.RUNNING: "🔄",
            NodeStatus.SUCCESS: "✅",
            NodeStatus.ERROR: "❌",
            NodeStatus.TIMEOUT: "⏱️",
        }[m.status]

        if m.status == NodeStatus.RUNNING:
            progress = f"{m.items_processed}/{m.items_total}"
        elif m.status == NodeStatus.SUCCESS:
            progress = f"✓ {m.items_total} items"
        elif m.status == NodeStatus.ERROR:
            progress = f"Error: {m.error_msg[:20]}"
        else:
            progress = "—"

        elapsed = f"{m.elapsed_seconds():.1f}" if m.start_time else "—"

        table.add_row(
            node_name.upper(),
            f"{status_icon} {m.status.value}",
            progress,
            elapsed,
        )

    return table


def run_pipeline_view(graph: Any, final_state: dict[str, Any]) -> dict[str, Any]:
    """在进度面板中运行流水线（search → screen → extract）。

    Args:
        graph: 编译后的 LangGraph StateGraph
        final_state: Guide Agent 完成后的最终状态

    Returns:
        final_state：流水线执行完毕后的最终状态字典
    """
    # 初始化各节点的度量数据
    metrics = {
        "guide": NodeMetrics("guide", NodeStatus.SUCCESS),
        "search": NodeMetrics("search", NodeStatus.PENDING),
        "screen": NodeMetrics("screen", NodeStatus.PENDING),
        "extract": NodeMetrics("extract", NodeStatus.PENDING),
    }

    config = {"configurable": {"thread_id": final_state.get("thread_id", "")}}

    try:
        # ── 运行流水线（简化版：直接调用 graph.invoke）
        # 实际版本会处理流式事件或检查点恢复
        console.print("[bold blue]启动流水线... (search → screen → extract)[/bold blue]")

        # 标记 search 节点开始
        metrics["search"].status = NodeStatus.RUNNING
        metrics["search"].start_time = datetime.now()

        # 调用图（当前版本：简化，直接返回状态）
        final_state = graph.invoke(final_state, config=config)

        # 标记 search 完成
        metrics["search"].status = NodeStatus.SUCCESS
        metrics["search"].end_time = datetime.now()
        metrics["search"].items_total = 10  # 占位

        # screen 和 extract 在模式模式下简化处理
        for node_name in ["screen", "extract"]:
            metrics[node_name].status = NodeStatus.SUCCESS
            metrics[node_name].start_time = datetime.now()
            metrics[node_name].end_time = datetime.now()
            metrics[node_name].items_total = 10

        # 输出最终进度
        table = build_pipeline_table(metrics)
        console.print(table)

    except KeyboardInterrupt:
        console.print("[red]\\n流水线已中止[/red]")
        for m in metrics.values():
            if m.status == NodeStatus.RUNNING:
                m.status = NodeStatus.TIMEOUT

    return final_state
