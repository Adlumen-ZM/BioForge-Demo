# Extraction Agent README

## 定位

Extract Agent 接收 PDF 路径和 schema 模板，调用 RAG 工具完成结构化抽取，并把 `rag_csv_dir` 交给 Graph 写库。

## 文件

```text
backend/src/agents/extract_agent/agent.py
backend/src/agents/extract_agent/plan.yaml
backend/src/agents/extract_agent/skills/*.md
backend/src/tools/rag_paper/tools.py
```

## 核心工具

```python
run_bio_paper_extraction_pipeline(pdf_path, output_dir, template_id="hap_peptide_v1", schema_template_path=None, overwrite=False)
```

## RAG 流程

```text
PDF → parser/RAGFlow → chunks → Scout 实体发现 → Hybrid retrieval → LLM extraction → normalizer → five-table CSV
```

## 输出

```python
extraction
extract_summary
rag_csv_dir
rag_csv_files
ragflow_ref
```

## 原则

Extract Agent 不直接写业务数据库；写库由 `write_db_node` 完成。
