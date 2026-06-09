"""Real PDF download tool for screened papers."""

from __future__ import annotations

import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from Bio import Entrez
from langchain_core.tools import tool
from pydantic import BaseModel, Field

_METAPUB_OK = False
_METAPUB_ERR = ""
_PAPERSCRAPER_OK = False
_PAPERSCRAPER_ERR = ""

try:
    from metapub import FindIt, PubMedFetcher as _PubMedFetcher

    _METAPUB_OK = True
except ImportError as exc:
    FindIt = None  # type: ignore[assignment,misc]
    _PubMedFetcher = None  # type: ignore[assignment,misc]
    _METAPUB_ERR = str(exc)

try:
    from paperscraper.pdf import save_pdf as _save_pdf

    _PAPERSCRAPER_OK = True
except ImportError as exc:
    _save_pdf = None  # type: ignore[assignment]
    _PAPERSCRAPER_ERR = str(exc)

NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "")
Entrez.api_key = NCBI_API_KEY
Entrez.email = NCBI_EMAIL

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_REQUEST_TIMEOUT_S = int(os.environ.get("DOWNLOAD_PDF_TIMEOUT_S", "30"))


class DownloadPaperInput(BaseModel):
    pmid: str | None = Field(default=None, description="PubMed ID")
    doi: str | None = Field(default=None, description="Paper DOI")
    title: str | None = Field(default=None, description="Paper title")
    extraction_profile: str = Field(default="hap_peptide_v1", description="Storage profile")
    run_id: str | None = Field(default=None, description="Current pipeline run id")
    force_redownload: bool = Field(default=False, description="Redownload even if cached")


@tool(args_schema=DownloadPaperInput)
def download_paper(
    pmid: str | None = None,
    doi: str | None = None,
    title: str | None = None,
    extraction_profile: str = "hap_peptide_v1",
    run_id: str | None = None,
    force_redownload: bool = False,
) -> dict[str, Any]:
    """Download a PDF and write manifest metadata beside it."""
    started_at = time.monotonic()

    if not any([pmid, doi, title]):
        result = {
            "status": "error",
            "download_status": "failed",
            "pdf_path": None,
            "failure_reason": "invalid_input",
            "message": "至少需要提供 pmid、doi 或 title 之一",
        }
        _trace_download_event("pdf_download_finished", "failed", started_at, result)
        return result

    paper_key = _generate_paper_key(doi=doi, pmid=pmid, title=title)
    trace_ctx = {
        "pmid": pmid,
        "doi": doi,
        "paper_key": paper_key,
        "extraction_profile": extraction_profile,
    }

    _trace_download_event("download_attempt_started", "running", started_at, trace_ctx)

    if not _METAPUB_OK:
        result = {
            "status": "error",
            "download_status": "failed",
            "paper_key": paper_key,
            "pdf_path": None,
            "failure_reason": f"dependency_missing:{_METAPUB_ERR}",
            "message": (
                f"依赖缺失，无法执行真实下载（{_METAPUB_ERR}）。"
                " 请在容器内安装缺失依赖。"
            ),
        }
        _trace_download_event("pdf_download_finished", "failed", started_at, {**trace_ctx, **result})
        return result

    paper_dir = _PROJECT_ROOT / "data" / "projects" / extraction_profile / "papers" / paper_key / "raw"
    paper_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = paper_dir / "source.pdf"
    manifest_path = paper_dir / "manifest.json"

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
        result = {
            "status": "ok",
            "paper_key": paper_key,
            "pdf_path": str(pdf_path),
            "download_status": "already_exists",
            "file_sha256": existing_sha256,
            "file_size_bytes": pdf_path.stat().st_size,
            "source_url": None,
            "message": "PDF 已存在，跳过下载",
        }
        _trace_download_event("pdf_download_finished", "success", started_at, {**trace_ctx, **result})
        return result

    fetched_doi = doi
    fetched_pmcid = None
    failure_reasons: list[str] = []

    if pmid:
        try:
            fetcher = _get_fetcher()
            article = fetcher.article_by_pmid(pmid)
            fetched_doi = fetched_doi or article.doi
            fetched_pmcid = article.pmc
        except Exception as exc:
            failure_reasons.append(f"metadata_lookup_failed:{type(exc).__name__}")

    source_url = None
    success = False

    if pmid and not success and _METAPUB_OK:
        try:
            src = FindIt(pmid)
            if src.url:
                res = requests.get(
                    src.url,
                    timeout=_REQUEST_TIMEOUT_S,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if res.status_code == 200 and res.content.startswith(b"%PDF"):
                    pdf_path.write_bytes(res.content)
                    if _verify_pdf(pdf_path):
                        source_url = src.url
                        success = True
                    else:
                        failure_reasons.append("direct_pdf_invalid_file")
                else:
                    failure_reasons.append(f"direct_pdf_invalid_response:{res.status_code}")
            else:
                failure_reasons.append("direct_pdf_url_not_found")
        except requests.Timeout:
            failure_reasons.append(f"direct_pdf_timeout:{_REQUEST_TIMEOUT_S}s")
        except Exception as exc:
            failure_reasons.append(f"direct_pdf_failed:{type(exc).__name__}")

    if not success and fetched_pmcid and _PAPERSCRAPER_OK:
        try:
            _save_pdf(
                {"doi": fetched_doi, "pmcid": "PMC" + fetched_pmcid},
                filepath=str(pdf_path),
            )
            if _verify_pdf(pdf_path):
                source_url = f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{fetched_pmcid}/"
                success = True
            else:
                failure_reasons.append("pmc_pdf_invalid_file")
        except Exception as exc:
            failure_reasons.append(f"pmc_download_failed:{type(exc).__name__}")
    elif not success and fetched_pmcid and not _PAPERSCRAPER_OK:
        failure_reasons.append(f"paperscraper_missing:{_PAPERSCRAPER_ERR}")
    elif not success and not fetched_pmcid:
        failure_reasons.append("pmcid_not_found")

    _clean_non_pdf(paper_dir)

    if not success:
        if pdf_path.exists() and pdf_path.stat().st_size < 100:
            pdf_path.unlink(missing_ok=True)

        failure_summary = "; ".join(failure_reasons[:3]) if failure_reasons else "pdf_not_found"
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
        result = {
            "status": "ok",
            "paper_key": paper_key,
            "pdf_path": None,
            "download_status": "failed",
            "file_sha256": None,
            "file_size_bytes": None,
            "source_url": None,
            "failure_reason": failure_summary,
            "message": f"PDF 下载失败（pmid={pmid}, doi={fetched_doi}）。原因：{failure_summary}",
        }
        _trace_download_event("pdf_download_finished", "failed", started_at, {**trace_ctx, **result})
        return result

    file_sha256 = _sha256_file(pdf_path)
    file_size = pdf_path.stat().st_size
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

    if pmid:
        _download_supplements(pmid, paper_dir)

    result = {
        "status": "ok",
        "paper_key": paper_key,
        "pdf_path": str(pdf_path),
        "download_status": "downloaded",
        "file_sha256": file_sha256,
        "file_size_bytes": file_size,
        "source_url": source_url,
        "message": f"下载成功（{file_size // 1024} KB）",
    }
    _trace_download_event("pdf_download_finished", "success", started_at, {**trace_ctx, **result})
    return result


_fetcher_instance: Any = None


def _get_fetcher() -> Any:
    global _fetcher_instance
    if _METAPUB_OK and _fetcher_instance is None:
        _fetcher_instance = _PubMedFetcher()
    return _fetcher_instance


def _generate_paper_key(doi: str | None, pmid: str | None, title: str | None) -> str:
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
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_pdf(path: Path) -> bool:
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
    manifest = {
        "paper_key": paper_key,
        "pmid": pmid,
        "doi": doi,
        "title": title,
        "extraction_profile": extraction_profile,
        "run_id": run_id,
        "pdf_path": pdf_path,
        "source_url": source_url,
        "file_sha256": file_sha256,
        "file_size_bytes": file_size_bytes,
        "download_status": download_status,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_non_pdf(directory: Path) -> None:
    for path in directory.iterdir():
        if path.is_file() and not path.name.lower().endswith(".pdf") and path.name != "manifest.json":
            try:
                path.unlink()
            except Exception:
                pass


def _download_supplements(pmid: str, output_dir: Path) -> None:
    """Best-effort supplement download for PMC papers."""
    try:
        xlink_href = "{http://www.w3.org/1999/xlink}href"

        elink_handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid)
        elink_record = Entrez.read(elink_handle)
        elink_handle.close()

        if not elink_record or not elink_record[0]["LinkSetDb"]:
            return

        pmcid_internal = elink_record[0]["LinkSetDb"][0]["Link"][0]["Id"]

        xml_handle = Entrez.efetch(db="pmc", id=pmcid_internal, rettype="full", retmode="xml")
        xml_bytes = xml_handle.read()
        xml_handle.close()

        root = ET.fromstring(xml_bytes)

        doi_node = root.find(".//article-id[@pub-id-type='doi']")
        current_doi = doi_node.text.strip() if doi_node is not None and doi_node.text else ""
        article_ref = quote(f"art:{current_doi}", safe="") if current_doi else ""

        supp_nodes = root.findall(".//supplementary-material")
        for idx, node in enumerate(supp_nodes, start=1):
            href = node.attrib.get(xlink_href)
            if not href or not href.lower().endswith(".pdf"):
                continue
            pdf_url = (
                "https://pmc.ncbi.nlm.nih.gov/articles/instance/"
                f"{article_ref}/bin/{quote(href)}"
                if article_ref
                else None
            )
            if not pdf_url:
                continue
            try:
                resp = requests.get(
                    pdf_url,
                    timeout=_REQUEST_TIMEOUT_S,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
                    (output_dir / f"supplement_{idx}.pdf").write_bytes(resp.content)
            except Exception:
                continue
    except Exception:
        pass


def _trace_download_event(
    event_type: str,
    status: str,
    started_at: float,
    payload: dict[str, Any],
) -> None:
    """Best-effort trace emission without affecting the main flow."""
    try:
        from backend.src.db_access.trace.trace_manager import record

        record(
            event_type,
            stage="screen",
            status=status,
            duration_ms=(time.monotonic() - started_at) * 1000,
            payload=payload,
        )
    except Exception:
        pass
