"""
event_types.py — Trace 事件类型常量

位置：backend/src/db_access/trace/
职责：集中定义所有事件名常量，避免字符串散落各模块。

与现有 hooks.py TraceEvent 的关系：
  hooks.py 使用 plan_start / step_start / step_end / plan_end 等框架级事件，
  这些仍然保留。本模块额外定义业务级事件和新增的 pipeline/node 级事件。

事件分组：
  Pipeline 级    — pipeline_started / pipeline_finished / pipeline_failed
  Node 级        — node_started / node_finished / node_failed
  Guide 级       — guide_started / guide_llm_called / guide_step_confirmed / guide_output_ready
  Search 业务    — search_query_built / search_results_collected / search_candidates_saved
  Screen 业务    — screen_decision_made / download_attempt_started / pdf_download_finished
  Extract 业务   — rag_extraction_started / rag_tool_called / rag_csv_generated /
                   csv_quality_checked / extraction_package_built
  Persist 业务   — db_persist_started / db_persist_finished / db_persist_failed
  LLM 调用       — llm_call_started / llm_call_finished / llm_call_failed / llm_output_parsed
  Tool 调用      — tool_call_started / tool_call_finished
"""


class TraceEventType:
    """Trace 事件类型常量集合。所有事件名均为小写下划线格式。"""

    # ── Pipeline 级 ──────────────────────────────────────────────────────────
    PIPELINE_STARTED  = "pipeline_started"
    PIPELINE_FINISHED = "pipeline_finished"
    PIPELINE_FAILED   = "pipeline_failed"

    # ── Node 级 ──────────────────────────────────────────────────────────────
    NODE_STARTED  = "node_started"
    NODE_FINISHED = "node_finished"
    NODE_FAILED   = "node_failed"

    # ── Guide 级（CLI 不显示，已由 interrupt 流处理）────────────────────────
    GUIDE_STARTED          = "guide_started"
    GUIDE_LLM_CALLED       = "guide_llm_called"
    GUIDE_STEP_CONFIRMED   = "guide_step_confirmed"
    GUIDE_OUTPUT_READY     = "guide_output_ready"

    # ── Search 业务事件 ───────────────────────────────────────────────────────
    SEARCH_QUERY_BUILT        = "search_query_built"
    SEARCH_TOOL_CALLED        = "search_tool_called"
    SEARCH_RESULTS_COLLECTED  = "search_results_collected"
    SEARCH_CANDIDATES_SAVED   = "search_candidates_saved"

    # ── Screen / Download 业务事件 ────────────────────────────────────────────
    SCREEN_DECISION_MADE      = "screen_decision_made"
    DOWNLOAD_ATTEMPT_STARTED  = "download_attempt_started"
    PDF_DOWNLOAD_FINISHED     = "pdf_download_finished"
    DOWNLOAD_REPORT_SAVED     = "download_report_saved"

    # ── Extract / RAG 业务事件 ────────────────────────────────────────────────
    RAG_EXTRACTION_STARTED    = "rag_extraction_started"
    RAG_TOOL_CALLED           = "rag_tool_called"
    RAG_CSV_GENERATED         = "rag_csv_generated"
    CSV_QUALITY_CHECKED       = "csv_quality_checked"
    EXTRACTION_PACKAGE_BUILT  = "extraction_package_built"
    VALIDATION_REPORT_SAVED   = "validation_report_saved"

    # ── Persist 业务事件 ──────────────────────────────────────────────────────
    DB_PERSIST_STARTED  = "db_persist_started"
    DB_PERSIST_FINISHED = "db_persist_finished"
    DB_PERSIST_FAILED   = "db_persist_failed"

    # ── LLM 调用事件 ──────────────────────────────────────────────────────────
    LLM_CALL_STARTED           = "llm_call_started"
    LLM_CALL_FINISHED          = "llm_call_finished"
    LLM_CALL_FAILED            = "llm_call_failed"
    LLM_OUTPUT_PARSED          = "llm_output_parsed"
    LLM_OUTPUT_VALIDATION_FAILED = "llm_output_validation_failed"

    # ── Tool 调用事件 ─────────────────────────────────────────────────────────
    TOOL_CALL_STARTED  = "tool_call_started"
    TOOL_CALL_FINISHED = "tool_call_finished"

    # ── 框架级事件（来自 hooks.py TraceHook，保持兼容）───────────────────────
    PLAN_START      = "plan_start"
    PLAN_END        = "plan_end"
    STEP_START      = "step_start"
    STEP_END        = "step_end"
    STEP_REPLANNED  = "step_replanned"


# 不在 CLI normal 级别显示的事件（guide 已由 interrupt 流显示，框架级事件太细）
CLI_QUIET_EVENTS = frozenset({
    TraceEventType.PIPELINE_STARTED,
    TraceEventType.PIPELINE_FINISHED,
    TraceEventType.PIPELINE_FAILED,
})

CLI_NORMAL_EVENTS = frozenset({
    TraceEventType.PIPELINE_STARTED,
    TraceEventType.PIPELINE_FINISHED,
    TraceEventType.PIPELINE_FAILED,
    TraceEventType.NODE_STARTED,
    TraceEventType.NODE_FINISHED,
    TraceEventType.SEARCH_QUERY_BUILT,
    TraceEventType.SEARCH_RESULTS_COLLECTED,
    TraceEventType.PDF_DOWNLOAD_FINISHED,
    TraceEventType.RAG_CSV_GENERATED,
    TraceEventType.CSV_QUALITY_CHECKED,
    TraceEventType.EXTRACTION_PACKAGE_BUILT,
    TraceEventType.DB_PERSIST_FINISHED,
})

CLI_DEBUG_EVENTS = CLI_NORMAL_EVENTS | frozenset({
    TraceEventType.LLM_CALL_FINISHED,
    TraceEventType.TOOL_CALL_FINISHED,
    TraceEventType.NODE_FAILED,
    TraceEventType.PLAN_END,
    TraceEventType.STEP_END,
})

# guide 事件：只写文件，不显示在 CLI（interrupt 流已处理）
GUIDE_ONLY_EVENTS = frozenset({
    TraceEventType.GUIDE_STARTED,
    TraceEventType.GUIDE_LLM_CALLED,
    TraceEventType.GUIDE_STEP_CONFIRMED,
    TraceEventType.GUIDE_OUTPUT_READY,
})
