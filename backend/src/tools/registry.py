"""
tools/registry.py — 工具统一注册表

位置：全局，被 executor.py 通过 get_tools(names) 调用。
职责：按名称查找并返回 @tool 函数列表，供各 agent step 的 create_react_agent 使用。

接入规范（tools 负责人参考）：
  1. 在 backend/src/tools/<module>/ 下创建 .py 文件。
  2. 用 @tool 装饰器定义工具函数（来自 langchain_core.tools）。
  3. 将函数对象注册到本文件的 _REGISTRY dict（使用条件导入 guard block）。
  4. executor.py 调用 get_tools(["tool_name"]) 即可获取。
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import tool

# ─────────────────────────────────────────────
# PubMed 检索工具（真实 Biopython Entrez 实现）
# ─────────────────────────────────────────────
try:
    from backend.src.tools.search.pubmed_search import pubmed_search as _real_pubmed_search
    _PUBMED_SEARCH_LOADED = True
except ImportError:
    _PUBMED_SEARCH_LOADED = False
    _real_pubmed_search = None  # type: ignore

# ─────────────────────────────────────────────
# screen_paper 工具（BM25 实现）
# ─────────────────────────────────────────────
try:
    from backend.src.tools.screen.screen_paper import screen_paper as _real_screen_paper
    _SCREEN_PAPER_LOADED = True
except ImportError:
    _SCREEN_PAPER_LOADED = False
    _real_screen_paper = None  # type: ignore

# ─────────────────────────────────────────────
# download_paper：real/demo 模式加载真实版，其余模式加载 mock 版。
# download_paper.py 内部已将 metapub/paperscraper 改为延迟导入，
# 缺少 unidecode 等间接依赖时模块仍可加载，工具在调用阶段才失败（返回 download_status=failed）。
# ─────────────────────────────────────────────
_agent_mode = os.getenv(“GRAPH_AGENT_MODE”, “demo”).lower()
_DOWNLOAD_PAPER_LOADED = False
_download_paper_tool = None  # type: ignore
try:
    if _agent_mode in (“real”, “demo”):
        from backend.src.tools.screen.download_paper import download_paper as _download_paper_tool
    else:
        from backend.src.tools.screen.download_paper_mock import download_paper as _download_paper_tool
    _DOWNLOAD_PAPER_LOADED = True
except ImportError as _dp_import_err:
    # download_paper.py 本身的基础依赖（如 biopython/langchain-core）缺失；极少见
    import warnings as _warnings
    _warnings.warn(
        f”[tools.registry] download_paper 加载失败（{_dp_import_err}）；”
        “请确认容器内已安装 biopython 和 langchain-core。”,
        stacklevel=2,
    )
    _DOWNLOAD_PAPER_LOADED = False
    _download_paper_tool = None  # type: ignore

# ─────────────────────────────────────────────
# 新 RAG 工具（主流程，extract_agent 使用）
# ─────────────────────────────────────────────
try:
    from backend.src.tools.rag_paper.tools import (
        run_bio_paper_extraction_pipeline,
        parse_pdf_with_ragflow,
        retrieve_pdf_evidence,
    )
    _RAG_PAPER_TOOLS_LOADED = True
except ImportError:
    _RAG_PAPER_TOOLS_LOADED = False
    run_bio_paper_extraction_pipeline = parse_pdf_with_ragflow = retrieve_pdf_evidence = None  # type: ignore

# ─────────────────────────────────────────────
# 旧 RAG tools（rag/as_tool.py — legacy，不再注册到主流程）
# ─────────────────────────────────────────────
# try:
#     from rag.as_tool import chunk_document, build_rag_index, retrieve_chunks, reset_rag_state
# except ImportError:
#     pass

# ─────────────────────────────────────────────
# test_agent 专属 mock tools（物理隔离在 tools/test_agent/）
# ─────────────────────────────────────────────
try:
    from backend.src.tools.test_agent.mock_success import mock_success
    from backend.src.tools.test_agent.mock_fail import mock_fail
    from backend.src.tools.test_agent.mock_slow import mock_slow
    from backend.src.tools.test_agent.mock_flaky import mock_flaky
    from backend.src.tools.test_agent.mock_rich_output import mock_rich_output
    from backend.src.tools.test_agent.mock_literature_search import mock_literature_search
    from backend.src.tools.test_agent.mock_fetch_details import mock_fetch_details
    from backend.src.tools.test_agent.mock_binding_analysis import mock_binding_analysis
    from backend.src.tools.test_agent.mock_generate_report import mock_generate_report
    _TEST_TOOLS_LOADED = True
except ImportError:
    _TEST_TOOLS_LOADED = False
    mock_success = mock_fail = mock_slow = mock_flaky = mock_rich_output = None  # type: ignore
    mock_literature_search = mock_fetch_details = mock_binding_analysis = mock_generate_report = None  # type: ignore


# ─────────────────────────────────────────────
# Stub Tools（兜底用，真实版会覆盖）
# ─────────────────────────────────────────────

@tool
def pubmed_search(query: str, max_results: int = 20) -> dict[str, Any]:
    """PubMed 文献检索（stub 兜底）。真实版由 tools/search/pubmed_search.py 覆盖。"""
    stub_ids = [f"PMID{i:07d}" for i in range(1, min(max_results, 10) + 1)]
    return {
        "paper_ids":   stub_ids,
        "candidate_paper_ids": stub_ids,
        "total_found": len(stub_ids),
        "candidates":  [],
        "_stub":       True,
    }


@tool
def screen_paper(paper_id: str, criteria: str) -> dict[str, Any]:
    """文献相关性筛选（stub 兜底）。真实版由 tools/screen/screen_paper.py 覆盖。"""
    return {
        "paper_id": paper_id,
        "relevant": True,
        "reason":   "stub：默认相关",
        "_stub":    True,
    }


# ─────────────────────────────────────────────
# 注册表（name → tool 函数对象）
# ─────────────────────────────────────────────

_REGISTRY: dict[str, Any] = {
    # stub 兜底，下方条件块会覆盖为真实版
    "pubmed_search": pubmed_search,
    "screen_paper":  screen_paper,
}

# ── 真实 pubmed_search（Biopython Entrez）──
if _PUBMED_SEARCH_LOADED and _real_pubmed_search is not None:
    _REGISTRY["pubmed_search"] = _real_pubmed_search

# ── 真实 screen_paper（BM25）──
if _SCREEN_PAPER_LOADED and _real_screen_paper is not None:
    _REGISTRY["screen_paper"] = _real_screen_paper

# ── download_paper（real / mock 由 GRAPH_AGENT_MODE 决定）──
if _DOWNLOAD_PAPER_LOADED and _download_paper_tool is not None:
    _REGISTRY["download_paper"] = _download_paper_tool

# ── 新 RAG 工具（rag_paper，主流程使用）──
if _RAG_PAPER_TOOLS_LOADED:
    _REGISTRY.update({
        "run_bio_paper_extraction_pipeline": run_bio_paper_extraction_pipeline,
        "parse_pdf_with_ragflow":            parse_pdf_with_ragflow,
        "retrieve_pdf_evidence":             retrieve_pdf_evidence,
    })

# ── test_agent 专属 mock tools ──
if _TEST_TOOLS_LOADED:
    _REGISTRY.update({
        "mock_success":           mock_success,
        "mock_fail":              mock_fail,
        "mock_slow":              mock_slow,
        "mock_flaky":             mock_flaky,
        "mock_rich_output":       mock_rich_output,
        "mock_literature_search": mock_literature_search,
        "mock_fetch_details":     mock_fetch_details,
        "mock_binding_analysis":  mock_binding_analysis,
        "mock_generate_report":   mock_generate_report,
    })


def get_tools(names: list[str]) -> list:
    """按名称列表返回 tool 函数对象列表。

    未注册的名称会被跳过并打印警告，不抛异常（向前兼容）。
    """
    result = []
    for name in names:
        if name in _REGISTRY:
            result.append(_REGISTRY[name])
        else:
            print(f"[tools.registry] 警告：tool '{name}' 未在注册表中找到，已跳过。")
    return result


def register_tool(name: str, tool_fn: Any) -> None:
    """动态注册 tool（供测试或运行时扩展使用）。"""
    _REGISTRY[name] = tool_fn


def list_registered_tools() -> list[str]:
    """返回所有已注册 tool 的名称列表（调试用）。"""
    return list(_REGISTRY.keys())
