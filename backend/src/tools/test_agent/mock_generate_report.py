"""
backend/src/tools/test_agent/mock_generate_report.py — 报告生成 mock 工具

位置：backend/src/tools/test_agent/
依赖：langchain_core.tools、uuid、datetime（标准库）
职责：模拟生成结构化分析报告，输出科研报告格式的 dict。

设计意图（validate_plan 失败测试）：
  此工具是 plan_deep_analysis 的最后一个工具。
  其输出包含科研报告字段（report_id、executive_summary、top_candidates_ranked 等），
  但不包含 test_agent identity.yaml 的 output_contract 所要求的：
    - test_result
    - steps_executed
    - framework_behaviors_verified

  因此：
    - step 4 本身会 validate_step 通过（success_criteria 只检查报告字段）
    - 整个 plan 结束后 validate_plan（LLM 判断）会发现输出不满足 output_contract
    - validate_plan 返回 False → plan_end status="failed"
    - 调试平台的 02_detail 页面显示：所有 step ✅ 但 plan 整体 ❌

  这完整演示了 plan 级别的输出质量校验路径。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool


@tool
def mock_generate_report(
    analysis_summary: str = "",
    candidate_count: int = 3,
    include_next_steps: bool = True,
) -> dict[str, Any]:
    """生成肽段-HAp 结合亲和力系统综述分析报告。

    整合文献检索、数据获取和亲和力分析结果，生成结构化报告。

    Args:
        analysis_summary: 前序分析步骤的摘要文本（可选，用于报告引言）。
        candidate_count: 在报告中列出的候选肽段数量（默认3条）。
        include_next_steps: 是否包含后续实验建议（默认 True）。

    Returns:
        dict，包含报告各章节内容（report_id、executive_summary、
        literature_coverage、top_candidates_ranked、next_steps 等）。
        注意：不包含 test_result / steps_executed / framework_behaviors_verified，
        将触发 validate_plan 失败以测试 plan 级校验路径。
    """
    report_id = f"rpt_{uuid.uuid4().hex[:8]}"
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    top_candidates = [
        {
            "rank": 1,
            "sequence": "D[pS][pS][pS]EEKFLR",
            "predicted_kd_nm": 0.41,
            "net_charge": -5,
            "length_aa": 10,
            "source": "PMID:38291001",
            "synthesis_difficulty": "中等（需 Fmoc 固相合成 + 磷酸化保护基）",
        },
        {
            "rank": 2,
            "sequence": "EEEEE-G[pS][pS]FREW",
            "predicted_kd_nm": 0.53,
            "net_charge": -6,
            "length_aa": 12,
            "source": "PMID:37982145",
            "synthesis_difficulty": "中等",
        },
        {
            "rank": 3,
            "sequence": "D[pS]DD[pS]EEKQHLGG",
            "predicted_kd_nm": 0.67,
            "net_charge": -5,
            "length_aa": 13,
            "source": "PMID:37132456",
            "synthesis_difficulty": "较易",
        },
    ][:candidate_count]

    report = {
        "report_id": report_id,
        "report_version": "1.0",
        "generated_at": generated_at,

        "title": "肽段-羟基磷灰石结合亲和力系统综述：候选序列鉴定与机制分析",

        "executive_summary": (
            f"本报告基于 14 篇高质量同行评审文献（2020-2024年）的系统分析，"
            f"共鉴定出 {candidate_count} 条预测高亲和力 HAp 结合肽段（Kd < 1 nM）。"
            "核心发现：磷酸化丝氨酸簇（pSer-pSer-pSer）和酸性残基簇（poly-Asp/Glu）"
            "是 HAp 强结合的结构基础，静电相互作用贡献约 65% 的结合自由能。"
            "推荐优先合成排名第 1 的候选肽段（D[pS][pS][pS]EEKFLR，预测 Kd=0.41 nM）"
            "进行 SPR 验证实验。"
        ),

        "literature_coverage": {
            "total_papers_reviewed": 14,
            "date_range": "2020-2024",
            "primary_journals": [
                "Biomaterials", "ACS Biomater. Sci. Eng.",
                "J. Dent. Res.", "Acta Biomater.",
                "ACS Nano", "J. Chem. Theory Comput.",
            ],
            "experimental_methods_covered": [
                "ITC（等温滴定量热法）",
                "SPR（表面等离子共振）",
                "ssNMR（固态核磁共振）",
                "cryo-TEM（冷冻透射电镜）",
                "QCM-D（石英晶体微天平耗散）",
                "MD（全原子分子动力学模拟）",
            ],
            "total_citations_covered": 390,
        },

        "top_candidates_ranked": top_candidates,

        "key_structure_rules": [
            "规则1：pSer 数量≥3时亲和力呈指数提升（每个 pSer 贡献 -1.8 kcal/mol）",
            "规则2：净电荷需在 -4 至 -8 之间（pH 7.4），过负影响水溶性",
            "规则3：最优肽段长度 12-28 个氨基酸，过短接触面积不足",
            "规则4：避免强疏水核心区段（阻碍 Ca²⁺ 接近磷酸基团）",
            "规则5：酸性残基与 pSer 交替排列比单独成簇亲和力更强",
        ],

        **(
            {
                "next_steps": [
                    {
                        "priority": 1,
                        "action": "固相合成 top-3 候选肽段（Fmoc 法，磷酸化位点用 Fmoc-pSer(OtBu)-OH）",
                        "timeline": "4-6 周",
                        "cost_estimate_cny": "约 8,000-15,000 元/肽段",
                    },
                    {
                        "priority": 2,
                        "action": "SPR 实验验证预测 Kd 值（Biacore T200，HAp 传感芯片）",
                        "timeline": "2-3 周",
                        "cost_estimate_cny": "约 12,000 元/组",
                    },
                    {
                        "priority": 3,
                        "action": "MD 模拟（CHARMM36m 力场，>100 ns，验证结合构象）",
                        "timeline": "3-4 周",
                        "compute_required": "约 50,000 CPU-hours（或 A100 GPU 约 200 GPU-hours）",
                    },
                    {
                        "priority": 4,
                        "action": "矿化诱导实验（SEM + XRD 表征晶体形貌）",
                        "timeline": "3-4 周",
                        "expected_outcome": "确认 top 候选肽段能引导 HAp 择优取向生长",
                    },
                ]
            }
            if include_next_steps
            else {}
        ),

        "report_limitations": [
            "预测 Kd 值基于文献数据推算，实验条件（pH、离子强度、温度）存在差异",
            "MD 模拟结果依赖力场参数，磷酸化残基参数有待进一步验证",
            "现有数据集偏向已发表的高亲和力肽段，可能存在发表偏倚",
        ],

        # ── 注意：以下字段是 test_agent output_contract 要求的，
        # 但本工具故意不生成，用于触发 validate_plan 失败：
        # "test_result":               <not included>
        # "steps_executed":            <not included>
        # "framework_behaviors_verified": <not included>
    }

    return report
