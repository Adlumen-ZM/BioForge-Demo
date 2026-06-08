"""
backend/src/cli/conversation.py — 对话式中断处理

职责：与 Guide Agent 的三步中断流程交互，处理三种 interrupt 类型：
  1. task_confirm — 任务描述确认
  2. schema_confirm — 数据库字段确认
  3. criteria_confirm — 过滤规则确认

核心函数：
  - run_guide_conversation(graph, input_data, session)
    调用 graph.invoke 并处理中断，返回最终状态
  - _render_task_panel(payload) → None
    渲染任务描述面板
  - _render_schema_table(payload) → None
    渲染数据库字段表格
  - _render_criteria_panel(payload) → None
    渲染过滤规则面板
  - wait_for_ok() → None
    阻塞等待用户确认
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def wait_for_ok() -> None:
    """阻塞等待用户按 OK（输入任意字符后回车）。

    用于分步式对话的确认点。
    """
    try:
        console.print("[bold yellow]按 Enter 继续... [/bold yellow]", end="")
        input()
    except (EOFError, KeyboardInterrupt):
        console.print("[red]\\n用户中断[/red]")
        raise


def _render_task_panel(payload: dict[str, Any]) -> None:
    """渲染任务描述确认面板。

    Args:
        payload: interrupt 的 task_confirm_payload，含 task_description 和建议
    """
    task_desc = payload.get("task_description", "无")

    console.print()
    console.print(
        Panel(
            f"[bold cyan]{task_desc}[/bold cyan]",
            title="[yellow]Step 1: 任务描述[/yellow]",
            border_style="cyan",
            expand=False,
        )
    )
    console.print()


def _render_schema_table(payload: dict[str, Any]) -> None:
    """渲染数据库字段表格。

    Args:
        payload: interrupt 的 schema_confirm_payload，含 db_schema（字段列表）
    """
    db_schema = payload.get("db_schema", {})

    table = Table(
        title="Step 2: 推荐数据库字段",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("字段名", style="cyan", width=20)
    table.add_column("类型", width=15)
    table.add_column("说明")

    if isinstance(db_schema, dict):
        for field_name, field_info in db_schema.items():
            if isinstance(field_info, dict):
                field_type = field_info.get("type", "string")
                description = field_info.get("description", "")
            else:
                field_type = str(field_info)
                description = ""

            table.add_row(field_name, field_type, description)

    console.print()
    console.print(table)
    console.print()


def _render_criteria_panel(payload: dict[str, Any]) -> None:
    """渲染过滤规则确认面板。

    Args:
        payload: interrupt 的 criteria_confirm_payload，含 inclusion_criteria 和 exclusion_criteria
    """
    inclusion = payload.get("inclusion_criteria", {})
    exclusion = payload.get("exclusion_criteria", {})

    criteria_text = "[bold cyan]纳入标准（Inclusion）:[/bold cyan]\n"
    if isinstance(inclusion, dict):
        for i, (key, val) in enumerate(inclusion.items(), 1):
            criteria_text += f"  {i}. {key}: {val}\n"

    criteria_text += "\n[bold red]排除标准（Exclusion）:[/bold red]\n"
    if isinstance(exclusion, dict):
        for i, (key, val) in enumerate(exclusion.items(), 1):
            criteria_text += f"  {i}. {key}: {val}\n"

    console.print()
    console.print(
        Panel(
            criteria_text,
            title="[yellow]Step 3: 纳入/排除标准[/yellow]",
            border_style="cyan",
            expand=False,
        )
    )
    console.print()


def run_guide_conversation(
    graph: Any,
    input_data: dict[str, Any],
    session: Any,
) -> tuple[dict[str, Any], bool]:
    """运行 Guide Agent 三步对话流程（支持中断和恢复）。

    流程：
      1. graph.invoke() 启动 Guide Agent
      2. Guide Agent 生成三个 interrupt 事件（task/schema/criteria）
      3. 每次 interrupt 后渲染对应的确认面板
      4. 用户按 OK 后 resume，继续下一步
      5. 全部完成后返回最终状态

    Args:
        graph: 编译后的 LangGraph StateGraph
        input_data: 初始输入数据（包含 run_id、task_description 等字段）
        session: CLISession 实例，记录中断点和恢复状态

    Returns:
        (final_state, was_confirmed)
        - final_state: Guide 完成后的状态字典
        - was_confirmed: 用户是否确认了所有三步（True/False）
    """
    config = {"configurable": {"thread_id": session.thread_id}}
    final_state = {}
    was_confirmed = True

    try:
        # ── 第一次调用：开始 Guide Agent（会在第一个 interrupt 停下）
        state = graph.invoke(input_data, config=config)

        # ── 处理三个 interrupt 事件
        # 当前简化实现：直接从 state 中读取三步数据并渲染
        # 完整实现应通过 LangGraph 的事件流或 HumanMessage 处理中断

        # ── Step 1: 任务描述确认
        task_payload = {
            "task_description": state.get("task_description", ""),
        }
        _render_task_panel(task_payload)
        wait_for_ok()

        # ── Step 2: 数据库字段确认
        schema_payload = {
            "db_schema": state.get("db_schema", {}),
        }
        _render_schema_table(schema_payload)
        wait_for_ok()

        # ── Step 3: 过滤规则确认
        criteria_payload = {
            "inclusion_criteria": state.get("inclusion_criteria", {}),
            "exclusion_criteria": state.get("exclusion_criteria", {}),
        }
        _render_criteria_panel(criteria_payload)
        wait_for_ok()

        # ── 三步都确认完毕
        final_state = state
        was_confirmed = state.get("user_confirmed", True)

        console.print("[bold green]✅ 任务配置完成[/bold green]")
        console.print()

    except KeyboardInterrupt:
        console.print("[red]\\n对话已中断，可通过 resume 恢复[/red]")
        was_confirmed = False
        final_state = {}
    except Exception as e:
        console.print(f"[red]对话过程出错：{e}[/red]")
        was_confirmed = False
        final_state = {}

    return final_state, was_confirmed
