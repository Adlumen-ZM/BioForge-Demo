# RAG 召回与上下文回填指南

## 1. RAG 在 extract_agent 中的作用

RAG（Retrieval-Augmented Generation）用于在 LLM 抽取前，先通过向量检索召回与研究目标相关的文档片段作为上下文，提升抽取的准确性和相关性。

## 2. RAG 流程

```
PDF 文档
    ↓
[1] chunk_documents（文档切块）
    ↓
[2] embed_and_index（Embedding + 建索引）
    ↓
[3] retrieve_context（RAG 召回）
    ↓
context_summary（召回的上下文）
    ↓
[4] llm_extract（LLM 信息抽取）
    ↓
结构化抽取结果
```

## 3. 工具调用说明

### 3.1 chunk_document

```python
result = chunk_document(pdf_path="paper.pdf")
# 返回：{status, chunks: [{chunk_id, text, type, is_abstract}], chunk_count, error}
```

**使用场景**：
- 输入是 PDF 文件路径时调用
- 解析后会返回结构化的文档块

### 3.2 build_rag_index

```python
result = build_rag_index(chunks=None, model_dir="BAAI/bge-m3", alpha=0.4, beta=0.6)
# chunks: 可选，不传则使用上一步的结果
# 返回：{status, indexed_count, error}
```

**使用场景**：
- 在完成文档切块后调用
- 建立 BGE-M3 混合向量索引

### 3.3 retrieve_chunks

```python
result = retrieve_chunks(
    query="FAE peptide adsorption mechanism on HAp",
    top_k=8,
    threshold=0.1
)
# 返回：{status, query, retrieved_chunks, retrieved_count, context_summary, error}
```

**使用场景**：
- 在建立索引后调用
- 根据研究目标 query 召回相关片段
- `context_summary` 将作为 LLM 抽取的上下文输入

## 4. 检索策略

### 4.1 Query 构建

针对生物医学文献检索，建议使用以下 query 模式：

```
模式1: "<肽段名称> + <矿物类型> + <相互作用类型>"
示例: "FAE peptide HAp adsorption"

模式2: "<实验方法> + <矿物类型>"
示例: "SEM analysis hydroxyapatite crystal growth"

模式3: "<生物活性> + <材料类型>"
示例: "osteogenic peptide calcium phosphate"
```

### 4.2 阈值设置

| 场景 | threshold | top_k |
|------|-----------|-------|
| 高精度（长论文） | 0.15 | 5 |
| 默认 | 0.1 | 8 |
| 高召回（短片段） | 0.05 | 10 |

## 5. 上下文回填

retrieve_chunks 返回的 `context_summary` 格式：

```
【检索结果：N 条相关片段】

--- [源区块 ID: xxx] ---
<召回的文本片段 1>

--- [源区块 ID: yyy] ---
<召回的文本片段 2>

...
```

此 context_summary 将自动注入到后续 llm_extract 步骤的 prompt 中，作为 LLM 抽取的上下文依据。

## 6. 错误处理

| 错误 | 原因 | 处理方式 |
|------|------|----------|
| "无可用 chunks" | 未调用 chunk_document | 检查步骤顺序 |
| "请先建立索引" | 未调用 build_rag_index | 检查步骤顺序 |
| 召回数量为 0 | query 不匹配或阈值过高 | 降低 threshold |
| RAGFlow 连接失败 | API 配置错误 | 检查环境变量 |

## 7. 性能考虑

- **批量处理**：多篇论文可共享同一个索引建立（如果内容相似）
- **内存管理**：处理完一篇论文后调用 `reset_rag_state()` 释放内存
- **并行检索**：多个 query 可并行调用 retrieve_chunks，然后合并结果