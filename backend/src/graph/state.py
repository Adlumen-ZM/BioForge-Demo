"""
state.py — LangGraph 流水线状态定义

位置：graph 层，被 graph/pipeline.py 中的 StateGraph 和各 agent 的 output_adapter 使用。
职责：定义 PipelineState TypedDict，是三个 agent（search/screen/extract）之间
     传递结构化结果的唯一通道。

设计原则：
  - 只传轻量结构化结果 + 压缩摘要，不传完整 ReAct messages 历史。
  - 各 agent 的 output_adapter 生成 patch dict，graph node 负责 merge 进此 state。
  - 字段按 agent 阶段分组，便于各阶段 agent 读写对应字段。

扩展点：
  - 新增 agent 阶段时，在对应分组下添加新字段即可。
  - 需要更复杂的 state 合并策略（如 list append 而非覆盖），
    可改用 LangGraph Annotated + operator.add 装饰器。
"""

from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict


class PipelineState(TypedDict, total=False):
    """BioForge 三段式流水线的共享状态。

    total=False 表示所有字段均为可选，各 agent 只写自己产出的字段，
    graph 层按需读取，未写入的字段为 undefined（不是 None）。

    字段命名规范：
      <agent>_summary — 各 agent 的摘要文本（由 output_adapter 生成）
      候选/过滤结果字段 — 跨 agent 传递的核心数据
      run_metadata — 最后一次 run 的元数据（调试用）
    """

    # ── Search Agent 产出 ─────────────────────────────────────────────────
    candidate_paper_ids: list[str]
    """检索到的候选文献 ID 列表（PubMed ID 或 DOI），由 search_agent 写入。"""

    search_summary: str
    """search_agent 的运行摘要（不超过 200 字），由 output_adapter 生成。"""

    # ── Screen Agent 产出 ─────────────────────────────────────────────────
    screened_paper_ids: list[str]
    """经相关性筛选后保留的文献 ID 列表，由 screen_agent 写入。"""

    screen_summary: str
    """screen_agent 的运行摘要，由 output_adapter 生成。"""

    # ── Extract Agent 产出 ────────────────────────────────────────────────
    extracted_record_ids: list[str]
    """成功抽取并写入数据库的记录 ID 列表，由 extract_agent 写入。"""

    extract_summary: str
    """extract_agent 的运行摘要，由 output_adapter 生成。"""

    # ── 通用元数据 ────────────────────────────────────────────────────────
    run_metadata: dict[str, Any]
    """最后一次 agent run 的元数据（run_id / agent_name / status / step_count），
    主要用于调试和日志关联，graph 层不依赖此字段做决策。"""
