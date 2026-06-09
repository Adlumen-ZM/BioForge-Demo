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
    """search_agent 的运行摘要（不超过 200 字），由 output_adapter 生成。"""

    # ── Screen Agent 产出 ─────────────────────────────────────────────────
    screened_paper_ids: list[str]
    """经相关性筛选后保留的文献 ID 列表，由 screen_agent 写入。"""

    selected_paper: dict[str, Any] | None
    """当前选中处理的单篇文献（screen_agent 写入，extract_agent 读取）。"""

    screen_summary: str
    """screen_agent 的运行摘要，由 output_adapter 生成。"""

    # ── Extract Agent 产出 ────────────────────────────────────────────────
    extracted_papers: list[dict]
    """成功抽取的论文结构化记录列表（含 paper 元数据和 fae_records），由 extract_agent 写入。"""

    failed_papers: list[dict]
    """抽取失败的论文列表及错误原因，由 extract_agent 写入。"""

    extracted_record_ids: list[str]
    """成功抽取并写入数据库的记录 ID 列表，由 graph 层写入（基于 extracted_papers）。"""

    extract_summary: str
    """extract_agent 的运行摘要，由 output_adapter 生成。"""

    extraction: dict[str, Any] | None
    """单篇文献的结构化抽取结果。"""

    result: dict[str, Any] | None
    """最终结果数据。"""

    # ── 文件资产与 PDF 下载（v0.1）────────────────────────────────────────
    paper_key: str | None
    """SHA256(doi/pmid/title)[:16]，文件路径唯一键。"""

    pdf_path: str | None
    """PDF 绝对路径（容器内），download 工具写入，extract 读取。"""

    download_status: str | None
    """下载状态：downloaded / already_exists / failed / skipped。"""

    file_sha256: str | None
    """PDF 文件内容 SHA-256 摘要，用于完整性校验和去重。"""

    # ── RAG / CSV 阶段（v0.1 预留）───────────────────────────────────────
    rag_csv_dir: str | None
    """RAG 解析输出的 CSV 文件夹路径。"""

    rag_csv_files: dict | None
    """各 CSV 文件元信息（{table_name: {path, rows, exists}}）。"""

    ragflow_ref: dict | None
    """RAGFlow 文档引用信息（{document_id, knowledge_base_id, ...}）。"""

    csv_quality_status: str | None
    """CSV 质量检查状态（pass / warning / fail）。"""

    csv_quality_issues: list[dict] | None
    """CSV 质量问题列表（[{field, issue, severity}]）。"""

    # ── 业务数据库初始化（v0.1）──────────────────────────────────────────
    extraction_profile: str | None
    """提取配置名，决定数据库路径分层（默认与 template_id 相同）。"""

    template_id: str | None
    """schema 模板 ID（如 hap_peptide_v1），供 init_db_node 和 write_db_node 读取。"""

    biz_db_path: str | None
    """业务 SQLite 数据库绝对路径，由 init_db_node 写入。"""

    biz_db_init_result: dict | None
    """数据库初始化结果（{status, tables_created, vocab_count, already_existed}）。"""

    # ── Search 多轮检索式（v0.1）─────────────────────────────────────────
    queries: list[dict] | None
    """Search Agent 构建的多条检索式（[{query_id, query_string, purpose}]）。"""

    # ── Screen 下载批结果（v0.1）──────────────────────────────────────────
    download_results: list[dict] | None
    """Screen Agent 每篇文献的下载结果列表（[{pmid, doi, paper_key, pdf_path, download_status}]）。"""

    # ── 模板路径（v0.1）──────────────────────────────────────────────────
    schema_template_path: str | None
    """schema.yaml 文件绝对路径，供 extract_agent 和 RAG 工具读取。"""

    # ── 写库阶段（v0.1 预留）─────────────────────────────────────────────
    extraction_package_path: str | None
    """打包后的 extraction JSON 路径（含 entities + metadata）。"""

    validation_report_path: str | None
    """数据库写入前的校验报告路径。"""

    db_write_result: dict | None
    """数据库写入结果（{paper_id, entities_written, status}）。"""

    # ── 通用元数据 ────────────────────────────────────────────────────────
    run_metadata: dict[str, Any]
    """最后一次 agent run 的元数据，主要用于调试和日志关联。"""

    # ── 新增：流水线最终状态 ──────────────────────────────────────────────
    status: str | None
    """流水线最终状态（由 finalize_node 写入）：
    success / no_candidates / no_pdf_downloaded / extraction_failed / db_write_failed / error。"""

    # ── 新增：运行时目录（由 _with_defaults 注入）────────────────────────
    trace_dir: str | None
    """trace 文件目录：data/runs/{run_id}/trace。"""

    artifacts_dir: str | None
    """artifact 文件目录：data/runs/{run_id}/artifacts。"""

    # ── 新增：finalize_node 输出路径 ─────────────────────────────────────
    summary_path: str | None
    """流水线摘要 JSON 路径：data/runs/{run_id}/trace/summary.json。"""

    timeline_path: str | None
    """流水线时间线 Markdown 路径：data/runs/{run_id}/trace/timeline.md。"""

    # ── 新增：search_node 扩展输出 ───────────────────────────────────────
    query_strings: list[str] | None
    """检索式扁平列表（从 queries 中提取 query_string 字段），供 trace/CLI 展示。"""

    search_artifact_path: str | None
    """search_candidates.json artifact 路径：data/runs/{run_id}/artifacts/search_candidates.json。"""

    # ── 新增：screen_node 扩展输出 ───────────────────────────────────────
    download_report_path: str | None
    """下载报告 artifact 路径：data/runs/{run_id}/artifacts/download_report.json。"""

    # ── 新增：prepare_extraction_context_node 输出 ───────────────────────
    rag_extraction_contract: dict | None
    """RAG 抽取合约（get_rag_extraction_contract() 返回值），包含 csv_tables/enum_groups。"""

    field_mapping_path: str | None
    """field_mapping.yaml 文件路径，供 RAG 工具按需读取。"""

    # ── 新增：版本与用户输入 ──────────────────────────────────────────────
    template_version: str | None
    """schema 模板版本（如 "v1"），由 guide_agent 或 CLI 入口写入。"""

    user_input: str | None
    """用户原始输入（run_demo_pipeline --topic 参数），与 user_query 等价，供 search_node 读取。"""


GraphState = PipelineState
PaperState = PipelineState

__all__ = ["GraphState", "PaperState", "PipelineState"]
