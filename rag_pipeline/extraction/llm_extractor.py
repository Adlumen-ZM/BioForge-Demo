"""
3.3 大模型提取与溯源层 — 4 表关系型数据库版

职责：
  PaperExtractor   — 从侦察阶段上下文提取论文元数据（对应 paper 表）
  EntityExtractor  — 对单个实体提取多层嵌套结构：
                     entity 层（对应 paper_entity_record 表）
                     └─ functions[] 层（对应 record_function 表）
                        └─ evidence_items[] 层（对应 function_assay_evidence 表）

约束：
  JSON mode 强制开启；jsonschema 二次校验；格式非法时抛 ExtractionFormatError。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

import jsonschema

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 共享枚举常量
# ─────────────────────────────────────────────────────────────────────────────

_EVIDENCE_LEVEL_ENUM = ["in_vitro", "ex_vivo", "animal_in_vivo", "clinical", "in_silico", "unclear"]
_TRACE_STATUS_ENUM   = ["complete", "partial", "missing", "disputed"]

# ─────────────────────────────────────────────────────────────────────────────
# Table 1：paper 元数据 Schema
# ─────────────────────────────────────────────────────────────────────────────

PAPER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["doi", "title", "journal_title", "publication_year",
                 "full_text_availability", "retrieval_source"],
    "additionalProperties": False,
    "properties": {
        "doi":                    {"type": ["string", "null"]},
        "pmid":                   {"type": ["string", "null"]},
        "title":                  {"type": "string"},
        "journal_title":          {"type": "string"},
        "publication_year":       {"type": ["integer", "null"]},
        "abstract":               {"type": ["string", "null"]},
        "keywords":               {"type": ["array",  "null"], "items": {"type": "string"}},
        "full_text_availability": {
            "type": "string",
            "enum": ["open_access", "subscription", "preprint", "unknown"],
        },
        "retrieval_source": {
            "type": "string",
            "enum": ["pubmed", "crossref", "manual_entry", "agent_crawl"],
        },
        "curator_note": {"type": ["string", "null"]},
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Table 2/3/4：实体嵌套 Schema
# ─────────────────────────────────────────────────────────────────────────────

_EVIDENCE_ITEM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["evidence_level", "assay_category", "validation_method",
                 "result_text_summary", "trace_status"],
    "additionalProperties": False,
    "properties": {
        "evidence_level":          {"type": "string", "enum": _EVIDENCE_LEVEL_ENUM},
        "assay_category": {
            "type": "string",
            "enum": [
                "binding_affinity", "surface_localization", "retention_test",
                "crystal_structure", "mineral_morphology", "elemental_composition",
                "molecular_composition", "mechanical_property", "mineral_quantity",
                "lesion_morphology", "biological_response", "in_vivo_efficacy",
                "simulation", "other",
            ],
        },
        "validation_method_raw":   {"type": ["string", "null"]},
        "validation_method": {
            "type": "string",
            "enum": [
                "CLSM", "fluorescence_microscopy", "micro-CT", "nanoindentation",
                "SEM", "TEM", "AFM", "XRD", "FTIR", "EDX", "ICP-OES",
                "SPR", "ITC", "ELISA", "MTT",
                "molecular_docking", "MD_simulation", "other", "unclear",
            ],
        },
        "readout_main":            {"type": ["string", "null"]},
        "result_text_summary":     {"type": "string"},
        "result_value_raw":        {"type": ["string", "null"]},
        "result_value_normalized": {"type": ["object", "null"]},
        "source_locations":        {"type": ["array",  "null"], "items": {"type": "string"}},
        "text_to_evidence":        {"type": ["string", "null"]},
        "trace_status":            {"type": "string", "enum": _TRACE_STATUS_ENUM},
        "curator_note":            {"type": ["string", "null"]},
    },
}

_FUNCTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["function_layer", "function_label", "evidence_level",
                 "trace_status", "evidence_items"],
    "additionalProperties": False,
    "properties": {
        "function_layer": {
            "type": "string",
            "enum": ["binding", "kinetics", "crystallography", "protection", "biology", "other"],
        },
        "function_label": {
            "type": "string",
            "enum": [
                "adsorption", "localization", "ion_capture",
                "nucleation", "mineral_deposition", "crystal_growth_promotion",
                "phase_stabilization", "phase_transformation_promotion",
                "crystal_growth_inhibition", "crystal_orientation_modulation",
                "crystal_morphology_modulation",
                "anti_demineralization",
                "antimicrobial", "cell_adhesion_promotion",
                "other",
            ],
        },
        "function_source_raw": {"type": ["string", "null"]},
        "evidence_level":      {"type": "string", "enum": _EVIDENCE_LEVEL_ENUM},
        "text_to_function":    {"type": ["string", "null"]},
        "trace_status":        {"type": "string", "enum": _TRACE_STATUS_ENUM},
        "curator_note":        {"type": ["string", "null"]},
        "evidence_items":      {"type": "array", "items": _EVIDENCE_ITEM_SCHEMA},
    },
}

ENTITY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "entity_name_raw", "entity_name_normalized",
        "sequence_status", "design_source", "target_material", "target_substrate",
        "summary_functions", "evidence_overall_level", "trace_status", "functions",
    ],
    "additionalProperties": False,
    "properties": {
        "entity_name_raw":        {"type": "string"},
        "entity_name_normalized": {"type": "string"},
        "sequence_status": {
            "type": "string",
            "enum": ["explicit", "partial", "not_reported", "backtrace_required"],
        },
        "sequence_raw":        {"type": ["string", "null"]},
        "sequence_normalized": {"type": ["string", "null"]},
        "design_source_raw":   {"type": ["string", "null"]},
        "design_source": {
            "type": "string",
            "enum": ["natural_derived", "rational_design", "phage_display",
                     "computational", "synthetic", "unclear"],
        },
        "target_material_raw": {"type": ["string", "null"]},
        "target_material": {
            "type": "string",
            "enum": ["HAP", "collagen", "ACP", "other", "not_reported", "unclear"],
        },
        "target_substrate_raw": {"type": ["string", "null"]},
        "target_substrate": {
            "type": "string",
            "enum": ["enamel", "dentin", "bone", "mineral_surface",
                     "in_vitro_crystal", "other", "not_reported", "unclear"],
        },
        "summary_functions": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "adsorption", "localization", "mineral_deposition",
                    "phase_stabilization", "phase_transformation_promotion",
                    "nucleation", "crystal_growth_inhibition", "crystal_growth_promotion",
                    "crystal_orientation_modulation", "crystal_morphology_modulation",
                    "anti_demineralization", "ion_capture",
                    "antimicrobial", "cell_adhesion_promotion", "other",
                ],
            },
        },
        "evidence_overall_level": {"type": "string", "enum": _EVIDENCE_LEVEL_ENUM},
        "model_system_summary":   {"type": ["string", "null"]},
        "text_to_sequence":       {"type": ["string", "null"]},
        "trace_status":           {"type": "string", "enum": _TRACE_STATUS_ENUM},
        "curator_note":           {"type": ["string", "null"]},
        "functions":              {"type": "array", "items": _FUNCTION_SCHEMA},
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# System Prompts
# ─────────────────────────────────────────────────────────────────────────────

_PAPER_SYSTEM_PROMPT = """\
你是一个生物医学文献元数据提取引擎，专门从文献全文或摘要中提取论文的基础书目信息。

【行为约束】
1. 只能从下方"参考文本"中提取，绝对禁止捏造。
2. 只返回合法的 JSON 对象，不附加任何解释文字。
3. JSON 必须严格符合以下字段定义：
   {
     "doi":                    <string|null>   论文 DOI（如 "10.1016/j.xxx.2023.e23176"），找不到填 null,
     "pmid":                   <string|null>   PubMed ID，找不到填 null,
     "title":                  <string>        论文完整标题,
     "journal_title":          <string>        期刊名称,
     "publication_year":       <integer|null>  发表年份（4 位整数），找不到填 null,
     "abstract":               <string|null>   摘要全文，找不到填 null,
     "keywords":               <array|null>    关键词列表，如 ["enamel", "peptide"]，找不到填 null,
     "full_text_availability": <string>        枚举：open_access | subscription | preprint | unknown,
     "retrieval_source":       <string>        枚举：pubmed | crossref | manual_entry | agent_crawl,
     "curator_note":           <string|null>   任何值得注意的信息，无则填 null
   }
4. full_text_availability：文本中若有 open access / CC 许可 → open_access；否则填 unknown。
5. retrieval_source：若来自 PubMed → pubmed；来自 DOI 解析 → crossref；其余 → manual_entry。\
"""

_PAPER_USER_TEMPLATE = """\
以下是文献的摘要与首页内容（已标注来源区块 ID）：

{context}

请从上述文本中提取论文元数据，严格按照系统指令中的 JSON Schema 输出。\
"""

# ── 实体提取的 function_layer ↔ function_label 约束说明（嵌入 prompt）────────
_LAYER_LABEL_CONSTRAINT = """\
function_layer 与 function_label 的对应关系（必须严格遵守）：
  binding       → adsorption, localization, ion_capture
  kinetics      → nucleation, mineral_deposition, crystal_growth_promotion
  crystallography → phase_stabilization, phase_transformation_promotion,
                    crystal_growth_inhibition, crystal_orientation_modulation,
                    crystal_morphology_modulation
  protection    → anti_demineralization
  biology       → antimicrobial, cell_adhesion_promotion
  other         → other\
"""

_ENTITY_SYSTEM_PROMPT = f"""\
你是一个生物医学文献结构化提取引擎，专门从文献文本中提取生物矿化相关肽段/蛋白的多层实验证据。

【提取目标层次】
1. 实体层（entity）：肽段/蛋白的基本属性（序列、设计来源、靶标材料、靶标基底、功能概要）
2. 功能层（functions）：该实体的每项独立功能（功能分类、证据级别）
3. 证据层（evidence_items）：支撑该功能的具体实验（检测方法、结果描述）

【行为约束】
1. 只能从下方"参考文本"中提取，绝对禁止捏造。
2. 只返回合法的 JSON 对象，不附加任何解释文字。
3. {_LAYER_LABEL_CONSTRAINT}
4. 枚举字段必须选取枚举表中的值（详见 User Prompt 中的 Schema 说明）。
5. 若某字段在文中无法确定，填 null 或 unclear（视字段类型）。
6. functions 至少包含 1 条记录；每条 function 的 evidence_items 至少包含 1 条记录。
7. text_to_* 字段：填写文中支持该条目的原始句子（可供人工核查），若无则填 null。

【assay_category 识别规则（必须优先于默认归类）】
以下实验场景有明确的 assay_category 对应，必须严格使用，不得归入 "other"：
  - FITC / 荧光素标记肽段 + CLSM / 共聚焦显微镜 / 荧光显微镜观察结合/吸附情况
      → assay_category = "surface_localization"
      → validation_method = "CLSM" 或 "fluorescence_microscopy"
      → 对应 function_label = "localization"（binding 层）
  - 微硬度测试（Vickers hardness / VHN）/ 弹性模量
      → assay_category = "mechanical_property"
      → validation_method = "other"（Vickers 硬度非纳米压痕，填 other）
  - 纳米压痕（nanoindentation）
      → assay_category = "mechanical_property"
      → validation_method = "nanoindentation"
  - Raman 光谱 / 拉曼光谱 分析矿物含量或矿化率
      → assay_category = "mineral_quantity"
      → validation_method = "other"（Raman 不在标准枚举中时填 other）
  - XRD / X 射线衍射 分析晶体取向或晶型
      → assay_category = "crystal_structure"
      → validation_method = "XRD"
  - FESEM / SEM / TEM 观察晶体或矿物形貌
      → assay_category = "mineral_morphology"
      → validation_method = "SEM" 或 "TEM"
  - EDX / EDXS / EDAX / EDS 元素分析
      → assay_category = "elemental_composition"
      → validation_method = "EDX"
  - 氨基酸侧链离子相互作用分析（理论推断，无实验检测）
      → assay_category = "other"，trace_status = "partial"\
"""

_ENTITY_USER_TEMPLATE = """\
【提取目标实体】
实体名称：{target_entity}

【JSON Schema 说明】
{{
  "entity_name_raw":        <string>        文中原始名称（与输入一致）,
  "entity_name_normalized": <string>        规范化名称（序列或标准命名）,
  "sequence_status":        <string>        explicit | partial | not_reported | backtrace_required,
  "sequence_raw":           <string|null>   文中原始氨基酸序列，无则 null,
  "sequence_normalized":    <string|null>   规范化单字母序列（全大写），无则 null,
  "design_source_raw":      <string|null>   文中描述设计来源的原文，无则 null,
  "design_source":          <string>        natural_derived | rational_design | phage_display | computational | synthetic | unclear,
  "target_material_raw":    <string|null>   文中靶标矿物原文，无则 null,
  "target_material":        <string>        HAP | collagen | ACP | other | not_reported | unclear,
  "target_substrate_raw":   <string|null>   文中靶标基底原文，无则 null,
  "target_substrate":       <string>        enamel | dentin | bone | mineral_surface | in_vitro_crystal | other | not_reported | unclear,
  "summary_functions":      <array>         该实体所有功能标签列表（枚举值从 functions[].function_label 聚合）,
  "evidence_overall_level": <string>        in_vitro | ex_vivo | animal_in_vivo | clinical | in_silico | unclear,
  "model_system_summary":   <string|null>   实验模型简述，无则 null,
  "text_to_sequence":       <string|null>   文中描述序列的原始句子，无则 null,
  "trace_status":           <string>        complete | partial | missing | disputed,
  "curator_note":           <string|null>   备注，无则 null,
  "functions": [
    {{
      "function_layer":    <string>        binding | kinetics | crystallography | protection | biology | other,
      "function_label":    <string>        见约束表（必须与 function_layer 匹配）,
      "function_source_raw": <string|null> 功能描述原文，无则 null,
      "evidence_level":    <string>        in_vitro | ex_vivo | animal_in_vivo | clinical | in_silico | unclear,
      "text_to_function":  <string|null>   支持该功能的原文句子，无则 null,
      "trace_status":      <string>        complete | partial | missing | disputed,
      "curator_note":      <string|null>   备注，无则 null,
      "evidence_items": [
        {{
          "evidence_level":          <string>        同上,
          "assay_category":          <string>        binding_affinity | surface_localization | retention_test | crystal_structure | mineral_morphology | elemental_composition | molecular_composition | mechanical_property | mineral_quantity | lesion_morphology | biological_response | in_vivo_efficacy | simulation | other,
          "validation_method_raw":   <string|null>   检测方法原文，无则 null,
          "validation_method":       <string>        CLSM | fluorescence_microscopy | micro-CT | nanoindentation | SEM | TEM | AFM | XRD | FTIR | EDX | ICP-OES | SPR | ITC | ELISA | MTT | molecular_docking | MD_simulation | other | unclear,
          "readout_main":            <string|null>   主要读数指标，无则 null,
          "result_text_summary":     <string>        结果的文字描述（必填）,
          "result_value_raw":        <string|null>   原始数值字符串，无则 null,
          "result_value_normalized": <object|null>   规范化数值对象，如 {{"value": 1.2, "unit": "MPa"}}，无则 null,
          "source_locations":        <array|null>    来源区块 ID 列表，如 ["paper_p3_c5_text"]，无则 null,
          "text_to_evidence":        <string|null>   支持该证据的原文句子，无则 null,
          "trace_status":            <string>        complete | partial | missing | disputed,
          "curator_note":            <string|null>   备注，无则 null
        }}
      ]
    }}
  ]
}}

【参考文本】
{context}

请严格按照系统指令与上述 JSON Schema，提取实体 "{target_entity}" 的全部结构化信息。\
"""


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _lazy_openai():
    try:
        import openai  # noqa: PLC0415
        return openai
    except ImportError as e:
        raise ImportError("请先安装 openai：pip install openai") from e


def _make_client(api_key: str | None, base_url: str | None):
    openai = _lazy_openai()
    return openai.OpenAI(
        api_key=api_key or os.environ.get("OPENAI_API_KEY"),
        base_url=base_url,
    )


def _parse_and_validate(raw: str, schema: Dict, label: str) -> Dict[str, Any]:
    """解析 JSON 字符串并做 Schema 二次校验，失败时抛 ExtractionFormatError。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        # [E7] 截断 raw，避免将大段 LLM 响应（含版权文本）写入日志
        raise ExtractionFormatError(
            f"JSON 解析失败（{label}）: {e}\n原始响应（前500字符）: {raw[:500]!r}"
        ) from e
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        raise ExtractionFormatError(
            f"Schema 校验失败（{label}）: {e.message}\n原始数据: {data}"
        ) from e
    return data


# ─────────────────────────────────────────────────────────────────────────────
# PaperExtractor — 论文元数据（Table 1）
# ─────────────────────────────────────────────────────────────────────────────

class PaperExtractor:
    """
    从侦察上下文中提取论文级别元数据。

    典型用法::

        extractor = PaperExtractor(model="ark-code-latest", api_key=key, base_url=url)
        paper_meta = extractor.extract(context_str)
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model     = model
        self.client    = _make_client(api_key, base_url)
        self._last_raw = ""   # trace 用：保存最后一次 LLM 原始输出

    # [E1] 上下文长度上限：防止超过模型窗口导致静默截断
    _MAX_CONTEXT_CHARS = 30_000

    def extract(self, context: str) -> Dict[str, Any]:
        """
        Args:
            context: 拼装好的侦察上下文（摘要 + 表格块）

        Returns:
            符合 PAPER_SCHEMA 的 dict

        Raises:
            ExtractionFormatError
        """
        if not context.strip():
            logger.warning("paper meta context 为空，返回默认占位值")
            return _default_paper_meta()

        # [E1] 超长上下文截断
        if len(context) > self._MAX_CONTEXT_CHARS:
            logger.warning("[PaperExtractor] context 过长（%d chars），截断至 %d",
                           len(context), self._MAX_CONTEXT_CHARS)
            context = context[:self._MAX_CONTEXT_CHARS]

        user_prompt = _PAPER_USER_TEMPLATE.format(context=context)
        logger.info("[PaperExtractor] 调用 LLM，模型=%s", self.model)
        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _PAPER_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.0,
        )
        raw = response.choices[0].message.content
        self._last_raw = raw[:2000]
        logger.info("[PaperExtractor] Raw: %s", raw[:400])
        return _parse_and_validate(raw, PAPER_SCHEMA, "paper_meta")


# ─────────────────────────────────────────────────────────────────────────────
# EntityExtractor — 实体 + 功能 + 证据嵌套（Table 2/3/4）
# ─────────────────────────────────────────────────────────────────────────────

class EntityExtractor:
    """
    对单个实体提取嵌套结构：entity → functions → evidence_items。

    典型用法::

        extractor = EntityExtractor(model="ark-code-latest", api_key=key, base_url=url)
        entity_dict = extractor.extract("WGNYAYK", context_str)
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model     = model
        self.client    = _make_client(api_key, base_url)
        self._last_raw = ""   # trace 用：保存最后一次 LLM 原始输出

    def extract(self, target_entity: str, context: str) -> Dict[str, Any]:
        """
        Args:
            target_entity: 实体名称，如 "WGNYAYK"
            context:       检索到的参考文本（已附 Trace ID）

        Returns:
            符合 ENTITY_SCHEMA 的 dict

        Raises:
            ExtractionFormatError
        """
        if not context.strip():
            logger.info("[EntityExtractor] context 为空，返回 not_found 占位（目标: %s）", target_entity)
            return _default_entity(target_entity)

        # [E1] 超长上下文截断
        _MAX_CONTEXT_CHARS = 30_000
        if len(context) > _MAX_CONTEXT_CHARS:
            logger.warning("[EntityExtractor] context 过长（%d chars），截断至 %d（目标: %s）",
                           len(context), _MAX_CONTEXT_CHARS, target_entity)
            context = context[:_MAX_CONTEXT_CHARS]

        user_prompt = _ENTITY_USER_TEMPLATE.format(
            target_entity=target_entity,
            context=context,
        )

        logger.info("[EntityExtractor] 调用 LLM，模型=%s，目标=%s", self.model, target_entity)
        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _ENTITY_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.0,
        )
        raw = response.choices[0].message.content
        self._last_raw = raw[:2000]
        logger.info("[EntityExtractor] Raw (target=%s): %s", target_entity, raw[:600])
        return _parse_and_validate(raw, ENTITY_SCHEMA, f"entity:{target_entity}")


# ─────────────────────────────────────────────────────────────────────────────
# 默认占位值
# ─────────────────────────────────────────────────────────────────────────────

def _default_paper_meta() -> Dict[str, Any]:
    return {
        "doi": None, "pmid": None,
        "title": "Unknown", "journal_title": "Unknown",
        "publication_year": None, "abstract": None, "keywords": None,
        "full_text_availability": "unknown",
        "retrieval_source": "manual_entry",
        # [E2] 使用英文短标记，避免中文诊断文本污染下游数据分析
        "curator_note": "EXTRACTION_SKIPPED:empty_context",
    }


def _default_entity(name: str) -> Dict[str, Any]:
    return {
        "entity_name_raw":        name,
        "entity_name_normalized": name,
        "sequence_status":        "not_reported",
        "sequence_raw":           None,
        "sequence_normalized":    None,
        "design_source_raw":      None,
        "design_source":          "unclear",
        "target_material_raw":    None,
        "target_material":        "unclear",
        "target_substrate_raw":   None,
        "target_substrate":       "unclear",
        "summary_functions":      [],
        "evidence_overall_level": "unclear",
        "model_system_summary":   None,
        "text_to_sequence":       None,
        "trace_status":           "missing",
        # [E2] 使用英文短标记
        "curator_note":           "EXTRACTION_SKIPPED:empty_context",
        "functions":              [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 向后兼容：保留 LLMExtractor 名称（供旧代码 import）
# ─────────────────────────────────────────────────────────────────────────────

LLMExtractor = EntityExtractor


class ExtractionFormatError(Exception):
    """LLM 输出格式非法，供上层 Orchestrator 捕获后决定重试策略。"""
