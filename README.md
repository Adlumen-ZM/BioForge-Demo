# BioForge: Agentic Framework for Biomedical Literature Mining

BioForge 是一个面向生物医学文献挖掘的多智能体框架。本 demo 版本以 HAp 结合肽段文献抽取任务 为示例，串联 Guide Agent、PubMed 检索、文献筛选、PDF 下载、RAG 抽取、业务 SQLite 写入和 Trace 记录等多模块，搭建了检索、筛选到抽取的全流程。

## BioForge-Video-and-Photo
https://github.com/user-attachments/assets/0a7216b3-0ad2-4479-90b0-688ff393e727

**获取高清展示视频及更多使用截图:** 链接: https://pan.baidu.com/s/1oPC0cAVSq4jC_eADKjQHfg?pwd=nhfr 提取码: nhfr 

主要运行链路：

```text
用户确认任务 / 字段 / 纳排标准
  -> Guide Agent
  -> init_business_db
  -> Search Agent: 构建检索式，PubMed 检索及去重
  -> Screen Agent: 文献筛选及PDF 下载
  -> Extract Agent: 调用 RAGFlow，BGE-M3，LLM 召回获得数据
  -> DB Write: 写入业务 SQLite
  -> export-db: 从业务库导出为 CSV
```

## Repository Structure

```text
demo/
├── Dockerfile                    # Docker 环境镜像：安装依赖并预加载 BGE-M3
├── docker-compose.yml            # Compose 运行入口，服务名为 bioforge
├── .env.example                  # 环境变量模板，需要复制为 .env 后填写必填项
├── requirements.txt              # Python 依赖清单
├── README.md                     # 仓库入口说明
├── docs/
│   ├── DOCKER_USAGE.md           # Docker 构建、拉取、运行的详细说明
│   ├── CLI_GUIDE.md              # CLI 使用指南
│   ├── RUNNING.md                # 运行说明
│   ├── TECHNICAL_ROUTE.md        # 技术路线
│   ├── DEMO_FLOW.md              # Demo 流程说明
│   ├── schema_templates/         # 抽取字段和 CSV schema
│   ├── modules/                  # 各模块详细文档
│   └── operations/               # Docker、测试、排错等开发运维文档
├── backend/
│   └── src/
│       ├── cli/                  # Rich CLI：对话、进度面板、export-db
│       ├── graph/                # LangGraph state / nodes / pipeline / factory
│       ├── agents/
│       │   ├── guide_agent/      # 任务、schema、criteria 确认
│       │   ├── search_agent/     # PubMed 检索 Agent
│       │   ├── screen_agent/     # 文献筛选与 PDF 下载 Agent
│       │   ├── extract_agent/    # 调用 RAG 工具生成 CSV
│       │   └── agent_template/   # Plan-and-Execute + ReAct 通用运行时
│       ├── tools/                # LangChain tools：search / screen / rag_paper
│       └── db_access/            # 业务库、Trace、CSV 写入/导出访问
├── rag/                          # 本地 RAG 业务代码、RAGFlow parser、BGE 检索、LLM 抽取
├── db/                           # SQL schema、初始化脚本和数据库设计资产
├── data/                         # 运行数据：SQLite、PDF、RAG CSV、trace
├── output/                       # export-db 默认的导出目录
├── scripts/                      # 调试、迁移及单独运行脚本
├── verify_cli.py                 # CLI 基础验证脚本
├── pyproject.toml                # Ruff 等开发过程的代码审查配置
├── .github/                      # GitHub Actions / CI 配置
├── .review.yml                   # Review 配置
└── CLAUDE.md                     # 基于 Claude Code 和 Codex 的 vibe coding 协作上下文和开发约定
```

## Quick Start

### 1. 获取仓库

```bash
git clone <your-repo-url> bioforge-demo
cd bioforge-demo
```

如果你已经有本仓库副本，直接进入目录即可：

```powershell
cd D:\Dev\BioForge\demo
```

### 2. 复制并编辑 `.env`

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

请至少填写 `.env` 中标记为 `[REQUIRED]` 的项目，尤其是：

```env
# OpenAI 兼容接口
OPENAI_API_KEY=your_openai_compatible_api_key_here
OPENAI_API_BASE=https://your-openai-compatible-endpoint/v1
DEFAULT_LLM_MODEL=openai/your-model-name

RAGFLOW_API_BASE_URL=https://ragflow.adlumen.top
RAGFLOW_API_KEY=ragflow-xxxxxxxxxxxxxxxx

NCBI_EMAIL=your_email@example.com # 可选，注册后填写可以提升检索和文献下载速度
```

RAGFlow 需要配置可用的 API base URL 和 token。我们之前提交的 zip 中提供了可参考的 RAGFlow 配置；你也可以使用自己的 RAGFlow 服务。如果在 Docker 容器中访问宿主机本地 RAGFlow，通常应使用：

```env
RAGFLOW_API_BASE_URL=http://host.docker.internal:9380
```

另外，请不要把 `/api/v1` 拼到 `RAGFLOW_API_BASE_URL` 后面，代码会自动拼接。

### 3. 准备 Docker 镜像

BioForge 当前推荐使用 Docker 作为环境镜像，镜像里包含依赖和 BGE-M3 缓存，代码通过 volume 挂载到 `/app`。

#### 方案 A：本地构建

使用 Compose 构建：

```bash
docker compose build bioforge
```

等价的直接 build：

```bash
docker build \
  --build-arg HF_ENDPOINT=https://huggingface.co \
  --build-arg PYTORCH_VERSION=2.12.0 \
  -t bioforge:demo .
```

如果 HuggingFace 访问较慢，可以改用镜像站：

```bash
docker build \
  --build-arg HF_ENDPOINT=https://hf-mirror.com \
  --build-arg PYTORCH_VERSION=2.12.0 \
  -t bioforge:demo .
```

#### 方案 B：拉取 Docker Hub 镜像

```bash
docker pull jamesizhao/bioforge:demo
```

如果使用 Compose 拉取远端镜像，请把 `.env` 中镜像名改成：

```env
DOCKER_IMAGE=jamesizhao/bioforge
DOCKER_TAG=demo
```

然后运行：

```bash
docker compose pull bioforge
```

### 4. 挂载代码目录运行

#### Compose 方式

先做环境检查：

```bash
docker compose run --rm bioforge python -m backend.src.cli --check-only
```

启动交互 CLI：

```bash
docker compose run --rm bioforge python -m backend.src.cli
```

#### 直接 `docker run`

本地构建镜像：

```powershell
docker run -it --rm `
  --name bioforge-demo-test `
  -v "D:\Dev\BioForge\demo:/app" `
  --env-file "D:\Dev\BioForge\demo\.env" `
  -w /app `
  bioforge:demo `
  python -m backend.src.cli
```

若拉取 Docker Hub 镜像：

```powershell
docker run -it --rm `
  --name bioforge-demo-test `
  -v "D:\Dev\BioForge\demo:/app" `
  --env-file "D:\Dev\BioForge\demo\.env" `
  -w /app `
  jamesizhao/bioforge:demo `
  python -m backend.src.cli
```

### 5. 使用 CLI

进入 CLI 后可以输入：

```text
/help       查看命令帮助
/demo       按提示运行完整 demo
demo        等价于 /demo
/export-db  将业务数据库导出为 CSV
export-db   等价于 /export-db
/quit       退出
```

Demo 会按提示进行任务确认、schema 确认、纳排标准确认，然后自动运行检索、筛选、下载、RAG 抽取和写库。

如果启动或运行报错，请优先检查：

- `.env` 是否填了 LLM key、model、RAGFlow URL、RAGFlow token、NCBI email。
- `RAGFLOW_API_BASE_URL` 是否能从容器内访问。
- 如果使用本机 RAGFlow，容器内通常使用 `http://host.docker.internal:9380`，不是 `http://localhost:9380`。
- PDF 上传到公网 RAGFlow 可能受到网关超时影响，较大的 PDF 建议控制在 5MB 以下。

### 6. 导出结果

运行完成后，业务数据会写入：

```text
/app/data/hap_v01.db
```

在 CLI 中输入：

```text
export-db
```

会把当前业务库反向导出成 CSV，默认输出到仓库根目录：

```text
output/<数据库名>-<时间>/
```

Docker 容器内路径示例：

```text
/app/output/hap_v01-20260610-142504/
```

宿主机对应：

```text
D:\Dev\BioForge\demo\output\hap_v01-20260610-142504\
```

导出的五张表单如下：

```text
paper.csv
paper_entity_record.csv
entity_component.csv
record_function.csv
function_assay_evidence.csv
```

也可以指定数据库和输出目录：

```text
/export-db /app/data/hap_v01.db /app/output/my-export
```

## Output Locations

```text
data/
├── hap_v01.db                                      # demo 默认业务 SQLite
├── hap_trace.db                                    # legacy trace SQLite
├── projects/hap_peptide_v1/
│   └── papers/{paper_key}/
│       ├── raw/source.pdf                          # 下载或缓存的原始 PDF
│       └── outputs/rag_csv/*.csv                   # 单篇 RAG 抽取 CSV
└── runs/
    ├── run_xxx/trace/summary.json                  # 本轮运行摘要
    ├── run_xxx/trace/timeline.md                   # 时间线摘要
    └── YYYYMMDD/run_xxx/trace/events.jsonl         # 结构化 trace 事件

output/
└── hap_v01-YYYYMMDD-HHMMSS/*.csv                   # export-db 导出的全库 CSV
```

## Documentation

总体技术说明：

- [Docker 使用说明](docs/DOCKER_USAGE.md)
- [CLI 使用指南](docs/CLI_GUIDE.md)
- [运行说明](docs/RUNNING.md)
- [Demo 流程](docs/DEMO_FLOW.md)
- [技术路线](docs/TECHNICAL_ROUTE.md)
- [环境变量说明](docs/ENVIRONMENT.md)
- [架构说明](docs/architecture.md)
- [Guide CLI 技术规范](docs/guide_cli_technical_spec.md)

模块代码说明：

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

开发协作说明：

- [Docker 与开发协作](docs/operations/DOCKER_AND_DEV.md)
- [测试与排错](docs/operations/TESTING_AND_TROUBLESHOOTING.md)
- [Docker 环境细节](docs/DOCKER_ENVIRONMENT.md)
- [开发日志](docs/development_log.md)
- [Agent 开发指南](docs/agent_dev_guide.md)
