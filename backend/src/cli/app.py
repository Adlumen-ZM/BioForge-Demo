"""
backend/src/cli/app.py — CLI 主程序

位置：backend/src/cli/
依赖：rich（Panel/Rule/Text/Group）、system_check、session、conversation、pipeline_view
职责：编排整个 CLI 流程：
  1. system_check — 环境检测
  2. print_banner — 单一 Panel（标题 + Rule 分隔 + 系统状态），符合 §10 规范
  3. 初始化 CLISession
  4-6. Guide Agent 三步中断对话（task/schema/criteria）
  7-9. pipeline_view — 流水线实时进度
  10. REPL — 交互式查询（规划中）

Banner 设计（§10）：
  ╭─────────────────────────────────────────────────────────╮
  │                                                         │
  │   BioForge                                              │
  │   Agentic Framework for Biomedical Literature Mining    │
  │   v0.1  Demo Mode                                       │
  │                                                         │
  ├─────────────────────────────────────────────────────────┤
  │  System Status                                          │
  │   LLM         ✅  MiniMax-M2.7  (MINIMAX_API_KEY)      │
  │   ...                                                   │
  ╰─────────────────────────────────────────────────────────╯
    输入 /help 查看命令  ·  /demo 一键体验  ·  /quit 退出
"""

from __future__ import annotations

import os
import shlex
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from backend.src.cli.system_check import run_system_check
from backend.src.cli.session import CLISession

console = Console()


def _normalize_command_name(command_name: str) -> str:
    """Normalize REPL command names while keeping displayed commands slash-prefixed."""
    normalized = command_name.strip().lstrip("/").lower()
    if normalized == "?":
        return "?"
    for dash in ("–", "—", "−"):
        normalized = normalized.replace(dash, "-")

    chars: list[str] = []
    previous_was_separator = False
    for char in normalized:
        if char.isalnum():
            chars.append(char)
            previous_was_separator = False
        elif not previous_was_separator:
            chars.append("-")
            previous_was_separator = True

    return "".join(chars).strip("-")


def _get_command_name(command_line: str) -> str:
    """Return the normalized first token of a REPL command line."""
    try:
        parts = shlex.split(command_line)
    except ValueError:
        parts = command_line.split(maxsplit=1)
    if not parts:
        return ""
    return _normalize_command_name(parts[0])


_LOGO = r"""
 ██████╗ ██╗ ██████╗ ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
 ██╔══██╗██║██╔═══██╗██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
 ██████╔╝██║██║   ██║█████╗  ██║   ██║██████╔╝██║  ███╗█████╗
 ██╔══██╗██║██║   ██║██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
 ██████╔╝██║╚██████╔╝██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
 ╚═════╝ ╚═╝ ╚═════╝ ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝"""

_HELIX = (
    "  ·  ·○·  ·  ·○·  ·  ·○·  ·  ·○·  ·  ·○·  ·  ·○·  ·  ·○·",
    "  ○·  ·  ·○·  ·  ·○·  ·  ·○·  ·  ·○·  ·  ·○·  ·  ·○·  ·  ",
)


def print_banner(results: list[dict]) -> None:
    """打印大型生物风格 banner（Block ASCII logo + DNA 螺旋装饰 + 系统状态）。

    结构：
      - 大型 BioForge 块状 ASCII logo（蓝绿渐变）
      - DNA 双螺旋装饰线
      - 副标题 + 版本模式
      - Rule 分隔线
      - System Status 状态行（对齐，彩色）
      - 底部提示行

    Args:
        results: 来自 run_system_check() 的检测结果列表。
    """
    # Demo 模式下固定显示 "Demo"，不直接显示 env var 的 "mock" 字符串
    raw_mode = os.getenv("GRAPH_AGENT_MODE", "demo").lower()
    mode     = "Demo" if raw_mode in ("demo", "mock") else raw_mode.upper()

    # ── 大型 Logo ─────────────────────────────────────────────────────────────
    logo = Text()
    for line in _LOGO.split("\n"):
        logo.append(line + "\n", style="bold cyan")

    # ── DNA 双螺旋装饰（两行交错） ─────────────────────────────────────────────
    helix = Text()
    helix.append(_HELIX[0] + "\n", style="green")
    helix.append(_HELIX[1] + "\n", style="cyan")

    # ── 副标题 ────────────────────────────────────────────────────────────────
    subtitle = Text()
    subtitle.append(
        "  Agentic Framework for Biomedical Literature Mining  ",
        style="bold white",
    )
    subtitle.append(f"  v0.1 · {mode} Mode\n", style="dim cyan")

    # ── 分隔线 ────────────────────────────────────────────────────────────────
    divider = Rule(style="dim blue")

    # ── 系统状态 ──────────────────────────────────────────────────────────────
    status = Text()
    status.append("\n  System Status\n", style="bold")

    name_map  = {
        "LLM":        "LLM",
        "TraceDB":    "Trace DB",
        "BizDB":      "Business DB",
        "Mode":       "Mode",
        "Checkpoint": "Checkpoint",
    }
    icon_map  = {"ok": "✅", "warn": "⚠️ ", "error": "❌"}
    color_map = {"ok": "green", "warn": "yellow", "error": "red"}

    for r in results:
        icon   = icon_map.get(r["status"], "❓")
        color  = color_map.get(r["status"], "white")
        label  = name_map.get(r["name"], r["name"]).ljust(12)
        detail = r.get("detail", "")
        status.append(f"   {icon}  {label}  ", style="")
        status.append(detail + "\n", style=color)

    status.append("")

    # ── 组合为单一 Panel ──────────────────────────────────────────────────────
    content = Group(logo, helix, subtitle, divider, status)
    console.print()
    console.print(Panel(content, border_style="blue", padding=(0, 1)))
    console.print("  [dim]输入 /help 查看命令  ·  /demo 一键体验  ·  /export-db 导出数据  ·  /quit 退出[/dim]")
    console.print()


def _run_demo(session: Any, console: Any) -> None:
    """执行一次完整的 demo 流水线（Guide + 搜索/筛选/提取/写库）。

    调用方（main REPL）负责异常捕获和 trace_manager 关闭。
    """
    from backend.src.cli.conversation import run_guide_conversation
    from backend.src.cli.pipeline_view import run_pipeline_view
    from backend.src.graph.pipeline import build_graph
    from langgraph.checkpoint.memory import MemorySaver
    from backend.src.db_access.trace.trace_manager import TraceManager, set_manager

    run_id = session.new_run_id()
    console.print(f"[dim]Session: {run_id}  ·  Thread: {session.thread_id}[/dim]\n")

    trace_manager = TraceManager.create(run_id=run_id)
    set_manager(trace_manager)

    checkpointer = MemorySaver()
    mode  = os.getenv("GRAPH_AGENT_MODE", "demo")
    graph = build_graph(mode=mode, checkpointer=checkpointer)

    input_data  = {"run_id": run_id}
    final_state: dict = {}

    try:
        was_confirmed = run_guide_conversation(
            graph=graph,
            input_data=input_data,
            session=session,
        )

        if was_confirmed:
            final_state = run_pipeline_view(
                graph=graph,
                session=session,
                trace_manager=trace_manager,
            )
            session.add_history({
                "run_id":  run_id,
                "status":  final_state.get("status", "success"),
                "summary": f"流水线执行完成 status={final_state.get('status', '?')}",
            })

    finally:
        try:
            trace_manager.close()
        except Exception:
            pass


def _run_export_db(command: str, console: Any) -> None:
    """Export the business SQLite database to the standard 5-table CSV layout."""
    from backend.src.db_access.business import export_business_db_to_csv

    try:
        parts = shlex.split(command)
    except ValueError as exc:
        console.print(f"[red]Invalid command arguments: {exc}[/red]")
        return

    args = parts[1:]
    if len(args) > 2:
        console.print(
            "[yellow]Usage:[/yellow]\n"
            "  /export-db\n"
            "  /export-db /app/data/hap_v01.db\n"
            "  /export-db /app/data/hap_v01.db /app/output/my-export\n"
            "[dim]The leading slash is optional: export-db also works.[/dim]"
        )
        return

    db_path = args[0] if len(args) >= 1 else None
    output_dir = args[1] if len(args) >= 2 else None

    result = export_business_db_to_csv(db_path=db_path, output_dir=output_dir)
    status = result.get("status")

    if status == "error":
        console.print(Panel(
            f"[red]{result.get('error', 'Export failed')}[/red]\n\n"
            f"DB: {result.get('db_path', '-')}\n"
            f"Output: {result.get('output_dir', '-')}",
            title="DB Export Failed",
            border_style="red",
        ))
        return

    table = Table(title="Business DB Export")
    table.add_column("Table", style="cyan")
    table.add_column("Rows", justify="right")
    table.add_column("CSV")

    tables_exported = result.get("tables_exported", {})
    csv_files = result.get("csv_files", {})
    for table_name, row_count in tables_exported.items():
        table.add_row(table_name, str(row_count), csv_files.get(table_name, "-"))

    console.print(Panel(
        f"[green]Export status: {status}[/green]\n"
        f"DB: {result.get('db_path', '-')}\n"
        f"Output: {result.get('output_dir', '-')}",
        title="DB Export Complete",
        border_style="green" if status == "ok" else "yellow",
    ))
    console.print(table)

    missing_tables = result.get("missing_tables") or []
    errors = result.get("errors") or []
    if missing_tables:
        console.print(f"[yellow]Missing DB tables exported as empty CSVs: {', '.join(missing_tables)}[/yellow]")
    if errors:
        console.print("[yellow]Export warnings:[/yellow]")
        for err in errors:
            console.print(f"  - {err}")


def _print_help() -> None:
    """打印 REPL 帮助信息。"""
    console.print(
        "\n  [bold cyan]Available commands[/bold cyan]\n"
        "   [yellow]/demo[/yellow]                       Run the HAp peptide literature mining demo\n"
        "   [yellow]/export-db[/yellow] \\[db_path] \\[out]   Export a business DB to 5 CSV tables\n"
        "   [yellow]/help[/yellow]                       Show this help message\n"
        "   [yellow]/quit[/yellow]                       Exit\n"
        "\n  [bold cyan]Export examples[/bold cyan]\n"
        "   [yellow]/export-db[/yellow]\n"
        "   [yellow]/export-db[/yellow] /app/data/hap_v01.db\n"
        "   [yellow]/export-db[/yellow] /app/data/hap_v01.db /app/output/my-export\n"
        "\n  [dim]The leading slash is optional, so demo/export-db/help/quit also work.[/dim]\n"
    )


def main():
    """CLI 主函数：banner → REPL 命令循环。

    步骤：
      1. 环境检测
      2. 打印 banner（单 Panel，含系统状态）
      3. REPL 循环：等待用户输入 /demo / /help / /quit
      4. /demo 触发 Guide 四步对话 + 流水线执行
    """
    # ── 步骤 1：环境检测 ──────────────────────────────────────────────────────
    results = run_system_check()

    # ── 步骤 2：Banner ────────────────────────────────────────────────────────
    print_banner(results)

    session = CLISession()

    # ── 步骤 3：REPL 命令循环 ─────────────────────────────────────────────────
    console.print("  [dim]输入 [bold]/demo[/bold] 开始体验  ·  [bold]/export-db[/bold] 导出数据  ·  [bold]/help[/bold] 查看命令  ·  [bold]/quit[/bold] 退出[/dim]\n")

    while True:
        try:
            cmd = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]已退出[/yellow]")
            break

        if not cmd:
            continue

        command_name = _get_command_name(cmd)

        if command_name in ("quit", "exit", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break

        elif command_name in ("help", "?"):
            _print_help()

        elif command_name in ("export-db", "export"):
            _run_export_db(cmd, console)

        elif command_name == "demo":
            try:
                _run_demo(session, console)
            except KeyboardInterrupt:
                console.print("\n[yellow]已中断[/yellow]")
                session.add_history({"run_id": session.run_id or "?",
                                     "status": "interrupted", "summary": "用户中断"})
            except Exception as e:
                console.print(f"\n[red]错误：{e}[/red]")
                session.add_history({"run_id": session.run_id or "?",
                                     "status": "error", "summary": str(e)})
            # demo 结束后回到 REPL
            console.print("\n  [dim]输入 [bold]/demo[/bold] 再次运行  ·  [bold]/export-db[/bold] 导出数据  ·  [bold]/quit[/bold] 退出[/dim]\n")

        else:
            console.print(f"  [dim]未知命令：{cmd!r}。输入 /help 查看可用命令；命令前面的 / 可省略。[/dim]")


if __name__ == "__main__":
    main()
