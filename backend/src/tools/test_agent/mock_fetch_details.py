"""
backend/src/tools/test_agent/mock_fetch_details.py — 异步论文详情获取 mock 工具

位置：backend/src/tools/test_agent/
依赖：langchain_core.tools、uuid（标准库）
职责：模拟异步批量获取论文详情的服务（提交任务→轮询进度→获取结果）。

设计意图（多轮轮询测试）：
  首次调用（不传 job_id）：提交任务，返回 job_id + status="submitted"。
  第二次调用（传 job_id）：返回 status="processing" + progress_pct=55。
  第三次调用（传同一 job_id）：返回 status="complete" + 完整论文详情数据。

  LLM 看到 status="submitted"/"processing" 会自然判断"任务未完成，需要继续轮询"，
  从而在 step 内进行 3 次工具调用。instruction 中不提"轮询"二字。

输出数据：
  包含真实感强的科研数据：摘要片段、关键词、实验测量的 Kd 值、引用计数等。
  让调试平台的输出展示有实际内容可看。

状态管理：
  _FETCH_JOBS dict 记录每个 job 已被查询次数。
  job_id 由 UUID 生成，跨 run 不冲突，无需 reset。
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.tools import tool

# ── 模块级状态（job_id → 查询次数）──────────────────────────────────────────
_FETCH_JOBS: dict[str, int] = {}

# ── 预设论文详情数据（对应 mock_literature_search 返回的前6篇高引论文）────────
_PAPER_DETAILS = [
    {
        "pmid": "38291001",
        "title": "Phosphoserine-rich peptides nucleate hydroxyapatite with nanoscale precision",
        "abstract": (
            "We investigated the role of phosphoserine (pSer) clustering in HAp nucleation using "
            "a series of synthetic peptides with 1-5 consecutive pSer residues. Isothermal titration "
            "calorimetry revealed dissociation constants (Kd) of 0.82 nM for the pSer3 motif, "
            "representing a 40-fold enhancement over non-phosphorylated controls. Cryo-TEM analysis "
            "confirmed template-directed nucleation along the peptide backbone."
        ),
        "keywords": ["hydroxyapatite", "phosphoserine", "nucleation", "ITC", "cryo-TEM"],
        "binding_affinity_kd_nm": 0.82,
        "experimental_method": "ITC + cryo-TEM + MD simulation",
        "key_peptide_sequence": "pSER-pSER-pSER-EEK",
        "citations": 41,
    },
    {
        "pmid": "37982145",
        "title": "Statherin N-terminal domain pSer-pSer controls enamel crystal elongation",
        "abstract": (
            "The N-terminal 15-residue segment of statherin (DpSpSEEKFLRRIGRFG) was studied "
            "using solid-state NMR on HAp single crystals. Binding was confirmed at the (100) "
            "face with Kd = 0.34 nM. Phosphorylation at Ser2 and Ser3 is essential; "
            "dephosphorylation reduces affinity 200-fold."
        ),
        "keywords": ["statherin", "ssNMR", "enamel", "crystal face selectivity"],
        "binding_affinity_kd_nm": 0.34,
        "experimental_method": "Solid-state NMR + SPR",
        "key_peptide_sequence": "DpSpSEEKFLRRIGRFG",
        "citations": 35,
    },
    {
        "pmid": "37132456",
        "title": "Osteopontin phosphopeptide binding affinity measured by SPR",
        "abstract": (
            "Surface plasmon resonance measurements of osteopontin-derived phosphopeptides "
            "on HAp sensor chips. The SVVYGLR-pSER sequence showed Kd = 1.12 nM with "
            "slow off-rate (koff = 3.2×10⁻⁴ s⁻¹), consistent with near-irreversible adsorption. "
            "Phosphorylation of the serine residue increased affinity 85-fold."
        ),
        "keywords": ["osteopontin", "SPR", "phosphopeptide", "adsorption kinetics"],
        "binding_affinity_kd_nm": 1.12,
        "experimental_method": "SPR (Biacore)",
        "key_peptide_sequence": "SVVYGLRpSER",
        "citations": 24,
    },
    {
        "pmid": "36819234",
        "title": "Amelogenin phosphorylation state determines HAp binding specificity",
        "abstract": (
            "Comparative study of phosphorylated and non-phosphorylated amelogenin on HAp, "
            "OCP, and DCPD surfaces. Phospho-amelogenin showed 12-fold selectivity for HAp over "
            "OCP (Kd_HAp = 2.1 nM vs Kd_OCP = 24.8 nM), suggesting a role in preventing "
            "undesirable calcium phosphate polymorph formation during enamel development."
        ),
        "keywords": ["amelogenin", "polymorph selectivity", "phosphorylation", "enamel development"],
        "binding_affinity_kd_nm": 2.1,
        "experimental_method": "QCM-D + AFM imaging",
        "key_peptide_sequence": "MPLPPHPGHPGYINFSYEVLTPLKWYQSIRPPYPSYGYEPMGGWLHHQIIPVLSQQHPPTHTLQPHHHIPVVPAQQPMPMPGQHHSMSPGNGQPYGQP",
        "citations": 43,
    },
    {
        "pmid": "36506012",
        "title": "Molecular dynamics of peptide-mineral interfaces: free energy landscape",
        "abstract": (
            "All-atom MD simulations of 12 HAp-binding peptides on (001) and (100) crystal faces "
            "using CHARMM36m force field with explicit solvent. Free energy perturbation calculations "
            "revealed that each pSer contributes -1.8 kcal/mol to binding ΔG. Glutamate clusters "
            "contribute -0.9 kcal/mol per residue via Ca²⁺-mediated bridging."
        ),
        "keywords": ["molecular dynamics", "free energy", "CHARMM", "crystal face"],
        "binding_affinity_kd_nm": None,  # computational, no direct Kd
        "experimental_method": "All-atom MD + FEP",
        "key_finding": "每个 pSer 贡献 -1.8 kcal/mol 结合自由能",
        "citations": 56,
    },
    {
        "pmid": "36349456",
        "title": "HAp nanocrystal surface chemistry governs peptide adsorption selectivity",
        "abstract": (
            "Systematic study of 24 synthetic peptides on stoichiometric and Ca-deficient HAp "
            "nanocrystals. Acidic peptides (net charge ≤ -4 at pH 7.4) showed Kd < 5 nM on "
            "stoichiometric HAp but 10-20× lower affinity on Ca-deficient surfaces. "
            "Basic peptides showed the reverse selectivity pattern."
        ),
        "keywords": ["surface chemistry", "Ca-deficient HAp", "adsorption selectivity", "net charge"],
        "binding_affinity_kd_nm": 1.87,
        "experimental_method": "Fluorescence quenching + ITC",
        "key_finding": "净电荷 ≤ -4（pH 7.4）是高亲和力结合的充分条件",
        "citations": 72,
    },
]


@tool
def mock_fetch_details(pmids: list | None = None, job_id: str = "") -> dict[str, Any]:
    """批量获取论文详情（摘要、实验方法、结合亲和力数据）。

    该服务为异步执行：首次调用提交任务，返回 job_id；
    后续使用 job_id 轮询进度，直到 status 变为 "complete" 后获取完整结果。

    Args:
        pmids: 论文 PMID 列表（首次调用时传入，后续轮询时可省略）。
        job_id: 异步任务 ID。首次调用时留空，后续轮询时必须传入。

    Returns:
        dict，包含 status 字段（"submitted" / "processing" / "complete"）。
        status="complete" 时包含完整论文详情列表和统计摘要。
    """
    is_new_job = not job_id or job_id not in _FETCH_JOBS

    if is_new_job:
        # ── 首次调用：提交任务 ────────────────────────────────────────────────
        new_job_id = f"job_{uuid.uuid4().hex[:8]}"
        _FETCH_JOBS[new_job_id] = 0
        paper_count = len(pmids) if pmids else 14
        return {
            "status": "submitted",
            "job_id": new_job_id,
            "queued_papers": paper_count,
            "estimated_seconds": 6,
            "message": (
                f"任务已提交，正在后台获取 {paper_count} 篇论文的详情数据。"
                "请用返回的 job_id 稍后查询进度。"
            ),
        }

    # ── 后续轮询：检查任务状态 ────────────────────────────────────────────────
    poll_count = _FETCH_JOBS[job_id]
    _FETCH_JOBS[job_id] = poll_count + 1

    if poll_count == 0:
        # 第一次轮询：处理中
        return {
            "status": "processing",
            "job_id": job_id,
            "progress_pct": 55,
            "completed_papers": 8,
            "total_papers": 14,
            "message": (
                "正在获取摘要和实验数据，已完成 8/14 篇。"
                "请继续使用相同 job_id 查询直到 status=complete。"
            ),
        }
    else:
        # 第二次或后续轮询：任务完成
        kd_values = [
            p["binding_affinity_kd_nm"]
            for p in _PAPER_DETAILS
            if p.get("binding_affinity_kd_nm") is not None
        ]
        mean_kd = round(sum(kd_values) / len(kd_values), 3) if kd_values else None

        return {
            "status": "complete",
            "job_id": job_id,
            "papers_with_details": _PAPER_DETAILS,
            "total_retrieved": len(_PAPER_DETAILS),
            "statistics": {
                "mean_binding_affinity_kd_nm": mean_kd,
                "min_kd_nm": min(kd_values) if kd_values else None,
                "max_kd_nm": max(kd_values) if kd_values else None,
                "papers_with_kd_data": len(kd_values),
                "total_citations": sum(p["citations"] for p in _PAPER_DETAILS),
                "experimental_methods_used": [
                    "ITC", "cryo-TEM", "solid-state NMR", "SPR", "QCM-D", "MD simulation"
                ],
            },
            "high_affinity_candidates": [
                p["pmid"] for p in _PAPER_DETAILS
                if p.get("binding_affinity_kd_nm") and p["binding_affinity_kd_nm"] < 1.5
            ],
            "message": "任务完成，已获取全部论文详情。",
        }
