from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict


class PipelineState(TypedDict, total=False):
    """Shared state for the three business-agent LangGraph pipeline."""

    """
    total=False 表示所有字段均为可选，各 agent 只写自己产出的字段，
    graph 层按需读取，未写入的字段为 undefined（不是 None）。

    字段命名规范：
      <agent>_summary — 各 agent 的摘要文本（由 output_adapter 生成）
      候选/过滤结果字段 — 跨 agent 传递的核心数据
      run_metadata — 最后一次 run 的元数据（调试用）
    """

    # ── 基础字段 ──────────────────────────────────────────────────────────
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

    # ── Search Agent 产出 ─────────────────────────────────────────────────
    candidate_paper_ids: list[str]
    """检索到的候选文献 ID 列表（PubMed ID 或 DOI），由 search_agent 写入。"""
    candidates: list[dict[str, Any]]
    """候选文献的完整信息列表。"""

    search_summary: str
    """search_agent 的运行摘要（不超过 200 字），由 output_adapter 生成。"""

    # ── Screen Agent 产出 ─────────────────────────────────────────────────
    screened_paper_ids: list[str]
    """经相关性筛选后保留的文献 ID 列表，由 screen_agent 写入。"""
    selected_paper: dict[str, Any] | None
    """用户选择的目标论文。"""

    screen_summary: str
    """screen_agent 的运行摘要，由 output_adapter 生成。"""

    # ── Extract Agent 产出 ────────────────────────────────────────────────
    extracted_papers: list[dict]
    """成功抽取的论文结构化记录列表，由 extract_agent 写入。
    每条记录包含 paper 元数据和 fae_records。"""

    failed_papers: list[dict]
    """抽取失败的论文列表及错误原因，由 extract_agent 写入。"""

    extracted_record_ids: list[str]
    """成功抽取并写入数据库的记录 ID 列表，由 graph 层写入（基于 extracted_papers）。"""

    extraction: dict[str, Any] | None
    """抽取的完整结果数据。"""

    extract_summary: str
    """extract_agent 的运行摘要，由 output_adapter 生成。"""

    # ── Trace 关联 ────────────────────────────────────────────────────────
    run_metadata: dict[str, Any]
    """运行元数据（调试用）。"""

    result: dict[str, Any] | None
    """最终结果数据。"""


GraphState = PipelineState
PaperState = PipelineState

__all__ = ["GraphState", "PaperState", "PipelineState"]
