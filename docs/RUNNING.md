# 代码运行说明

## 1. 本地环境准备

```bash
cd template_agent_dev
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

确认导入：

```bash
python - <<'PYCODE'
from backend.src.graph.pipeline import build_graph
from backend.src.tools.registry import list_registered_tools
print(build_graph)
print(list_registered_tools())
PYCODE
```

## 2. 配置环境变量

```bash
cp .env.example .env
```

最小 Demo 配置：

```env
GRAPH_AGENT_MODE=demo
DEFAULT_LLM_MODEL=openai/your-model
OPENAI_API_KEY=your_key
NCBI_EMAIL=your_email@example.com
DATA_ROOT=./data
EXTRACTION_PROFILE=hap_peptide_v1
BIZ_DB_PATH=./data/projects/hap_peptide_v1/db/business.sqlite
TRACE_ENABLED=true
TRACE_FILE_ENABLED=true
TRACE_CLI_ENABLED=true
TRACE_DATA_ROOT=./data/runs
```

真实 RAG 配置：

```env
RAGFLOW_API_BASE_URL=https://your-ragflow-host
RAGFLOW_API_KEY=ragflow-xxxx
LLM_API_KEY=your_llm_key
LLM_BASE_URL=https://your-openai-compatible-base-url
LLM_MODEL=your-model
BGE_MODEL_DIR=BAAI/bge-m3
RETRIEVAL_TOP_K=8
RETRIEVAL_THRESHOLD=0.1
```

## 3. 系统检查

```bash
python -m backend.src.cli --check-only
```

输出应包含：

```text
LLM
TraceDB
BizDB
Mode
Checkpoint
```

常见 warning：

- `No module named sqlalchemy`：未完整安装依赖，执行 `pip install -r requirements.txt`。
- `BIZ_DB_PATH 未配置`：检查 `.env` 是否在项目根目录被加载。

## 4. 运行 CLI Demo

```bash
python -m backend.src.cli
```

运行顺序：

```text
system_check
  ↓
print_banner
  ↓
CLISession + TraceManager
  ↓
build_graph(mode, MemorySaver)
  ↓
Guide Agent 四步 interrupt 对话
  ↓
Search/Screen/Extract/WriteDB 进度面板
```

## 5. 检查输出

```bash
find data/runs -maxdepth 4 -type f | sort
find data/projects -maxdepth 6 -type f | sort
```

查看 trace：

```bash
tail -20 data/runs/*/run_*/trace/events.jsonl
```

查看数据库：

```bash
sqlite3 data/projects/hap_peptide_v1/db/business.sqlite '.tables'
sqlite3 data/projects/hap_peptide_v1/db/business.sqlite 'select * from workflow_extraction_call limit 5;'
```

## 6. 验证脚本

```bash
python verify_cli.py
python -m pytest backend/tests -v
```

`verify_cli.py` 检查 CLI 模块导入、系统检测、会话管理和进度表构建。

## 7. 单模块调试

### 7.1 初始化业务库

```python
from backend.src.db_access.business import ensure_business_db
print(ensure_business_db(template_id="hap_peptide_v1", extraction_profile="hap_peptide_v1"))
```

### 7.2 调用 Search Agent

```python
from backend.src.agents.search_agent.agent import create_search_agent
agent = create_search_agent()
print(agent.run({"run_id": "debug", "query": "hydroxyapatite binding peptide"}))
```

### 7.3 调用 RAG 工具

```python
from backend.src.tools.rag_paper.tools import run_bio_paper_extraction_pipeline
result = run_bio_paper_extraction_pipeline.invoke({
    "pdf_path": "/absolute/path/to/paper.pdf",
    "output_dir": "./data/projects/hap_peptide_v1/papers/demo/outputs/rag_csv",
    "template_id": "hap_peptide_v1",
})
print(result)
```

## 8. Docker 运行

当前 Dockerfile 不复制业务代码。推荐修改 `docker-compose.yml`：

```yaml
services:
  pepclaw:
    build: .
    image: bioforge:local
    volumes:
      - ./:/app
      - ./.env:/app/.env
      - ./data:/app/data
    working_dir: /app
    stdin_open: true
    tty: true
```

命令：

```bash
docker compose build
docker compose run --rm pepclaw python -m backend.src.cli --check-only
docker compose run --rm pepclaw python -m backend.src.cli
```

当前文档生成环境没有 Docker CLI，因此未实际构建镜像。
