# HAp Peptide v1 数据库填写规则（Agent Skill）

> 适用模板：`hap_peptide_v1`  
> 适用对象：HAp 相互作用肽段、牙釉质/矿化相关肽段、蛋白片段、融合肽、修饰肽及载体复合体系文献。  
> 用途：作为 Extract Agent 的字段填写 skill，配合 `schema.yaml`、RAG 检索工具与 `save_extraction_package()` 写库服务使用。

---

## 0. 总原则

### 0.1 信息层级

本模板采用五张逻辑表：

1. `paper`：论文层，1 行 = 1 篇论文。
2. `paper_entity_record`：对象层，1 行 = 1 篇论文中的 1 个独立肽段/对象。
3. `entity_component`：对象组成层，1 行 = 1 个对象中的 1 个组成模块。
4. `record_function`：功能层，1 行 = 1 个对象的 1 种功能结论。
5. `function_assay_evidence`：证据层，1 行 = 1 个功能结论对应的 1 种实验方法 + 1 组结果。

### 0.2 抽取优先级

Agent 填写字段时按以下证据优先级处理：

1. 原文 Methods / Results / 图表 / 表格 / Supplementary 中的明确描述。
2. 摘要或 Discussion 中的总结性描述。
3. PubMed / CrossRef 元数据。
4. 引文、数据库、补充材料等外源回补信息。
5. 无法确认时填 `unclear`、`not_reported` 或 NULL，并在 `curator_note` 或相应来源字段中说明。

### 0.3 禁止事项

- 不得编造序列、实验结果、统计值、图表编号或页码。
- 不得把只有泛泛讨论的内容当作实验证据。
- 不得把 RAG 返回的候选片段直接视为正式证据；必须判断其是否支持当前字段。
- 不得直接写业务数据库物理表；输出 extraction package 后由 `save_extraction_package()` 统一写入。
- 枚举不确定时优先使用 `unclear`；确有明确但未收录类别时使用 `other`，并保留原文描述。

### 0.4 溯源要求

所有核心字段应尽量附带结构化溯源：

- 章节：`section_path`
- 小节：`subsection_label`
- 图：`figure_ref`
- 表：`table_ref`
- 页码：`page_no`
- 原文关键句：`quote_snippet`
- 偏移：`offset_start` / `offset_end`（由系统/RAG 提供时填写）

人读聚合字段如 `text_to_sequence`、`text_to_function`、`text_to_evidence` 应由结构化溯源字段生成，不应替代结构化溯源字段。

---

## 1. `paper` 表填写规则

### 1.1 记录粒度

`paper` 表 1 行对应 1 篇被收录论文。该表只记录论文元数据，不记录具体肽段功能。

### 1.2 字段规则

#### `paper_id`

- 系统生成，格式 `Pnnnnnn`，如 `P000001`。
- Agent 通常不直接生成，除非在离线标注模板中模拟填写。

#### `doi`

- 从 PubMed、CrossRef 或原文提取。
- 保留标准 DOI 字符串，去除 URL 前缀如 `https://doi.org/`。
- 同一 DOI 不应重复录入。

#### `pmid`

- 仅 PubMed 收录文献填写。
- 不存在时留空。

#### `title`

- 保留原文标题大小写、标点和专业术语。
- 不要自行翻译成中文。

#### `journal_title`

- 优先使用 PubMed 标准刊名或标准缩写。
- 不确定时使用原文期刊名。

#### `publication_year`

- 四位整数。
- 预出版论文使用在线发表年份，并在人工备注中说明。

#### `abstract`

- 保存摘要全文。
- 去除多余控制字符。
- 结构化摘要可保留 Background / Methods / Results 等段落标记。

#### `keywords`

- 作者关键词以列表形式保存。
- 未提供则为空，不要从题目中自行生成关键词。

#### `full_text_availability`

- `open_access`：可合法免费获取全文。
- `subscription`：需机构订阅或付费。
- `preprint`：预印本。
- `unknown`：未确认。

#### `retrieval_source`

- `pubmed`：PubMed API/E-utilities。
- `crossref`：CrossRef。
- `manual_entry`：人工录入。
- `agent_crawl`：Agent 从网页/PDF 抽取。

---

## 2. `paper_entity_record` 表填写规则

### 2.1 记录粒度

1 行 = 1 篇论文中的 1 个独立研究对象。  
如果一篇论文同时研究多个肽段、多个突变体、多个融合肽或多个材料复合物，应分别建立多条 `paper_entity_record`。

### 2.2 序列字段

#### `sequence_status`

| 值 | 含义 | 填写规则 |
|---|---|---|
| `explicit` | 原文完整给出序列 | 正文、图、表或补充材料直接出现完整氨基酸序列 |
| `partial` | 原文只给出部分序列 | 仅出现片段、部分残基或需要上下文拼接 |
| `not_reported` | 原文未报告序列 | 通篇无序列且无明确回补线索 |
| `backtrace_required` | 原文未完整给出，但提供回补线索 | 明确引用文献、GenBank、UniProt、补充材料、专利或数据库等 |

#### `sequence_raw`

- 原文明确给出时填写原文序列。
- 回补成功时填写回补序列。
- 未报告且未回补时留空。
- 可保留原文修饰符号；但应同步生成 `sequence_normalized`。

#### `sequence_normalized`

- 去除空格、连字符、修饰标记等。
- 仅保留大写单字母氨基酸代码。
- 若含 D-氨基酸、磷酸化、FITC 等修饰，标准序列只保留氨基酸骨架，修饰进入 `entity_component.modification_category/detail`。

#### `is_sequence_backfilled`

| 场景 | `sequence_status` | `sequence_raw` | `is_sequence_backfilled` |
|---|---|---|---|
| 原文直接给出完整序列 | `explicit` | 原文序列 | `false` |
| 原文只给部分序列 | `partial` | 部分序列 | `false` |
| 原文完全未给序列 | `not_reported` | NULL | `false` |
| 原文未给完整序列，但回补成功 | `backtrace_required` | 回补序列 | `true` |
| 有回补线索但未成功回补 | `backtrace_required` | NULL | `false` |

重点：回补成功后，`sequence_status` 仍保留 `backtrace_required`，用以区分字段来源。

### 2.3 序列回补字段

#### `sequence_source_type`

适用于 `sequence_status = backtrace_required`：

- `ref`：参考文献。
- `genbank`：GenBank 登录号。
- `uniprot`：UniProt 登录号。
- `suppl`：补充材料。
- `patent`：专利。
- `database`：其他数据库，如 PDB/RCSB。
- `other`：其他来源。

#### `sequence_source_id`

按来源类型填写：

- `ref`：参考文献信息，建议含作者、题名、年份、期刊和参考文献编号。
- `genbank` / `uniprot`：登录号。
- `suppl`：补充材料位置，如 `Table S1`。
- `patent`：专利号。
- `database`：数据库名 + accession。

#### `source_paper_id`

当回补来源是已收录文献时填写，对应 `paper.paper_id`。  
若该字段有值，`sequence_source_type` 应为 `ref`。

#### `sequence_source_location`

当来源为未入库参考文献、补充材料或外部数据库位置时填写 JSON 位置线索。  
结构字段参考 `source_location`：`section_path`、`subsection_label`、`figure_ref`、`table_ref`、`page_no`、`offset_start`、`offset_end`。

### 2.4 对象类型字段

#### `entity_type`

由 `entity_component` 中功能类模块推断：

- 功能类模块：`functional_module`、`protein_fragment`。
- 非功能类模块：`linker`、`tag`、`modification`、`carrier`、`other`。

推断规则：

1. 功能类模块数 = 1，且无独立修饰/载体：`single_peptide`、`protein_fragment` 或 `full_protein`。
2. 功能类模块数 = 1，且存在修饰模块或修饰属性：`modified_peptide`。
3. 功能类模块数 = 2：`fusion_peptide`。
4. 功能类模块数 ≥ 3：`chimeric_peptide`。
5. 蛋白片段为全长时可推断为 `full_protein`。

### 2.5 来源和材料字段

#### `design_source`

| 值 | 使用场景 |
|---|---|
| `natural_derived` | 来自天然蛋白片段，未人工改动 |
| `rational_design` | 基于结构/功能规则理性设计 |
| `phage_display` | 噬菌体展示筛选获得 |
| `computational` | 计算筛选、分子对接、模拟设计 |
| `synthetic` | 明确化学合成但设计逻辑不清，或随机/重复序列 |
| `unclear` | 原文未说明来源 |

#### `target_material`

- `HAp`：羟基磷灰石晶体、表面或涂层。
- `collagen`：胶原纤维或胶原模板。
- `ACP`：无定形磷酸钙稳定或转化。
- `other`：其他明确材料。
- `not_reported`：未涉及材料直接相互作用。
- `unclear`：信息不足。

#### `target_substrate`

- `enamel`：釉质、釉质病损、釉质粉末/切片。
- `dentin`：牙本质。
- `bone`：骨组织。
- `mineral_surface`：矿物表面或涂层。
- `in_vitro_crystal`：独立合成矿物晶体/颗粒。
- `other` / `not_reported` / `unclear` 按信息情况填写。

区分 `mineral_surface` 与 `in_vitro_crystal`：

- `mineral_surface` 强调界面/表面，如 HAp 涂层、HAp 盘。
- `in_vitro_crystal` 强调独立晶体或颗粒，如 HAp 粉末、ACP 纳米颗粒。

### 2.6 摘要功能字段

`summary_functions` 是派生展示字段，应由同一 `record_id` 下所有 `record_function.function_label` 去重聚合生成。  
Agent 可以在草稿包中给出建议，但最终应由系统基于 `record_function` 同步。

---

## 3. `entity_component` 表填写规则

### 3.1 记录粒度

每个 `paper_entity_record` 至少有 1 条 `entity_component`。  
简单肽段也应建立 1 条 `functional_module` 记录。

### 3.2 `component_type`

| 值 | 含义 | 示例 |
|---|---|---|
| `functional_module` | 有独立功能的结构模块 | HAp-binding peptide、抗菌肽 |
| `linker` | 连接子序列 | GGGGS linker |
| `tag` | 检测/纯化标签 | His-tag、FLAG、FITC 标记（若作为标签） |
| `protein_fragment` | 天然蛋白截取片段 | amelogenin fragment、CEMP1-p1 |
| `modification` | 独立修饰模块 | 磷酸尾、PEG 链、DPS |
| `carrier` | 载体/基质组分 | 壳聚糖水凝胶、丝蛋白支架 |
| `other` | 其他模块 | 无法归类但需要保留 |

#### 优先级规则

`protein_fragment` 优先级高于 `functional_module`。  
如果模块可明确追溯到母体蛋白和截取区域，应填 `protein_fragment`，即使它本身具有功能。

### 3.3 `component_order`

- 按 N 端到 C 端顺序从 1 开始递增。
- 载体类组件若不属于序列顺序，可放在功能模块之后，并在 `curator_note` 说明。

### 3.4 `is_natural`

仅主要适用于 `component_type = protein_fragment`：

| 值 | 含义 |
|---|---|
| `true` | 与母体蛋白天然序列完全一致 |
| `false` | 截取后经过人工突变、优化或设计 |
| NULL | 不适用，通常不是 protein_fragment |

### 3.5 修饰建模

#### `modification_category`

| 值 | 含义 |
|---|---|
| `post_translational` | 翻译后修饰，如磷酸化 |
| `chemical_conjugation` | 化学偶联，如 FITC、生物素、PEG |
| `non_natural_aa` | D-氨基酸、β-氨基酸等 |
| `terminal_modification` | N 端乙酰化、C 端酰胺化 |
| `cross_linking` | 二硫键、环化 |
| `other` | 其他修饰 |

#### `modification_detail`

格式：

```text
{位点或范围}:{修饰子类型}:{简要描述}
```

多个修饰用分号分隔。

示例：

- `Ser-15,Ser-16:phosphorylation:增加钙结合能力`
- `全部:D-aa:抗菌模块全D-氨基酸`
- `N端:FITC:荧光标记`
- `N端:acetylation; C端:amidation`

#### 修饰是属性还是独立模块

- 如果修饰只是对已有模块的局部化学改造，作为该模块的属性填写 `modification_category/detail`。
- 如果修饰引入独立序列或独立功能单元，则新建一条 `component_type = modification` 或 `tag` 的组件记录。

### 3.6 蛋白片段字段

适用于 `component_type = protein_fragment`：

- `parent_protein_raw`：母体蛋白原始名称。
- `parent_protein_accession`：UniProt/GenBank 等登录号。
- `fragment_start`：起始残基。
- `fragment_end`：结束残基。
- `fragment_derivation_type`：片段来源区域。

#### `fragment_derivation_type`

| 值 | 判断规则 |
|---|---|
| `n_terminal` | 片段来自 N 端；通常 `fragment_start = 1` 且未覆盖全长 |
| `c_terminal` | 片段来自 C 端；通常 `fragment_end` 接近母体蛋白全长且 `fragment_start > 1` |
| `internal` | 片段来自内部区域；不包含 N 端或 C 端 |
| `full_length` | 全长或几乎全长，通常长度 ≥ 母体蛋白 95% |

特别规则：

- 当 `component_type != protein_fragment` 时，本字段不适用，填 NULL。
- 当 `component_type = protein_fragment` 但 start/end 未知时，可根据原文描述推断，如 “N-terminal fragment” → `n_terminal`。
- 若完全无法判断，填 NULL 并说明。
- **无论 `is_natural` 取何值，本字段均需正常填写；片段来源区域不因是否突变而改变。**

---

## 4. `record_function` 表填写规则

### 4.1 记录粒度

1 行 = 1 个对象的一种功能结论。  
同一对象有多个功能时，应建立多条记录。

### 4.2 `function_layer` 与 `function_label`

必须先选宏观层级，再选具体标签。

| function_layer | 可用 function_label |
|---|---|
| `binding` | `adsorption`, `localization`, `ion_capture` |
| `kinetics` | `nucleation`, `mineral_deposition`, `crystal_growth_promotion` |
| `crystallography` | `phase_stabilization`, `phase_transformation_promotion`, `crystal_growth_inhibition`, `crystal_orientation_modulation`, `crystal_morphology_modulation` |
| `protection` | `anti_demineralization` |
| `biology` | `antimicrobial`, `cell_adhesion_promotion` |
| `other` | `other` |

### 4.3 功能标签判定要点

#### `adsorption` vs `localization`

- `adsorption`：强调分子层面结合/吸附，有亲和力、吸附量、Kd/Ka、SPR、ITC、QCM-D、消耗法或模拟结合证据。
- `localization`：强调空间分布、定位、富集、渗透深度，多来自 CLSM、荧光显微镜或成像证据。

二者不互斥。若同一论文既有定量结合数据，又有定位成像，可同时建立两条功能记录。  
若定位证据只说明“有分布”且被吸附实验充分覆盖，可优先保留 `adsorption`。

#### `mineral_deposition`

用于矿物质量、体积、密度或再矿化程度增加。仅形貌变化不足以填此项。

#### `crystal_morphology_modulation`

用于晶体形貌变化，如针状、片状、纳米棒、排列方式、表面形态变化。仅矿量增加不足以填此项。

#### `anti_demineralization`

主要作用是抑制酸蚀、抗脱矿。若论文核心是再矿化恢复，不优先填此项。

### 4.4 `evidence_level`

本字段是该功能结论的最高证据层级。  
若功能由多条证据支持，取最接近体内/临床的层级，但不得高于实际证据。

---

## 5. `function_assay_evidence` 表填写规则

### 5.1 记录粒度

1 行 = 1 个功能结论对应的 1 种实验方法 + 1 组结果。

如果同一功能由多种方法支持，例如 CLSM + micro-CT + SEM，应建立多条 evidence。  
如果同一方法支持多个功能，应分别归属到对应功能，或在物理库中通过 link 表多对多关联。

### 5.2 `evidence_level`

- `in_vitro`：人工构建体系、合成矿物、细胞/细菌培养、矿化液等。
- `ex_vivo`：离体组织/器官，如人牙、牛牙、骨片等，并保留天然结构。
- `animal_in_vivo`：动物体内实验。
- `clinical`：人体/临床研究。
- `in_silico`：计算模拟。
- `unclear`：无法判断。

注意：脱矿处理后的釉质块如果保留天然组织结构，可根据项目统一口径在 `ex_vivo` 与 `in_vitro` 之间人工确认；Agent 不确定时填 `unclear` 并保留原文模型描述。

### 5.3 材料体系与递送方式

#### `additive_system_type`

| 值 | 含义 |
|---|---|
| `free_in_solution` | 肽以自由分子形式存在于溶液中 |
| `hydrogel` | 水凝胶载体 |
| `protein_matrix` | 蛋白质基质，如丝蛋白、胶原 |
| `polysaccharide_matrix` | 多糖基质，如壳聚糖、海藻酸 |
| `coating` | 表面涂层 |
| `scaffold` | 三维支架 |
| `composite` | 复合材料 |
| `other` | 其他明确体系 |
| `unclear` | 无法判断 |
| `none` | 已确认无载体体系 |

区分：

- `none`：确认无载体。
- `free_in_solution`：确认肽在溶液中自由作用。
- `unclear`：信息不足。

#### `delivery_mode`

- `free_solution`：溶液中直接添加。
- `surface_coating`：表面涂覆/预吸附。
- `sustained_release`：载体缓释。
- `immobilized`：共价固定。
- `pretreatment`：预处理/预浸泡。
- `co_assembly`：共组装。
- `other` / `unclear`。

### 5.4 `assay_category`

| 值 | 使用场景 |
|---|---|
| `binding_affinity` | 结合强度、亲和力、动力学 |
| `surface_localization` | 空间定位/分布观察 |
| `retention_test` | 冲洗、刷牙、酸挑战后残留 |
| `crystal_structure` | 晶体结构/晶相 |
| `mineral_morphology` | 矿物形貌 |
| `elemental_composition` | 元素组成 |
| `molecular_composition` | 分子键合/化学态 |
| `mechanical_property` | 硬度、弹性模量、力学性能 |
| `mineral_quantity` | 矿量、矿物密度、钙磷定量 |
| `lesion_morphology` | 病损深度、面积、形态 |
| `biological_response` | 细胞/细菌/生物膜反应 |
| `in_vivo_efficacy` | 体内/临床效果 |
| `simulation` | 计算模拟 |
| `other` | 其他明确实验类别 |

### 5.5 `validation_method`

优先从枚举中选择。  
方法明确但未收录时填 `other`，并在 `validation_method_raw` 保留原文名称。

常见映射：

- CLSM / LSCM / confocal → `CLSM`
- wide-field fluorescence / epifluorescence → `fluorescence_microscopy`
- μCT / micro-computed tomography → `micro-CT`
- SEM / scanning electron → `SEM`
- TEM / transmission electron → `TEM`
- XRD / X-ray diffraction → `XRD`
- FTIR / Fourier transform infrared → `FTIR`
- EDS / EDX / energy dispersive → `EDX`
- molecular dynamics → `MD_simulation`
- docking → `molecular_docking`

若原文只提 FITC、Calcein 等探针而未说明成像平台，`validation_method` 可填 `unclear`，`validation_method_raw` 保留原文。

### 5.6 `result_text_summary`

必须填写。  
要求简明概括本条证据支持的核心结果，不做过度解释。

示例：

- “CLSM showed that FITC-labeled peptide localized on the enamel lesion surface and penetrated into the subsurface lesion.”
- “Micro-CT analysis indicated increased mineral density after peptide treatment compared with control.”
- “SEM images showed more organized mineral deposits in the peptide-treated group.”

### 5.7 `result_value_raw` 与 `result_value_normalized`

- `result_value_raw` 保留原文数值，如 `p < 0.05`、`2.3-fold increase`。
- `result_value_normalized` 可结构化为 JSON，例如：

```json
{"type": "fold_change", "value": 2.3, "unit": "fold", "comparison": "vs control"}
```

无法标准化时只填 raw。

### 5.8 证据溯源字段

`section_path`、`subsection_label`、`figure_ref`、`table_ref`、`page_no`、`quote_snippet` 中至少应尽量填写一个足以支持判断的字段。  
优先级：

1. 结果图表/表格。
2. 结果小节正文。
3. 图注/表注。
4. 摘要或讨论中的总结性语句。
5. 方法部分仅可支持“方法存在”，不能单独支持“效果结果”。

### 5.9 `trace_status`

| 值 | 判定 |
|---|---|
| `complete` | 能精确追溯到段落、图表或关键句，足以支持字段 |
| `partial` | 能大致定位章节，但缺少具体图表/关键句 |
| `missing` | 无可靠来源定位 |
| `disputed` | 原文不同位置有冲突或矛盾 |

---

## 6. Agent RAG 使用规则

### 6.1 字段驱动检索

Agent 调用 RAG 时应围绕字段缺口检索，而不是泛泛总结论文。

推荐 query 模板：

- paper 层：`DOI title journal publication year abstract`
- 序列：`peptide sequence amino acid WGNYAYK peptide synthesis`
- 对象来源：`phage display peptide design derived from parent protein`
- 组成模块：`fusion peptide linker tag protein fragment parent protein`
- 功能：`peptide hydroxyapatite binding localization remineralization function`
- 证据：`CLSM micro-CT SEM nanoindentation result peptide remineralization`
- 溯源：`Figure Table Results peptide mineral deposition`

### 6.2 RAG 输出处理

RAG 返回的片段只作为候选证据。Agent 必须判断：

1. 该片段是否直接支持当前字段。
2. 是否包含结果，而不仅是方法。
3. 是否包含图表或页码。
4. 是否存在与其他片段冲突。
5. 是否需要再次检索更具体字段。

### 6.3 自检清单

输出 extraction package 前必须检查：

- 每个 `paper_entity_record` 至少有 1 个 `entity_component`。
- `summary_functions` 与 `record_function.function_label` 一致。
- 每个 `record_function` 至少有 1 条 evidence，或说明证据缺失。
- 每条 `function_assay_evidence.result_text_summary` 非空。
- 枚举值均来自 `schema.yaml`。
- `protein_fragment` 的 `fragment_derivation_type` 不因 `is_natural` 变化而省略。
- 所有核心证据尽量有 `quote_snippet`、`figure_ref` 或 `section_path`。
- 不确定内容不能编造，应使用 `unclear`/NULL 并说明。

---

## 7. 输出格式要求

Agent 输出应为 `extraction_package`，而不是 SQL 或 CSV。

推荐结构：

```json
{
  "template_id": "hap_peptide_v1",
  "paper": {},
  "paper_entity_records": [
    {
      "entity_components": [],
      "record_functions": [
        {
          "function_assay_evidences": []
        }
      ]
    }
  ]
}
```

最终写库由 `validate_node` + `persist_node` 完成。
