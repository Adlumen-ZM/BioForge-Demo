"""
backend/src/cli/session.py — CLI 会话状态管理

位置：backend/src/cli/
依赖：uuid、dataclasses、datetime
职责：维护单次 CLI 会话的状态（run_id、thread_id、运行历史等），
     支持多轮对话和流水线执行的状态持久化。

CLISession 与 LangGraph checkpointer 的关系：
  - thread_id：由 LangGraph checkpointer（如 SqliteSaver）用来标识一个执行线程，
    支持 interrupt() 断点恢复
  - run_id：当前运行的唯一 ID，用于 trace 关联
  - history：存储此会话的所有运行记录（结构化日志）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CLISession:
    """单个 CLI 会话的状态容器。

    Attributes:
        run_id:    当前运行的唯一标识（格式 "run_<uuid_hex[:8]>"），
                   用于 trace 落库和日志关联。
        thread_id: LangGraph checkpointer 用的线程 ID（格式 "thread_<uuid_hex[:8]}"），
                   用于 interrupt() resume 和检查点管理。
                   每次 new_run_id() 时自动更新。
        history:   此会话的运行历史记录列表，每项为 dict：
                   {run_id, agent, status, start_time, end_time, summary}。
        created_at: 会话创建时间戳。
    """

    run_id:      str = ""
    thread_id:   str = ""
    history:     list[dict[str, Any]] = field(default_factory=list)
    created_at:  datetime = field(default_factory=datetime.now)

    def new_run_id(self) -> str:
        """生成新的 run_id 和 thread_id，同步更新会话状态。

        LangGraph interrupt() 依赖 thread_id 来管理检查点，所以每次开始新的
        run 时需要生成一对新的 ID。

        Returns:
            str，新生成的 run_id（"run_<8位16进制>"）。
        """
        self.run_id    = f"run_{uuid.uuid4().hex[:8]}"
        self.thread_id = f"thread_{uuid.uuid4().hex[:8]}"
        return self.run_id

    def add_history(self, record: dict[str, Any]) -> None:
        """向历史记录列表追加一条运行记录。

        Args:
            record: 运行记录 dict，应含 run_id、status、summary 等字段。
        """
        record.setdefault("recorded_at", datetime.now().isoformat())
        self.history.append(record)

    def reset(self) -> None:
        """重置会话状态（清空 run_id、thread_id、历史），保留 created_at。

        用于重新开始会话或清理资源时调用。
        """
        self.run_id   = ""
        self.thread_id = ""
        self.history  = []

    def summary(self) -> dict[str, Any]:
        """返回会话摘要（用于输出或日志）。

        Returns:
            dict，含 run_count、success_count、created_at 等统计信息。
        """
        total_runs = len(self.history)
        success_runs = sum(1 for r in self.history if r.get("status") == "success")
        return {
            "total_runs":    total_runs,
            "success_runs":  success_runs,
            "created_at":    self.created_at.isoformat(),
            "current_run_id": self.run_id,
            "current_thread_id": self.thread_id,
        }
