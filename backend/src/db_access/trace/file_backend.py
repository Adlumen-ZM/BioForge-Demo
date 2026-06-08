"""
file_backend.py — Trace 文件写入 Sink

位置：backend/src/db_access/trace/
职责：
  - 将所有 trace 事件写入 data/runs/YYYYMMDD/{run_id}/trace/events.jsonl
  - 将 LLM/Tool/Node 类事件分流到 operator_debug/*.jsonl
  - 超长 payload 自动截断（TRACE_MAX_PAYLOAD_CHARS）
  - 不依赖 PostgreSQL

目录结构（自动创建）：
  {run_dir}/
    trace/
      events.jsonl          ← 所有事件
    operator_debug/
      llm_calls.jsonl       ← LLM 调用事件
      tool_calls.jsonl      ← Tool 调用事件
      node_io.jsonl         ← Node 输入输出事件
    artifacts/              ← 业务中间文件（由 agent 写入，trace 只记录路径）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FileJsonlSink:
    """将 trace 事件追加写入本地 JSONL 文件。

    每行一个 JSON event，同时分流到 operator_debug/。
    Payload 超过 max_payload_chars 时截断（避免大文件）。
    """

    def __init__(self, run_dir: Path, max_payload_chars: int = 4000):
        self.run_dir          = run_dir
        self.max_payload_chars = max_payload_chars

        # ── 创建目录 ──────────────────────────────────────────────────────────
        trace_dir = run_dir / "trace"
        debug_dir = run_dir / "operator_debug"
        artifacts_dir = run_dir / "artifacts"
        for d in [trace_dir, debug_dir, artifacts_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # ── 打开文件（追加模式）────────────────────────────────────────────────
        self._events_file = open(trace_dir / "events.jsonl",           "a", encoding="utf-8")
        self._llm_file    = open(debug_dir / "llm_calls.jsonl",        "a", encoding="utf-8")
        self._tool_file   = open(debug_dir / "tool_calls.jsonl",       "a", encoding="utf-8")
        self._node_file   = open(debug_dir / "node_io.jsonl",          "a", encoding="utf-8")
        self._valid_file  = open(debug_dir / "validation_events.jsonl","a", encoding="utf-8")

    def write(self, event: dict[str, Any]) -> None:
        """将事件写入 events.jsonl，并按类型分流到 operator_debug/。"""
        event = self._truncate_payload(event)
        line  = json.dumps(event, ensure_ascii=False)

        # 写主事件流
        self._events_file.write(line + "\n")
        self._events_file.flush()

        # 按事件类型分流
        etype = event.get("event_type", "")
        if "llm_call" in etype or "llm_output" in etype:
            self._llm_file.write(line + "\n")
            self._llm_file.flush()
        elif "tool_call" in etype:
            self._tool_file.write(line + "\n")
            self._tool_file.flush()
        elif etype in {"node_started", "node_finished", "node_failed"}:
            self._node_file.write(line + "\n")
            self._node_file.flush()
        elif "validation" in etype or "csv_quality" in etype:
            self._valid_file.write(line + "\n")
            self._valid_file.flush()

    def _truncate_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        """若 payload 序列化后超过 max_payload_chars，替换为截断标记。"""
        payload     = event.get("payload", {})
        payload_str = json.dumps(payload, ensure_ascii=False)
        if len(payload_str) > self.max_payload_chars:
            event = dict(event)
            event["payload"] = {
                "truncated":           True,
                "original_size_chars": len(payload_str),
            }
        return event

    def close(self) -> None:
        """关闭所有文件句柄。"""
        for f in [self._events_file, self._llm_file, self._tool_file,
                  self._node_file, self._valid_file]:
            try:
                f.close()
            except Exception:
                pass
