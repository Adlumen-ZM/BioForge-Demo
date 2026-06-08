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

from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from backend.src.cli.system_check import run_system_check
from backend.src.cli.session import CLISession

console = Console()


def print_banner(results: list[dict]) -> None:
    """打印欢迎 banner（单一 Panel，符合技术方案 §10 规范）。

    Panel 内部结构：
      - 上半部分：BioForge 标题 + 副标题 + 版本/模式
      - 中间：Rule 分隔线（模拟 ├─────┤ 效果）
      - 下半部分：System Status 各检测项（对齐，彩色）

    Args:
        results: 来自 run_system_check() 的检测结果列表。
    """
    mode = os.getenv("GRAPH_AGENT_MODE", "mock").upper()

    # ── 上半部分：标题区 ─────────────────────────────────────────────────────
    header = Text()
    header.append("\n  BioForge\n", style="bold cyan")
    header.append("  Agentic Framework for Biomedical Literature Mining\n")
    header.append(f"  v0.1  {mode} Mode\n", style="dim")

    # ── 中间：分隔线 ─────────────────────────────────────────────────────────
    divider = Rule(style="dim blue")

    # ── 下半部分：系统状态区 ─────────────────────────────────────────────────
    status = Text()
    status.append("\n  System Status\n", style="bold")

    # 名称对齐宽度
    name_map = {
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

    status.append("")  # 底部留一行空白

    # ── 组合为单一 Panel ──────────────────────────────────────────────────────
    content = Group(header, divider, status)
    console.print()
    console.print(Panel(content, border_style="blue", padding=(0, 1)))
    console.print("  [dim]输入 /help 查看命令  ·  /demo 一键体验  ·  /quit 退出[/dim]")
    console.print()


def main():
    """CLI 主函数。

    步骤：
      1. 环境检测
      2. 打印 banner（单 Panel，含系统状态）
      3. 初始化 CLISession（生成 run_id/thread_id）
      4-6. Guide Agent 三步中断对话
      7-9. 流水线执行（Search/Screen/Extract 实时进度）
      10. REPL（规划中）
    """
    from backend.src.cli.conversation import run_guide_conversation
    from backend.src.cli.pipeline_view import run_pipeline_view
    from backend.src.graph.pipeline import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    # ── 步骤 1：环境检测（静默，结果交给 banner 显示）────────────────────────
    results = run_system_check()

    # ── 步骤 2：Banner ────────────────────────────────────────────────────────
    print_banner(results)

    # ── 步骤 3：初始化会话 ────────────────────────────────────────────────────
    session = CLISession()
    run_id  = session.new_run_id()
    console.print(f"[dim]Session: {run_id}  ·  Thread: {session.thread_id}[/dim]\n")

    # ── 步骤 4-6：构建 graph + Guide 三步对话 ─────────────────────────────────
    # MemorySaver 提供 interrupt/resume 所需的检查点支持（进程内有效）
    checkpointer = MemorySaver()

    mode  = os.getenv("GRAPH_AGENT_MODE", "mock")
    graph = build_graph(mode=mode, checkpointer=checkpointer)

    input_data = {"run_id": run_id}

    try:
        final_state, was_confirmed = run_guide_conversation(
            graph=graph,
            input_data=input_data,
            session=session,
        )

        # ── 步骤 7-9：流水线执行 ─────────────────────────────────────────────
        if was_confirmed:
            final_state = run_pipeline_view(
                graph=graph,
                final_state=final_state,
            )

            # 记录历史
            session.add_history({
                "run_id": run_id,
                "status": "success",
                "summary": "流水线执行完成",
            })

            # ── 步骤 10：REPL（规划中）──────────────────────────────────────
            console.print("[dim]输入 /quit 退出[/dim]\n")

    except KeyboardInterrupt:
        console.print("\n[yellow]已中断[/yellow]")
        session.add_history({"run_id": run_id, "status": "interrupted", "summary": "用户中断"})

    except Exception as e:
        console.print(f"\n[red]错误：{e}[/red]")
        session.add_history({"run_id": run_id, "status": "error", "summary": str(e)})


if __name__ == "__main__":
    main()
