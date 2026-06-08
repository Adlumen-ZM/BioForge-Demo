"""
tools/registry.py — 工具统一注册表

位置：全局，被 executor.py 通过 get_tools(names) 调用。
职责：按名称查找并返回 @tool 函数列表，供各 agent step 的 create_react_agent 使用。

v0.1 现状：
  - get_tools() 为 mock 实现，返回内置的 stub tool 列表。
  - 内置 stub：pubmed_search（返回假文献 ID，不发真实网络请求）。
  - tools 负责人实现真实工具后，只需在 _REGISTRY dict 中注册即可，
    executor.py 和各 agent 代码零改动。

接入规范（tools 负责人参考）：
  1. 在 backend/src/tools/shared/ 或 backend/src/tools/<agent_name>/ 下创建 .py 文件。
  2. 用 @tool 装饰器定义工具函数（来自 langchain_core.tools）。
  3. 将函数对象注册到本文件的 _REGISTRY dict：
       from backend.src.tools.shared.pubmed_search import pubmed_search_tool
       _REGISTRY["pubmed_search"] = pubmed_search_tool
  4. executor.py 调用 get_tools(["pubmed_search"]) 即可获取。

扩展点：
  - 需要懒加载（工具较重时）：改为 _REGISTRY 存储工厂函数，get_tools 时实例化。
  - 需要权限控制：get_tools 增加 agent_name 参数，按 agent 白名单过滤。
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import tool

# ─────────────────────────────────────────────
# 业务 tools（真实实现）
# ─────────────────────────────────────────────
try:
    from backend.src.tools.screen.screen_paper import screen_paper as _real_screen_paper
    _SCREEN_PAPER_LOADED = True
except ImportError:
    _SCREEN_PAPER_LOADED = False
    _real_screen_paper = None  # type: ignore

# download_paper：根据 GRAPH_AGENT_MODE 决定加载真实版还是 mock 版
_agent_mode = os.getenv("GRAPH_AGENT_MODE", "demo").lower()
try:
    if _agent_mode in ("real",):
        from backend.src.tools.screen.download_paper import download_paper as _download_paper_tool
    else:
        from backend.src.tools.screen.download_paper_mock import download_paper as _download_paper_tool
    _DOWNLOAD_PAPER_LOADED = True
except ImportError:
    _DOWNLOAD_PAPER_LOADED = False
    _download_paper_tool = None  # type: ignore

# ─────────────────────────────────────────────
# RAG tools（由 rag/as_tool.py 提供，extract_agent 使用）
# ─────────────────────────────────────────────
try:
    from rag.as_tool import chunk_document, build_rag_index, retrieve_chunks, reset_rag_state
    _RAG_TOOLS_LOADED = True
except ImportError:
    _RAG_TOOLS_LOADED = False
    chunk_document = build_rag_index = retrieve_chunks = reset_rag_state = None  # type: ignore

# ─────────────────────────────────────────────
# test_agent 专属 mock tools（懒加载，避免循环依赖）
# 物理隔离在 tools/test_agent/，禁止出现在业务 agent 的 plan.yaml 中。
# ─────────────────────────────────────────────
try:
    from backend.src.tools.test_agent.mock_success import mock_success
    from backend.src.tools.test_agent.mock_fail import mock_fail
    from backend.src.tools.test_agent.mock_slow import mock_slow
    from backend.src.tools.test_agent.mock_flaky import mock_flaky
    from backend.src.tools.test_agent.mock_rich_output import mock_rich_output
    # plan_deep_analysis 专属工具（多轮轮询 + validate_plan 失败测试）
    from backend.src.tools.test_agent.mock_literature_search import mock_literature_search
    from backend.src.tools.test_agent.mock_fetch_details import mock_fetch_details
    from backend.src.tools.test_agent.mock_binding_analysis import mock_binding_analysis
    from backend.src.tools.test_agent.mock_generate_report import mock_generate_report
    _TEST_TOOLS_LOADED = True
except ImportError:
    # 单元测试环境若缺少依赖，mock tools 跳过注册不报错
    _TEST_TOOLS_LOADED = False
    mock_success = mock_fail = mock_slow = mock_flaky = mock_rich_output = None  # type: ignore
    mock_literature_search = mock_fetch_details = mock_binding_analysis = mock_generate_report = None  # type: ignore


# ─────────────────────────────────────────────
# Stub Tools（v0.1 mock，不发真实网络请求）
# ─────────────────────────────────────────────

@tool
def pubmed_search(query: str, max_results: int = 20) -> dict[str, Any]:
    """在 PubMed 中检索生物医学文献。

    Args:
        query: PubMed 检索式（支持 MeSH 术语和布尔运算符）。
        max_results: 最大返回文献数量（默认 20，上限 500）。

    Returns:
        dict，包含 'paper_ids'（list[str]）和 'total_found'（int）。

    注意：v0.1 为 stub 实现，返回固定的假数据。
    真实实现请在 backend/src/tools/shared/pubmed_search.py 中接入 metapub 或 Entrez API。
    """
    # TODO(tools负责人): 替换为真实 PubMed API 调用
    stub_ids = [f"PMID{i:07d}" for i in range(1, min(max_results, 10) + 1)]
    return {
        "paper_ids": stub_ids,
        "total_found": len(stub_ids),
        "_stub": True,
    }


@tool
def screen_paper(paper_id: str, criteria: str) -> dict[str, Any]:
    """根据相关性标准筛选单篇文献。

    Args:
        paper_id: 文献 ID（PubMed ID 或 DOI）。
        criteria: 筛选标准描述（自然语言）。

    Returns:
        dict，包含 'relevant'（bool）和 'reason'（str）。

    注意：v0.1 为 stub 实现，下方会被真实 BM25 实现覆盖。
    """
    return {
        "paper_id": paper_id,
        "relevant": True,
        "reason": "stub：默认相关",
        "_stub": True,
    }


# ─────────────────────────────────────────────
# 注册表（name → tool 函数对象）
# ─────────────────────────────────────────────

_REGISTRY: dict[str, Any] = {
    # ── stub tools（供测试和依赖缺失时兜底，下方条件块会覆盖为真实版）──
    "pubmed_search": pubmed_search,
    "screen_paper":  screen_paper,
}

# ── 真实 screen_paper（rank-bm25 实现，替换 stub）──
if _SCREEN_PAPER_LOADED and _real_screen_paper is not None:
    _REGISTRY["screen_paper"] = _real_screen_paper

# ── download_paper（real 模式加载真实版，其余模式加载 mock 版）──
if _DOWNLOAD_PAPER_LOADED and _download_paper_tool is not None:
    _REGISTRY["download_paper"] = _download_paper_tool

# ── RAG tools（extract_agent 的 RAGFlow 工具链，加载失败时跳过）──
if _RAG_TOOLS_LOADED:
    _REGISTRY.update({
        "chunk_document":  chunk_document,   # PDF → chunk 列表
        "build_rag_index": build_rag_index,  # 构建向量索引
        "retrieve_chunks": retrieve_chunks,  # 混合检索
        "reset_rag_state": reset_rag_state,  # 重置 RAG 状态
    })

# ── test_agent 专属 mock tools（若加载成功则注册）──
if _TEST_TOOLS_LOADED:
    _REGISTRY.update({
        "mock_success":     mock_success,
        "mock_fail":        mock_fail,
        "mock_slow":        mock_slow,
        "mock_flaky":       mock_flaky,
        "mock_rich_output": mock_rich_output,
        "mock_literature_search": mock_literature_search,
        "mock_fetch_details":     mock_fetch_details,
        "mock_binding_analysis":  mock_binding_analysis,
        "mock_generate_report":   mock_generate_report,
    })


def get_tools(names: list[str]) -> list:
    """按名称列表返回 tool 函数对象列表。

    Args:
        names: tool 名称列表（与 PlanStep.tools_required / AgentTemplateConfig.tools 对应）。

    Returns:
        list of @tool 函数，可直接传给 create_react_agent(tools=...)。
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
    """动态注册 tool（供测试或运行时扩展使用）。

    Args:
        name: tool 名称。
        tool_fn: @tool 装饰的函数对象。
    """
    _REGISTRY[name] = tool_fn


def list_registered_tools() -> list[str]:
    """返回所有已注册 tool 的名称列表（调试用）。"""
    return list(_REGISTRY.keys())
