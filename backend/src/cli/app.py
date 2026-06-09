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

    # ── 步骤 3：初始化会话 + TraceManager ────────────────────────────────────
    session = CLISession()
    run_id  = session.new_run_id()
    console.print(f"[dim]Session: {run_id}  ·  Thread: {session.thread_id}[/dim]\n")

    # TraceManager：file sink + CLI buffer sink，目录 data/runs/YYYYMMDD/{run_id}/
    from backend.src.db_access.trace.trace_manager import TraceManager, set_manager
    trace_manager = TraceManager.create(run_id=run_id)
    set_manager(trace_manager)

    # ── 步骤 4-6：构建 graph + Guide 三步对话 ─────────────────────────────────
    # MemorySaver 提供 interrupt/resume 所需的检查点支持（进程内有效）
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

        # ── 步骤 7-9：流水线执行（pipeline_view 驱动真实 graph.stream）──────
        if was_confirmed:
            final_state = run_pipeline_view(
                graph=graph,
                session=session,
                trace_manager=trace_manager,
            )

            # 记录历史
            session.add_history({
                "run_id":  run_id,
                "status":  final_state.get("status", "success"),
                "summary": f"流水线执行完成 status={final_state.get('status', '?')}",
            })

            # ── 步骤 10：REPL（规划中）──────────────────────────────────────
            console.print("[dim]输入 /quit 退出[/dim]\n")

    except KeyboardInterrupt:
        console.print("\n[yellow]已中断[/yellow]")
        session.add_history({"run_id": run_id, "status": "interrupted", "summary": "用户中断"})

    except Exception as e:
        console.print(f"\n[red]错误：{e}[/red]")
        session.add_history({"run_id": run_id, "status": "error", "summary": str(e)})

    finally:
        # 关闭 trace sink（刷写文件句柄）
        try:
            trace_manager.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
