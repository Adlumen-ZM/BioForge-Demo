"""
3.1 视觉文档解析层 — RAGFlow HTTP API 真实接入版

完整生命周期（单篇 PDF）：
  [1/4]  POST /api/v1/datasets                              新建临时 dataset
  [2/4]  POST /api/v1/datasets/{ds_id}/documents            上传 PDF
  [3/4]  POST /api/v1/datasets/{ds_id}/chunks               触发 deepdoc 视觉解析
         GET  /api/v1/datasets/{ds_id}/documents?id=...      轮询直到 run == DONE
  [4/4]  GET  /api/v1/datasets/{ds_id}/documents/{doc_id}/chunks  分页拉取全量切片
  finally  DELETE /api/v1/datasets                          彻底销毁临时 dataset

端点与字段严格对照 test(2).py，已过真实联调验证。

输出格式（每条 chunk）：
  {
    "text":        str,   # 切片正文
    "type":        str,   # "table" | "text"（依据 image_id 判断）
    "is_abstract": bool,  # 启发式检测摘要段落
    "trace_id":    str,   # {doc_name}_p{page}_c{idx}_{type}
  }
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)

# ── 摘要段落启发式关键词（匹配生物医学文献首页摘要）────────────────────
_ABSTRACT_SIGNALS = ("abstract", "summary", "摘要", "overview", "synopsis")


def _is_done(run_value: Any) -> bool:
    if run_value is None:
        return False
    return str(run_value).upper() in {"3", "DONE"}


def _is_fail(run_value: Any) -> bool:
    if run_value is None:
        return False
    return str(run_value).upper() in {"4", "FAIL"}


def _detect_is_abstract(text: str, page_num: int) -> bool:
    """摘要通常在第 1-2 页，且段落头部含 abstract/summary/摘要 等关键词。"""
    if page_num > 2:
        return False
    head = text.lower().strip()[:200]
    return any(kw in head for kw in _ABSTRACT_SIGNALS)


class RAGFlowParser:
    """
    通过 RAGFlow HTTP API 完成 PDF 视觉解析。

    每次 parse() 调用都会：
      1. 创建一个以文件名命名的临时 dataset
      2. 上传 → 触发 → 轮询 → 拉取切片
      3. 在 finally 中彻底删除该 dataset，保证无资源泄漏

    典型用法::

        parser = RAGFlowParser()          # 从 .env 读取环境变量
        chunks = parser.parse("paper.pdf")
    """

    POLL_INTERVAL_SEC: int = 3     # 与 test(2).py 保持一致
    POLL_TIMEOUT_SEC:  int = int(os.getenv("RAGFLOW_POLL_TIMEOUT_SEC", "600"))
    CHUNK_PAGE_SIZE:   int = 1024  # 与 test(2).py 保持一致

    def __init__(
        self,
        api_key:  str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key  = api_key  or os.getenv("RAGFLOW_API_KEY",  "")
        # BASE_URL 不含 /api/v1，由各方法内部拼接
        self.base_url = (base_url or os.getenv("RAGFLOW_API_BASE_URL", "")).rstrip("/")

        if not self.api_key:
            raise ValueError("缺少 RAGFLOW_API_KEY，请在 .env 中配置")
        if not self.base_url:
            raise ValueError("缺少 RAGFLOW_API_BASE_URL，请在 .env 中配置")

        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self.api_key}"

    # ──────────────────────────────────────────────────────────────────
    # 公开接口
    # ──────────────────────────────────────────────────────────────────

    def parse(
        self,
        pdf_path: str | Path,
        chunk_method: str = "paper",
    ) -> List[Dict]:
        """
        解析单篇 PDF，返回 Orchestrator 格式的 chunk 列表。

        Args:
            pdf_path:     本地 PDF 路径。
            chunk_method: RAGFlow 切块策略，"paper" 针对学术文献优化。

        Returns:
            [{"text", "type", "is_abstract", "trace_id"}, ...]

        Raises:
            RuntimeError:  API 业务错误或解析失败。
            TimeoutError:  轮询超时。
            requests.RequestException: 网络层异常。
        """
        pdf_path   = Path(pdf_path)
        dataset_id = None
        doc_id     = None

        try:
            # ── [1/4] 新建临时 dataset ────────────────────────────────
            dataset_id = self._create_dataset(pdf_path.name, chunk_method)
            logger.info("[1/4] Dataset 创建成功: %s", dataset_id)

            # ── [2/4] 上传 PDF ────────────────────────────────────────
            doc_id = self._upload(pdf_path, dataset_id)
            logger.info("[2/4] 上传成功: %s", doc_id)

            # ── [3/4] 触发解析 + 轮询 ────────────────────────────────
            self._trigger_parse(dataset_id, doc_id)
            logger.info("[3/4] 已触发解析，等待完成...")
            self._poll_until_done(dataset_id, doc_id)

            # ── [4/4] 拉取切片并映射 ──────────────────────────────────
            chunks = self._fetch_and_map_chunks(dataset_id, doc_id, pdf_path.name)
            logger.info("[4/4] 解析完成，共 %d 个 chunk（表格块: %d）",
                        len(chunks), sum(1 for c in chunks if c['type'] == 'table'))
            return chunks

        finally:
            # ── 无论成功/失败，必须销毁临时 dataset ──────────────────
            if dataset_id:
                self._delete_dataset(dataset_id)
                logger.info("临时 dataset 已清理")

    # ──────────────────────────────────────────────────────────────────
    # [1/4] 新建临时 dataset
    # ──────────────────────────────────────────────────────────────────

    def _create_dataset(self, filename: str, chunk_method: str) -> str:
        resp = self._session.post(
            f"{self.base_url}/api/v1/datasets",
            headers={"Content-Type": "application/json"},
            json={
                "name":         f"tmp_{filename}",
                "chunk_method": chunk_method,
            },
            timeout=60,
        )
        resp.raise_for_status()
        body = _check_code(resp, step="create_dataset")
        return body["data"]["id"]

    # ──────────────────────────────────────────────────────────────────
    # [2/4] 上传 PDF
    # ──────────────────────────────────────────────────────────────────

    def _upload(self, pdf_path: Path, dataset_id: str, max_retries: int = 3) -> str:
        url = f"{self.base_url}/api/v1/datasets/{dataset_id}/documents"
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info("[上传] 第 %d/%d 次尝试...", attempt, max_retries)
                with open(pdf_path, "rb") as f:
                    resp = self._session.post(
                        url,
                        files={"file": (pdf_path.name, f, "application/pdf")},
                        timeout=300,
                    )
                resp.raise_for_status()
                body = _check_code(resp, step="upload")
                return body["data"][0]["id"]
            # [V1] 仅捕获网络相关异常，避免 MemoryError 等非网络问题被掩盖
            except (requests.RequestException, ConnectionError, TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    logger.warning("[上传] 失败（%s），5s 后重试...", exc)
                    time.sleep(5)
        raise last_exc  # type: ignore[misc]

    # ──────────────────────────────────────────────────────────────────
    # [3/4-a] 触发解析
    # ──────────────────────────────────────────────────────────────────

    def _trigger_parse(self, dataset_id: str, doc_id: str) -> None:
        resp = self._session.post(
            f"{self.base_url}/api/v1/datasets/{dataset_id}/chunks",
            headers={"Content-Type": "application/json"},
            json={"document_ids": [doc_id]},
            timeout=60,
        )
        resp.raise_for_status()
        _check_code(resp, step="trigger_parse")

    # ──────────────────────────────────────────────────────────────────
    # [3/4-b] 轮询直到 run == DONE
    # ──────────────────────────────────────────────────────────────────

    def _poll_until_done(self, dataset_id: str, doc_id: str) -> None:
        url     = f"{self.base_url}/api/v1/datasets/{dataset_id}/documents"
        elapsed = 0

        while elapsed < self.POLL_TIMEOUT_SEC:
            try:
                resp = self._session.get(
                    url,
                    params={"id": doc_id, "page": 1, "page_size": 1},
                    timeout=60,
                )
                resp.raise_for_status()
                docs = resp.json()["data"].get("docs", [])

                if not docs:
                    raise RuntimeError(f"轮询找不到 document_id={doc_id}")

                doc      = docs[0]
                run      = doc.get("run")
                progress = doc.get("progress", "?")
                logger.info("[轮询] run=%r  progress=%s", run, progress)

                if _is_done(run):
                    return
                if _is_fail(run):
                    raise RuntimeError(
                        f"RAGFlow 解析失败: {doc.get('progress_msg', '')}"
                    )

            except RuntimeError:
                raise
            except requests.RequestException as e:
                # [V3] DNS 永久失败立即终止，不浪费 10 分钟重试
                cause = e.__context__ or e.__cause__
                if isinstance(cause, socket.gaierror):
                    raise RuntimeError(
                        f"DNS 解析失败，无法访问 RAGFlow 服务，请检查网络: {e}"
                    ) from e
                logger.warning("[轮询] 网络异常: %s，%ds 后重试...", e, self.POLL_INTERVAL_SEC)

            time.sleep(self.POLL_INTERVAL_SEC)
            elapsed += self.POLL_INTERVAL_SEC

        raise TimeoutError(f"轮询超时（>{self.POLL_TIMEOUT_SEC}s），doc_id={doc_id}")

    # ──────────────────────────────────────────────────────────────────
    # [4/4] 分页拉取全量切片并映射
    # ──────────────────────────────────────────────────────────────────

    def _fetch_and_map_chunks(
        self, dataset_id: str, doc_id: str, doc_name: str
    ) -> List[Dict]:
        url      = f"{self.base_url}/api/v1/datasets/{dataset_id}/documents/{doc_id}/chunks"
        all_raw: List[Dict] = []
        page     = 1

        while True:
            resp = self._session.get(
                url,
                params={"page": page, "page_size": self.CHUNK_PAGE_SIZE},
                timeout=60,
            )
            resp.raise_for_status()
            data   = resp.json()["data"]
            chunks = data.get("chunks", [])

            if not chunks:
                break

            all_raw.extend(chunks)

            # 不足一页说明已是最后一页
            if len(chunks) < self.CHUNK_PAGE_SIZE:
                break

            page += 1
            time.sleep(0.05)   # 与 test(2).py 保持一致，礼貌性限速

        return [_map_chunk(raw, idx, doc_name) for idx, raw in enumerate(all_raw)]

    # ──────────────────────────────────────────────────────────────────
    # finally：销毁临时 dataset
    # ──────────────────────────────────────────────────────────────────

    def _delete_dataset(self, dataset_id: str) -> None:
        try:
            self._session.delete(
                f"{self.base_url}/api/v1/datasets",
                headers={"Content-Type": "application/json"},
                json={"ids": [dataset_id]},
                timeout=60,
            )
        except Exception:
            # [V4] 清理失败记录到 logger，便于后续手动清理
            logger.warning("临时 dataset %s 清理失败，请手动删除", dataset_id, exc_info=True)


# ──────────────────────────────────────────────────────────────────────
# 模块级工具函数
# ──────────────────────────────────────────────────────────────────────

def _check_code(resp: requests.Response, step: str) -> Dict:
    """统一校验 RAGFlow 业务码，非 0 立即抛出 RuntimeError。"""
    try:
        body = resp.json()
    except json.JSONDecodeError as exc:
        # [V5] 明确捕获 JSONDecodeError，避免其他 ValueError 被误报为"响应非 JSON"
        raise RuntimeError(
            f"[{step}] 响应非 JSON (HTTP {resp.status_code}): {resp.text[:200]}"
        ) from exc

    code = body.get("code", 0)
    if code != 0:
        msg = body.get("message") or body.get("msg") or body
        raise RuntimeError(f"[{step}] RAGFlow 业务错误 code={code}: {msg}")

    return body


def _map_chunk(raw: Dict, index: int, doc_name: str) -> Dict:
    """
    将 RAGFlow 原始 chunk 映射为 Orchestrator 统一格式。

      content            → text
      image_id 非空       → type = "table"
      positions[0][0]    → page_num
      启发式 abstract 检测 → is_abstract
    """
    text     = (raw.get("content") or "").strip()
    image_id = (raw.get("image_id") or "").strip()

    # paper 模式下几乎每个 chunk 都有 image_id（渲染图），不能单靠它判断。
    # 改为：内容含 Markdown 表格行（含 | 且行数 >= 2）才视为 table。
    lines = [l for l in text.splitlines() if "|" in l]
    chunk_type = "table" if len(lines) >= 2 else "text"

    # 提取物理页码
    page_num  = 1
    positions = raw.get("positions") or []
    if positions and isinstance(positions[0], (list, tuple)):
        try:
            page_num = int(positions[0][0])
        except (ValueError, IndexError, TypeError):
            pass

    is_abstract = _detect_is_abstract(text, page_num)
    trace_id    = f"{doc_name}_p{page_num}_c{index}_{chunk_type}"

    return {
        "text":        text,
        "type":        chunk_type,
        "is_abstract": is_abstract,
        "trace_id":    trace_id,
    }
