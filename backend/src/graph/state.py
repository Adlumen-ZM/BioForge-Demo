"""
state.py — BioForge LangGraph 流水线共享状态

位置：backend/src/graph/
职责：定义 PipelineState TypedDict，是 guide/search/screen/extract
     四个 agent 之间传递结构化结果的唯一通道。
"""

from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict


class PipelineState(TypedDict, total=False):
    """BioForge 四段式流水线的共享状态（guide → search → screen → extract）。"""

    # ── 通用运行标识 ──────────────────────────────────────────────────────
    agent_mode: str
    """运行模式（"mock" / "real"），由 CLI 写入，各节点读取。"""

    project_id: str
    run_id: str
    """pipeline 级别 run_id（格式 "pipe_<hex12>"），trace 事件共享此 ID。"""

    # ── 输入字段 ──────────────────────────────────────────────────────────
    query: str
    user_query: str
    pdf_path: str
    pdf_name: str

    # ── Guide Agent 产出（三件核心物）────────────────────────────────────
    # 由 guide_agent 通过三步 interrupt 对话产出，search/screen/extract 均可读取
    task_description: str
    """引导员产出的自然语言任务描述（3-5 句话），供 pipeline 各阶段参考。
    由 guide_agent 在第一个 interrupt 确认后写入。"""

    db_schema: dict
    """引导员产出的数据库字段模板（字段名 → {type, description, example}）。
    由 guide_agent 在第二个 interrupt 确认后写入，extract_agent 据此决定抽取字段。"""

    inclusion_criteria: dict
    """引导员产出的文献准入/排除标准（{inclusion: list, exclusion: list}）。
    由 guide_agent 在第三个 interrupt 确认后写入，screen_agent 据此筛选。"""

    user_confirmed: bool
    """用户是否完成引导阶段所有三步确认，guide_agent 完成后设为 True。"""

    # ── 流水线状态 ────────────────────────────────────────────────────────
    current_stage: str
    """当前所处阶段（"init" / "search" / "screen" / "extract" / "done" / "error"）。"""

    ok: bool
    message: str | None
    errors: list[dict[str, Any]]

    # ── Search Agent 产出 ─────────────────────────────────────────────────
    candidate_paper_ids: list[str]
    """检索到的候选文献 ID 列表（PubMed ID 或 DOI）。"""

    candidates: list[dict[str, Any]]
    """候选文献的元数据列表（title/abstract/doi 等），由 search_agent 写入。"""

    search_summary: str

    # ── Screen Agent 产出 ─────────────────────────────────────────────────
    screened_paper_ids: list[str]
    selected_paper: dict[str, Any] | None
    """当前选中处理的单篇文献（screen_agent 写入，extract_agent 读取）。"""

    screen_summary: str

    # ── Extract Agent 产出 ────────────────────────────────────────────────
    extracted_record_ids: list[str]
    extract_summary: str
    extraction: dict[str, Any] | None
    """单篇文献的结构化抽取结果。"""

    result: dict[str, Any] | None

    # ── 通用元数据 ────────────────────────────────────────────────────────
    run_metadata: dict[str, Any]
    """最后一次 agent run 的元数据，主要用于调试和日志关联。"""


GraphState = PipelineState
PaperState = PipelineState

__all__ = ["GraphState", "PaperState", "PipelineState"]
