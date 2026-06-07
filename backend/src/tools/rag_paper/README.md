# tools/rag_paper/ — PepClaw LangChain 工具注册层

## 概述

本目录将 `rag.service.BioPaperRAGService` 的核心能力包装为
**LangChain `@tool`**，供 Agent（LangGraph / ReAct / ToolCallingAgent）直接调用。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `__init__.py` | 包入口，导出三个工具函数 |
| `schemas.py` | 工具输入参数的 Pydantic 校验模型 |
| `service_factory.py` | `build_rag_service()`：从环境变量构造服务实例 |
| `tools.py` | `@tool` 装饰的三个 LangChain 工具函数 |

---

## 三个工具

### 1. `run_bio_paper_extraction_pipeline`

**一键全流程抽取**（Scout + Strike）

```python
result = run_bio_paper_extraction_pipeline.invoke({"pdf_path": "/data/paper.pdf"})
# 返回 paper_meta 和 entities
```

### 2. `parse_pdf_with_ragflow`

**解析 PDF，获取 parse_id**

```python
parsed = parse_pdf_with_ragflow.invoke({"pdf_path": "/data/paper.pdf"})
parse_id = parsed["parse_id"]
```

### 3. `retrieve_pdf_evidence`

**定向检索特定字段的文献证据**

```python
evidence = retrieve_pdf_evidence.invoke({
    "parse_id": parse_id,
    "query": "HAp crystallinity XRD Raman",
    "top_k": 8,
})
```

---

## 在 Agent 中注册

```python
from tools.rag_paper import (
    run_bio_paper_extraction_pipeline,
    parse_pdf_with_ragflow,
    retrieve_pdf_evidence,
)

tools = [
    run_bio_paper_extraction_pipeline,
    parse_pdf_with_ragflow,
    retrieve_pdf_evidence,
]

# 绑定到 LLM
llm_with_tools = llm.bind_tools(tools)
```

---

## 调用流程示意

```
Agent
 ├─ (方案 A) run_bio_paper_extraction_pipeline(pdf_path)
 │              └── rag.service.run_pipeline()
 │
 └─ (方案 B) parse_pdf_with_ragflow(pdf_path) -> parse_id
              retrieve_pdf_evidence(parse_id, query_1)
              retrieve_pdf_evidence(parse_id, query_2)
               └── rag.service.retrieve_evidence()
```

---

## 环境变量

必填：`RAGFLOW_API_BASE_URL`、`RAGFLOW_API_KEY`、`LLM_API_KEY`

参见项目根目录 `.env.example` 中 `PepClaw RAG Integration` 段落。
