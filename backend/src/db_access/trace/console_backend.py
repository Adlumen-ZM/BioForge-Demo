"""
console_backend.py - Trace CLI log sink.

Writes concise trace lines into a shared buffer for the rich Live panel and
maintains a small shared progress snapshot for in-node progress display.
"""

from __future__ import annotations

from .event_types import (
    CLI_DEBUG_EVENTS,
    CLI_NORMAL_EVENTS,
    CLI_QUIET_EVENTS,
    GUIDE_ONLY_EVENTS,
)

_STAGE_LABELS: dict[str, str] = {
    "guide_node": "GUIDE",
    "search_node": "SEARCH",
    "screen_node": "SCREEN",
    "extract_node": "EXTRACT",
    "persist_node": "PERSIST",
    "search_agent": "SEARCH",
    "screen_agent": "SCREEN",
    "extract_agent": "EXTRACT",
    "pipeline": "PIPELINE",
    "screen": "SCREEN",
    "extract": "EXTRACT",
}


class CLIConsoleSink:
    """Format trace events into one-line logs for the CLI live view."""

    def __init__(
        self,
        log_buffer: list[str],
        progress_state: dict | None = None,
        level: str = "normal",
    ):
        self._buffer = log_buffer
        self._progress = progress_state if progress_state is not None else {}
        self.level = level
        self._max_buffer = 60

    def write(self, event: dict) -> None:
        etype = event.get("event_type", "")
        self._update_progress(event)

        if etype in GUIDE_ONLY_EVENTS:
            return

        allowed = {
            "quiet": CLI_QUIET_EVENTS,
            "normal": CLI_NORMAL_EVENTS,
            "debug": CLI_DEBUG_EVENTS,
        }.get(self.level, CLI_NORMAL_EVENTS)

        if etype not in allowed:
            return

        msg = self._format(event)
        if msg:
            self._buffer.append(msg)
            while len(self._buffer) > self._max_buffer:
                self._buffer.pop(0)

    def _format(self, event: dict) -> str:
        etype = event.get("event_type", "")
        stage = event.get("stage", "")
        payload = event.get("payload", {}) or {}
        status = event.get("status", "success")

        label = _STAGE_LABELS.get(stage, stage.upper()[:8] or "SYS")

        if etype == "pipeline_started":
            return f"[RUN] run_id={event.get('run_id', '')} started"

        if etype == "pipeline_finished":
            return "[RUN] pipeline finished"

        if etype == "pipeline_failed":
            err = str(payload.get("error", ""))[:40]
            return f"[RUN] pipeline failed: {err}"

        if etype == "node_started":
            return f"[{label}] start"

        if etype == "node_finished":
            ms = event.get("duration_ms")
            ms_str = f" ({ms:.0f}ms)" if ms else ""
            return f"[{label}] done{ms_str}"

        if etype == "node_failed":
            err = str(payload.get("error", ""))[:40]
            return f"[{label}] failed: {err}"

        if etype == "search_query_built":
            q = str(payload.get("query_string", ""))
            return f"[{label}] query: {q[:60]}" + ("..." if len(q) > 60 else "")

        if etype == "search_results_collected":
            n = payload.get("candidate_count", "?")
            return f"[{label}] candidates: {n}"

        if etype == "download_attempt_started":
            pmid = payload.get("pmid") or "?"
            return f"[{label}] download PMID {pmid}"

        if etype == "pdf_download_finished":
            if payload.get("pmid"):
                pmid = payload.get("pmid") or "?"
                dl_status = payload.get("download_status", "?")
                if dl_status in ("downloaded", "already_exists"):
                    size = payload.get("file_size_bytes")
                    size_str = (
                        f" ({int(size) // 1024} KB)"
                        if isinstance(size, int) and size > 0
                        else ""
                    )
                    return f"[{label}] ok PMID {pmid} {dl_status}{size_str}"
                reason = str(payload.get("failure_reason") or payload.get("message") or "")[:60]
                return f"[{label}] failed PMID {pmid} {reason}".rstrip()

            ok_n = payload.get("success_count", "?")
            fail_n = payload.get("failed_count", 0)
            return f"[{label}] download: ok {ok_n} fail {fail_n}"

        if etype == "rag_csv_generated":
            tables = payload.get("tables", {})
            n = sum(1 for v in tables.values() if isinstance(v, dict) and v.get("exists"))
            paper = payload.get("paper_key", "")[:8]
            return f"[EXTRACT] {paper} CSV: {n} tables"

        if etype == "csv_quality_checked":
            st = payload.get("quality_status", "?")
            issues = payload.get("issues_count", 0)
            icon = "warn" if issues > 0 else "ok"
            return f"[EXTRACT] quality {icon}: {st} ({issues} issues)"

        if etype == "extraction_package_built":
            entities = payload.get("entities_count", 0)
            paper = payload.get("paper_key", "")[:8]
            return f"[EXTRACT] {paper} package: {entities} entities"

        if etype == "db_persist_finished":
            pid = payload.get("paper_id", "?")
            written = payload.get("entities_written", 0)
            return f"[PERSIST] {pid}: {written} entities written"

        if etype == "llm_call_finished":
            model = payload.get("model", "?")
            tokens = payload.get("token_usage", {}).get("total_tokens", "?")
            lat = event.get("duration_ms")
            lat_str = f" {lat:.0f}ms" if lat else ""
            return f"[{label}] LLM {model} {tokens}tok{lat_str}"

        if etype == "tool_call_finished":
            tool = payload.get("tool_name", "?")
            ms = event.get("duration_ms")
            ms_str = f" {ms:.0f}ms" if ms else ""
            return f"[{label}] tool:{tool}{ms_str}"

        if status in ("failed", "error"):
            return f"[{label}] {etype} failed"

        return ""

    def _update_progress(self, event: dict) -> None:
        """Maintain a small progress snapshot for the live panel."""
        etype = event.get("event_type", "")
        payload = event.get("payload", {}) or {}
        state = self._progress.setdefault("screen_download", {})

        if etype == "screen_started":
            reason = payload.get("reason")
            if reason == "all_downloads_failed":
                state["retry_attempt"] = payload.get("retry_attempt", 0)
                state["retry_wait_s"] = payload.get("wait_s", 0)
                return

            self._progress["screen_download"] = {
                "done": 0,
                "ok": 0,
                "failed": 0,
                "current_pmid": "",
                "last_failure_reason": "",
                "retry_attempt": 0,
                "retry_wait_s": 0,
            }
            return

        if etype == "download_attempt_started":
            state["current_pmid"] = payload.get("pmid") or ""
            return

        if etype == "pdf_download_finished" and payload.get("pmid"):
            state["done"] = int(state.get("done", 0)) + 1
            if payload.get("download_status") in ("downloaded", "already_exists"):
                state["ok"] = int(state.get("ok", 0)) + 1
                state["last_failure_reason"] = ""
            else:
                state["failed"] = int(state.get("failed", 0)) + 1
                state["last_failure_reason"] = payload.get("failure_reason") or ""
            state["current_pmid"] = ""
            return

        if etype == "screen_finished":
            state["done"] = payload.get("total_attempted", state.get("done", 0))
            state["ok"] = payload.get("downloaded_count", state.get("ok", 0))
