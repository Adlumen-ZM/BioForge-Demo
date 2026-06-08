"""
backend/src/cli/conversation.py — 对话式中断处理

职责：与 Guide Agent 的三步中断流程交互：
  1. 等待 interrupt（task_confirm_payload）→ 渲染任务描述面板 → wait_for_ok() → resume
  2. 等待 interrupt（schema_confirm_payload）→ 渲染数据库表格 → wait_for_ok() → resume
  3. 等待 interrupt（criteria_confirm_payload）→ 渲染过滤规则面板 → wait_for_ok() → resume

核心函数：
  - run_guide_conversation(graph, input_data, session) → (state_after_guide, was_confirmed)
    调用 graph.invoke 并处理中断，返回最终状态
  - wait_for_ok() → None
    简单的 [按 OK 继续] 阻塞

当前版本：骨架 + 占位实现，完整渲染见 Step 09 文档。
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel

console = Console()


def wait_for_ok() -> None:
    """阻塞等待用户按 OK（输入任意字符后回车）。

    用于分步式对话的确认点。
    """
    try:
        console.print("[bold yellow]按 Enter 继续... [/bold yellow]", end="")
        input()
    except (EOFError, KeyboardInterrupt):
        console.print("[red]用户中断[/red]")
        raise


def run_guide_conversation(
    graph: Any,
    input_data: dict[str, Any],
    session: Any,
) -> tuple[dict[str, Any], bool]:
    """运行 Guide Agent 三步对话流程（支持中断和恢复）。

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

    try:
        # ── 第一次调用：开始 Guide Agent（会在第一个 interrupt 停下）
        state = graph.invoke(input_data, config=config)

        # ── 检查是否有 interrupt 事件（当前版本：简化处理）
        # 实际实现会通过 LangGraph 的 HumanMessage 或事件流处理中断
        console.print("[bold cyan]Guide Agent: 任务描述[/bold cyan]")
        console.print(f"  {state.get('task_description', '无')}")
        wait_for_ok()

        console.print("[bold cyan]Guide Agent: 数据库字段[/bold cyan]")
        console.print(f"  {state.get('db_schema', {})}")
        wait_for_ok()

        console.print("[bold cyan]Guide Agent: 过滤规则[/bold cyan]")
        console.print(f"  {state.get('inclusion_criteria', {})}")
        wait_for_ok()

        final_state = state
        was_confirmed = state.get("user_confirmed", True)

    except KeyboardInterrupt:
        console.print("[red]\\n对话已中断，可通过 resume 恢复[/red]")
        was_confirmed = False
        final_state = {}

    return final_state, was_confirmed
