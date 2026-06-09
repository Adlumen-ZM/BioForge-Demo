"""
3.0 Pipeline Orchestrator — 调度中枢（4 表版）

盲盒自驱动模式流水线：
  阶段一（自主侦察）：从 table / abstract 块发现实验实体名单，同步提取论文元数据
  阶段二（定向狙击）：遍历名单，Retriever → EntityExtractor，逐一抽取嵌套结构

返回值（process_pdf）：
  {
    "paper_meta": { doi, pmid, title, ... },       # paper 表字段
    "entities":   [ { entity_name_raw, functions, ... }, ... ]   # 嵌套 record/function/evidence
  }

内存隔离底线：
  每篇 PDF 独占一个 hash 命名的临时 ChromaDB Collection，
  finally 块必须销毁，防止 OOM 与串库。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional

from rag.extraction.llm_extractor import (
    EntityExtractor,
    ExtractionFormatError,
    PaperExtractor,
    _default_paper_meta,
)
from rag.retrieval.bge_hybrid_retriever import BGEHybridRetriever

logger = logging.getLogger(__name__)

# ── Scout 阶段 Prompt（职责：发现实体名单，不做深度提取）────────────────────

_SCOUT_SYSTEM_PROMPT = """\
你是一个生物医学文献侦察引擎。
你的唯一任务是：从给定的文献文本中，识别本文实验研究的所有生物活性肽段/蛋白/生物矿化功能分子的名称。

【行为约束】
1. 只返回一个合法的 JSON 对象，格式为 {"entities": ["名称1", "名称2", ...]}。
2. 不附加任何解释或多余文字。
3. 识别范围：包含且不限于 —— 肽段序列名、蛋白名称、融合肽、功能肽、矿化诱导因子、
   釉质结合肽、牙本质基质蛋白衍生肽等生物矿化领域的实验材料名称。
4. 若无法识别任何实验材料，返回 {"entities": []}。
5. 绝对禁止捏造文中未出现的名称。\
"""

_SCOUT_USER_TEMPLATE = """\
以下是本文的摘要与关键文本内容（已标注来源区块 ID）：

{context}

请识别并返回本文实验研究的全部生物活性肽段/蛋白/功能分子名称。\
"""


def _lazy_openai():
    try:
        import openai  # noqa: PLC0415
        return openai
    except ImportError as e:
        raise ImportError("请先安装 openai：pip install openai") from e


class PipelineOrchestrator:
    """
    单篇 PDF 的全生命周期调度器（4 表版）。

    典型用法::

        orchestrator = PipelineOrchestrator(
            retriever, paper_extractor, entity_extractor, chroma_client
        )
        result = orchestrator.process_pdf(pdf_path, chunks)

    返回值为 {"paper_meta": {...}, "entities": [...]}。
    """

    def __init__(
        self,
        retriever: BGEHybridRetriever,
        paper_extractor: PaperExtractor,
        entity_extractor: EntityExtractor,
        chroma_client: Any,
        scout_model: str = "gpt-4o",
        scout_api_key: Optional[str] = None,
        scout_base_url: Optional[str] = None,
    ) -> None:
        self.retriever        = retriever
        self.paper_extractor  = paper_extractor
        self.entity_extractor = entity_extractor
        self.chroma_client    = chroma_client
        self.scout_model      = scout_model
        self._scout_api_key   = scout_api_key
        self._scout_base_url  = scout_base_url
        self._scout_llm: Any  = None
        self.trace_records: List[Dict] = []   # 每次 process_pdf 前清空

    # ──────────────────────────────────────────────────────────────────
    # 公开接口
    # ──────────────────────────────────────────────────────────────────

    def _emit(self, record: Dict) -> None:
        """将一条 trace 记录追加到 self.trace_records。"""
        record.setdefault("created_at",
                          datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z")
        self.trace_records.append(record)

    def process_pdf(
        self,
        pdf_path: str,
        chunks: List[Dict],
        paper_id: str = "",
        retrieval_threshold: float = 0.1,
        retrieval_top_k: int = 8,
    ) -> Dict[str, Any]:
        """
        处理单篇 PDF 的完整流水线。

        Returns:
            {
              "paper_meta": { paper 表字段 },
              "entities":   [ 嵌套实体 dict, ... ]
            }
            处理完全失败时 entities 为空列表，paper_meta 为默认占位。
        """
        collection_name = _make_collection_name(pdf_path)
        collection = None
        result: Dict[str, Any] = {"paper_meta": {}, "entities": []}
        self.trace_records.clear()

        logger.info("=" * 60)
        logger.info("[%s] PDF 处理开始", pdf_path)
        logger.info("[%s] 临时向量库名称: %s", pdf_path, collection_name)

        try:
            collection = self.chroma_client.create_collection(collection_name)
            logger.info("[%s] ChromaDB Collection 已创建", pdf_path)

            normalized = [_normalize_chunk(c) for c in chunks]
            _populate_collection(collection, normalized)
            logger.info("[%s] %d 条 chunk 已写入 ChromaDB", pdf_path, len(normalized))

            retriever_chunks = [
                {"chunk_id": c["chunk_id"], "text": c["text"]} for c in normalized
            ]
            self.retriever.build_index(retriever_chunks)
            logger.info("[%s] BGE-M3 内存索引构建完成", pdf_path)

            # ── 阶段一：自主侦察 ────────────────────────────────────
            logger.info("[%s] >>> 阶段一：自主侦察（实体名单 + 论文元数据）", pdf_path)
            scout_chunks = self._get_scout_chunks(normalized, pdf_path)
            scout_context = "\n\n".join(
                f"--- [{c['chunk_id']}] ---\n{c['text']}" for c in scout_chunks
            )

            # 并行运行：LLM 实体发现 + 论文元数据提取（都用同一个 scout_context）
            scout_chunk_ids = [c["chunk_id"] for c in scout_chunks]
            try:
                entity_list = self._call_scout_llm(scout_context)
                self._emit({
                    "paper_id":      paper_id,
                    "source_pdf":    pdf_path,
                    "stage":         "scout_entity",
                    "entity_name":   "",
                    "queries_used":  json.dumps(["(table+abstract chunks)"]),
                    "chunks_hit_ids": json.dumps(scout_chunk_ids),
                    "context_chars": len(scout_context),
                    "llm_model":     self.scout_model,
                    "llm_raw_output": self._scout_llm and
                                      getattr(self, "_scout_last_raw", "")[:2000] or "",
                    "status":        "success",
                    "error_msg":     "",
                    "entities_found": json.dumps(entity_list),
                })
            except Exception as exc:
                logger.exception("[%s] 侦察 LLM 调用失败", pdf_path)
                self._emit({
                    "paper_id": paper_id, "source_pdf": pdf_path,
                    "stage": "scout_entity", "entity_name": "",
                    "queries_used": json.dumps(["(table+abstract chunks)"]),
                    "chunks_hit_ids": json.dumps(scout_chunk_ids),
                    "context_chars": len(scout_context),
                    "llm_model": self.scout_model, "llm_raw_output": "",
                    "status": "error", "error_msg": str(exc), "entities_found": "[]",
                })
                entity_list = []

            try:
                paper_meta = self.paper_extractor.extract(scout_context)
                self._emit({
                    "paper_id":      paper_id,
                    "source_pdf":    pdf_path,
                    "stage":         "scout_paper_meta",
                    "entity_name":   "",
                    "queries_used":  json.dumps(["(table+abstract chunks)"]),
                    "chunks_hit_ids": json.dumps(scout_chunk_ids),
                    "context_chars": len(scout_context),
                    "llm_model":     self.paper_extractor.model,
                    "llm_raw_output": self.paper_extractor._last_raw,
                    "status":        "success",
                    "error_msg":     "",
                    "entities_found": "",
                })
            except Exception as exc:
                logger.exception("[%s] 论文元数据提取失败，使用默认占位", pdf_path)
                self._emit({
                    "paper_id": paper_id, "source_pdf": pdf_path,
                    "stage": "scout_paper_meta", "entity_name": "",
                    "queries_used": json.dumps(["(table+abstract chunks)"]),
                    "chunks_hit_ids": json.dumps(scout_chunk_ids),
                    "context_chars": len(scout_context),
                    "llm_model": self.paper_extractor.model, "llm_raw_output": "",
                    "status": "error", "error_msg": str(exc), "entities_found": "",
                })
                paper_meta = _default_paper_meta()

            result["paper_meta"] = paper_meta
            logger.info("[%s] 论文元数据提取完成: title=%r", pdf_path, paper_meta.get("title"))

            if not entity_list:
                logger.warning("[%s] 侦察未发现任何实验实体，跳过阶段二", pdf_path)
                return result

            logger.info("[%s] 侦察完成，共发现 %d 个实体: %s",
                        pdf_path, len(entity_list), entity_list)

            # ── 阶段二：定向狙击 ────────────────────────────────────
            logger.info("[%s] >>> 阶段二：定向狙击（逐实体检索+抽取）", pdf_path)
            for entity in entity_list:
                entity_dict = self._strike_entity(
                    entity, pdf_path, retrieval_threshold, retrieval_top_k,
                    paper_id=paper_id,
                )
                if entity_dict is not None:
                    result["entities"].append(entity_dict)

            logger.info("[%s] 阶段二完成，成功抽取 %d / %d 条实体",
                        pdf_path, len(result["entities"]), len(entity_list))

        except Exception:
            logger.exception("[%s] 流水线发生未预期异常，已隔离", pdf_path)

        finally:
            if collection is not None:
                try:
                    self.chroma_client.delete_collection(collection_name)
                    logger.info("[%s] 临时向量库 %s 已销毁", pdf_path, collection_name)
                except Exception:
                    logger.warning("[%s] 销毁临时向量库失败", pdf_path, exc_info=True)

            logger.info("[%s] PDF 处理结束，共输出 %d 条实体",
                        pdf_path, len(result["entities"]))
            logger.info("=" * 60)

        return result

    # ──────────────────────────────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────────────────────────────

    def _get_scout_chunks(self, normalized: List[Dict], pdf_path: str) -> List[Dict]:
        """选取侦察用的 chunk 子集：优先 table/abstract，否则均匀采样 20 块。"""
        # [O2] 空列表守卫：避免后续 n//sample_size 除零崩溃
        if not normalized:
            logger.warning("[%s] chunk 列表为空，无法选取侦察块", pdf_path)
            return []
        scout = [c for c in normalized if c["type"] == "table" or c["is_abstract"]]
        logger.info("[%s] [DEBUG] 全部 chunk=%d，table/abstract=%d",
                    pdf_path, len(normalized), len(scout))
        if scout:
            return scout
        n = len(normalized)
        sample_size = min(20, n)
        step = max(1, n // sample_size)
        scout = normalized[::step][:sample_size]
        logger.warning("[%s] 无 table/abstract 块，均匀采样 %d 块（共 %d）",
                       pdf_path, len(scout), n)
        return scout

    # 补充检索 query 列表：覆盖常见实验技术，防止单纯用实体名漏掉功能相关段落
    _SUPPLEMENT_QUERIES = [
        "binding capacity FITC fluorescence CLSM confocal",      # surface_localization
        "microhardness nanoindentation Vickers elastic modulus",  # mechanical_property
        "Raman spectroscopy mineral content recovery",            # mineral_quantity
        "XRD crystal orientation diffraction peak",               # crystal_structure
        "SEM FESEM TEM morphology nanocrystal",                   # mineral_morphology
        "EDX EDXS elemental analysis calcium phosphorus",         # elemental_composition
    ]

    def _strike_entity(
        self,
        entity: str,
        pdf_path: str,
        threshold: float,
        top_k: int,
        paper_id: str = "",
    ) -> Optional[Dict]:
        """
        阶段二（单实体）：多 query 检索 → 合并去重上下文 → EntityExtractor。

        除了用实体名本身检索，还用预设的实验技术关键词补充检索，
        确保 FITC/CLSM、microhardness 等功能段落不被遗漏。
        """
        try:
            seen_ids: set = set()
            blocks: list[str] = []
            query_log: list[dict] = []   # trace 用：记录每条 query 命中了哪些 chunk

            def _collect(query: str, k: int) -> None:
                raw = self.retriever.retrieve(query, threshold=threshold, top_k=k)
                new_ids: list[str] = []
                for block in raw.split("\n--- [源区块 ID:"):
                    if not block.strip():
                        continue
                    bid = block.split("]")[0].strip()
                    if bid not in seen_ids:
                        seen_ids.add(bid)
                        blocks.append(("--- [源区块 ID:" if blocks else "") + block)
                        new_ids.append(bid)
                if new_ids:
                    query_log.append({"query": query, "new_chunks": new_ids})

            _collect(entity, top_k)
            logger.info("[DEBUG] 实体 '%s' 主检索命中 %d 块", entity, len(blocks))

            for q in self._SUPPLEMENT_QUERIES:
                before = len(blocks)
                _collect(q, max(2, top_k // 2))
                added = len(blocks) - before
                if added:
                    logger.info("[DEBUG] 补充检索 '%s' 新增 %d 块", q[:40], added)

            context = "\n".join(blocks)

            if not context.strip():
                logger.warning("[%s] 实体 '%s' 所有检索均无命中，跳过", pdf_path, entity)
                self._emit({
                    "paper_id": paper_id, "source_pdf": pdf_path,
                    "stage": "strike", "entity_name": entity,
                    "queries_used": json.dumps([ql["query"] for ql in query_log]),
                    "chunks_hit_ids": json.dumps(list(seen_ids)),
                    "context_chars": 0,
                    "llm_model": self.entity_extractor.model,
                    "llm_raw_output": "", "entities_found": "",
                    "status": "skipped", "error_msg": "no chunks retrieved",
                })
                return None

            logger.info("[DEBUG] 实体 '%s' 合并后 context 总长=%d 字符，共 %d 块",
                        entity, len(context), len(seen_ids))
            entity_dict = self.entity_extractor.extract(entity, context)
            logger.info("[%s] 实体 '%s' 抽取完成，功能数=%d",
                        pdf_path, entity, len(entity_dict.get("functions", [])))
            self._emit({
                "paper_id": paper_id, "source_pdf": pdf_path,
                "stage": "strike", "entity_name": entity,
                "queries_used": json.dumps([ql["query"] for ql in query_log]),
                "chunks_hit_ids": json.dumps(list(seen_ids)),
                "context_chars": len(context),
                "llm_model": self.entity_extractor.model,
                "llm_raw_output": self.entity_extractor._last_raw,
                "entities_found": "",
                "status": "success", "error_msg": "",
            })
            return entity_dict

        except ExtractionFormatError:
            logger.error("[%s] 实体 '%s' LLM 格式错误，已隔离跳过", pdf_path, entity,
                         exc_info=True)
            self._emit({
                "paper_id": paper_id, "source_pdf": pdf_path,
                "stage": "strike", "entity_name": entity,
                "queries_used": "", "chunks_hit_ids": "",
                "context_chars": 0,
                "llm_model": self.entity_extractor.model,
                "llm_raw_output": self.entity_extractor._last_raw,
                "entities_found": "",
                "status": "error", "error_msg": "ExtractionFormatError",
            })
            return None

        except Exception as exc:
            # [O1] 捕获 API 层异常（网络超时、429、500 等），隔离单实体失败
            # 避免穿透到外层 except 导致当前 PDF 剩余所有实体全部丢失
            logger.error("[%s] 实体 '%s' API/未预期异常，已隔离跳过: %s",
                         pdf_path, entity, exc, exc_info=True)
            self._emit({
                "paper_id": paper_id, "source_pdf": pdf_path,
                "stage": "strike", "entity_name": entity,
                "queries_used": "", "chunks_hit_ids": "",
                "context_chars": 0,
                "llm_model": self.entity_extractor.model,
                "llm_raw_output": "",
                "entities_found": "",
                "status": "error", "error_msg": str(exc),
            })
            return None

    def _call_scout_llm(self, context: str) -> List[str]:
        """调用 LLM 侦察，返回实验实体名称列表。可 monkey-patch 用于测试。"""
        llm = self._get_scout_llm()
        response = llm.chat.completions.create(
            model=self.scout_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SCOUT_SYSTEM_PROMPT},
                {"role": "user",   "content": _SCOUT_USER_TEMPLATE.format(context=context)},
            ],
            temperature=0.0,
        )
        raw = response.choices[0].message.content
        logger.info("[DEBUG] Scout Raw: %s", raw)
        data = json.loads(raw)

        if isinstance(data, dict):
            for key in ("entities", "peptides", "materials", "names", "list", "results"):
                if key in data and isinstance(data[key], list):
                    # [O3] 过滤非字符串元素，避免 str(dict) 序列化污染检索 query
                    entities = []
                    for e in data[key]:
                        if not e:
                            continue
                        if not isinstance(e, str):
                            logger.warning("[DEBUG] Scout 返回非字符串实体元素，已跳过: %r", e)
                            continue
                        stripped = e.strip()
                        if stripped:
                            entities.append(stripped)
                    logger.info("[DEBUG] Scout 解析到实体（key=%r）: %s", key, entities)
                    return entities

        logger.warning("[DEBUG] Scout 返回非预期格式: %s", data)
        return []

    def _get_scout_llm(self) -> Any:
        """懒加载 Scout 专用 OpenAI client。"""
        if self._scout_llm is None:
            openai = _lazy_openai()
            self._scout_llm = openai.OpenAI(
                api_key=self._scout_api_key or os.environ.get("OPENAI_API_KEY"),
                base_url=self._scout_base_url,
            )
        return self._scout_llm


# ──────────────────────────────────────────────────────────────────────
# 模块级工具函数
# ──────────────────────────────────────────────────────────────────────

def _make_collection_name(pdf_path: str) -> str:
    digest = hashlib.md5(str(pdf_path).encode("utf-8")).hexdigest()[:16]
    return f"tmp_{digest}"


def _normalize_chunk(c: Dict) -> Dict:
    return {
        "chunk_id":    c.get("trace_id") or c.get("chunk_id") or "unknown",
        "text":        c.get("text", ""),
        "type":        c.get("type", "text"),
        "is_abstract": bool(c.get("is_abstract", False)),
    }


def _populate_collection(collection: Any, chunks: List[Dict]) -> None:
    if not chunks:
        return
    collection.add(
        documents=[c["text"] for c in chunks],
        ids=[c["chunk_id"] for c in chunks],
        metadatas=[
            {"type": c["type"], "is_abstract": str(c["is_abstract"])}
            for c in chunks
        ],
    )
