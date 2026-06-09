# BioForge Demo 完整技术路线

## 1. 设计目标

BioForge Demo 要解决的问题是：如何从一段用户给出的研究目标和文献纳排标准出发，半自动构建一个可复核的肽段-矿物相互作用结构化数据库。系统不把流程写成单个脚本，而是拆成可独立开发、可追踪、可替换的多个模块。

最终形成两类产物：

1. **业务产物**：结构化数据库，包含论文、实体、功能、实验和证据。
2. **工程产物**：多 Agent 流水线，包含 Graph 编排、AgentTemplate、工具协议、RAG 工具、Trace 日志和 CLI 演示界面。

## 2. 总体技术选型

| 层级 | 技术 | 当前用途 | 备注 |
|---|---|---|---|
| 外层编排 | LangGraph `StateGraph` | 串联 guide/init/search/screen/extract/write_db | 显式 state、节点、边和 checkpoint |
| 普通 Agent 运行时 | 自研 `AgentTemplate` | Plan-and-Execute + step 内 ReAct | Search/Screen/Extract 共用 |
| Guide Agent | LangGraph `interrupt()` | 用户确认任务、纳排和字段模板 | 不走 AgentTemplate |
| 模型调用 | LiteLLM / ChatLiteLLM | 统一调用不同供应商 LLM | 通过模型字符串和 `.env` 切换 |
| 工具协议 | LangChain `@tool` + Pydantic args_schema | PubMed、screen、download、RAG 工具 | 返回结构化 dict/list |
| 文献检索 | Biopython Entrez / PubMed API | 获取候选 PMID/DOI/标题/摘要 | 需要 NCBI_EMAIL |
| 文献筛选 | BM25 + 规则/LLM | 根据纳排标准初筛 | Demo 先保证可解释和稳定 |
| PDF 下载 | paperscraper + mock | real 下载 / demo 演示 | demo 默认 mock 更稳定 |
| RAG | RAGFlow + BGE-M3 hybrid retrieval + LLM extraction | PDF → evidence → CSV | 作为工具被 Extract Agent 调用 |
| 业务库 | SQLite demo / PostgreSQL future | 存储结构化科研数据 | schema.yaml 动态建表 |
| Trace | JSONL + PostgreSQL backend | 记录运行过程 | 与业务库分离 |
| CLI | rich | 演示、确认、进度展示 | 当前主要 UI |
| 测试 | pytest + verify_cli.py | 最小质量保证 | 模块负责人各自补充 |
| Docker | python:3.11-slim + compose | 团队统一环境 | 当前需补源码挂载或 COPY |

## 3. 总体数据流

```text
User input
  ├─ raw_user_prompt
  └─ raw_user_screening_rules
        ↓
Guide Agent
  ├─ refined_task_prompt
  ├─ refined_screening_criteria
  └─ schema_template(hap_peptide_v1)
        ↓
LangGraph PipelineState
        ↓
Search Agent
  ├─ queries
  ├─ candidate_paper_ids
  └─ candidates(title/abstract/doi/pmid)
        ↓
Screen Agent
  ├─ screened_paper_ids
  ├─ selected_paper
  ├─ paper_key
  └─ pdf_path
        ↓
Extract Agent
  ├─ call RAG tool
  ├─ extraction
  ├─ rag_csv_dir
  └─ rag_csv_files
        ↓
write_db_node
  ├─ ensure business DB
  └─ write CSV to SQLite
        ↓
Business DB + Trace logs
```

## 4. Graph 编排路线

代码位置：`backend/src/graph/`

Graph 的职责是“串联流程”和“维护跨 Agent 状态”。它不负责具体检索、筛选、抽取逻辑。

节点顺序：

```text
START → guide → init_business_db → search → screen → extract → write_rag_csv_to_db → END
```

关键文件：

- `state.py`：定义 `PipelineState`，是节点之间唯一共享状态。
- `pipeline.py`：定义 `build_graph(mode, checkpointer)`。
- `nodes.py`：定义每个节点函数。
- `factory.py`：根据 `agent_name` 和 `mode` 创建 Agent。

节点必须返回 state patch，不应直接覆盖整个 state。

## 5. AgentTemplate 路线

代码位置：`backend/src/agents/agent_template/`

AgentTemplate 是普通 Agent 的运行时。每个 Agent 通过四类配置获得个性化行为：

```text
identity.yaml  → 角色、目标、约束、输出契约
plan.yaml      → step 列表、工具需求、成功标准、重试次数
skills/*.md    → 领域技能和执行规范
tools          → 在 registry 中注册的可调用工具
```

运行过程：

```text
AgentTemplate.run(input_data)
  ↓
load plan + identity + skills
  ↓
PlanRunner 逐 step 执行
  ↓
context_builder 组装 system prompt
  ↓
executor 调用 LLM/ReAct/tool
  ↓
validator 检查 step 输出
  ↓
replanner 决定 retry/modify/abort
  ↓
TraceHook 记录事件
  ↓
output_adapter 转成 PipelineState patch
```

这一设计让 Search、Screen、Extract 的 Python 代码很薄，主要差异放到 YAML/MD/tool 配置中。

## 6. Guide Agent 路线

代码位置：`backend/src/agents/guide_agent/`

Guide Agent 特殊，不走 AgentTemplate。原因：它的关键能力是人机确认，而非自主工具调用。它使用 LangGraph `interrupt()`，在 CLI 中暂停并等待用户确认。

四步：

1. Q1 研究目标确认。
2. Q2 研究对象边界和纳排规则确认。
3. Q3 字段模板确认。
4. Q4 开始进入 pipeline。

输出：

```python
refined_task_prompt: str
refined_screening_criteria: dict
schema_template: dict
user_confirmed: bool
guide_questions: list
guide_summary: str
```

## 7. Search Agent 路线

代码位置：`backend/src/agents/search_agent/` 和 `backend/src/tools/search/`

Search Agent 的任务是把研究目标转化为 PubMed 检索式，并输出候选文献。

Plan：

1. `task_understanding`：识别核心实体、关系类型、实验模型和约束。
2. `query_build`：生成 3–5 条 PubMed query，包括精准、高召回、序列设计、牙釉质专项等。
3. `search_execute`：调用 `pubmed_search`。
4. `dedup_filter`：按 PMID/DOI/标题去重。

输出：

```python
candidate_paper_ids: list[str]
candidates: list[dict]
queries: list[dict]
search_summary: str
```

## 8. Screen Agent 路线

代码位置：`backend/src/agents/screen_agent/` 和 `backend/src/tools/screen/`

Screen Agent 的任务是从候选文献中筛出符合纳排标准的文献，并下载或定位 PDF。

Plan：

1. `screen_papers`：调用 `screen_paper`，输出入选和排除理由。
2. `download_papers`：调用 `download_paper`，输出 `paper_key/pdf_path/download_status`。

Demo 模式下下载工具用 mock，real 模式下用真实下载。

输出：

```python
screened_paper_ids: list[str]
selected_paper: dict
paper_key: str
pdf_path: str
download_results: list[dict]
screen_summary: str
```

## 9. Extract Agent 路线

代码位置：`backend/src/agents/extract_agent/` 和 `backend/src/tools/rag_paper/`

Extract Agent 接收 PDF 和字段模板，调用 RAG 工具，输出 CSV 路径和抽取结果。

核心工具：

```python
run_bio_paper_extraction_pipeline(
    pdf_path,
    output_dir,
    template_id="hap_peptide_v1",
    schema_template_path=None,
    overwrite=False,
)
```

RAG 内部流程：

```text
PDF → RAGFlow/Parser → chunks → Scout 实体发现 → Hybrid Retrieval → LLM Extractor → Normalizer → five-table CSV
```

Extract Agent 不直接写业务库；写库由 Graph 的 `write_db_node` 完成。

## 10. 业务数据库路线

代码位置：`db/business/` 和 `backend/src/db_access/business/`

初始化：

```python
ensure_business_db(template_id="hap_peptide_v1", extraction_profile="hap_peptide_v1")
```

根据 `docs/schema_templates/hap_peptide_v1/schema.yaml` 创建：

```text
controlled_vocabulary
paper
paper_entity_record
entity_component
record_function
function_assay_evidence
document_asset
rag_document_reference
workflow_extraction_call
```

写入：

```python
write_rag_csv_to_business_db(csv_dir, db_path, template_id, run_id, paper_key)
```

CSV 写入默认幂等，`overwrite=False` 时使用 `INSERT OR IGNORE`。

## 11. Trace 路线

代码位置：`backend/src/db_access/trace/`

Trace 采用事件流：

```text
run_id / agent_run_id / stage / event_type / step_id / status / duration_ms / payload / created_at
```

默认写入：

```text
data/runs/YYYYMMDD/run_xxx/trace/events.jsonl
```

可选 PostgreSQL：

```env
TRACE_DB_URL=postgresql+psycopg://user:password@host:5432/db
```

Trace 用于调试、复盘、算子优化和可复核性说明，不替代 Business DB。

## 12. RAG 与未来 MCP 路线

当前建议：先把 RAG、下载、PubMed 检索作为 Python `@tool` 直接注册。MCP 作为未来扩展，用于用户自定义下载源、机构内网工具、独立 RAG 服务或跨项目复用。

未来工具分层：

```text
tools/builtins/    # 内置无外部依赖工具
tools/community/   # 依赖第三方 API 的工具
tools/mcp/         # MCP client/server 管理层
tools/registry.py  # 聚合工具
```

## 13. 验收标准

- `python verify_cli.py` 通过。
- `python -m backend.src.cli --check-only` 可显示五项检查。
- CLI 可完成 Guide 四步确认。
- Graph 可从 Guide 流转到 write_db。
- Trace 可记录关键事件。
- Business DB 可初始化并可写入 RAG CSV。
- 每个模块 README 能说明职责、输入输出、技术选型和扩展点。
