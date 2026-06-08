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
    """CLI 主函数 — 10 步编排流程。

    步骤：
      1. 系统检测（LLM/DB/Checkpoint）
      2. 打印 banner 和状态
      3. 初始化 CLI 会话（生成 run_id/thread_id）
      4-6. Guide Agent 三步中断对话（task/schema/criteria）
      7-9. 流水线执行（search/screen/extract 实时进度）
      10. 交互式 REPL（查询结果、编辑标签）
    """

    # ── 步骤 1：系统检测 ──────────────────────────────────────────────────────
    console.print("[bold]正在检测系统环境...[/bold]")
    results = run_system_check()

    # ── 步骤 2：打印 banner ───────────────────────────────────────────────────
    print_banner(results)

    # ── 步骤 3：初始化 CLI 会话 ──────────────────────────────────────────────
    session = CLISession()
    run_id = session.new_run_id()
    console.print(f"[dim]Session: {run_id}  |  Thread: {session.thread_id}[/dim]")
    console.print()

    # ── 步骤 4-6：Guide Agent 三步中断对话 ────────────────────────────────────
    # 这里简化处理：直接构造虚拟的 input_data 和 final_state
    # 完整实现：调用 graph.invoke() 并处理真实的 interrupt 事件

    from backend.src.cli.conversation import run_guide_conversation
    from backend.src.cli.pipeline_view import run_pipeline_view

    # 构造初始输入（模拟）
    input_data = {
        "run_id": run_id,
        "thread_id": session.thread_id,
        "task_description": "",
    }

    try:
        # 调用 Guide Agent（当前版本：模拟）
        # 实际版本：final_state, was_confirmed = run_guide_conversation(
        #     graph=graph,  # 需要从 graph module 获取
        #     input_data=input_data,
        #     session=session,
        # )

        # 模拟 Guide Agent 输出
        final_state = {
            "run_id": run_id,
            "thread_id": session.thread_id,
            "task_description": "挖掘 HAp 与肽段相互作用的文献",
            "db_schema": {
                "source_title": {"type": "str", "description": "论文标题"},
                "abstract": {"type": "str", "description": "摘要"},
                "doi": {"type": "str", "description": "DOI 标识"},
                "pub_date": {"type": "date", "description": "发表日期"},
                "hap_type": {"type": "str", "description": "HAp 类型"},
                "peptide_name": {"type": "str", "description": "肽段名称"},
                "interaction_type": {"type": "str", "description": "相互作用类型"},
                "binding_affinity": {"type": "float", "description": "结合亲和力"},
            },
            "inclusion_criteria": {
                "有 HAp": "论文涉及羟基磷灰石（HAp）",
                "有肽段": "论文涉及肽段分子",
                "有相互作用数据": "包含结合能或吸附数据",
            },
            "exclusion_criteria": {
                "综述文献": "仅限原始研究",
                "非英文": "仅限英文文献",
            },
            "user_confirmed": True,
        }
        was_confirmed = True

        # 如果用户确认了所有三步，则继续执行流水线
        if was_confirmed:
            # ── 步骤 7-9：流水线执行 ─────────────────────────────────────────
            # 模拟流水线执行（当前版本：直接调用 run_pipeline_view）
            final_state = run_pipeline_view(
                graph=None,  # 实际版本需要传入真实的 graph
                final_state=final_state,
            )

            # ── 步骤 10：交互式 REPL（简化版） ─────────────────────────────────
            console.print("[bold cyan]REPL 模式（输入 'help' 查看命令）[/bold cyan]")
            console.print("[dim]当前功能：display/export（开发中）[/dim]")
            console.print()

            # 记录历史
            session.add_history({
                "run_id": run_id,
                "status": "success",
                "summary": f"完成挖掘，共 {len(final_state.get('results', []))} 条结果",
            })

    except KeyboardInterrupt:
        console.print("[red]\\n用户中断，保存状态[/red]")
        session.add_history({
            "run_id": run_id,
            "status": "interrupted",
            "summary": "用户中断",
        })

    except Exception as e:
        console.print(f"[red]错误：{e}[/red]")
        session.add_history({
            "run_id": run_id,
            "status": "error",
            "summary": str(e),
        })

    # ── 完成 ──────────────────────────────────────────────────────────────────
    console.print()
    console.print("[bold green]✅ CLI 流程完成[/bold green]")
    print_summary = session.summary()
    console.print(f"[dim]Created: {print_summary['created_at']}[/dim]")
    console.print()


if __name__ == "__main__":
    main()
