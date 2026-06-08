# Search Agent & Extract Agent 开发与测试日志

**项目**：PepClaw 生物医学文献智能挖掘系统  
**日期**：2026-06-07  
**分支**：template_agent_dev

---

## 一、项目概述

### 1.1 系统架构

本项目采用 **Plan-and-Execute** + **ReAct** 双层架构：

```
┌─────────────────────────────────────────────────────────────┐
│                    AgentTemplate                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │           PlanRunner（外层：Plan-and-Execute）       │   │
│  │   while step in plan.steps:                        │   │
│  │       ContextBuilder → Executor → Validator          │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │   Executor.run_step() → create_react_agent()        │   │
│  │   （内层：LangGraph ReAct Agent）                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Agent 职责

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **search_agent** | 文献检索 | 研究目标关键词 | candidate_paper_ids |
| **extract_agent** | 信息抽取 | 论文 PDF 文本 | extracted_papers |

---

## 二、search_agent 开发记录

### 2.1 目录结构

```
backend/src/agents/search_agent/
├── __init__.py
├── agent.py              # 入口函数 create_search_agent()
├── plan.yaml            # 执行计划（3 步）
├── identity.yaml        # 身份配置
└── skills/
    ├── pubmed_query.md     # 检索式构建指南
    └── dedup_strategy.md    # 去重策略指南
```

### 2.2 执行流程

```
Step 1: query_build
   ├─ 职责：构建 PubMed 检索式
   ├─ 工具：无
   └─ 输出：{"query_string": "...", "rationale": "..."}

Step 2: search_execute
   ├─ 职责：调用 pubmed_search 工具执行检索
   ├─ 工具：pubmed_search
   └─ 输出：{"candidate_ids": [...], "search_stats": {...}}

Step 3: dedup_filter
   ├─ 职责：ID 级去重
   ├─ 工具：无
   └─ 输出：{"candidate_paper_ids": [...], "dedup_stats": {...}}
```

### 2.3 关键配置

**plan.yaml 核心配置**：
```yaml
steps:
  - step_id: "query_build"
    tools_required: []
    success_criteria:
      required_fields: ["query_string"]
  - step_id: "search_execute"
    tools_required: ["pubmed_search"]
    success_criteria:
      required_fields: ["candidate_ids"]
      min_count: {candidate_ids: 1}
  - step_id: "dedup_filter"
    tools_required: []
    success_criteria:
      required_fields: ["candidate_paper_ids"]
      min_count: {candidate_paper_ids: 1}
```

**identity.yaml 核心配置**：
```yaml
agent_name: "search_agent"
role: "生物医学文献检索专家"
output_contract:
  candidate_paper_ids: "至少 1 篇，list[str] 类型"
  search_summary: "不超过 200 字的检索过程摘要"
```

---

## 三、extract_agent 开发记录

### 3.1 开发背景

extract_agent 是全新构建的 Agent，参考了旧版 `text_agent.py` 的 10 阶段流程，但采用新的 AgentTemplate 架构重新实现。

### 3.2 旧版 text_agent.py 分析

**旧版 10 阶段流程**：
```
阶段 1  → PDF 文本提取
阶段 2  → DOI 预查重
阶段 3  → 生成 paper_id
阶段 4  → 初始化 TraceLogger
阶段 5  → 构建 System/User Prompt
阶段 6  → 调用 LLM
阶段 7  → 插入 trace_step
阶段 8  → 解析 LLM 响应
阶段 9  → 业务字段校验
阶段 10 → 写入业务数据库
```

### 3.3 新版 extract_agent 设计

**设计原则**：
- 保留核心 LLM 抽取逻辑
- 适配 AgentTemplate 架构
- 简化为 2 步流程

### 3.4 目录结构

```
backend/src/agents/extract_agent/
├── __init__.py              # 导出 create_extract_agent
├── agent.py                  # 入口函数
├── plan.yaml                 # 执行计划（2 步）
├── identity.yaml             # 身份配置
├── skills/
│   ├── extraction_guide.md   # FAE 抽取指南
│   └── field_dict_guide.md   # 字段字典规范
├── graph_integration.py      # Graph 层集成示例
└── [遗留模块，兼容旧版]
    ├── text_agent.py
    ├── pdf_extractor.py
    ├── prompt_builder.py
    └── ...
```

### 3.5 执行流程

```
Step 1: llm_extract
   ├─ 职责：LLM 信息抽取
   ├─ 工具：无（LLM 调用由 executor 处理）
   ├─ 输入：paper_texts（论文 PDF 文本）
   └─ 输出：
       {
         "papers": [...],
         "extraction_stats": {
           "papers_processed": N,
           "papers_succeeded": M,
           "papers_failed": K
         }
       }

Step 2: validate_output
   ├─ 职责：输出格式校验
   ├─ 工具：无
   ├─ 输入：上一步的 papers
   └─ 输出：
       {
         "validation_result": "pass" | "partial" | "fail",
         "valid_papers": [...],
         "invalid_papers": [...],
         "summary": "..."
       }
```

### 3.6 关键配置

**plan.yaml 核心配置**：
```yaml
steps:
  - step_id: "llm_extract"
    tools_required: []
    success_criteria:
      required_fields: ["papers"]
      min_count: {papers: 1}
    max_retries: 2
  - step_id: "validate_output"
    tools_required: []
    success_criteria:
      required_fields: ["validation_result", "valid_papers"]
    max_retries: 1
```

**identity.yaml 核心配置**：
```yaml
agent_name: "extract_agent"
role: "生物医学文献信息提取专家"
output_contract:
  extracted_papers: "list[dict]，每篇论文的抽取结果"
  extraction_summary: "不超过 200 字的抽取过程摘要"
  failed_papers: "list[dict]，抽取失败的论文及错误原因"
```

---

## 四、Graph 层集成

### 4.1 PipelineState 扩展

更新 `graph/state.py`，添加 extract_agent 相关字段：

```python
class PipelineState(TypedDict, total=False):
    # Extract Agent 产出
    extracted_papers: list[dict]
    """成功抽取的论文结构化记录列表"""

    failed_papers: list[dict]
    """抽取失败的论文列表及错误原因"""
```

### 4.2 output_adapter 扩展

更新 `agent_template/output_adapter.py`，添加 extract_agent 字段映射：

```python
# extract_agent 特定字段映射
if agent_name == "extract_agent":
    if "papers" in final:
        patch["extracted_papers"] = final["papers"]
    if "failed_papers" in final:
        patch["failed_papers"] = final["failed_papers"]
```

### 4.3 工作流示例

```python
# search_agent → extract_agent 工作流
workflow = StateGraph(WorkflowState)
workflow.add_node("search", search_node)
workflow.add_node("extract", extract_node)
workflow.add_edge(START, "search")
workflow.add_edge("search", "extract")
workflow.add_edge("extract", END)
app = workflow.compile()
```

---

## 五、测试记录

### 5.1 测试环境

| 项目 | 值 |
|------|-----|
| Python | 3.14.2 |
| pytest | 9.0.3 |
| 测试框架 | pytest + anyio |
| 工作目录 | `PepClaw/backend` |

### 5.2 测试结果

**执行命令**：
```bash
cd backend && python -m pytest tests/test_search_agent.py tests/test_extract_agent.py -v
```

**结果**：✅ **18 passed, 2 warnings in 10.95s**

### 5.3 search_agent 测试详情

| 测试用例 | 结果 | 说明 |
|---------|------|------|
| test_create_agent | ✅ PASSED | Agent 实例创建 |
| test_config_values | ✅ PASSED | 配置值验证 |
| test_plan_steps | ✅ PASSED | 3 步计划加载 |
| test_identity_config | ✅ PASSED | 身份配置验证 |
| test_plan_step_requirements | ✅ PASSED | 步骤工具要求 |
| test_custom_model | ✅ PASSED | 自定义模型 |
| test_plan_file_exists | ✅ PASSED | 文件存在性 |

### 5.4 extract_agent 测试详情

| 测试用例 | 结果 | 说明 |
|---------|------|------|
| test_create_agent | ✅ PASSED | Agent 实例创建 |
| test_config_values | ✅ PASSED | 配置值验证 |
| test_plan_steps | ✅ PASSED | 5 步计划加载（集成 RAG） |
| test_identity_config | ✅ PASSED | 身份配置验证 |
| test_plan_step_requirements | ✅ PASSED | 步骤工具要求 |
| test_step_instructions | ✅ PASSED | 步骤指令内容 |
| test_custom_model | ✅ PASSED | 自定义模型 |
| test_plan_file_exists | ✅ PASSED | 文件存在性 |
| test_skills_files_exist | ✅ PASSED | 技能文件存在 |
| test_success_criteria | ✅ PASSED | 成功标准配置 |
| test_max_retries | ✅ PASSED | 最大重试次数 |

### 5.5 警告信息

测试过程中出现 2 个警告，但不影响功能：

```
UserWarning: Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater.
LangChainPendingDeprecationWarning: The default value of `allowed_objects` will change in a future version.
```

**原因**：项目依赖的 langchain 与 Python 3.14 的兼容性警告，不影响功能。

---

## 六、文件清单

### 6.1 新建文件

| 文件路径 | 说明 |
|----------|------|
| `extract_agent/identity.yaml` | extract_agent 身份配置 |
| `extract_agent/plan.yaml` | extract_agent 执行计划 |
| `extract_agent/skills/extraction_guide.md` | FAE 抽取指南 |
| `extract_agent/skills/field_dict_guide.md` | 字段字典规范 |
| `extract_agent/agent.py` | extract_agent 入口函数 |
| `extract_agent/graph_integration.py` | Graph 层集成示例 |
| `backend/tests/test_extract_agent.py` | extract_agent 测试文件 |

### 6.2 修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `extract_agent/__init__.py` | 修复导入，导出 create_extract_agent |
| `agent_template/output_adapter.py` | 添加 extract_agent 字段映射 |
| `graph/state.py` | 添加 extracted_papers、failed_papers 字段 |

### 6.3 现有文件（未修改）

| 文件路径 | 说明 |
|----------|------|
| `search_agent/` | 全部文件已存在，无需修改 |

---

## 七、调用示例

### 7.1 search_agent

```python
from backend.src.agents.search_agent.agent import create_search_agent

# 创建 agent
agent = create_search_agent()

# 执行检索
result = agent.run(
    pipeline_state={"query": "HAp peptide biomineralization"}
)

# 获取结果
print(result.final_output["candidate_paper_ids"])
print(result.final_output["search_summary"])
```

### 7.2 extract_agent

```python
from backend.src.agents.extract_agent.agent import create_extract_agent

# 创建 agent
agent = create_extract_agent()

# 执行抽取
result = agent.run(
    pipeline_state={"paper_texts": ["论文1文本...", "论文2文本..."]}
)

# 获取结果
print(result.final_output["papers"])
print(result.final_output["extraction_stats"])
```

### 7.3 Graph 层集成

```python
from backend.src.agents.extract_agent.graph_integration import create_extract_workflow

# 创建工作流
app = create_extract_workflow()

# 执行
result = app.invoke({
    "query": "HAp peptide biomineralization",
    "candidate_paper_ids": [],
    "extracted_papers": [],
    "workflow_summary": "",
})

print(f"候选文献数: {len(result['candidate_paper_ids'])}")
print(f"抽取记录数: {len(result['extracted_papers'])}")
```

---

## 八、RAG 集成（2026-06-08 更新）

### 8.1 RAG 流程

```
PDF 文档
    ↓
[1] chunk_documents（文档切块）→ RAGFlow 视觉解析
    ↓
[2] embed_and_index（Embedding + 建索引）→ BGE-M3 混合向量索引
    ↓
[3] retrieve_context（RAG 召回）→ 上下文回填
    ↓
[4] llm_extract（LLM 信息抽取）→ 使用召回上下文
    ↓
[5] validate_output（输出校验）
```

### 8.2 新增/修改的文件

| 文件路径 | 说明 |
|----------|------|
| `rag/as_tool.py` | 新增：RAG 工具接口封装 |
| `backend/src/tools/registry.py` | 修改：注册 RAG 工具 |
| `extract_agent/plan.yaml` | 修改：新增 3 个 RAG 步骤 |
| `extract_agent/agent.py` | 修改：配置 RAG 工具 |
| `extract_agent/skills/rag_guide.md` | 新增：RAG 使用指南 |

### 8.3 RAG 工具

| 工具名称 | 功能 | 输入 | 输出 |
|----------|------|------|------|
| `chunk_document` | 文档切块 | pdf_path | chunks 列表 |
| `build_rag_index` | 建立向量索引 | chunks | indexed_count |
| `retrieve_chunks` | RAG 召回 | query, top_k, threshold | context_summary |
| `reset_rag_state` | 重置状态 | - | status |

### 8.4 测试结果

```
============================= test session starts =============================
tests\test_extract_agent.py::TestExtractAgent::test_create_agent PASSED  [  9%]
tests\test_extract_agent.py::TestExtractAgent::test_config_values PASSED [ 18%]
tests\test_extract_agent.py::TestExtractAgent::test_plan_steps PASSED    [ 27%]
...
============================== 11 passed, 2 warnings in 12.96s ========================
```

---

## 九、后续工作

### 9.1 screen_agent

screen_agent 尚未迁移到 AgentTemplate 架构，后续需要：
1. 创建 `screen_agent/plan.yaml`
2. 创建 `screen_agent/identity.yaml`
3. 创建 `screen_agent/agent.py`
4. 更新 Graph 层工作流

### 8.2 完整 Pipeline

最终目标是实现完整的三阶段工作流：

```
search_agent → screen_agent → extract_agent
```

---

## 九、附录

### 9.1 AgentTemplate 架构要点

```
┌─────────────────────────────────────────────────────────────┐
│  AgentTemplate(config)                                      │
│  ├─ 初始化时加载：                                          │
│  │    ├─ plan.yaml → Plan 对象                            │
│  │    ├─ identity.yaml → dict                             │
│  │    └─ skills/*.md → dict                               │
│  └─ 运行时不加载，通过 self.xxx 直接访问                     │
│                                                             │
│  agent.run()                                                │
│  ├─ PlanRunner.run() → while 循环执行 steps                │
│  ├─ ContextBuilder.build_context() → 组合 prompt           │
│  ├─ Executor.run_step() → create_react_agent()            │
│  └─ Validator.validate_step() → 校验结果                    │
└─────────────────────────────────────────────────────────────┘
```

### 9.2 关键设计原则

| 原则 | 说明 |
|------|------|
| 组合优于继承 | Agent 通过配置注入，不继承模板 |
| 初始化与运行分离 | 初始化加载配置，运行时不重复加载 |
| 上下文传递 | 通过 TemplateAgentState 共享状态 |
| 摘要压缩 | 只传 step summary，不传完整 messages |

---

**日志生成时间**：2026-06-07  
**生成工具**：Trae AI  
**文档版本**：v1.0
