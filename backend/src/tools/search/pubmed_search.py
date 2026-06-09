# backend/src/tools/search/pubmed_search.py
"""
真实 PubMed 检索工具

使用 Biopython Entrez API 执行真实文献检索。
NCBI_EMAIL / NCBI_API_KEY 从环境变量读取。
"""

from __future__ import annotations

import os
import time
from typing import Any

from langchain_core.tools import tool

try:
    from Bio import Entrez, Medline
    _BIOPYTHON_AVAILABLE = True
except ImportError:
    _BIOPYTHON_AVAILABLE = False


def _setup_entrez(email: str | None, api_key: str | None) -> None:
    Entrez.email   = email   or os.getenv("NCBI_EMAIL",   "bioforge@example.com")
    Entrez.api_key = api_key or os.getenv("NCBI_API_KEY") or None


def _fetch_metadata(pmid_list: list[str]) -> list[dict[str, Any]]:
    """批量抓取 PubMed 摘要，返回结构化候选文献列表。"""
    if not pmid_list:
        return []

    # efetch 最多每次 200 条
    results: list[dict[str, Any]] = []
    batch_size = 200
    for i in range(0, len(pmid_list), batch_size):
        batch = pmid_list[i : i + batch_size]
        try:
            handle = Entrez.efetch(
                db="pubmed",
                id=",".join(batch),
                rettype="medline",
                retmode="text",
            )
            records = list(Medline.parse(handle))
            handle.close()
        except Exception:
            # 网络或解析异常时跳过本批次
            continue

        for rec in records:
            pmid = rec.get("PMID", "")
            # DOI 从 AID 字段提取
            doi  = None
            for aid in rec.get("AID", []):
                if aid.endswith("[doi]"):
                    doi = aid.replace(" [doi]", "").strip()
                    break

            authors = rec.get("AU", [])
            results.append({
                "pmid":             pmid,
                "doi":              doi,
                "title":            rec.get("TI", ""),
                "abstract":         rec.get("AB", ""),
                "journal_title":    rec.get("TA", "") or rec.get("JT", ""),
                "publication_year": _extract_year(rec.get("DP", "")),
                "authors":          authors,
                "source":           "pubmed",
            })

        if i + batch_size < len(pmid_list):
            time.sleep(0.35)  # NCBI 限速：有 API key 10 req/s，无 key 3 req/s

    return results


def _extract_year(dp: str) -> int | None:
    """从 PubMed DP 字段（如 '2023 Jan'）提取年份。"""
    if not dp:
        return None
    try:
        return int(dp.strip()[:4])
    except ValueError:
        return None


@tool
def pubmed_search(
    query: str,
    max_results: int = 100,
    email: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """在 PubMed 中检索生物医学文献并返回元数据。

    Args:
        query:       PubMed 检索式（支持 MeSH 术语和布尔运算符）。
        max_results: 最大返回文献数量（默认 100，上限 500）。
        email:       NCBI 账号邮箱；None 时读环境变量 NCBI_EMAIL。
        api_key:     NCBI API Key；None 时读环境变量 NCBI_API_KEY。

    Returns:
        {
          status:              "ok" / "error",
          query_used:          实际使用的检索式,
          total_found:         PubMed 命中总数,
          retrieved_count:     本次实际返回数,
          candidate_paper_ids: [pmid, ...],
          candidates:          [{pmid, doi, title, abstract, journal_title,
                                  publication_year, authors, source}, ...],
        }
    """
    if not _BIOPYTHON_AVAILABLE:
        return {
            "status":  "error",
            "error":   "Biopython 未安装，请运行 pip install biopython",
            "_stub":   False,
        }

    max_results = min(max_results, 500)
    _setup_entrez(email, api_key)

    try:
        # 1. esearch：拿 PMID 列表
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results)
        search_result = Entrez.read(handle)
        handle.close()

        total_found  = int(search_result.get("Count", 0))
        pmid_list    = list(search_result.get("IdList", []))

        # 2. efetch：拿元数据
        candidates = _fetch_metadata(pmid_list)

        return {
            "status":              "ok",
            "query_used":          query,
            "total_found":         total_found,
            "retrieved_count":     len(candidates),
            "candidate_paper_ids": [c["pmid"] for c in candidates],
            "candidates":          candidates,
        }

    except Exception as e:
        return {
            "status": "error",
            "error":  str(e),
            "query_used": query,
            "total_found": 0,
            "retrieved_count": 0,
            "candidate_paper_ids": [],
            "candidates": [],
        }
