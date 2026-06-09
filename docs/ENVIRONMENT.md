# 环境变量说明

## LLM

| 变量 | 说明 |
|---|---|
| `DEFAULT_LLM_MODEL` | AgentTemplate / Guide 默认模型 |
| `OPENAI_API_KEY` | OpenAI-compatible key |
| `MINIMAX_API_KEY` | MiniMax key |
| `ANTHROPIC_API_KEY` | Anthropic key |
| `LLM_API_KEY` | RAG 抽取 LLM key |
| `LLM_BASE_URL` | RAG 抽取 LLM base url |
| `LLM_MODEL` | RAG 抽取模型 |
| `LLM_TEMPERATURE` | 抽取建议 0 |

## 运行模式

| 变量 | 值 | 说明 |
|---|---|---|
| `GRAPH_AGENT_MODE` | `demo` | 推荐 Demo 模式 |
| `GRAPH_AGENT_MODE` | `real` | 启用真实工具，需要完整外部服务 |

## PubMed / NCBI

| 变量 | 说明 |
|---|---|
| `NCBI_EMAIL` | NCBI 要求提供 |
| `NCBI_API_KEY` | 可选，提高速率 |

## 数据与业务库

| 变量 | 说明 |
|---|---|
| `DATA_ROOT` | 数据根目录 |
| `EXTRACTION_PROFILE` | 默认 `hap_peptide_v1` |
| `BIZ_DB_PATH` | SQLite 业务库路径 |
| `BIZ_DB_BACKEND` | 当前为 `sqlite` |
| `DATABASE_URL` | 未来 PostgreSQL 业务库 |

## Schema

| 变量 | 说明 |
|---|---|
| `TEMPLATE_VERSION` | 模板版本 |
| `SCHEMA_TEMPLATE_PATH` | 显式 schema.yaml 路径，可为空 |
| `FIELD_MAPPING_PATH` | 字段映射路径，可为空 |

## Trace

| 变量 | 说明 |
|---|---|
| `TRACE_ENABLED` | Trace 总开关 |
| `TRACE_FILE_ENABLED` | 是否写 JSONL |
| `TRACE_CLI_ENABLED` | 是否推送到 CLI |
| `TRACE_CLI_LEVEL` | `quiet/normal/debug` |
| `TRACE_DATA_ROOT` | Trace 根目录 |
| `TRACE_DB_URL` | PostgreSQL Trace 后端 |

## RAG

| 变量 | 说明 |
|---|---|
| `RAGFLOW_API_BASE_URL` | RAGFlow 地址 |
| `RAGFLOW_API_KEY` | RAGFlow key |
| `BGE_MODEL_DIR` | BGE-M3 模型路径 |
| `BGE_USE_FP16` | 是否 FP16 |
| `BGE_DENSE_WEIGHT` | 稠密权重 |
| `BGE_SPARSE_WEIGHT` | 稀疏权重 |
| `RETRIEVAL_TOP_K` | 召回数量 |
| `RETRIEVAL_THRESHOLD` | 召回阈值 |
