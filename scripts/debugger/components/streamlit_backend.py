"""
scripts/debugger/components/streamlit_backend.py — Streamlit 流式 TraceBackend

位置：scripts/debugger/components/
依赖：backend/src/agents/agent_template/hooks.py（TraceBackend ABC, TraceEvent）
      queue（标准库）
职责：
  1. StreamlitProgressBackend — 把 TraceEvent 放入 queue.Queue，供 Streamlit 页面实时消费。
     不做任何 UI 操作，纯数据传递。队列满时静默丢弃，不影响主流程。
  2. CompositeBackend — 把一次 write 请求扇出给多个 TraceBackend，
     任何一个后端失败不影响其他后端，保证落库与实时显示同时发生。

架构说明：
  AgentTemplate.run()（后台线程）
      ↓ TraceHook 在4个固定位置调用
  CompositeBackend
      ├── PostgresBackend  →  写 agent_trace_events 表（持久化）
      └── StreamlitProgressBackend  →  写 queue.Queue（实时传给 UI）

使用方式（04_editor.py）：
    import queue
    from components.streamlit_backend import CompositeBackend, StreamlitProgressBackend
    from backend.src.db_access.trace.postgres_backend import PostgresBackend

    progress_q = queue.Queue(maxsize=100)
    agent.hook.backend = CompositeBackend(
        PostgresBackend(),
        StreamlitProgressBackend(progress_q),
    )
    # 在 Streamlit 主线程中轮询 progress_q 消费事件

注意：CompositeBackend 定义于此（而非 postgres_backend.py），
      因为 db_access/trace/ 零改动约束。
"""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING

# 从 agent_template/hooks.py 导入抽象基类（零改动约束：只 import，不修改）
from backend.src.agents.agent_template.hooks import TraceBackend, TraceEvent

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────
# StreamlitProgressBackend
# ─────────────────────────────────────────────

class StreamlitProgressBackend(TraceBackend):
    """把 TraceEvent 序列化后放入 queue.Queue，供 Streamlit 页面实时消费。

    设计原则：
    - 不做任何 Streamlit UI 操作（UI 由页面代码负责）
    - 纯数据传递：TraceEvent.to_dict() → put_nowait → 主线程消费
    - 队列满（maxsize=100）时静默丢弃，不阻塞，不报错
    - write() 不抛异常（遵守 TraceBackend 约定）
    """

    def __init__(self, q: queue.Queue) -> None:
        """
        Args:
            q: Streamlit 主线程共享的队列。
               建议 maxsize=100，防止内存无限增长。
        """
        self.q = q

    def write(self, event: TraceEvent) -> None:
        """将 TraceEvent 序列化为 dict 后放入队列。

        非阻塞写入（put_nowait）。队列满时静默跳过，不影响主流程。

        Args:
            event: 由 TraceHook 生成的 TraceEvent 实例。
        """
        try:
            self.q.put_nowait(event.to_dict())
        except queue.Full:
            # 队列满时静默丢弃：UI 稍有滞后但主流程不受影响
            pass
        except Exception:
            # 其他异常也静默跳过（TraceBackend 约定：write 不抛异常）
            pass


# ─────────────────────────────────────────────
# CompositeBackend
# ─────────────────────────────────────────────

class CompositeBackend(TraceBackend):
    """将一次 write 请求扇出给多个 TraceBackend，实现同时落库 + 实时显示。

    任何一个后端的 write() 抛异常时，只打印警告，继续调用其余后端，
    保证「落库」和「实时显示」互不阻塞。

    用法示例：
        backend = CompositeBackend(
            PostgresBackend(),            # 持久化 trace
            StreamlitProgressBackend(q),  # 实时推送到 UI
        )
        agent.hook.backend = backend

    扩展：
        后续可加入更多 backend（如 LangfuseBackend、WebSocketBackend 等），
        只需在构造时传入即可，template 代码零改动。
    """

    def __init__(self, *backends: TraceBackend) -> None:
        """
        Args:
            *backends: 任意数量的 TraceBackend 实例，按顺序逐一调用 write()。
        """
        self.backends: tuple[TraceBackend, ...] = backends

    def write(self, event: TraceEvent) -> None:
        """将 event 逐一写入所有 backend。

        任何一个 backend 抛异常时，打印警告并继续处理其余 backend。

        Args:
            event: 由 TraceHook 生成的 TraceEvent 实例。
        """
        for backend in self.backends:
            try:
                backend.write(event)
            except Exception as exc:
                # 打印警告但不传播异常（TraceBackend 约定：write 不抛异常）
                print(f"[CompositeBackend] ⚠️ {type(backend).__name__} 写入失败，已跳过：{exc}")
