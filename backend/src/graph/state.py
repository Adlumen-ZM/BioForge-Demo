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

    # ── Guide Agent 产出（四步确认后产出）────────────────────────────────
    # 由 guide_agent 通过四步 interrupt 对话产出（Q1→Q2→Q3→Q4）

    # 旧字段（向后兼容保留，guide_agent v2 不再写入）
    task_description: str
    db_schema: dict
    inclusion_criteria: dict

    user_confirmed: bool
    """用户是否完成引导阶段所有确认，guide_agent 完成后设为 True。"""

    # 新字段（guide_agent v2 输出，供 search / screen / extract 读取）
    raw_user_prompt: str
    """用户原始任务描述（未经处理的自然语言输入）。"""

    raw_user_screening_rules: dict
    """用户原始纳排规则（easy 版本，不直接传入 pipeline）。"""

    refined_task_prompt: str
    """Guide Agent 规范化后的任务描述（供 search / extract 参考）。"""

    refined_screening_criteria: dict
    """Guide Agent 系统化纳排标准（{version, inclusion, exclusion, borderline_rules}），
    供 screen_agent 读取。"""

    schema_template: dict
    """固定数据库字段模板元数据（{template_id, schema_template_path, schema_file, filling_rules_file}），
    template_id 强制为 hap_peptide_v1，供 extract_agent 和写库层读取。"""

    guide_questions: list
    """四步确认记录（[{id, topic, confirmed}, ...]），用于审计和日志。"""

    guide_summary: str
    """Guide Agent 完成后的一句话摘要。"""

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
