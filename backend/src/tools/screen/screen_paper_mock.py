"""
tools/screen/screen_paper_mock.py — screen_paper 的 Mock 版本

行为：模拟单篇文献相关性筛选，返回固定的假数据，便于测试 screen_agent 的正常流程。
      不依赖 scikit-learn / numpy，可离线运行。

规则（可预测、可控）：
  - 列表中第一篇判定为相关，其余判定为不相关
  - 始终返回与真实工具一致的数据结构
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class ScreenPaperMockInput(BaseModel):
    """screen_paper mock 的输入 schema（与真实工具一致）。"""

    papers: list[dict[str, Any]] = Field(
        description="候选文献元数据列表，每条至少包含 pmid / title / abstract。",
    )
    criteria: str = Field(
        description="筛选标准描述（自然语言）。",
    )
    threshold: float = Field(
        default=1.0,
        description="相关度阈值（mock 版本中不使用，仅为接口一致保留）",
    )


@tool(args_schema=ScreenPaperMockInput)
def screen_paper(
    papers: list[dict[str, Any]],
    criteria: str,
    threshold: float = 0.05,
) -> dict[str, Any]:
    """根据筛选标准判断每篇候选文献的相关性。（Mock 版本）

    何时调用：当获得候选文献元数据后，需要根据筛选标准判断相关性时调用。

    返回：筛选后的 PMID 列表、每篇判定结果、筛选摘要。
    """
    if not papers:
        return {
            "screened_paper_ids": [],
            "screened_count": 0,
            "excluded": [],
            "screen_summary": "无候选文献。",
            "is_mock": True,
        }

    # ── 模拟行为：第一篇相关，其余不相关 ──
    screened: list[str] = [str(papers[0].get("pmid", ""))]
    excluded: list[dict[str, Any]] = [
        {
            "pmid": str(p.get("pmid", "")),
            "reason": "文献内容与筛选标准不匹配（相关度 0.0100）[mock]",
            "relevance": 0.01,
        }
        for p in papers[1:]
    ]

    return {
        "screened_paper_ids": screened,
        "screened_count": len(screened),
        "excluded": excluded,
        "screen_summary": (
            f"根据标准筛选 {len(papers)} 篇文献，"
            f"相关 {len(screened)} 篇，排除 {len(excluded)} 篇。[mock]"
        ),
        "is_mock": True,
    }
