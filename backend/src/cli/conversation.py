"""
backend/src/cli/conversation.py — Guide Agent 三步中断对话处理

位置：backend/src/cli/
依赖：rich（Panel/Table）、langgraph.types.Command
职责：
  - 通过 graph.stream() 启动 Guide Agent，监听 __interrupt__ 事件
  - 根据 payload["type"] 选择对应的渲染函数（task/schema/criteria）
  - 用户按 Enter 后通过 Command(resume=0) 恢复执行
  - 返回最终 PipelineState 和用户是否全部确认

与 agent.py 的关系：
  guide_node 内部调用三次 interrupt(payload)，每次 payload 格式为：
    {"type": "task_confirm"|"schema_confirm"|"criteria_confirm",
     "label": "...", "content": ..., "options": [...], "default": 0}
  本模块负责消费这三个 interrupt 事件并渲染给用户。
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

def _render_task_panel(payload: dict[str, Any]) -> None:
    """渲染任务描述确认面板（对应 task_confirm payload）。

    payload 结构：
      {"type": "task_confirm", "label": "...", "content": "<任务描述字符串>",
       "options": ["确认，继续"], "default": 0}

    Args:
        payload: guide_node 传给 interrupt() 的 task_confirm payload。
    """
    label   = payload.get("label", "任务描述")
    content = payload.get("content", "（无）")
    option  = payload.get("options", ["确认，继续"])[0]

    console.print(
        Panel(
            f"[white]{content}[/white]",
            title=f"[bold yellow]Step 1 · {label}[/bold yellow]",
            subtitle=f"[dim]► {option}[/dim]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _render_schema_table(payload: dict[str, Any]) -> None:
    """渲染数据库字段模板确认表格（对应 schema_confirm payload）。

    payload 结构：
      {"type": "schema_confirm", "label": "...",
       "content": {"字段名": {"type": ..., "description": ..., "example": ...}, ...},
       "options": ["确认，使用此模板"], "default": 0}

    Args:
        payload: guide_node 传给 interrupt() 的 schema_confirm payload。
    """
    label     = payload.get("label", "数据库字段模板")
    db_schema = payload.get("content", {})
    option    = payload.get("options", ["确认，使用此模板"])[0]

    table = Table(
        title=f"[bold yellow]Step 2 · {label}[/bold yellow]",
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
        padding=(0, 1),
    )
    table.add_column("字段名",   style="cyan",  width=22)
    table.add_column("类型",     style="yellow", width=8)
    table.add_column("说明",     width=30)
    table.add_column("示例值",   style="dim",    width=20)

    if isinstance(db_schema, dict):
        for field_name, field_info in db_schema.items():
            if isinstance(field_info, dict):
                ftype   = field_info.get("type",        "str")
                desc    = field_info.get("description", "")
                example = field_info.get("example",     "")
            else:
                ftype, desc, example = str(field_info), "", ""
            table.add_row(field_name, ftype, desc, example)

    console.print(table)
    console.print(f"[dim]  ► {option}[/dim]")


def _render_criteria_panel(payload: dict[str, Any]) -> None:
    """渲染文献准入/排除标准确认面板（对应 criteria_confirm payload）。

    payload 结构：
      {"type": "criteria_confirm", "label": "...",
       "content": {"inclusion": ["..."], "exclusion": ["..."]},
       "options": ["确认，进入检索"], "default": 0}

    Args:
        payload: guide_node 传给 interrupt() 的 criteria_confirm payload。
    """
    label     = payload.get("label", "文献准入/排除标准")
    content   = payload.get("content", {})
    option    = payload.get("options", ["确认，进入检索"])[0]
    inclusion = content.get("inclusion", [])
    exclusion = content.get("exclusion", [])

    text = Text()
    text.append("  纳入标准\n", style="bold green")
    for i, item in enumerate(inclusion, 1):
        text.append(f"   {i}. {item}\n", style="green")

    text.append("\n  排除标准\n", style="bold red")
    for i, item in enumerate(exclusion, 1):
        text.append(f"   {i}. {item}\n", style="red")

    console.print(
        Panel(
            text,
            title=f"[bold yellow]Step 3 · {label}[/bold yellow]",
            subtitle=f"[dim]► {option}[/dim]",
            border_style="cyan",
            padding=(0, 1),
        )
    )


def _render_interrupt(payload: dict[str, Any]) -> None:
    """根据 payload["type"] 分派到对应的渲染函数。

    Args:
        payload: interrupt() 传出的 payload dict，type 字段决定渲染方式。
    """
    ptype = payload.get("type", "")
    console.print()
    if ptype == "task_confirm":
        _render_task_panel(payload)
    elif ptype == "schema_confirm":
        _render_schema_table(payload)
    elif ptype == "criteria_confirm":
        _render_criteria_panel(payload)
    else:
        # 未知类型：原样打印
        console.print(f"[yellow][interrupt][/yellow] {payload}")
    console.print()


def _wait_for_ok() -> None:
    """阻塞等待用户按 Enter 确认。

    interrupt 确认点——用户按 Enter 后图从断点继续（resume=0 即选项0"确认"）。
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
        input_or_command: 首次调用时传 input_data dict；
                          resume 时传 Command(resume=0)。
        config:           {"configurable": {"thread_id": ...}}

    Returns:
        interrupt payload dict（若遇到 interrupt），或 None（图执行完毕）。
    """
    for chunk in graph.stream(input_or_command, config=config):
        if "__interrupt__" in chunk:
            # chunk["__interrupt__"] 是 Interrupt 对象列表，取第一个的 value
            return chunk["__interrupt__"][0].value
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def run_guide_conversation(
    graph: Any,
    input_data: dict[str, Any],
    session: Any,
) -> tuple[dict[str, Any], bool]:
    """运行 Guide Agent 三步对话流程（interrupt/resume 完整实现）。

    流程：
      1. graph.stream(input_data) → 等到第一个 interrupt（task_confirm）
      2. 渲染 task panel → 用户 Enter → Command(resume=0) 继续
      3. 等到第二个 interrupt（schema_confirm）
      4. 渲染 schema table → 用户 Enter → Command(resume=0) 继续
      5. 等到第三个 interrupt（criteria_confirm）
      6. 渲染 criteria panel → 用户 Enter → Command(resume=0) 继续
      7. graph 完成，读取最终 state

    Args:
        graph:      编译后的 LangGraph StateGraph（带 SqliteSaver checkpointer）。
        input_data: 初始输入 dict（至少含 run_id 字段）。
        session:    CLISession 实例（提供 thread_id）。

    Returns:
        (final_state, was_confirmed)
    """
    from langgraph.types import Command

    config = {"configurable": {"thread_id": session.thread_id}}

    try:
        # ── Step 1: 启动 graph，等第一个 interrupt（task_confirm）──────────────
        payload = _stream_until_interrupt(graph, input_data, config)
        if payload:
            _render_interrupt(payload)
            _wait_for_ok()

        # ── Step 2: resume，等第二个 interrupt（schema_confirm）─────────────────
        payload = _stream_until_interrupt(graph, Command(resume=0), config)
        if payload:
            _render_interrupt(payload)
            _wait_for_ok()

        # ── Step 3: resume，等第三个 interrupt（criteria_confirm）───────────────
        payload = _stream_until_interrupt(graph, Command(resume=0), config)
        if payload:
            _render_interrupt(payload)
            _wait_for_ok()

        # ── Step 4: 最终 resume，graph 执行完毕，读取最终 state ─────────────────
        for _ in graph.stream(Command(resume=0), config=config):
            pass

        final_state = dict(graph.get_state(config).values)

        console.print("[bold green]✅ 任务配置已确认，准备启动流水线[/bold green]\n")
        return final_state, True

    except KeyboardInterrupt:
        console.print("\n[yellow]引导对话已中断（可重新启动 CLI 恢复）[/yellow]\n")
        return {}, False
    except Exception as e:
        console.print(f"\n[red]引导对话出错：{e}[/red]\n")
        return {}, False
