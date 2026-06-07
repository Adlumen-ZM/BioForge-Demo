# rag/ — PepClaw RAG 能力层

## 概述

本目录是 PepClaw 生物矿化文献结构化抽取系统的 **RAG 核心能力层**，
对外暴露唯一入口类：`BioPaperRAGService`。

Agent 框架通过 `backend/src/tools/rag_paper/` 中的 LangChain 工具调用本层，
**不应**直接 import 本层内部模块（`rag_pipeline.*`）。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `__init__.py` | 包入口，导出 `BioPaperRAGService` |
| `service.py` | **门面类**，封装解析 / 检索 / 抽取三大能力 |

---

## BioPaperRAGService 接口

### 初始化

```python
from rag.service import BioPaperRAGService

svc = BioPaperRAGService(
    ragflow_base_url="https://your-ragflow-host",  # 必填
    ragflow_api_key="ragflow-xxx",                  # 必填
    llm_api_key="your-llm-key",                     # 必填
    llm_base_url=None,       # 选填，None 表示 OpenAI 官方端点
    llm_model="gpt-4o",      # 选填，默认 gpt-4o
    bge_model_dir="BAAI/bge-m3",  # 选填
    bge_use_fp16=False,      # 选填，GPU 内存紧张时设为 True
    retrieval_top_k=8,       # 选填
    retrieval_threshold=0.1, # 选填
)
```

### 方法一：端到端抽取（推荐）

```python
result = svc.run_pipeline("/path/to/paper.pdf")
# 返回：
# {
#   "status": "ok",
#   "pdf_path": "/path/to/paper.pdf",
#   "paper_meta": {"title": ..., "authors": ..., "doi": ...},
#   "entities": [{"entity_type": "HApParticle", "fields": {...}}]
# }
```

### 方法二：两步流程（先解析，后多次检索）

```python
# Step 1: 解析 PDF，获取 parse_id
parsed = svc.parse_pdf("/path/to/paper.pdf")
parse_id = parsed["parse_id"]  # 32 位 md5 字符串

# Step 2: 用不同 query 多次检索（不重复解析）
evidence = svc.retrieve_evidence(
    parse_id=parse_id,
    query="HAp particle size XRD",
    top_k=8,
)
# 返回：
# {
#   "status": "ok",
#   "evidence": [{"chunk_id": "paper_p3_c5_text", "text": "..."}]
# }
```

---

## 依赖前提

本层依赖 PepClaw 的内部模块（`rag_pipeline.*`），需满足以下任一条件：

**方式 A（推荐）**：将 PepClaw 根目录加入 `PYTHONPATH`
```bash
export PYTHONPATH=/path/to/PepClaw:$PYTHONPATH
```

**方式 B**：以可编辑模式安装 PepClaw
```bash
pip install -e /path/to/PepClaw
```

---

## 环境变量

参见项目根目录 `.env.example` 中 `PepClaw RAG Integration` 段落。
