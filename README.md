# BioForge Demo README

BioForge Demo 是一个面向 **HAp / 磷酸钙 / 牙体矿化相关肽段文献** 的多智能体结构化数据抽取系统。当前版本的目标是跑通一个可演示、可追踪、可扩展的端到端流程：用户通过 Guide Agent 明确任务、字段模板和纳排规则，系统再完成文献检索、筛选、下载、RAG 抽取、CSV 生成、业务数据库写入和 Trace 记录。

## 1. 当前版本定位

当前仓库的核心设计是三层解耦：

1. **字段设计与业务数据库**：定义抽取什么、字段粒度如何、结果如何长期存储。
2. **Agent 系统与 Trace 日志**：负责流程编排、任务拆解、工具调用和过程记录。
3. **RAG 工具**：作为外部能力被 Agent 调用，负责 PDF 解析、证据召回和字段抽取。

整体流程：

```text
用户输入研究目标/纳排规则
  ↓
Guide Agent 四步确认
  ↓
init_business_db
  ↓
Search Agent：构建检索式 → PubMed 检索 → 去重
  ↓
Screen Agent：筛选候选文献 → 下载/定位 PDF
  ↓
Extract Agent：调用 RAG 工具 → 输出五表 CSV
  ↓
write_rag_csv_to_db：写入业务数据库
  ↓
Trace 日志记录完整运行过程
```

## 2. 仓库结构

```text
template_agent_dev/
├── README.md                         # 项目首页
├── CLAUDE.md                         # 团队协作与 Claude Code 开发约定
├── Dockerfile                        # Python 3.11 环境镜像；当前不复制业务代码
├── docker-compose.yml                # Demo 容器编排
├── requirements.txt                  # Python 依赖
├── pyproject.toml                    # Ruff 配置
├── verify_cli.py                     # CLI 验证脚本
├── backend/
│   ├── src/
│   │   ├── agents/
│   │   │   ├── agent_template/       # Plan-and-Execute + ReAct 通用运行时
│   │   │   ├── guide_agent/          # Guide Agent，LangGraph interrupt HITL
│   │   │   ├── search_agent/         # Search Agent，PubMed 检索
│   │   │   ├── screen_agent/         # Screening Agent，筛选和下载
│   │   │   ├── extract_agent/        # Extraction Agent，调用 RAG 工具
│   │   │   └── _template/            # 新 Agent 脚手架
│   │   ├── graph/                    # LangGraph state / nodes / pipeline / factory
│   │   ├── cli/                      # Rich CLI，Guide 对话和流程进度展示
│   │   ├── tools/                    # LangChain @tool 注册与实现
│   │   ├── db_access/                # Business / Trace / Memory 访问层
│   │   └── server.py                 # 服务端占位
│   └── tests/                        # pytest 测试
├── db/
│   ├── business/                     # 业务数据库初始化和字段字典
│   ├── trace/                        # Trace 表结构
│   ├── memory/                       # Memory 设计占位
│   └── init/                         # SQL 初始化脚本
├── docs/
│   ├── schema_templates/             # hap_peptide_v1 字段模板
│   ├── architecture.md
│   ├── guide_cli_technical_spec.md
│   └── ...
├── rag/                              # RAG 解析、召回、抽取内核
├── scripts/                          # 调试、迁移、RAG 运行脚本
├── frontend/                         # 前端占位
├── data/                             # 本地数据库、trace、运行产物
└── tests_io/                         # 测试输入输出样例
```

## 3. 文档导航

### 总体说明

- [完整技术路线](docs/TECHNICAL_ROUTE.md)
- [代码运行说明](docs/RUNNING.md)
- [Demo 流程与运行实例](docs/DEMO_FLOW.md)
- [环境变量说明](docs/ENVIRONMENT.md)
- [Docker 与协作开发](docs/operations/DOCKER_AND_DEV.md)
- [测试与排错](docs/operations/TESTING_AND_TROUBLESHOOTING.md)

### 模块 README

- [Graph 编排模块](docs/modules/GRAPH.md)
- [AgentTemplate 通用运行时](docs/modules/AGENT_TEMPLATE.md)
- [Guide Agent](docs/modules/GUIDE_AGENT.md)
- [Search Agent](docs/modules/SEARCH_AGENT.md)
- [Screen Agent](docs/modules/SCREEN_AGENT.md)
- [Extract Agent](docs/modules/EXTRACT_AGENT.md)
- [Tools 注册与工具协议](docs/modules/TOOLS_REGISTRY.md)
- [RAG 工具](docs/modules/RAG_TOOL.md)
- [业务数据库](docs/modules/BUSINESS_DB.md)
- [Trace 日志](docs/modules/TRACE_LOGGING.md)
- [CLI 模块](docs/modules/CLI.md)
- [未来 MCP 集成](docs/modules/MCP_FUTURE.md)

## 4. QuickStart：本地运行

```bash
cd template_agent_dev
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python -m backend.src.cli --check-only
python -m backend.src.cli
```

最小 `.env` 关键项：

```env
GRAPH_AGENT_MODE=demo
DEFAULT_LLM_MODEL=openai/your-compatible-model
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

## 5. QuickStart：Docker 运行

当前 Dockerfile 是 **environment image**，只安装依赖，不复制业务代码。要在 Docker 中运行 CLI，必须在 compose 中挂载源码，或在 Dockerfile 中增加 `COPY . /app`。

推荐 compose 关键配置：

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

运行：

```bash
docker compose build
docker compose run --rm pepclaw python -m backend.src.cli --check-only
docker compose run --rm pepclaw python -m backend.src.cli
```

## 6. Demo 输出位置

```text
data/
├── projects/hap_peptide_v1/
│   ├── db/business.sqlite
│   └── papers/{paper_key}/outputs/rag_csv/*.csv
└── runs/YYYYMMDD/run_xxx/
    ├── trace/events.jsonl
    ├── operator_debug/*.jsonl
    └── artifacts/
```

## 7. 当前环境验证记录

本次文档生成时在当前容器内执行：

```text
python verify_cli.py                       ✅ 通过
python -m backend.src.cli --check-only     ⚠️ 可运行，但当前环境缺 sqlalchemy，且未配置 BizDB
Docker CLI                                 ❌ 当前环境未安装 docker
```

因此，CLI 模块结构验证通过；完整 demo 运行需要先在真实开发环境中安装 `requirements.txt` 并配置 `.env`。
