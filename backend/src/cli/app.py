"""
backend/src/cli/app.py — CLI 主程序

职责：编排整个 CLI 的 10 步流程：
  1. system_check — 环境检测
  2. print_banner — 欢迎 banner + 系统状态
  3. guide_conversation（中断，支持 resume）
  4. pipeline_view — 流水线执行进度
  5. REPL — 交互式查询/编辑结果

当前版本：骨架，完整实现见 Step 08 文档。
"""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from backend.src.cli.system_check import run_system_check
from backend.src.cli.session import CLISession

console = Console()


def print_banner(results: list[dict]) -> None:
    """打印欢迎 banner 和系统检测状态。

    Args:
        results: 来自 run_system_check() 的检测结果列表。
    """
    console.print()
    console.print(
        Panel(
            "[bold cyan]BioForge Guide Agent[/bold cyan]\n"
            "文献数据挖掘任务引导员\n"
            "[dim]利用 LangGraph interrupt 进行三步式用户对话[/dim]",
            border_style="blue",
        )
    )
    console.print()

    # 系统状态表
    table = Table(title="System Status", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan", width=15)
    table.add_column("Status", width=10)
    table.add_column("Detail")

    for r in results:
        status_style = {
            "ok": "green",
            "warn": "yellow",
            "error": "red",
        }.get(r["status"], "white")

        status_icon = {
            "ok": "✅",
            "warn": "⚠️",
            "error": "❌",
        }.get(r["status"], "❓")

        table.add_row(
            r["name"],
            f"[{status_style}]{status_icon}[/{status_style}]",
            r.get("detail", ""),
        )

    console.print(table)
    console.print()


def main():
    """CLI 主函数 — 10 步编排流程。"""

    # ── 步骤 1：系统检测 ──────────────────────────────────────────────────────
    console.print("[bold]正在检测系统环境...[/bold]")
    results = run_system_check()

    # ── 步骤 2：打印 banner ───────────────────────────────────────────────────
    print_banner(results)

    # ── 步骤 3：初始化 CLI 会话 ──────────────────────────────────────────────
    session = CLISession()
    run_id = session.new_run_id()
    console.print(f"[dim]Session: {run_id}[/dim]")
    console.print()

    # ── 步骤 4-10：三步引导对话 + 流水线执行 ────────────────────────────────
    # 当前 MVP：仅输出占位信息，实际实现见 conversation.py + pipeline_view.py
    console.print("[bold blue]Step 1: Task Description[/bold blue]")
    console.print("[dim]请描述你要挖掘的任务...[/dim]")
    console.print()

    console.print("[bold blue]Step 2: Database Schema[/bold blue]")
    console.print("[dim]根据任务推荐的数据库字段...[/dim]")
    console.print()

    console.print("[bold blue]Step 3: Inclusion/Exclusion Criteria[/bold blue]")
    console.print("[dim]基于任务的过滤规则...[/dim]")
    console.print()

    # ── 完成 ──────────────────────────────────────────────────────────────────
    session.add_history({
        "run_id":  run_id,
        "status":  "completed",
        "summary": "Guide conversation completed",
    })

    console.print("[bold green]✅ CLI 流程完成[/bold green]")
    print_summary = session.summary()
    console.print(f"[dim]Created at: {print_summary['created_at']}[/dim]")
    console.print()


if __name__ == "__main__":
    main()
