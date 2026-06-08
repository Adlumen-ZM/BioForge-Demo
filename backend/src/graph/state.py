from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict


class PipelineState(TypedDict, total=False):
    """Shared state for the three business-agent LangGraph pipeline."""

    agent_mode: str
    project_id: str
    run_id: str

    query: str
    user_query: str
    pdf_path: str
    pdf_name: str

    current_stage: str
    ok: bool
    message: str | None
    errors: list[dict[str, Any]]

    candidate_paper_ids: list[str]
    candidates: list[dict[str, Any]]
    search_summary: str

    screened_paper_ids: list[str]
    selected_paper: dict[str, Any] | None
    screen_summary: str

    extracted_record_ids: list[str]
    extract_summary: str
    extraction: dict[str, Any] | None

    run_metadata: dict[str, Any]
    result: dict[str, Any] | None


GraphState = PipelineState
PaperState = PipelineState

__all__ = ["GraphState", "PaperState", "PipelineState"]
