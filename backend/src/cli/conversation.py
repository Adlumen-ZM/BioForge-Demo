"""
backend/src/cli/conversation.py — Guide Agent 四步中断对话处理

位置：backend/src/cli/
依赖：rich（Panel/Table/Text）、langgraph.types.Command
职责：
  - 通过 graph.stream() 启动 Guide Agent，监听 __interrupt__ 事件
  - 根据 payload["type"] 路由到对应渲染函数（Q1→Q2→Q3→Q4）
  - 用户按 Enter 后通过 Command(resume=0) 恢复执行
  - 支持 4 次 interrupt + 1 次最终 resume

四步对话对应的 interrupt 类型：
  q1_goal_confirm        — 研究目标确认（文本 Panel）
  q2_boundary_confirm    — 研究对象边界确认（纳入/排除列表）
  q3_schema_confirm      — 数据库字段模板确认（模板元数据）
  q4_pipeline_start      — 是否进入 pipeline（流程确认）
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# 渲染函数（每种 interrupt 类型一个）
# ─────────────────────────────────────────────────────────────────────────────

def _render_q1_goal(payload: dict[str, Any]) -> None:
    """渲染研究目标确认 Panel（对应 q1_goal_confirm）。

    payload["content"] 是研究目标的字符串描述。
    """
    label   = payload.get("label", "研究目标确认")
    content = payload.get("content", "")
    option  = (payload.get("options") or ["确认"])[0]

    console.print(
        Panel(
            f"[white]{content}[/white]",
            title=f"[bold yellow]Q1 · {label}[/bold yellow]",
            subtitle=f"[dim]► {option}[/dim]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _render_q2_boundary(payload: dict[str, Any]) -> None:
    """渲染研究对象边界确认（对应 q2_boundary_confirm）。

    payload["content"] = {"inclusion": [...], "exclusion": [...]}
    """
    label   = payload.get("label", "研究对象边界确认")
    content = payload.get("content", {})
    option  = (payload.get("options") or ["确认"])[0]

    inclusion = content.get("inclusion", [])
    exclusion = content.get("exclusion", [])

    text = Text()
    text.append("  纳入对象\n", style="bold green")
    for i, item in enumerate(inclusion, 1):
        text.append(f"   {i}. {item}\n", style="green")
    text.append("\n  排除对象\n", style="bold red")
    for i, item in enumerate(exclusion, 1):
        text.append(f"   {i}. {item}\n", style="red")

    console.print(
        Panel(
            text,
            title=f"[bold yellow]Q2 · {label}[/bold yellow]",
            subtitle=f"[dim]► {option}[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


def _render_q3_schema(payload: dict[str, Any]) -> None:
    """渲染数据库字段模板确认（对应 q3_schema_confirm）。

    只展示模板元数据（template_id + 路径 + 用途说明），不展示完整 schema 内容。
    payload["content"] = {template_id, schema_path, filling_rules_path, description}
    """
    label   = payload.get("label", "数据库字段模板确认")
    content = payload.get("content", {})
    option  = (payload.get("options") or ["确认"])[0]

    template_id        = content.get("template_id", "hap_peptide_v1")
    schema_path        = content.get("schema_path", "")
    filling_rules_path = content.get("filling_rules_path", "")
    description        = content.get("description", "")

    text = Text()
    text.append(f"  template_id:         ", style="dim")
    text.append(f"{template_id}\n", style="bold cyan")
    text.append(f"  schema_path:         ", style="dim")
    text.append(f"{schema_path}\n", style="white")
    text.append(f"  filling_rules_path:  ", style="dim")
    text.append(f"{filling_rules_path}\n", style="white")
    if description:
        text.append(f"\n  {description}\n", style="dim")

    console.print(
        Panel(
            text,
            title=f"[bold yellow]Q3 · {label}[/bold yellow]",
            subtitle=f"[dim]► {option}[/dim]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _render_q4_pipeline(payload: dict[str, Any]) -> None:
    """渲染 pipeline 启动确认（对应 q4_pipeline_start）。

    payload["content"] 是流程字符串，如 "guide → search → screen → extract → database write"
    """
    label   = payload.get("label", "是否进入 pipeline")
    content = payload.get("content", "guide → search → screen → extract → database write")
    option  = (payload.get("options") or ["开始"])[0]

    console.print(
        Panel(
            f"[bold white]  {content}[/bold white]",
            title=f"[bold yellow]Q4 · {label}[/bold yellow]",
            subtitle=f"[dim]► {option}[/dim]",
            border_style="green",
            padding=(1, 2),
        )
    )


def _render_interrupt(payload: dict[str, Any]) -> None:
    """根据 payload["type"] 路由到对应的渲染函数。

    Args:
        payload: interrupt() 传出的 payload dict。
    """
    ptype = payload.get("type", "")
    console.print()
    if ptype == "q1_goal_confirm":
        _render_q1_goal(payload)
    elif ptype == "q2_boundary_confirm":
        _render_q2_boundary(payload)
    elif ptype == "q3_schema_confirm":
        _render_q3_schema(payload)
    elif ptype == "q4_pipeline_start":
        _render_q4_pipeline(payload)
    else:
        # 未知类型：原样打印（向后兼容旧 payload 格式）
        console.print(f"[yellow][interrupt {ptype}][/yellow] {payload}")
    console.print()


def _wait_for_ok() -> None:
    """阻塞等待用户按 Enter 确认。

    interrupt 确认点：用户按 Enter 后图从断点继续（Command(resume=0) = 选项0"确认"）。
    """
    try:
        console.print("[bold yellow]  按 Enter 确认继续... [/bold yellow]", end="")
        input()
    except (EOFError, KeyboardInterrupt):
        raise


def _stream_until_interrupt(
    graph: Any,
    input_or_command: Any,
    config: dict,
) -> dict | None:
    """流式执行 graph，直到遇到 __interrupt__ 事件或图执行完毕。

    Args:
        graph:            编译后的 LangGraph StateGraph。
        input_or_command: 首次调用传 input_data dict；resume 时传 Command(resume=0)。
        config:           {"configurable": {"thread_id": ...}}

    Returns:
        interrupt payload dict（若遇到 interrupt），或 None（图执行完毕）。
    """
    for chunk in graph.stream(input_or_command, config=config):
        if "__interrupt__" in chunk:
            return chunk["__interrupt__"][0].value
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def run_guide_conversation(
    graph: Any,
    input_data: dict[str, Any],
    session: Any,
) -> bool:
    """运行 Guide Agent 四步对话流程（interrupt/resume）。

    流程：
      1. graph.stream(input_data) → 等第一个 interrupt（Q1 研究目标）
      2. 渲染 Q1 → 用户 Enter → Command(resume=0)
      3-8. 重复 Q2/Q3/Q4
      9. Q4 确认后返回 True；pipeline 执行由 pipeline_view.run_pipeline_view() 负责

    Args:
        graph:      编译后的 LangGraph StateGraph（带 MemorySaver checkpointer）。
        input_data: 初始输入 dict（至少含 run_id 字段）。
        session:    CLISession 实例（提供 thread_id）。

    Returns:
        was_confirmed: 用户完成四步确认则 True，中断/出错则 False。
    """
    from langgraph.types import Command

    config  = {"configurable": {"thread_id": session.thread_id}}
    current = input_data

    try:
        # ── 4 次 interrupt（Q1 → Q2 → Q3 → Q4）──────────────────────────
        for _i in range(4):
            payload = _stream_until_interrupt(graph, current, config)
            if payload:
                _render_interrupt(payload)
                _wait_for_ok()
            # 第一次用 input_data 启动，后续都用 Command(resume=0) 继续
            current = Command(resume=0)

        console.print("[bold green]✅ 任务配置已确认，准备启动流水线[/bold green]\n")
        return True

    except KeyboardInterrupt:
        console.print("\n[yellow]引导对话已中断[/yellow]\n")
        return False
    except Exception as e:
        console.print(f"\n[red]引导对话出错：{e}[/red]\n")
        return False
