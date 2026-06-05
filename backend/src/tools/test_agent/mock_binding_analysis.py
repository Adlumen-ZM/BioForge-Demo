"""
backend/src/tools/test_agent/mock_binding_analysis.py — 肽段结合亲和力分析 mock 工具

位置：backend/src/tools/test_agent/
依赖：langchain_core.tools、uuid（标准库）
职责：模拟复杂的肽段-HAp 结合亲和力计算分析，返回丰富的结构化科研数据。

设计意图（富输出测试）：
  单次调用立即返回完整分析结果（无需轮询）。
  返回深度嵌套的结构化数据（结合基序、结构特征、候选肽段排名），
  测试 output_adapter 对复杂嵌套 dict 的处理健壮性，
  同时让调试平台的输出展示区有实际内容可读。

注意：故意不在输出中包含 test_result / steps_executed / framework_behaviors_verified，
  这三个字段由 output_contract 要求，但 plan_deep_analysis 的 step 3/4 都不产生它们，
  最终触发 validate_plan 失败（这是 plan_deep_analysis 的设计意图）。
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.tools import tool


@tool
def mock_binding_analysis(
    paper_details: list | None = None,
    focus_features: list | None = None,
) -> dict[str, Any]:
    """对收集到的 HAp 结合肽论文数据执行系统性亲和力分析。

    分析关键结合基序、序列结构特征、结合机制和候选肽段排名。

    Args:
        paper_details: 论文详情列表（来自 mock_fetch_details 的结果）。
                       若省略，使用内置参考数据集进行分析。
        focus_features: 重点分析的结构特征列表（可选），如 ["phosphorylation", "acidic_cluster"]。

    Returns:
        dict，包含：
          - key_binding_motifs: 高频结合基序及统计
          - structural_features: 影响结合的关键结构因素
          - top_candidate_peptides: 预测高亲和力候选肽段（含序列和预测 Kd）
          - binding_mechanism: 结合机制分析
          - recommendations: 后续研究建议
    """
    analysis_id = f"ana_{uuid.uuid4().hex[:6]}"
    paper_count = len(paper_details) if paper_details else 14

    return {
        "analysis_id": analysis_id,
        "papers_analyzed": paper_count,

        # ── 高频结合基序（按平均亲和力从强到弱排序）────────────────────────
        "key_binding_motifs": [
            {
                "motif": "pSer-pSer-pSer（三磷酸化丝氨酸簇）",
                "frequency_in_dataset": 8,
                "mean_kd_nm": 0.61,
                "rank": 1,
                "mechanism": "三齿配位直接键合 HAp Ca²⁺ 格点",
            },
            {
                "motif": "Asp-pSer-Asp-pSer（磷酸化-酸性残基交替）",
                "frequency_in_dataset": 5,
                "mean_kd_nm": 0.89,
                "rank": 2,
                "mechanism": "Ca²⁺ 桥联 + 氢键网络",
            },
            {
                "motif": "Glu-Glu-Glu-Glu（poly-Glu ≥ 4）",
                "frequency_in_dataset": 6,
                "mean_kd_nm": 1.15,
                "rank": 3,
                "mechanism": "Ca²⁺ 螯合，依赖链长，≥4 Glu 时协同效应显著",
            },
            {
                "motif": "RGD（精氨酸-甘氨酸-天冬氨酸）",
                "frequency_in_dataset": 3,
                "mean_kd_nm": 4.20,
                "rank": 4,
                "mechanism": "主要作用为细胞黏附整合素配体，HAp 亲和力较弱",
            },
        ],

        # ── 关键结构特征分析 ───────────────────────────────────────────────
        "structural_features": {
            "phosphorylation_essential": {
                "finding": "磷酸化是强结合的必要条件",
                "evidence": "去磷酸化后亲和力平均降低 85-200 倍（SPR 测量）",
                "key_papers": ["38291001", "37982145", "37132456"],
            },
            "acidic_residue_clusters": {
                "finding": "酸性残基簇（Asp/Glu ≥ 3 连续）高度富集于高亲和力肽段",
                "statistics": "87% 的高亲和力肽段（Kd < 2 nM）含酸性簇",
                "optimal_cluster_length": "3-5 个连续酸性残基",
            },
            "optimal_peptide_length": {
                "range_aa": "12-28",
                "finding": "太短（<8 aa）接触面积不足；太长（>35 aa）可能自聚集",
            },
            "net_charge_ph74": {
                "optimal_range": "-4 至 -8",
                "finding": "强负电荷驱动与 Ca²⁺ 的静电吸引，但过负（< -8）可能影响水溶性",
                "reference": "36349456",
            },
            "secondary_structure": {
                "preferred": "无规卷曲或 β-转角（α-螺旋会遮蔽磷酸基团）",
                "finding": "约 65% 的高亲和力肽段在结合状态下呈延伸构象",
            },
        },

        # ── 候选肽段排名（预测 Kd 最强的 3 条）──────────────────────────────
        "top_candidate_peptides": [
            {
                "rank": 1,
                "sequence": "Asp-pSer-pSer-pSer-Glu-Glu-Lys-Phe-Leu-Arg",
                "one_letter": "D[pS][pS][pS]EEKFLR",
                "predicted_kd_nm": 0.41,
                "source_pmid": "38291001",
                "net_charge_ph74": -5,
                "length_aa": 10,
                "rationale": "三连 pSer 提供最强 Ca²⁺ 配位，Glu-Glu 辅助定向",
            },
            {
                "rank": 2,
                "sequence": "Glu-Glu-Glu-Glu-Glu-Gly-pSer-pSer-Phe-Arg-Glu-Trp",
                "one_letter": "EEEEE-G[pS][pS]FREW",
                "predicted_kd_nm": 0.53,
                "source_pmid": "37982145",
                "net_charge_ph74": -6,
                "length_aa": 12,
                "rationale": "poly-Glu 簇 + pSer 双联，协同效应显著",
            },
            {
                "rank": 3,
                "sequence": "Asp-pSer-Asp-Asp-pSer-Glu-Glu-Lys-Gln-His-Leu-Gly-Gly",
                "one_letter": "D[pS]DD[pS]EEKQHLGG",
                "predicted_kd_nm": 0.67,
                "source_pmid": "37132456",
                "net_charge_ph74": -5,
                "length_aa": 13,
                "rationale": "磷酸化-酸性残基交替排列，结合位点空间匹配最优",
            },
        ],

        # ── 结合机制综合分析 ──────────────────────────────────────────────
        "binding_mechanism": {
            "primary_driver": "静电吸附（Ca²⁺ 与酸性/磷酸基团配位）",
            "energy_contributions": {
                "electrostatic_pct": 65,
                "hydrogen_bond_pct": 25,
                "hydrophobic_pct": 10,
            },
            "per_pSer_delta_G_kcal_mol": -1.8,
            "per_Glu_delta_G_kcal_mol": -0.9,
            "binding_face_preference": "HAp (100) 和 (001) 面均有结合，高亲和力肽段偏好 (100) 面",
        },

        # ── 研究建议 ─────────────────────────────────────────────────────
        "recommendations": [
            "优先合成 top-3 候选肽段进行 SPR 实验验证预测 Kd 值",
            "对候选肽段进行磷酸化位点突变扫描，确认关键 pSer 的贡献",
            "开展 MD 模拟（CHARMM36m，>100 ns）研究结合界面动力学",
            "测试 pH 5.0 / 7.4 / 9.0 条件下的结合差异（模拟口腔环境）",
            "对 top 候选肽段进行 HAp 矿化诱导实验（SEM + XRD 表征）",
        ],

        # ── 注意：故意不包含以下字段，用于触发 validate_plan 失败测试 ──────
        # "test_result": 未包含（output_contract 要求）
        # "steps_executed": 未包含（output_contract 要求）
        # "framework_behaviors_verified": 未包含（output_contract 要求）
    }
