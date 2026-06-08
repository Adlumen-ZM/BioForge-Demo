---
skill_id: screen_paper_skill
version: v1
applies_to_tools: [screen_paper]
agent: ScreenAgent
---

## 目的
指导 LLM 正确调用 `screen_paper` 工具，根据筛选标准判断候选文献的相关性。

## 筛选原理

`screen_paper` 使用 BM25 算法计算每篇文献（标题+摘要）与 criteria 的相关度。
BM25 是搜索引擎标准排序算法，基于词频和逆文档频率打分。
相关度 >= threshold（默认 1.0）判定为相关，否则排除。

## 调用规范

- **批量传入**：将所有候选文献整合为一个 list，单次调用 `screen_paper`。即使只有 1 篇也要以列表形式传入
- **输入字段**：每条文献至少包含 `pmid`、`title`、`abstract`
- **criteria 语言**：必须与文献语言一致。英文文献用英文 criteria，中文文献用中文 criteria，否则 BM25 无法跨语言匹配
- **criteria 撰写原则**：用简洁的自然语言描述应保留的文献特征，尽量包含领域关键词
  示例（英文文献）：`original experimental research on peptide or protein interactions with hydroxyapatite (HAp) or calcium phosphate, including in vivo or in vitro data, excluding pure computational studies and reviews`

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `papers` | `list[dict]` | 必填 | 候选文献元数据列表 |
| `criteria` | `str` | 必填 | 筛选标准（自然语言） |
| `threshold` | `float` | 1.0 | BM25 相关度阈值，提高 → 更严格。BM25 分值无上限，建议范围 0.5-3.0 |

## 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `screened_paper_ids` | `list[str]` | 判定为相关的 PMID |
| `screened_count` | `int` | 相关文献数量 |
| `excluded` | `list[dict]` | 被排除文献的 pmid / reason / relevance |
| `screen_summary` | `str` | 筛选过程摘要 |

## 禁止

- **严禁对裸 PMID 调用**：必须先获取 title / abstract 等元数据后再调用
- **严禁逐篇循环调用**：将所有文献一次性传入 papers 列表
- **严禁伪造结果**：不得在调用前自行判断相关性，必须通过工具判定
