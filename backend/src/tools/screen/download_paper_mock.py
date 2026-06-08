# tools/screen/download_paper_mock.py

import hashlib

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Any


class DownloadPaperInput(BaseModel):
    pmid: str | None = Field(default=None, description="PubMed ID，如 '34265844'。")
    doi: str | None = Field(default=None, description="文献 DOI。")
    title: str | None = Field(default=None, description="文献标题（兜底 paper_key 种子）。")
    extraction_profile: str = Field(default="hap_peptide_v1", description="项目提取配置名。")
    run_id: str | None = Field(default=None, description="当前 pipeline run_id。")
    force_redownload: bool = Field(default=False, description="是否强制重新下载。")


def _generate_paper_key(doi: str | None, pmid: str | None, title: str | None) -> str:
    """Mock 版 paper_key 生成，与真实版算法保持一致。"""
    if doi:
        seed = doi.lower().strip()
    elif pmid:
        seed = pmid.strip()
    elif title:
        seed = title.lower().strip()
    else:
        seed = "mock_fallback"
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


@tool(args_schema=DownloadPaperInput)
def download_paper(
    pmid: str | None = None,
    doi: str | None = None,
    title: str | None = None,
    extraction_profile: str = "hap_peptide_v1",
    run_id: str | None = None,
    force_redownload: bool = False,
) -> dict[str, Any]:
    """
    根据 PMID/DOI 下载文献 PDF 并存储（Mock 版本）。

    调用时机：screen 阶段确认目标文献后调用，传入 pmid 或 doi。
    Mock 行为：有 pmid/doi 时返回"成功"，否则返回"失败"——用于测试 agent 的错误处理逻辑。

    返回字段：paper_key / pdf_path / download_status / file_sha256 / file_size_bytes /
             source_url / message
    """
    if not any([pmid, doi, title]):
        return {
            "status": "error",
            "download_status": "failed",
            "message": "至少需要提供 pmid、doi 或 title 之一",
        }

    paper_key  = _generate_paper_key(doi=doi, pmid=pmid, title=title)
    mock_pdf   = f"/app/data/projects/{extraction_profile}/papers/{paper_key}/raw/source.pdf"
    mock_sha   = "mock_sha256_" + paper_key

    # Mock 规则：有 pmid 或 doi 即"下载成功"
    has_identifier = bool(pmid or doi)

    if has_identifier:
        return {
            "status": "ok",
            "paper_key": paper_key,
            "pdf_path": mock_pdf,
            "download_status": "downloaded",
            "file_sha256": mock_sha,
            "file_size_bytes": 2048000,
            "source_url": f"https://mock-source.example.com/{pmid or doi}",
            "message": "Mock 下载成功",
            "is_mock": True,
        }
    else:
        return {
            "status": "ok",
            "paper_key": paper_key,
            "pdf_path": None,
            "download_status": "failed",
            "file_sha256": None,
            "file_size_bytes": None,
            "source_url": None,
            "message": "Mock 下载失败（无 pmid/doi），agent 后续步骤将跳过此文献",
            "is_mock": True,
        }
