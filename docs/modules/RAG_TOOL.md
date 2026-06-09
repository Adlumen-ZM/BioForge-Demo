# RAG 工具 README

## 定位

RAG 是 Agent 外接工具，负责 PDF 解析、证据召回和结构化抽取。

## 文件

```text
rag/service.py
rag/core/orchestrator.py
rag/retrieval/bge_hybrid_retriever.py
rag/extraction/llm_extractor.py
backend/src/tools/rag_paper/tools.py
backend/src/tools/rag_paper/schemas.py
backend/src/tools/rag_paper/normalizer.py
backend/src/tools/rag_paper/csv_writer.py
```

## 三个工具

1. `run_bio_paper_extraction_pipeline`：PDF 到五表 CSV。
2. `parse_pdf_with_ragflow`：只解析 PDF，返回 parse_id。
3. `retrieve_pdf_evidence`：基于 parse_id 检索证据。

## 输出五表

```text
paper.csv
paper_entity_record.csv
entity_component.csv
record_function.csv
function_assay_evidence.csv
```

## 环境

需要 RAGFlow、LLM、BGE 相关环境变量。Demo 无真实 RAG 服务时应允许 mock 或跳过。
