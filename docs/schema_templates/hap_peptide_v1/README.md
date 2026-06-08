# hap_peptide_v1 Schema Template

本目录是 HAp 相互作用肽段结构化抽取的 v1 字段模板目录，建议放置于仓库：

```text
docs/schema_templates/hap_peptide_v1/
```

## 文件说明

| 文件 | 用途 |
|---|---|
| `schema.yaml` | 机器可读的数据库字段模板，定义逻辑表、字段、枚举、必填性、来源、评估参与状态和物理映射。 |
| `filling_rules.md` | Agent skill / 人工标注规则，解释每个字段如何判断、如何填写、如何处理边界情况。 |
| `field_mapping.yaml` | 逻辑字段到 PostgreSQL 业务库物理表的映射约定。 |
| `examples/example_extraction_package.json` | 最小示例 extraction package，用于 Pydantic 校验、Agent 输出测试和 writer smoke test。 |

## 使用方式建议

1. `load_schema_contract_node` 读取 `schema.yaml`，生成当前任务的 `extraction_contract`。
2. `extract_agent` 将 `filling_rules.md` 作为 skill，结合 RAG tools 完成字段驱动抽取。
3. `validate_node` 根据 `schema.yaml` 和枚举值校验 extraction package。
4. `persist_node` 根据 `field_mapping.yaml` 调用 `save_extraction_package()` 写入 PostgreSQL business DB。

## 重要边界

- 本目录定义的是“逻辑字段模板”，不是运行中的数据库。
- 真正运行时数据库应由 `db/business/schema.sql` 或生成的 SQL 初始化到 PostgreSQL。
- Agent 不直接写业务库物理表；必须输出 extraction package，由 db_access/business 写入服务统一处理。
