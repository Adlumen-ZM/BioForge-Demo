"""
tools/screen/screen_paper.py — 文献相关性筛选工具

根据给定的筛选标准（criteria），逐篇判断候选文献是否相关。
v0.1：基于标题/摘要与 criteria 的 BM25 相关度打分。

依赖：rank-bm25（纯 Python，零模型下载）
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi


# ── 分词函数 ──


def _tokenize(text: str) -> list[str]:
    """简单英文分词：lower + 去标点 + split。"""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return text.split()


# ── 输入 schema ──


class ScreenPaperInput(BaseModel):
    """screen_paper 工具的输入 schema。"""

    papers: list[dict[str, Any]] = Field(
        description=(
            "候选文献元数据列表，每条至少包含 pmid / title / abstract。"
            "示例：[{'pmid': '34265844', 'title': '...', 'abstract': '...'}, ...]"
        ),
    )
    criteria: str = Field(
        description=(
            "筛选标准描述（自然语言），说明什么样的文献应被视为相关。"
            "示例：'研究肽或蛋白质与羟基磷灰石(HAp)或磷酸钙相互作用的原创实验研究，"
            "不包含纯计算模拟或综述'"
        ),
    )
    threshold: float = Field(
        default=1.0,
        description="BM25 相关度阈值，低于此值视为不相关（默认 1.0）",
    )


# ── 工具函数 ──


@tool(args_schema=ScreenPaperInput)
def screen_paper(
    papers: list[dict[str, Any]],
    criteria: str,
    threshold: float = 0.1,
) -> dict[str, Any]:
    """根据筛选标准判断每篇候选文献的相关性。

    何时调用：当获得候选文献元数据（pmid / title / abstract）后，
    需要根据筛选标准判断哪些文献相关时调用。

    返回：筛选后的 PMID 列表、每篇判定结果、筛选摘要。
    """
    if not papers:
        return {
            "screened_paper_ids": [],
            "screened_count": 0,
            "excluded": [],
            "screen_summary": "无候选文献。",
        }

    # ── 构建文献文本并分词 ──
    paper_texts = [
        f"{p.get('title', '')} {p.get('abstract', '')[:1000]}"
        for p in papers
    ]
    tokenized_docs = [_tokenize(t) for t in paper_texts]

    # ── BM25 打分 ──
    # BM25 需要至少 2 篇文档才能计算有效的 IDF；单篇时直接保留
    n = len(papers)
    if n == 1:
        pmid = str(papers[0].get("pmid", "")).strip()
        return {
            "screened_paper_ids": [pmid],
            "screened_count": 1,
            "excluded": [],
            "screen_summary": "仅 1 篇候选文献，默认保留。",
        }

    try:
        bm25 = BM25Okapi(tokenized_docs)
        query_tokens = _tokenize(criteria)
        scores = bm25.get_scores(query_tokens)
    except Exception:
        return {
            "screened_paper_ids": [str(p.get("pmid", "")).strip() for p in papers],
            "screened_count": len(papers),
            "excluded": [],
            "screen_summary": f"无法计算相关度，{len(papers)} 篇全部保留。",
        }

    # ── 逐篇判定 ──
    screened: list[str] = []
    excluded: list[dict[str, Any]] = []

    for i, p in enumerate(papers):
        pmid = str(p.get("pmid", "")).strip()
        score = float(scores[i])
        if score >= threshold:
            screened.append(pmid)
        else:
            excluded.append({
                "pmid": pmid,
                "reason": f"文献内容与筛选标准不匹配（相关度 {score:.4f}）",
                "relevance": round(score, 4),
            })

    return {
        "screened_paper_ids": screened,
        "screened_count": len(screened),
        "excluded": excluded,
        "screen_summary": (
            f"根据标准「{criteria[:100]}...」筛选 {len(papers)} 篇文献，"
            f"相关 {len(screened)} 篇，排除 {len(excluded)} 篇。"
        ),
    }
