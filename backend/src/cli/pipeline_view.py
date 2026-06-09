# -*- coding: utf-8 -*-
"""
pipeline_view.py — 流水线执行进度面板

位置：backend/src/cli/
依赖：rich（Live/Table/Group/Rule/Panel/Text）
职责：
  - 驱动真实的 graph.stream(Command(resume=0)) 执行（在 Guide Q4 确认后调用）
  - 用 rich.Live 实时显示 init_business_db → search → screen → extract → write_rag_csv_to_db → finalize 进度
  - 节点完成后通过 graph.get_state().next 判断下一个运行节点
  - 流水线结束后打印最终摘要 Panel（检索式、候选文献数、PDF 路径、DB 路径等）

Live 面板结构：
  ┌──────────────────────────────────────────┐
  │ Pipeline Progress                         │
  │  Node             Status    Progress  Time│
  │  GUIDE            ✅ done   —          —  │
  │  INIT_BUSINESS_DB 🔄 run    —        1.2s │
  │  SEARCH           ⏳ pend   —          —  │
  │  ...                                      │
  ├──────────────────────────────────────────┤
  │  [SEARCH] 找到 42 篇候选文献               │  ← trace 日志区
  └──────────────────────────────────────────┘
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()


# ── 状态与度量 ────────────────────────────────────────────────────────────────

class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    ERROR   = "error"


@dataclass
class NodeMetrics:
    node_name:        str
    status:           NodeStatus = NodeStatus.PENDING
    start_time:       datetime | None = None
    end_time:         datetime | None = None
    error_msg:        str = ""
    items_processed:  int = 0
    items_total:      int = 0
    detail:           str = ""  # 节点完成后的一行摘要

    def elapsed_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()


# ── 表格构建 ──────────────────────────────────────────────────────────────────

# 显示名称映射
_NODE_LABEL = {
    "guide":               "Guide",
    "init_business_db":    "DB Init",
    "search":              "Search",
    "screen":              "Screen",
    "extract":             "Extract",
    "write_rag_csv_to_db": "DB Write",
    "finalize":            "Finalize",
}

_STATUS_ICON = {
    NodeStatus.PENDING:  "⏳",
    NodeStatus.RUNNING:  "🔄",
    NodeStatus.SUCCESS:  "✅",
    NodeStatus.SKIPPED:  "⏭ ",
    NodeStatus.ERROR:    "❌",
}

_NODE_ORDER = ["guide", "init_business_db", "search", "screen", "extract", "write_rag_csv_to_db", "finalize"]


def _build_table(metrics: dict[str, NodeMetrics]) -> Table:
    table = Table(title="Pipeline Progress", show_header=True, header_style="bold cyan",
                  min_width=60)
    table.add_column("Node",     width=18)
    table.add_column("Status",   width=14)
    table.add_column("Detail",   width=30)
    table.add_column("Time (s)", width=8)

    for name in _NODE_ORDER:
        m = metrics.get(name)
        if m is None:
            continue

        icon   = _STATUS_ICON[m.status]
        label  = _NODE_LABEL.get(name, name.upper())
        detail = m.detail or ("—" if m.status == NodeStatus.PENDING else "")
        if m.status == NodeStatus.ERROR:
            detail = f"Error: {m.error_msg[:25]}"
        elapsed = f"{m.elapsed_seconds():.1f}" if m.start_time else "—"

        status_color = {
            NodeStatus.RUNNING: "cyan",
            NodeStatus.SUCCESS: "green",
            NodeStatus.ERROR:   "red",
            NodeStatus.SKIPPED: "dim",
        }.get(m.status, "white")

        table.add_row(
            label,
            f"{icon} [{status_color}]{m.status.value}[/{status_color}]",
            detail,
            elapsed,
        )

    return table


def _build_renderable(
    metrics:    dict[str, NodeMetrics],
    log_buffer: list[str] | None = None,
    max_log:    int = 6,
) -> Any:
    table = _build_table(metrics)
    if not log_buffer:
        return table
    log_text = Text()
    for line in log_buffer[-max_log:]:
        log_text.append(f"  {line}\n", style="dim")
    return Group(table, Rule(style="dim"), log_text)


def _apply_live_progress(metrics: dict[str, NodeMetrics], trace_manager: Any = None) -> None:
    """用 trace manager 的共享进度补充节点运行中的 detail。"""
    if trace_manager is None:
        return

    progress = getattr(trace_manager, "progress_state", {}) or {}
    screen_progress = progress.get("screen_download") or {}
    screen_metrics = metrics.get("screen")
    if screen_metrics is None or screen_metrics.status != NodeStatus.RUNNING:
        return

    done = int(screen_progress.get("done", 0))
    ok = int(screen_progress.get("ok", 0))
    failed = int(screen_progress.get("failed", 0))
    retry_attempt = int(screen_progress.get("retry_attempt", 0))
    current_pmid = screen_progress.get("current_pmid") or ""
    last_reason = screen_progress.get("last_failure_reason") or ""

    parts = [f"下载中 {done} 篇", f"成功 {ok}", f"失败 {failed}"]
    if retry_attempt > 0:
        parts.append(f"重试 {retry_attempt}")
    if current_pmid:
        parts.append(f"PMID {current_pmid}")
    elif last_reason:
        parts.append(last_reason[:18])
    screen_metrics.detail = "  ".join(parts)


# ── 节点完成后更新度量 ────────────────────────────────────────────────────────

def _enrich_after_node(metrics: dict[str, NodeMetrics], node_name: str, state: dict) -> None:
    """根据 state 为刚完成的节点填入可读摘要。"""
    m = metrics.get(node_name)
    if m is None:
        return
    if node_name == "init_business_db":
        db_path = state.get("biz_db_path") or "—"
        m.detail = f"DB: ...{db_path[-30:]}" if len(db_path) > 32 else f"DB: {db_path}"
    elif node_name == "search":
        cnt = len(state.get("candidate_paper_ids") or [])
        m.items_total = cnt
        m.items_processed = cnt
        m.detail = f"候选 {cnt} 篇"
    elif node_name == "screen":
        dl = state.get("download_results") or []
        ok_dl = [r for r in dl if r.get("download_status") in ("downloaded", "already_exists")]
        failed = len(dl) - len(ok_dl)
        m.detail = f"下载 {len(ok_dl)}/{len(dl)} 篇  失败 {failed}"
    elif node_name == "extract":
        files = state.get("rag_csv_files") or {}
        q = state.get("csv_quality_status") or "?"
        m.detail = f"CSV {len(files)} 表  质量: {q}"
    elif node_name == "write_rag_csv_to_db":
        wr = state.get("db_write_result") or {}
        m.detail = f"写库 {wr.get('status', '?')}"
    elif node_name == "finalize":
        m.detail = state.get("status") or "done"


# ── 最终摘要 Panel ────────────────────────────────────────────────────────────

def _print_summary(final_state: dict[str, Any]) -> None:
    """打印流水线结束后的可读摘要 Panel。"""
    status = final_state.get("status", "unknown")
    color  = "green" if status == "success" else "red" if "fail" in status or "error" in status else "yellow"

    text = Text()
    text.append(f"\n  状态：", style="bold")
    text.append(f"{status}\n\n", style=f"bold {color}")

    # 🔍 检索
    qs  = final_state.get("query_strings") or []
    cnt = len(final_state.get("candidate_paper_ids") or [])
    text.append("  🔍 检索\n", style="bold cyan")
    if qs:
        for q in qs[:3]:
            text.append(f"     · {q}\n", style="dim")
        if len(qs) > 3:
            text.append(f"     （+ {len(qs) - 3} 条检索式）\n", style="dim")
    text.append(f"     候选文献：{cnt} 篇\n", style="white")

    # 📄 筛选与下载
    text.append("\n  📄 筛选与下载\n", style="bold cyan")
    screened = len(final_state.get("screened_paper_ids") or [])
    dl_res   = final_state.get("download_results") or []
    ok_dl    = [r for r in dl_res if r.get("download_status") in ("downloaded", "already_exists")]
    pdf_path = final_state.get("pdf_path") or (ok_dl[0].get("pdf_path") if ok_dl else None)
    text.append(f"     筛选通过 {screened} 篇  |  成功下载 {len(ok_dl)}/{len(dl_res)} 篇\n", style="white")
    if pdf_path:
        display_pdf = pdf_path if len(pdf_path) <= 60 else f"...{pdf_path[-57:]}"
        text.append(f"     PDF：{display_pdf}\n", style="dim")

    # 🧬 提取
    rag_dir   = final_state.get("rag_csv_dir")
    rag_files = final_state.get("rag_csv_files") or {}
    quality   = final_state.get("csv_quality_status") or "—"
    text.append("\n  🧬 提取\n", style="bold cyan")
    text.append(f"     CSV 表：{len(rag_files)} 张  |  质量：{quality}\n", style="white")
    if rag_dir:
        display_dir = rag_dir if len(rag_dir) <= 60 else f"...{rag_dir[-57:]}"
        text.append(f"     路径：{display_dir}\n", style="dim")

    # 💾 数据库
    db_path = final_state.get("biz_db_path")
    wr      = final_state.get("db_write_result") or {}
    text.append("\n  💾 数据库\n", style="bold cyan")
    text.append(f"     写入状态：{wr.get('status', '—')}\n", style="white")
    if db_path:
        display_db = db_path if len(db_path) <= 60 else f"...{db_path[-57:]}"
        text.append(f"     路径：{display_db}\n", style="dim")

    # 📊 摘要文件
    sp = final_state.get("summary_path")
    tp = final_state.get("timeline_path")
    if sp or tp:
        text.append("\n  📊 摘要\n", style="bold cyan")
        if sp:
            text.append(f"     summary : {sp}\n", style="dim")
        if tp:
            text.append(f"     timeline: {tp}\n", style="dim")

    # 错误列表
    errors = final_state.get("errors") or []
    if errors:
        text.append("\n  ⚠️  错误\n", style="bold red")
        for e in errors[:5]:
            msg = e.get("message", str(e))
            text.append(f"     · [{e.get('agent', '?')}] {msg[:80]}\n", style="red")

    text.append("")
    console.print()
    console.print(
        Panel(
            text,
            title=f"[bold {color}]流水线完成摘要[/bold {color}]",
            border_style=color,
            padding=(0, 1),
        )
    )
    console.print()


# ── 主函数 ────────────────────────────────────────────────────────────────────

def run_pipeline_view(
    graph:         Any,
    session:       Any,
    trace_manager: Any = None,
) -> dict[str, Any]:
    """在 rich.Live 进度面板中驱动流水线执行（Guide Q4 确认后调用）。

    调用 graph.stream(Command(resume=0)) 触发 guide_node 的最终 resume，
    随后 init_business_db → search → screen → extract → write_rag_csv_to_db → finalize
    依次执行。每个节点完成后实时更新进度表格。

    Args:
        graph:         编译后的 LangGraph StateGraph（已带 checkpointer）。
        session:       CLISession 实例（提供 thread_id）。
        trace_manager: 可选，TraceManager 实例（含 cli_log_buffer）。

    Returns:
        流水线执行完毕后的最终状态字典。
    """
    from langgraph.types import Command
    from backend.src.db_access.trace.trace_manager import record as _trace

    config     = {"configurable": {"thread_id": session.thread_id}}
    log_buffer = trace_manager.cli_log_buffer if trace_manager else []

    # guide 已在 conversation.py 完成，显示为 SUCCESS
    metrics: dict[str, NodeMetrics] = {
        "guide": NodeMetrics("guide", status=NodeStatus.SUCCESS, detail="已完成"),
    }
    for name in _NODE_ORDER[1:]:
        metrics[name] = NodeMetrics(name)

    # 标记第一个 pipeline 节点为 RUNNING（init_business_db）
    first = "init_business_db"
    metrics[first].status     = NodeStatus.RUNNING
    metrics[first].start_time = datetime.now()

    console.print()
    console.print("[bold blue]▶ 启动流水线 init_business_db → search → screen → extract → DB write → finalize[/bold blue]")
    console.print()

    run_id = getattr(session, "run_id", "") or ""
    _trace("pipeline_started", stage="pipeline", run_id=run_id)

    final_state: dict[str, Any] = {}

    try:
        with Live(
            _build_renderable(metrics, log_buffer),
            refresh_per_second=4,
            console=console,
            transient=False,
        ) as live:

            def refresh():
                _apply_live_progress(metrics, trace_manager)
                live.update(_build_renderable(metrics, log_buffer))

            # 触发 guide 最终 resume → pipeline 开始执行
            for chunk in graph.stream(
                Command(resume=0), config=config, stream_mode="updates"
            ):
                for node_name, _node_output in chunk.items():
                    if node_name.startswith("__"):
                        continue

                    if node_name in metrics:
                        m = metrics[node_name]
                        # 若节点从未被标记为 RUNNING（条件边跳入），补记时间
                        if m.status == NodeStatus.PENDING:
                            m.start_time = datetime.now()
                        m.status   = NodeStatus.SUCCESS
                        m.end_time = datetime.now()

                        # 直接用节点输出 dict 填充摘要（避免 graph.get_state 时序问题）
                        _enrich_after_node(metrics, node_name, _node_output)
                        _trace(
                            "node_finished",
                            stage=f"{node_name}_node",
                            duration_ms=int(m.elapsed_seconds() * 1000),
                        )

                        # 根据 graph 状态标记下一个将运行的节点
                        snap = graph.get_state(config)
                        for nn in (snap.next or []):
                            if nn in metrics and metrics[nn].status == NodeStatus.PENDING:
                                metrics[nn].status     = NodeStatus.RUNNING
                                metrics[nn].start_time = datetime.now()

                refresh()

        final_state = dict(graph.get_state(config).values)

        # 被跳过的节点（条件短路）标记为 SKIPPED
        for name in _NODE_ORDER[1:]:
            if metrics[name].status == NodeStatus.PENDING:
                metrics[name].status = NodeStatus.SKIPPED

        _trace(
            "pipeline_finished",
            stage="pipeline",
            status=final_state.get("status", "unknown"),
            payload={"run_id": run_id},
        )

    except KeyboardInterrupt:
        console.print("[red]\n⏸ 流水线已中止（用户中断）[/red]")
        _trace("pipeline_failed", stage="pipeline", status="failed",
               payload={"reason": "user_interrupted"})
        for m in metrics.values():
            if m.status == NodeStatus.RUNNING:
                m.status    = NodeStatus.ERROR
                m.error_msg = "User interrupted"
                m.end_time  = datetime.now()
        final_state = dict(graph.get_state(config).values) if graph else {}

    except Exception as exc:
        console.print(f"[red]\n❌ 流水线异常：{exc}[/red]")
        _trace("pipeline_failed", stage="pipeline", status="failed",
               payload={"error": str(exc)})
        for m in metrics.values():
            if m.status == NodeStatus.RUNNING:
                m.status    = NodeStatus.ERROR
                m.error_msg = str(exc)
                m.end_time  = datetime.now()
        try:
            final_state = dict(graph.get_state(config).values)
        except Exception:
            pass

    _print_summary(final_state)

    if trace_manager:
        try:
            run_dir = str(trace_manager.run_dir)
            console.print(f"[dim]  Trace: {run_dir}/trace/events.jsonl[/dim]\n")
        except Exception:
            pass

    return final_state
