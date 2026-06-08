# Screen Agent 技术文档

## 1. 概述

Screening Agent（`screen_agent`）是 BioForge 三阶段流水线（Search → Screen → Extract）中的第二阶段，负责接收上游 Search Agent 产出的候选文献元数据列表，根据研究目标构造筛选标准，通过 BM25 相关度算法逐篇判断相关性，产出精选 PMID 列表，并下载论文全文 PDF 及补充材料。

### 在流水线中的位置

```
Search Agent                    Screen Agent                   Extract Agent
    │                                │                              │
    │ candidate_paper_ids            │ screened_paper_ids           │
    │ + paper_details                │ + downloaded PDFs            │
    ├───────────────────────────────►├─────────────────────────────►│
    │                                │                              │
    └─ 检索 & 去重                   └─ 相关性筛选 & 下载全文        └─ 字段提取
```

### 核心职责

1. **构造筛选标准**：根据研究目标，生成明确可操作的自然语言筛选 criteria
2. **相关性筛选**：调用 `screen_paper` 工具，用 BM25 算法对每篇文献与 criteria 计算相关度，过滤低分文献
3. **文献下载**：通过 PMID 批量下载 PubMed 公开可获取的 PDF 全文及补充材料

---

## 2. 系统设计

### 2.1 架构

```
plan.yaml（预定义步骤）
identity.yaml（Agent 身份/约束/输出契约）
skills/screening_skill.md（LLM 操作指南）
skills/download_rule_skill.md（下载规则）
     │
     ▼
AgentTemplate(config).run(pipeline_state)
     │
     ├── PlanRunner ── while 循环执行 step
     │     ├── context_builder ── 组装 system_prompt + user_prompt
     │     ├── executor ── create_react_agent → LLM + Tool Calling
     │     │     └── registry.get_tools(["screen_paper", "download_paper"])
     │     ├── validator ── validate_step（规则）+ validate_plan（LLM）
     │     └── replanner ── retry / abort
     │
     └── output_adapter ── AgentRunResult → PipelineState patch
```

### 2.2 Plan 流程

```
Step 1: screen_papers（文献相关性筛选）
    │
    │  tools: [screen_paper]
    │  input:  上游 candidate_paper_ids 对应的 paper_details 列表 + criteria
    │  output: screened_paper_ids + excluded + screen_summary
    │
    ▼
Step 2: download_papers（下载论文全文及补充材料）
    │
    │  tools: [download_paper]
    │  input:  step 1 产出的 screened_paper_ids
    │  output: download_status
    │
    ▼
final_output（浅合并）→ validate_plan（对照 output_contract）
```

### 2.3 数据契约

| 字段 | 来源 | 类型 | 说明 |
|------|------|------|------|
| `screened_paper_ids` | Step 1 | `list[str]` | 判定为相关的 PMID 列表（纯数字字符串） |
| `screened_count` | Step 1 | `int` | 相关文献数量 |
| `excluded` | Step 1 | `list[dict]` | 排除文献的 pmid / reason / relevance |
| `screen_summary` | Step 1 | `str` | 筛选过程摘要 |
| `download_status` | Step 2 | `dict` | 下载统计（success/fail/supplementary/failed_pmids） |

---

## 3. 工具实现

### 3.1 `screen_paper` — 相关性筛选

**位置**：`backend/src/tools/screen/screen_paper.py`

**接口**：

```python
@tool
def screen_paper(
    papers: list[dict],      # 候选文献，每条含 pmid / title / abstract
    criteria: str,           # 筛选标准（自然语言，需与文献同语言）
    threshold: float = 1.0,  # BM25 相关度阈值
) -> dict:
```

**输出**：

```json
{
  "screened_paper_ids": ["34265844", "38360817"],
  "screened_count": 2,
  "excluded": [
    {"pmid": "12345678", "reason": "...", "relevance": 0.3956}
  ],
  "screen_summary": "根据标准筛选 4 篇文献，相关 2 篇，排除 2 篇。"
}
```

**算法**：BM25（Best Match 25），搜索引擎标准排序算法。将 criteria 作为 query，每篇文献的标题+摘要作为 document，计算相关度分值。相比 TF-IDF，BM25 对 query 长度不敏感、有文档长度归一化、更适合短 query vs 长 document 的场景。

**依赖**：`rank-bm25`（纯 Python，~20KB），零模型下载。

**线性相关描述**：`screen_paper` 不进行**出版时间**、**期刊质量**、**研究设计严谨性**等维度的打分——这些属于后续将加入的质量筛选步骤。

### 3.2 `download_paper` — 文献全文下载

**位置**：`backend/src/tools/screen/download_paper.py`

**核心功能**：
- 通过 PMID 下载论文 PDF 全文（多源回退：metapub FindIt → paperScraper）
- 提取 PMC XML 中的补充材料链接并下载
- 自动清理非 PDF 杂质文件
- 下载目录默认 `data/papers/pdf/`，可通过 `PAPER_DOWNLOAD_DIR` 环境变量覆盖

---

## 4. 配置体系

### 4.1 identity.yaml

```yaml
agent_name: "screen_agent"
role: "生物医学文献筛选与获取专家"
constraints:
  - 不做深度全文数据提取（extract_agent 职责）
  - 去重由 search_agent 负责
  - 筛选标准必须明确、可复现
output_contract:
  screened_paper_ids / screen_summary / download_status
```

### 4.2 plan.yaml

两步式流程：`screen_papers`（screen_paper 工具）→ `download_papers`（download_paper 工具）。
每步有 `tools_required`、`success_criteria`（required_fields + min_count）、`max_retries`。

### 4.3 skills

| Skill | 用途 |
|-------|------|
| `screening_skill.md` | 指导 LLM 调用 `screen_paper`：criteria 撰写原则（与文献同语言）、参数说明、输出字段、禁止事项 |
| `download_rule_skill.md` | 指导 LLM 调用 `download_paper`：批量传入、重试策略（3 轮）、不可重试错误分类、禁止事项 |

### 4.4 agent.py

```python
def create_screen_agent(...) -> AgentTemplate:
    config = AgentTemplateConfig(
        agent_name="screen_agent",
        tools=["screen_paper", "download_paper"],
        ...
    )
```

## 5. 当前完成情况

### 已完成

| 模块 | 状态 | 说明 |
|------|------|------|
| `identity.yaml` | ✅ | Agent 身份、职责、约束、输出契约 |
| `plan.yaml` | ✅ | 两步可执行计划（筛选 → 下载） |
| `agent.py` | ✅ | 工厂函数 + Mock/Real 类共存 |
| `__init__.py` | ✅ | 统一导出 |
| `tools/screen/screen_paper.py` | ✅ | BM25 相关性筛选工具 |
| `tools/screen/screen_paper_mock.py` | ✅ | Mock 版本，供单元测试 |
| `skills/screening_skill.md` | ✅ | screen_paper 工具使用指南 |
| `skills/download_rule_skill.md` | ✅ | download_paper 工具使用指南 |

### 新增依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| `rank-bm25` | >=0.2.2 | BM25 相关度打分（纯 Python，~20KB） |
