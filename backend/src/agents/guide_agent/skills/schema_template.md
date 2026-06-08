# HAp/肽段领域数据库字段模板
# 所属：backend/src/agents/guide_agent/skills/schema_template.md
# 用途：提供 HAp/矿化/肽段领域的推荐字段列表，供 guide_agent 生成字段模板时参考

---

## 推荐字段列表

以下字段来自 BioForge hap_v01.db 的 paper_record_v01_min 表，是当前系统支持抽取的核心字段。

### 一、文献元数据字段

| 字段名 | 类型 | 中文说明 | 示例值 |
|--------|------|----------|--------|
| paper_id | str | 内部论文编号，格式 P000001 | "P000001" |
| doi | str | 论文数字对象标识符，全局唯一 | "10.1021/acs.biomac.2c00123" |
| pmid | str | PubMed ID，部分论文可能为空 | "35678901" |
| title | str | 论文完整标题（原文字面量） | "Peptide-HAp binding affinity..." |
| journal_title | str | 期刊名称（原文字面量） | "Biomacromolecules" |
| publication_year | int | 发表年份（4位整数） | 2023 |

### 二、实体字段（肽段/蛋白对象）

| 字段名 | 类型 | 中文说明 | 示例值 |
|--------|------|----------|--------|
| entity_name_raw | str | 原文对象名，直接从论文抽取 | "enamel binding peptide (EBP)" |
| entity_name_normalized | str | 标准化名称，通常为氨基酸序列 | "WGNYAYK" |
| sequence_raw | str | 原始序列（单字母缩写） | "RKLPDA" |
| entity_type | str | 对象类型：synthetic_peptide / natural_peptide / protein_fragment | "synthetic_peptide" |

### 三、功能/相互作用字段

| 字段名 | 类型 | 中文说明 | 示例值 |
|--------|------|----------|--------|
| interaction_target | str | 作用靶底物：HAp / enamel / dentin / collagen / ACP / other / unclear | "HAp" |
| summary_functions | str | 功能标签（分号分隔）：adsorption / remineralization / inhibition / promotion 等 | "adsorption;remineralization" |
| model_system_summary | str | 实验模型简述（如 SBF 溶液中的 HAp 颗粒） | "Synthetic HAp nanoparticles in SBF" |

### 四、证据/实验字段

| 字段名 | 类型 | 中文说明 | 示例值 |
|--------|------|----------|--------|
| evidence_overall_level | str | 证据层级：in_vitro / ex_vivo / animal_in_vivo / clinical / in_silico / unclear | "in_vitro" |
| assay_category | str | 实验类别：binding_assay / mineralization_assay / inhibition_assay / simulation 等 | "binding_assay" |
| result_text_summary | str | 实验结果文字摘要（一句话） | "RKLPDA showed 3x higher HAp binding than control" |

### 五、溯源字段

| 字段名 | 类型 | 中文说明 | 示例值 |
|--------|------|----------|--------|
| text_to_sequence | str | 序列来源定位（论文中的章节/表格锚点） | "Table 2, Methods Section" |
| text_to_evidence_summary | str | 证据来源定位（可多个，分号分隔） | "Figure 3A;Results Section para.2" |
| trace_status | str | 溯源完整度：complete / partial / missing / disputed | "complete" |

---

## 最小推荐字段集（Demo 版必选）

对于 HAp/肽段领域，以下字段是必须抽取的核心集合：

```
paper_id, doi, title, publication_year,
entity_name_normalized, sequence_raw,
interaction_target, summary_functions,
evidence_overall_level, text_to_sequence
```

---

## 说明

> 以上为 Demo 版 HAp/肽段领域字段模板，来源于 BioForge hap_v01.db 的实际字段设计。
> 未来可根据不同领域（骨再生、牙釉质修复等）扩展新字段。
> extract_agent 将以此字段列表为依据，从文献中结构化抽取对应信息。
