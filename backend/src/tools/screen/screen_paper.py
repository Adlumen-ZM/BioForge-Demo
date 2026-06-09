"""
tools/screen/screen_paper.py — 文献相关性筛选工具

接收候选文献 PMID 列表，自动从 PubMed 获取标题/摘要，
再用 BM25 算法对每篇文献与筛选标准的相关度打分，输出通过筛选的 PMID 列表。

v0.2 变更：输入从 papers: list[dict] 改为 paper_ids: list[str]，
工具内部自动调用 PubMed efetch 获取元数据，LLM 只需传 PMID 列表。

依赖：rank-bm25（纯 Python，零模型下载）、biopython（已在 pubmed_search 中使用）
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

    paper_ids: list[str] = Field(
        description=(
            "候选文献的 PMID 列表。工具会自动从 PubMed 获取标题和摘要用于筛选。"
            "示例：['34265844', '38360817', '29145155']"
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


# ── BM25 筛选核心逻辑 ──


def _screen_with_bm25(
    papers: list[dict[str, Any]],
    criteria: str,
    threshold: float,
) -> dict[str, Any]:
    """对已获取元数据的文献列表执行 BM25 筛选，返回结果 dict。"""
    n = len(papers)

    if n == 0:
        return {
            "screened_paper_ids": [],
            "screened_count": 0,
            "excluded": [],
            "screen_summary": "无候选文献可供筛选。",
        }

    # BM25 需要至少 2 篇；单篇直接保留
    if n == 1:
        pmid = str(papers[0].get("pmid", "")).strip()
        return {
            "screened_paper_ids": [pmid],
            "screened_count": 1,
            "excluded": [],
            "screen_summary": "仅 1 篇候选文献，默认保留。",
        }

    # ── 构建文献文本并 BM25 打分 ──
    paper_texts = [
        f"{p.get('title', '')} {p.get('abstract', '')[:1000]}"
        for p in papers
    ]
    tokenized_docs = [_tokenize(t) for t in paper_texts]

    try:
        bm25 = BM25Okapi(tokenized_docs)
        query_tokens = _tokenize(criteria)
        scores = bm25.get_scores(query_tokens)
    except Exception:
        # BM25 初始化异常时保留全部文献
        all_pmids = [str(p.get("pmid", "")).strip() for p in papers]
        return {
            "screened_paper_ids": all_pmids,
            "screened_count": len(all_pmids),
            "excluded": [],
            "screen_summary": f"相关度计算异常，{n} 篇候选文献全部保留。",
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

    # 兜底：若全部低于阈值，保留得分最高的 5 篇（防止 step 因空结果失败）
    if not screened:
        top_k = min(5, n)
        top_indices = sorted(range(n), key=lambda idx: -float(scores[idx]))[:top_k]
        screened = [str(papers[idx].get("pmid", "")).strip() for idx in top_indices]
        excluded = []
        summary = (
            f"所有文献相关度低于阈值 {threshold}，保留得分最高的 {len(screened)} 篇。"
        )
    else:
        summary = (
            f"根据标准「{criteria[:80]}...」筛选 {n} 篇文献，"
            f"相关 {len(screened)} 篇，排除 {len(excluded)} 篇。"
        )

    return {
        "screened_paper_ids": screened,
        "screened_count": len(screened),
        "excluded": excluded,
        "screen_summary": summary,
    }


# ── 工具函数 ──


@tool(args_schema=ScreenPaperInput)
def screen_paper(
    paper_ids: list[str],
    criteria: str,
    threshold: float = 1.0,
) -> dict[str, Any]:
    """根据筛选标准，从候选文献 PMID 列表中筛选出相关文献。

    何时调用：当获得候选文献 PMID 列表（candidate_paper_ids）后，
    需要根据筛选标准判断哪些文献与研究主题相关时调用。

    工具会自动从 PubMed 获取每篇文献的标题和摘要，无需调用方预先获取。

    返回：筛选后的 PMID 列表、每篇判定结果、筛选摘要。
    """
    if not paper_ids:
        return {
            "screened_paper_ids": [],
            "screened_count": 0,
            "excluded": [],
            "screen_summary": "未传入候选文献 PMID 列表。",
        }

    # ── 从 PubMed 批量获取元数据（title / abstract）──
    try:
        from backend.src.tools.search.pubmed_search import _fetch_metadata, _setup_entrez
        _setup_entrez(None, None)
        papers = _fetch_metadata(paper_ids)
    except Exception as e:
        # 网络或导入异常时保留全部 PMID
        return {
            "screened_paper_ids": list(paper_ids),
            "screened_count": len(paper_ids),
            "excluded": [],
            "screen_summary": (
                f"无法从 PubMed 获取文献元数据（{e}），"
                f"保留全部 {len(paper_ids)} 篇候选文献。"
            ),
        }

    if not papers:
        # efetch 返回空（可能 PMID 无效或网络问题）
        return {
            "screened_paper_ids": list(paper_ids),
            "screened_count": len(paper_ids),
            "excluded": [],
            "screen_summary": f"无法获取文献元数据，保留全部 {len(paper_ids)} 篇候选文献。",
        }

    return _screen_with_bm25(papers, criteria, threshold)
