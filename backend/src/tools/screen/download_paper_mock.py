# tools/search/download_paper_mock.py

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Dict, Any

class DownloadPaperInput(BaseModel):
    pmids: list[str] = Field(
        description="文献的PMID列表,必须是字符串格式的PMID,如 ['34265844','38360817']。"
    )

@tool(args_schema=DownloadPaperInput)
def download_paper(pmids: list[str]) -> Dict[str, Any]:
    """
    根据 PMID 下载并解析文献全文。(Mock 版本）

    何时调用:当在检索阶段获得了目标文献的 PMID,且需要对该文献进行处理、建立数据库时调用
    注意:不要用作者名或论文标题直接调用此工具,必须先用 search 工具获取准确的 PMID。

    返回:包含下载状态(ok / error)、成功下载的文献 PMID 列表、下载失败的文献 PMID 列表的 dict 
    """

    # ── 协议：Mock 版本返回固定的假数据 ──
    # 模拟场景：第一个 PMID 成功，第二个失败（如果有的话）
    success_pmids = []
    fail_pmids = []
    
    if pmids:
        success_pmids = [pmids[0]]  # 假设列表第一个总是成功
        if len(pmids) > 1:
            fail_pmids = pmids[1:]  # 假设后续的总是失败，用于测试 Agent 的错误处理逻辑
    
    return {
        "status": "ok",
        "success_pmids": success_pmids,
        "fail_pmids": fail_pmids,
        "pmids": pmids,
        "is_mock": True  # 额外加个标识位，方便调试
    }
