"""
backend/src/tools/test_agent/mock_literature_search.py — 分页文献检索 mock 工具

位置：backend/src/tools/test_agent/
依赖：langchain_core.tools、uuid（标准库）
职责：模拟带分页的文献数据库检索。

设计意图（多轮轮询测试）：
  首次调用返回第一批论文 + has_more=True + search_session_id。
  LLM 看到 has_more=True 后会自然决定带 session_id 继续调用，无需 instruction 显式说明。
  第二次调用返回第二批 + has_more=True。
  第三次调用返回最后一批 + has_more=False + search_complete=True。

  整个 step 内 LLM 将进行 3 次工具调用，充分体现 ReAct 多轮轮询能力。

主题：肽段-羟基磷灰石（HAp）结合相互作用（与 BioForge 业务主题一致）。

状态管理：
  模块级 _SEARCH_SESSIONS dict 记录每个 session 已经返回到第几批。
  session_id 由 UUID 生成，跨 run 不冲突，无需 reset。
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.tools import tool

# ── 模块级状态（session_id → 已返回批次数）──────────────────────────────────
# UUID 生成的 session_id 跨 run 不会冲突，无需 reset 函数。
_SEARCH_SESSIONS: dict[str, int] = {}

# ── 预设论文数据集（分 3 批，共 14 篇，模拟真实检索结果）───────────────────
_ALL_PAPERS = [
    # Batch 0（首批，5 篇，2023-2024 高引）
    [
        {"pmid": "38291001", "title": "Phosphoserine-rich peptides nucleate hydroxyapatite with nanoscale precision", "journal": "Biomaterials", "year": 2024, "citations": 41},
        {"pmid": "38156234", "title": "Biomimetic mineralization: designed peptide templates control HAp polymorph", "journal": "ACS Biomater. Sci. Eng.", "year": 2023, "citations": 28},
        {"pmid": "37982145", "title": "Statherin N-terminal domain pSer-pSer controls enamel crystal elongation", "journal": "J. Dent. Res.", "year": 2023, "citations": 35},
        {"pmid": "37834291", "title": "DMP1 acidic serine-aspartate-rich peptide promotes dentin remineralization", "journal": "Acta Biomater.", "year": 2023, "citations": 22},
        {"pmid": "37712089", "title": "Acidic cluster peptides selectively bind calcium-deficient apatite", "journal": "Langmuir", "year": 2023, "citations": 19},
    ],
    # Batch 1（第二批，5 篇，2021-2022）
    [
        {"pmid": "37601234", "title": "SAAS peptide mineralization kinetics studied by in-situ SAXS", "journal": "CrystEngComm", "year": 2022, "citations": 15},
        {"pmid": "37445678", "title": "Poly-glutamate sequences in amelogenin modulate enamel matrix assembly", "journal": "J. Struct. Biol.", "year": 2022, "citations": 31},
        {"pmid": "37289012", "title": "RGD-functionalized HAp scaffolds for bone regeneration", "journal": "Biomaterials", "year": 2021, "citations": 88},
        {"pmid": "37132456", "title": "Osteopontin phosphopeptide binding affinity measured by SPR", "journal": "FEBS Lett.", "year": 2021, "citations": 24},
        {"pmid": "36975890", "title": "Charged peptide sequences control hydroxyapatite crystal morphology", "journal": "Cryst. Growth Des.", "year": 2021, "citations": 17},
    ],
    # Batch 2（第三批，4 篇，2020）
    [
        {"pmid": "36819234", "title": "Amelogenin phosphorylation state determines HAp binding specificity", "journal": "J. Biol. Chem.", "year": 2020, "citations": 43},
        {"pmid": "36662578", "title": "Peptide-mediated calcium phosphate polymorph selection: OCP vs HAp", "journal": "Nanoscale", "year": 2020, "citations": 29},
        {"pmid": "36506012", "title": "Molecular dynamics of peptide-mineral interfaces: free energy landscape", "journal": "J. Chem. Theory Comput.", "year": 2020, "citations": 56},
        {"pmid": "36349456", "title": "HAp nanocrystal surface chemistry governs peptide adsorption selectivity", "journal": "ACS Nano", "year": 2020, "citations": 72},
    ],
]


@tool
def mock_literature_search(query: str, search_session_id: str = "") -> dict[str, Any]:
    """在 HAp 结合肽数据库中检索相关文献，支持分页获取全部结果。

    首次调用（不传 search_session_id）返回第一批论文和新的 search_session_id。
    后续调用需传入相同的 search_session_id 以继续获取下一批。
    当返回 has_more=false 时表示已检索完毕，无需再次调用。

    Args:
        query: 检索关键词或主题描述（自然语言）。
        search_session_id: 分页会话 ID。首次调用时留空，后续调用传入上次返回的值。

    Returns:
        dict，包含当前批次论文、分页状态（has_more）和会话 ID。
        最后一批额外包含 search_complete=True 和 all_pmids 汇总。
    """
    is_new_session = not search_session_id or search_session_id not in _SEARCH_SESSIONS

    if is_new_session:
        # ── 新检索：分配 session，返回第一批 ─────────────────────────────────
        session_id = f"srch_{uuid.uuid4().hex[:8]}"
        _SEARCH_SESSIONS[session_id] = 0  # 标记已返回第 0 批（即将返回）
        batch = _ALL_PAPERS[0]
        return {
            "search_session_id": session_id,
            "papers_this_batch": batch,
            "batch_number": 1,
            "retrieved_so_far": len(batch),
            "total_available": 14,
            "has_more": True,
            "note": f"已返回第1批共{len(batch)}篇，还有更多结果。请将 search_session_id 传入下次调用继续获取。",
        }

    # ── 继续已有 session：返回下一批 ─────────────────────────────────────────
    batch_idx = _SEARCH_SESSIONS[search_session_id] + 1
    _SEARCH_SESSIONS[search_session_id] = batch_idx

    if batch_idx == 1:
        # 第二批
        batch = _ALL_PAPERS[1]
        retrieved = 5 + len(batch)
        return {
            "search_session_id": search_session_id,
            "papers_this_batch": batch,
            "batch_number": 2,
            "retrieved_so_far": retrieved,
            "total_available": 14,
            "has_more": True,
            "note": f"已返回第2批共{len(batch)}篇，累计{retrieved}篇，仍有更多。请继续传入 search_session_id。",
        }
    else:
        # 第三批（最后一批）
        batch = _ALL_PAPERS[2]
        all_pmids = [p["pmid"] for papers in _ALL_PAPERS for p in papers]
        return {
            "search_session_id": search_session_id,
            "papers_this_batch": batch,
            "batch_number": 3,
            "retrieved_so_far": 14,
            "total_available": 14,
            "has_more": False,
            "search_complete": True,
            "all_pmids": all_pmids,
            "note": "检索完成，已获取全部14篇论文。",
        }
