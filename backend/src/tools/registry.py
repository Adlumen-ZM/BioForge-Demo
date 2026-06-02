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

from typing import Any

from langchain_core.tools import tool


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
    # 示例真实实现：
    #   from metapub import PubMedFetcher
    #   fetch = PubMedFetcher()
    #   pmids = fetch.pmids_for_query(query, retmax=max_results)
    #   return {"paper_ids": pmids, "total_found": len(pmids)}
    stub_ids = [f"PMID{i:07d}" for i in range(1, min(max_results, 10) + 1)]
    return {
        "paper_ids": stub_ids,
        "total_found": len(stub_ids),
        "_stub": True,  # 标记为 stub，便于测试断言
    }


@tool
def screen_paper(paper_id: str, criteria: str) -> dict[str, Any]:
    """根据相关性标准筛选单篇文献。

    Args:
        paper_id: 文献 ID（PubMed ID 或 DOI）。
        criteria: 筛选标准描述（自然语言）。

    Returns:
        dict，包含 'relevant'（bool）和 'reason'（str）。

    注意：v0.1 为 stub 实现。
    """
    # TODO(tools负责人): 替换为真实摘要获取 + 相关性判断逻辑
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
    "pubmed_search": pubmed_search,
    "screen_paper": screen_paper,
}


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
