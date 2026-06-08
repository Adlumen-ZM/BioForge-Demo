# tools/screen/download_paper.py

import os

NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "")
from pathlib import Path
import requests
import xml.etree.ElementTree as ET
from Bio import Entrez
Entrez.api_key = NCBI_API_KEY
Entrez.email = NCBI_EMAIL
from urllib.parse import quote
from metapub import PubMedFetcher
from metapub import FindIt
from paperscraper.pdf import save_pdf

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Dict, Any

# 环境变量可能需要加一个 NCBI_API_KEY 以及 PubMed 邮箱

class DownloadPaperInput(BaseModel):
    pmids: list[str] = Field(
        description="文献的PMID列表,必须是字符串格式的PMID,如 ['34265844','38360817']。\
        请勿直接使用作者名或论文标题调用此工具,必须传入准确的PMID。"
    )

@tool(args_schema=DownloadPaperInput)
def download_paper(pmids: list[str]) -> Dict[str, Any]:
    """
    根据 PMID 下载并解析文献全文。

    何时调用:当在检索阶段获得了目标文献的 PMID,且需要对该文献进行处理、建立数据库时调用
    注意:不要用作者名或论文标题直接调用此工具,必须先用 search 工具获取准确的 PMID。

    返回:包含下载状态(ok / error)、成功下载的文献 PMID 列表、下载失败的文献 PMID 列表的 dict 
    """

    success_pmids = []
    fail_pmids = []
    _PROJECT_ROOT = Path(__file__).resolve().parents[4]     # screen→ tools → src → backend → 项目根
    PDF_DIR = str(_PROJECT_ROOT / "data" / "papers" / "pdf") # 文献下载目录
    try:
        for pmid in pmids:
            pmid = pmid.replace("PMID:", "").strip() # 清理可能的前缀和空白
            success = download_pubmed_pdf(pmid, with_supplementary=True, output_dir=PDF_DIR) 
            if success:
                success_pmids.append(pmid)
            else:
                fail_pmids.append(pmid)
        return {
            "status": "ok",
            "success_pmids": success_pmids, # 成功下载的 PMID 列表
            "fail_pmids": fail_pmids,       # 下载失败的 PMID 列表
            "pmids": pmids,                 # 回传，方便 trace
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),      # 错误信息
            "success_pmids": success_pmids,
            "fail_pmids": fail_pmids,
            "pmids": pmids,
        }



fetcher = PubMedFetcher()

def download_pubmed_pdf(pmid: str, with_supplementary: bool = False, output_dir: str = "./tmp") -> bool:
    """
    根据 PMID 下载 PDF,自动清理非pdf的垃圾文件,并验证下载结果。
    可选是否下载补充材料
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    save_path = os.path.join(output_dir, f"{pmid}.pdf")
    
    # 1. 提取元数据获取下载标识符
    try:
        article = fetcher.article_by_pmid(pmid)
        doi = article.doi
        pmcid = article.pmc
        print(f"pmcid: {pmcid}")
    except Exception:
        return False

    # 2. 执行下载
    success = False

    # 先尝试用metapub
    src = FindIt(pmid)
    if src.url:
        try:
            res = requests.get(src.url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code == 200 and res.content.startswith(b'%PDF'):
                with open(save_path, 'wb') as f:
                    f.write(res.content)
                # 验证下载结果
                if os.path.exists(save_path):
                    with open(save_path, 'rb') as f:
                        if f.read(4) == b'%PDF':
                            success = True
        except Exception:
            pass

    # 如果失败，再尝试paperscraper
    if not success:
        if pmcid:
            try:
                save_pdf({"doi": doi, "pmcid": "PMC"+ pmcid}, filepath=save_path)
                # 验证下载结果
                if os.path.exists(save_path):
                    with open(save_path, 'rb') as f:
                        if f.read(4) == b'%PDF':
                            success = True
            except Exception:
                pass

    # 3. 下载补充材料pdf (仅支持 PMC 收录的 OA 文献有效)
    if with_supplementary:
        download_supplements(pmid, output_dir)
    # 清理垃圾文件 
    clean_garbage(output_dir)
    
    return success

def download_supplements(pmid: str, output_dir: str):
    """
    解析官方 XML 下载补充材料,需要先设置好 Entrez.email和 Entrez.api_key
    """
    try:
        # 1. 基础配置
        XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
        
        # 2. PMID -> PMCID 转换
        elink_handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid)
        elink_record = Entrez.read(elink_handle)
        elink_handle.close()
        
        if not elink_record or not elink_record[0]["LinkSetDb"]:
            return False
            
        pmcid_internal = elink_record[0]["LinkSetDb"][0]["Link"][0]["Id"]
        
        # 3. 获取并解析 XML
        xml_handle = Entrez.efetch(db="pmc", id=pmcid_internal, rettype="full", retmode="xml")
        xml_bytes = xml_handle.read()
        xml_handle.close()
        
        root = ET.fromstring(xml_bytes)
        
        # 提取 DOI 用于构造外部 CDN 链接
        doi_node = root.find(".//article-id[@pub-id-type='doi']")
        current_doi = doi_node.text.strip() if doi_node is not None else ""
        article_ref = quote(f"art:{current_doi}", safe="") if current_doi else ""

        # 4. 扫描所有潜在的附件 HREFs
        supp_filenames = set()
        
        # 路径 A: 标准 supplementary-material -> media 路径
        for item in root.findall(".//supplementary-material"):
            media = item.find(".//media")
            if media is not None and media.attrib.get(XLINK_HREF):
                href = media.attrib[XLINK_HREF]
                if href.lower().endswith('.pdf'):
                    supp_filenames.add(href)
        
        # 路径 B: 扩展扫描 ext-link 标签 (应对非标存储)
        for ext_link in root.findall(".//ext-link"):
            href = ext_link.attrib.get(XLINK_HREF)
            if href and href.lower().endswith('.pdf'):
                # 处理可能包含完整 URL 的情况，只取文件名
                filename = href.split('/')[-1]
                supp_filenames.add(filename)

        # 5. 执行多源探测下载
        supp_count = 0
        for href in supp_filenames:
            # 构造优先级下载队列
            urls = [
                f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmcid_internal}/bin/{href}",
                f"https://static-content.springer.com/esm/{article_ref}/MediaObjects/{href}" if article_ref else "",
                # 兼容旧版 PMC 路径
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid_internal}/bin/{href}"
            ]
            
            for url in urls:
                if not url: continue
                try:
                    res = requests.get(url, timeout=30, headers={'User-Agent': 'paper-loading/1.0'})
                    if res.status_code == 200 and res.content.startswith(b'%PDF'):
                        save_name = f"{pmid}_supp_{supp_count}.pdf"
                        with open(os.path.join(output_dir, save_name), 'wb') as f:
                            f.write(res.content)
                        supp_count += 1
                        break # 下载成功，跳过当前 href 的其他源
                except Exception:
                    continue
        
        return supp_count > 0

    except Exception:
        # 静默失败，确保主下载流程不中断
        return False

def clean_garbage(dir: str):
    """静默清理指定目录下所有的非 PDF 杂质文件"""
    if not os.path.exists(dir):
        return
    for filename in os.listdir(dir):
        filepath = os.path.join(dir, filename)
        if os.path.isfile(filepath) and not filename.lower().endswith('.pdf'):
            try:
                os.remove(filepath)
            except Exception:
                pass