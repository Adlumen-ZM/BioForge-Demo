"""
console_backend.py — Trace CLI 日志 Sink

位置：backend/src/db_access/trace/
职责：
  - 将 trace 事件格式化为单行文字，写入共享 buffer
  - pipeline_view 的 rich.Live 面板从 buffer 读取并显示
  - guide 事件不显示（interrupt 流已处理）
  - 根据 TRACE_CLI_LEVEL 控制输出粒度（quiet / normal / debug）

与 rich.Live 的关系：
  CLIConsoleSink 不直接打印，只往 log_buffer 追加字符串。
  pipeline_view.py 的 _build_live_renderable() 读取 buffer 最近 N 行，
  嵌入到 Live 面板下半部分展示，避免与 Live 独占终端冲突。

日志格式：
  [NODE]  精简标识（最多 8 字符）
  事件描述（不超过 80 字符，超长截断）
"""

from __future__ import annotations

from .event_types import (
    CLI_NORMAL_EVENTS,
    CLI_DEBUG_EVENTS,
    CLI_QUIET_EVENTS,
    GUIDE_ONLY_EVENTS,
)

# stage → 显示标识（最多 8 字符）
_STAGE_LABELS: dict[str, str] = {
    "guide_node":   "GUIDE",
    "search_node":  "SEARCH",
    "screen_node":  "SCREEN",
    "extract_node": "EXTRACT",
    "persist_node": "PERSIST",
    "search_agent": "SEARCH",
    "screen_agent": "SCREEN",
    "extract_agent":"EXTRACT",
    "pipeline":     "PIPELINE",
}


class CLIConsoleSink:
    """将 trace 事件格式化后写入共享 log_buffer，供 rich.Live 面板读取。

    Attributes:
        log_buffer: 与 pipeline_view 共享的字符串列表（最近 max_buffer 条）。
        level:      日志级别（quiet / normal / debug）。
    """

    def __init__(self, log_buffer: list[str], level: str = "normal"):
        self._buffer    = log_buffer
        self.level      = level
        self._max_buffer = 60  # 保留最近 60 条，Live 展示最近 8 条

    def write(self, event: dict) -> None:
        """根据事件类型和级别，格式化后写入 buffer。"""
        etype = event.get("event_type", "")

        # guide 事件不在 CLI 显示
        if etype in GUIDE_ONLY_EVENTS:
            return

        allowed = {
            "quiet":  CLI_QUIET_EVENTS,
            "normal": CLI_NORMAL_EVENTS,
            "debug":  CLI_DEBUG_EVENTS,
        }.get(self.level, CLI_NORMAL_EVENTS)

        if etype not in allowed:
            return

        msg = self._format(event)
        if msg:
            self._buffer.append(msg)
            # 超出上限时从头部删除最旧的一条
            while len(self._buffer) > self._max_buffer:
                self._buffer.pop(0)

    def _format(self, event: dict) -> str:
        """将 trace event 格式化为单行字符串。"""
        etype   = event.get("event_type", "")
        stage   = event.get("stage", "")
        payload = event.get("payload", {})
        status  = event.get("status", "success")

        label = _STAGE_LABELS.get(stage, stage.upper()[:8] or "SYS")

        # 状态前缀
        ok_icon = "⚠" if status == "warning" else "✗" if status in ("failed", "error") else "✓"

        if etype == "pipeline_started":
            return f"[RUN] run_id={event.get('run_id', '')} started"

        elif etype == "pipeline_finished":
            return f"[RUN] ✓ pipeline finished"

        elif etype == "pipeline_failed":
            err = str(payload.get("error", ""))[:40]
            return f"[RUN] ✗ pipeline failed: {err}"

        elif etype == "node_started":
            return f"[{label}] ▶ start"

        elif etype == "node_finished":
            ms = event.get("duration_ms")
            ms_str = f" ({ms:.0f}ms)" if ms else ""
            return f"[{label}] ✓ done{ms_str}"

        elif etype == "node_failed":
            err = str(payload.get("error", ""))[:40]
            return f"[{label}] ✗ failed: {err}"

        elif etype == "search_query_built":
            q = str(payload.get("query_string", ""))
            return f"[{label}] query: {q[:60]}" + ("..." if len(q) > 60 else "")

        elif etype == "search_results_collected":
            n = payload.get("candidate_count", "?")
            return f"[{label}] candidates: {n}"

        elif etype == "pdf_download_finished":
            ok_n  = payload.get("success_count", "?")
            fail  = payload.get("failed_count", 0)
            return f"[{label}] download: ✓{ok_n} ✗{fail}"

        elif etype == "rag_csv_generated":
            tables = payload.get("tables", {})
            n = sum(1 for v in tables.values() if isinstance(v, dict) and v.get("exists"))
            paper = payload.get("paper_key", "")[:8]
            return f"[EXTRACT] {paper} CSV: {n} tables"

        elif etype == "csv_quality_checked":
            st     = payload.get("quality_status", "?")
            issues = payload.get("issues_count", 0)
            icon   = "⚠" if issues > 0 else "✓"
            return f"[EXTRACT] quality {icon}: {st} ({issues} issues)"

        elif etype == "extraction_package_built":
            entities = payload.get("entities_count", 0)
            paper    = payload.get("paper_key", "")[:8]
            return f"[EXTRACT] {paper} package: {entities} entities"

        elif etype == "db_persist_finished":
            pid     = payload.get("paper_id", "?")
            written = payload.get("entities_written", 0)
            return f"[PERSIST] {pid}: {written} entities written"

        elif etype == "llm_call_finished":
            model  = payload.get("model", "?")
            tokens = payload.get("token_usage", {}).get("total_tokens", "?")
            lat    = event.get("duration_ms")
            lat_str = f" {lat:.0f}ms" if lat else ""
            return f"[{label}] LLM {model} {tokens}tok{lat_str}"

        elif etype == "tool_call_finished":
            tool  = payload.get("tool_name", "?")
            ms    = event.get("duration_ms")
            ms_str = f" {ms:.0f}ms" if ms else ""
            return f"[{label}] tool:{tool}{ms_str}"

        return ""
