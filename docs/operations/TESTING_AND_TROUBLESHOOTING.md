# 测试、验证与排错

## 验证命令

```bash
python verify_cli.py
python -m backend.src.cli --check-only
python -m pytest backend/tests -v
```

## Tool 注册检查

```bash
python - <<'PYCODE'
from backend.src.tools.registry import list_registered_tools
print(list_registered_tools())
PYCODE
```

## Trace 检查

```bash
find data/runs -name events.jsonl -print
tail -20 data/runs/*/run_*/trace/events.jsonl
```

## 数据库检查

```bash
sqlite3 data/projects/hap_peptide_v1/db/business.sqlite '.tables'
sqlite3 data/projects/hap_peptide_v1/db/business.sqlite 'select * from workflow_extraction_call limit 5;'
```

## 常见问题

### No module named backend

在项目根目录运行，或在 Docker 中挂载 `.:/app`。

### No module named sqlalchemy

执行 `pip install -r requirements.txt`。

### Guide interrupt 无法 resume

构建 graph 时传入 checkpointer：`MemorySaver()`。

### write_db skipped

说明 `rag_csv_dir` 为空，检查 Extract Agent 和 RAG 工具输出。

### RAG 工具失败

检查 RAGFlow、LLM、BGE 环境变量和 PDF 路径。Demo 阶段可使用 mock 或跳过真实 RAG。
