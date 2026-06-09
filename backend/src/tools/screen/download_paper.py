# tools/screen/download_paper.py

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import requests
from Bio import Entrez
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# metapub 和 paperscraper 按需延迟导入；缺少 unidecode 等间接依赖时模块仍可加载，
# 工具在运行时调用阶段给出明确的失败信息，而非在 import 期间崩溃。
_METAPUB_OK: bool = False
_METAPUB_ERR: str = ""
_PAPERSCRAPER_OK: bool = False
_PAPERSCRAPER_ERR: str = ""

try:
    from metapub import FindIt, PubMedFetcher as _PubMedFetcher
    _METAPUB_OK = True
except ImportError as _e:
    FindIt = None  # type: ignore[assignment,misc]
    _PubMedFetcher = None  # type: ignore[assignment,misc]
    _METAPUB_ERR = str(_e)

try:
    from paperscraper.pdf import save_pdf as _save_pdf
    _PAPERSCRAPER_OK = True
except ImportError as _e:
    _save_pdf = None  # type: ignore[assignment]
    _PAPERSCRAPER_ERR = str(_e)

# NCBI 凭据从环境变量读取
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
NCBI_EMAIL   = os.environ.get("NCBI_EMAIL", "")
Entrez.api_key = NCBI_API_KEY
Entrez.email   = NCBI_EMAIL

# 项目根目录（tools → screen → tools → src → backend → 项目根）
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


class DownloadPaperInput(BaseModel):
    pmid: str | None = Field(default=None, description="PubMed ID，如 '34265844'。")
    doi: str | None = Field(default=None, description="文献 DOI，如 '10.1016/j.biomater.2021.120935'。")
    title: str | None = Field(default=None, description="文献标题（pmid 和 doi 均不可用时作为 paper_key 种子）。")
    extraction_profile: str = Field(
        default="hap_peptide_v1",
        description="项目提取配置名，决定文件存储路径分层（如 hap_peptide_v1）。",
    )
    run_id: str | None = Field(default=None, description="当前 pipeline run_id，写入 manifest 用于追溯。")
    force_redownload: bool = Field(default=False, description="True 时即使 PDF 已存在也重新下载并覆盖。")


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
    下载单篇文献 PDF，按规范路径存储并生成 manifest.json。

    调用时机：screen 阶段确认目标文献后，获得 pmid/doi，调用此工具开始下载。
    注意：下载失败不抛异常，通过 download_status 字段告知 agent，后续步骤自行处理缺失。

    返回字段：paper_key / pdf_path / download_status / file_sha256 / file_size_bytes /
             source_url / message
    """
    # ── 0. 依赖可用性检查（metapub/paperscraper 缺失时给出明确错误而非崩溃）──
    if not _METAPUB_OK:
        return {
            "status": "error",
            "download_status": "failed",
            "paper_key": _generate_paper_key(doi=doi, pmid=pmid, title=title) if any([doi, pmid, title]) else None,
            "pdf_path": None,
            "message": f"依赖缺失，无法执行真实下载（{_METAPUB_ERR}）。请在容器内执行：pip install metapub unidecode",
        }

    # ── 1. 校验输入 ──────────────────────────────────────────────────────
    if not any([pmid, doi, title]):
        return {
            "status": "error",
            "download_status": "failed",
            "message": "至少需要提供 pmid、doi 或 title 之一",
        }

    # ── 2. 生成 paper_key ─────────────────────────────────────────────────
    paper_key = _generate_paper_key(doi=doi, pmid=pmid, title=title)

    # ── 3. 构造文件路径 ───────────────────────────────────────────────────
    paper_dir = _PROJECT_ROOT / "data" / "projects" / extraction_profile / "papers" / paper_key / "raw"
    paper_dir.mkdir(parents=True, exist_ok=True)
    pdf_path    = paper_dir / "source.pdf"
    manifest_path = paper_dir / "manifest.json"

    # ── 4. 已存在且不强制重新下载时，直接返回 ─────────────────────────────
    if pdf_path.exists() and not force_redownload:
        existing_sha256 = _sha256_file(pdf_path)
        _write_manifest(
            manifest_path=manifest_path,
            paper_key=paper_key,
            pmid=pmid,
            doi=doi,
            title=title,
            extraction_profile=extraction_profile,
            run_id=run_id,
            pdf_path=str(pdf_path),
            file_sha256=existing_sha256,
            file_size_bytes=pdf_path.stat().st_size,
            download_status="already_exists",
            source_url=None,
        )
        return {
            "status": "ok",
            "paper_key": paper_key,
            "pdf_path": str(pdf_path),
            "download_status": "already_exists",
            "file_sha256": existing_sha256,
            "file_size_bytes": pdf_path.stat().st_size,
            "source_url": None,
            "message": "PDF 已存在，跳过下载",
        }

    # ── 5. 通过 PMID 查询元数据（获取 doi/pmcid） ─────────────────────────
    fetched_doi   = doi
    fetched_pmcid = None
    if pmid:
        try:
            fetcher = _get_fetcher()
            article       = fetcher.article_by_pmid(pmid)
            fetched_doi   = fetched_doi or article.doi
            fetched_pmcid = article.pmc
        except Exception:
            pass  # 元数据获取失败不中断，继续尝试下载

    # ── 6. 执行下载 ───────────────────────────────────────────────────────
    source_url = None
    success    = False

    # 方案 A：metapub FindIt（通过 PMID 找直链）
    if pmid and not success and _METAPUB_OK:
        try:
            src = FindIt(pmid)
            if src.url:
                res = requests.get(src.url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
                if res.status_code == 200 and res.content.startswith(b"%PDF"):
                    pdf_path.write_bytes(res.content)
                    if _verify_pdf(pdf_path):
                        source_url = src.url
                        success    = True
        except Exception:
            pass

    # 方案 B：paperscraper（PMC OA 文献，需要 pmcid）
    if not success and fetched_pmcid and _PAPERSCRAPER_OK:
        try:
            _save_pdf(
                {"doi": fetched_doi, "pmcid": "PMC" + fetched_pmcid},
                filepath=str(pdf_path),
            )
            if _verify_pdf(pdf_path):
                source_url = f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{fetched_pmcid}/"
                success    = True
        except Exception:
            pass

    # ── 7. 清理非 PDF 杂质文件 ────────────────────────────────────────────
    _clean_non_pdf(paper_dir)

    # ── 8. 下载失败处理 ───────────────────────────────────────────────────
    if not success:
        # 删除可能写了一半的空文件
        if pdf_path.exists() and pdf_path.stat().st_size < 100:
            pdf_path.unlink(missing_ok=True)

        _write_manifest(
            manifest_path=manifest_path,
            paper_key=paper_key,
            pmid=pmid,
            doi=fetched_doi,
            title=title,
            extraction_profile=extraction_profile,
            run_id=run_id,
            pdf_path=None,
            file_sha256=None,
            file_size_bytes=None,
            download_status="failed",
            source_url=None,
        )
        return {
            "status": "ok",          # 工具本身执行成功，只是论文下载失败
            "paper_key": paper_key,
            "pdf_path": None,
            "download_status": "failed",
            "file_sha256": None,
            "file_size_bytes": None,
            "source_url": None,
            "message": f"PDF 下载失败（pmid={pmid}, doi={fetched_doi}），该文献后续步骤将跳过",
        }

    # ── 9. 下载成功：计算 hash，写 manifest ──────────────────────────────
    file_sha256    = _sha256_file(pdf_path)
    file_size      = pdf_path.stat().st_size

    _write_manifest(
        manifest_path=manifest_path,
        paper_key=paper_key,
        pmid=pmid,
        doi=fetched_doi,
        title=title,
        extraction_profile=extraction_profile,
        run_id=run_id,
        pdf_path=str(pdf_path),
        file_sha256=file_sha256,
        file_size_bytes=file_size,
        download_status="downloaded",
        source_url=source_url,
    )

    # ── 10. 下载补充材料（静默失败，不影响主流程）────────────────────────
    if pmid:
        _download_supplements(pmid, paper_dir)

    return {
        "status": "ok",
        "paper_key": paper_key,
        "pdf_path": str(pdf_path),
        "download_status": "downloaded",
        "file_sha256": file_sha256,
        "file_size_bytes": file_size,
        "source_url": source_url,
        "message": f"下载成功（{file_size // 1024} KB）",
    }


# ─────────────────────────── 内部工具函数 ────────────────────────────────

_fetcher_instance: Any = None  # PubMedFetcher 或 None（metapub 不可用时）


def _get_fetcher() -> Any:
    """单例 PubMedFetcher，避免重复初始化。metapub 不可用时返回 None。"""
    global _fetcher_instance
    if _METAPUB_OK and _fetcher_instance is None:
        _fetcher_instance = _PubMedFetcher()
    return _fetcher_instance


def _generate_paper_key(doi: str | None, pmid: str | None, title: str | None) -> str:
    """生成 paper_key：SHA-256(优先 doi > pmid > title)[:16]。"""
    if doi:
        seed = doi.lower().strip()
    elif pmid:
        seed = pmid.strip()
    elif title:
        seed = title.lower().strip()
    else:
        raise ValueError("至少需要 doi、pmid 或 title 之一")
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


def _sha256_file(path: Path) -> str:
    """计算文件 SHA-256 摘要（十六进制字符串）。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_pdf(path: Path) -> bool:
    """验证文件头是否为合法 PDF（%PDF 魔数）。"""
    if not path.exists() or path.stat().st_size < 100:
        return False
    with path.open("rb") as f:
        return f.read(4) == b"%PDF"


def _write_manifest(
    manifest_path: Path,
    paper_key: str,
    pmid: str | None,
    doi: str | None,
    title: str | None,
    extraction_profile: str,
    run_id: str | None,
    pdf_path: str | None,
    file_sha256: str | None,
    file_size_bytes: int | None,
    download_status: str,
    source_url: str | None,
) -> None:
    """写入或覆盖 manifest.json，记录文件资产完整元数据。"""
    manifest = {
        "paper_key":         paper_key,
        "pmid":              pmid,
        "doi":               doi,
        "title":             title,
        "extraction_profile": extraction_profile,
        "run_id":            run_id,
        "pdf_path":          pdf_path,
        "source_url":        source_url,
        "file_sha256":       file_sha256,
        "file_size_bytes":   file_size_bytes,
        "download_status":   download_status,
        "downloaded_at":     datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _clean_non_pdf(directory: Path) -> None:
    """静默清理目录内所有非 PDF 杂质文件。"""
    for p in directory.iterdir():
        if p.is_file() and not p.name.lower().endswith(".pdf") and p.name != "manifest.json":
            try:
                p.unlink()
            except Exception:
                pass


def _download_supplements(pmid: str, output_dir: Path) -> None:
    """
    下载 PMC OA 文献的补充材料 PDF（仅支持 PMC 收录文献）。
    静默失败，不影响主流程。
    """
    try:
        XLINK_HREF = "{http://www.w3.org/1999/xlink}href"

        elink_handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid)
        elink_record = Entrez.read(elink_handle)
        elink_handle.close()

        if not elink_record or not elink_record[0]["LinkSetDb"]:
            return

        pmcid_internal = elink_record[0]["LinkSetDb"][0]["Link"][0]["Id"]

        xml_handle = Entrez.efetch(db="pmc", id=pmcid_internal, rettype="full", retmode="xml")
        xml_bytes   = xml_handle.read()
        xml_handle.close()

        root = ET.fromstring(xml_bytes)

        doi_node    = root.find(".//article-id[@pub-id-type='doi']")
        current_doi = doi_node.text.strip() if doi_node is not None else ""
        article_ref = quote(f"art:{current_doi}", safe="") if current_doi else ""

        supp_filenames: set[str] = set()

        for item in root.findall(".//supplementary-material"):
            media = item.find(".//media")
            if media is not None and media.attrib.get(XLINK_HREF, "").lower().endswith(".pdf"):
                supp_filenames.add(media.attrib[XLINK_HREF])

        for ext_link in root.findall(".//ext-link"):
            href = ext_link.attrib.get(XLINK_HREF, "")
            if href.lower().endswith(".pdf"):
                supp_filenames.add(href.split("/")[-1])

        supp_count = 0
        for href in supp_filenames:
            urls = [
                f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmcid_internal}/bin/{href}",
                f"https://static-content.springer.com/esm/{article_ref}/MediaObjects/{href}" if article_ref else "",
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid_internal}/bin/{href}",
            ]
            for url in urls:
                if not url:
                    continue
                try:
                    res = requests.get(url, timeout=30, headers={"User-Agent": "paper-loading/1.0"})
                    if res.status_code == 200 and res.content.startswith(b"%PDF"):
                        save_name = output_dir / f"{pmid}_supp_{supp_count}.pdf"
                        save_name.write_bytes(res.content)
                        supp_count += 1
                        break
                except Exception:
                    continue

    except Exception:
        pass
