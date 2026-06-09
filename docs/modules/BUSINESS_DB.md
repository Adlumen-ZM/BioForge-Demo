# 业务数据库 README

## 定位

业务数据库存储最终科研数据，回答“抽取到了什么”。它与 Trace 分离。

## 文件

```text
db/business/sqlite_init.py
db/business/field_dict.json
backend/src/db_access/business/init_service.py
backend/src/db_access/business/csv_writer.py
docs/schema_templates/hap_peptide_v1/schema.yaml
```

## 初始化

```python
ensure_business_db(template_id="hap_peptide_v1", extraction_profile="hap_peptide_v1")
```

## 表

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

## 写入

`write_rag_csv_to_business_db(csv_dir, db_path, template_id, run_id, paper_key)` 按五表 CSV 写入 SQLite，默认 `INSERT OR IGNORE` 幂等。
