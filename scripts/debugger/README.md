# BioForge 算子调优平台 — 完整操作手册

> **适用版本**：`template_agent_dev` 分支  
> **定位**：AgentTemplate 算子调试工具，用于在不接真实业务数据库的情况下，可视化调试、调参、对比各 agent 的运行行为。

---

## 目录

1. [启动方式](#1-启动方式)
   - [Docker Desktop（Windows / Mac）](#11-docker-desktop)
   - [WSL / Linux](#12-wsl--linux)
   - [原生 Mac（无 Docker）](#13-原生-mac无-docker)
2. [.env 配置详解](#2-env-配置详解)
3. [Langfuse LLM 追踪（可选）](#3-langfuse-llm-追踪可选)
4. [平台页面完整操作指南](#4-平台页面完整操作指南)
   - [主页（快捷运行）](#41-主页快捷运行)
   - [📋 01 运行历史](#42--01-运行历史)
   - [🔍 02 运行详情](#43--02-运行详情)
   - [⚡ 03 对比实验](#44--03-对比实验)
   - [⚙️ 04 运行编辑器（核心）](#45-️-04-运行编辑器核心)
4. [Agent 状态说明](#4-agent-状态说明)
5. [调整 Agent 真实配置](#5-调整-agent-真实配置)
   - [修改 Plan（步骤 / 工具 / 重试逻辑）](#51-修改-plan步骤--工具--重试逻辑)
   - [修改 Identity（角色定义）](#52-修改-identity角色定义)
   - [修改 Skills（操作指南）](#53-修改-skills操作指南)
   - [修改模型和运行参数](#54-修改模型和运行参数)
6. [解锁未实现的 Agent](#6-解锁未实现的-agent)
7. [新增一个 Agent](#7-新增一个-agent)

---

## 1. 启动方式

### 1.1 Docker Desktop

适用于 **Windows**（需安装 Docker Desktop）和 **Mac**（Docker Desktop for Mac）。

**第一步：确认镜像已构建**

```bash
# 在项目根目录（template_agent_dev/）下
docker images | grep bioforge
```

如果没有镜像，先构建：

```bash
docker build -t bioforge:local .
```

**第二步：启动 Streamlit 容器**

```bash
# Windows PowerShell（注意用 ${PWD} 获取当前路径）
docker run -it --rm `
  -v ${PWD}:/app `
  -p 8501:8501 `
  --env-file .env `
  bioforge:local `
  streamlit run scripts/debugger/app.py `
    --server.port=8501 `
    --server.address=0.0.0.0 `
    --server.headless=true

# Mac / Linux（bash，用 $(pwd)）
docker run -it --rm \
  -v $(pwd):/app \
  -p 8501:8501 \
  --env-file .env \
  bioforge:local \
  streamlit run scripts/debugger/app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true
```

**关键参数说明**：

| 参数 | 说明 |
|------|------|
| `-v $(pwd):/app` | 将项目根目录挂载到容器 `/app`，代码修改**实时生效**，无需重建镜像 |
| `-p 8501:8501` | 将容器内 Streamlit 端口暴露到宿主机 |
| `--env-file .env` | 注入 `.env` 中的环境变量（LLM Key、TRACE_DB_URL 等） |
| `--server.headless=true` | 容器内无浏览器，必须加此参数，在宿主机浏览器中访问 |

**第三步：打开浏览器**

浏览器访问 `http://localhost:8501`

> **SQLite trace 文件持久化**：SQLite 文件写入 `/app/data/traces.db`，由于 `$(pwd):/app` 整目录挂载，宿主机上 `data/traces.db` 会实时同步更新，关闭容器后数据不丢失。

---

### 1.2 WSL / Linux

WSL（Windows Subsystem for Linux）和原生 Linux 操作相同。

**前提**：已安装 Docker，且 `docker` 命令在当前用户下可用（或加 `sudo`）。

```bash
# 在项目根目录下
cd /path/to/template_agent_dev

# 构建镜像（首次或 requirements.txt 变动后）
docker build -t bioforge:local .

# 启动 Streamlit
docker run -it --rm \
  -v $(pwd):/app \
  -p 8501:8501 \
  --env-file .env \
  bioforge:local \
  streamlit run scripts/debugger/app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true
```

WSL 下宿主机访问地址：`http://localhost:8501`（WSL2 会自动做端口转发）。

如果 localhost 不通，用 WSL 的 IP：
```bash
# 在 WSL 内查看 IP
ip addr show eth0 | grep "inet " | awk '{print $2}' | cut -d/ -f1
```
然后访问 `http://<上面的IP>:8501`。

---

### 1.3 原生 Mac（无 Docker）

如果本地有 Python 3.11+ 虚拟环境：

```bash
# 安装依赖（首次）
pip install -r requirements.txt

# 启动（在项目根目录下）
cd scripts/debugger
streamlit run app.py
```

浏览器自动打开 `http://localhost:8501`。

---

## 2. .env 配置详解

在项目根目录创建 `.env` 文件（复制 `.env.example` 后修改）：

```env
# ── Docker 镜像标识（用于 docker-compose，手动 docker run 时不影响）──────
DOCKER_IMAGE=bioforge
DOCKER_TAG=local

# ── LLM API（必须配置至少一个，否则 agent 无法调用模型）────────────────────

# 选项 A：华为云 ModelArts MAAS（OpenAI 兼容接口）
OPENAI_API_KEY=你的_API_Key
OPENAI_API_BASE=https://api.modelarts-maas.com/openai/v1
DEFAULT_LLM_MODEL=openai/glm-5.1          # 模型名，前缀 openai/ 表示走 OpenAI 兼容接口

# 选项 B：OpenAI 官方
# OPENAI_API_KEY=sk-...
# DEFAULT_LLM_MODEL=openai/gpt-4o

# 选项 C：Anthropic
# ANTHROPIC_API_KEY=sk-ant-...
# DEFAULT_LLM_MODEL=anthropic/claude-3-5-sonnet-20241022

# 选项 D：MiniMax（如不用，留空即可，不影响启动）
MINIMAX_API_KEY=
MINIMAX_GROUP_ID=

# ── Trace 落库（控制运行历史页面是否可用）──────────────────────────────────

# 选项 A：SQLite（推荐本地开发，无需任何 DB 容器）
# 文件自动创建在 data/traces.db，浏览器历史页面立刻可用
TRACE_DB_URL=sqlite:///data/traces.db

# 选项 B：PostgreSQL（生产或 CI 环境）
# 需要先启动 PostgreSQL 容器并执行 db/trace/schema.sql 建表
# TRACE_DB_URL=postgresql+psycopg://bioforge:密码@localhost:5432/bioforge

# 若 TRACE_DB_URL 完全不设置：
#   - 运行编辑器（04）可正常使用，trace 只打印到控制台
#   - 历史/详情/对比页面（01/02/03）不可用，会显示提示

# ── 其他数据库（与调试平台无关，业务流程用，留空不影响调试平台）─────────
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=bioforge
POSTGRES_PASSWORD=你的密码
POSTGRES_DB=bioforge
LANGGRAPH_CHECKPOINT_DB_URL=postgresql://bioforge:你的密码@localhost:5432/bioforge

# ── RAG（与调试平台无关）────────────────────────────────────────────────────
EMBEDDING_MODEL=BAAI/bge-m3
```

**最简配置**（只需2行就能启动并运行 test_agent）：

```env
OPENAI_API_KEY=你的Key
TRACE_DB_URL=sqlite:///data/traces.db
```

`DEFAULT_LLM_MODEL` 不配置时，平台会使用 `minimax/MiniMax-M2.7-highspeed` 作为默认值，但模型下拉框或文本框内可随时改。

---

## 3. Langfuse LLM 追踪（可选）

Langfuse 是开源 LLM 观测平台，为 BioForge 算子调优提供比调试平台更深层的数据：

| 调试平台（内置） | Langfuse（额外） |
|-----------------|-----------------|
| Step 级 status / 耗时 | 每次 LLM 调用完整 prompt + 输出 |
| LLM 思考链摘要 | Token 用量（prompt / completion 分开） |
| Tool 调用记录 | 费用估算（按模型单价） |
| SQLite / Postgres 历史 | 跨 run 的 p50/p95 延迟分布图 |
| — | Trace 树形图（Plan → Step → LLM Call 嵌套） |

### 3.1 注册获取免费 Key

1. 前往 [cloud.langfuse.com](https://cloud.langfuse.com) 注册（邮箱即可，无需信用卡）
2. 创建一个 Project（随意命名，如 `bioforge-dev`）
3. 进入 Project → Settings → API Keys → 生成一对 Key
4. 复制 **Public Key**（`pk-lf-...`）和 **Secret Key**（`sk-lf-...`）

**免费额度**：Hobby 档每月 **5 万次 observation**（一次 LLM 调用 ≈ 1 次 observation）。  
按 test_agent 每次 run 约消耗 10-30 次估算，5 万次可支撑 **1500+ 次调试运行**，日常开发完全够用。

### 3.2 配置 .env

在 `.env` 文件中加入（取消注释并填入真实 Key）：

```env
# Langfuse — LLM 全链路追踪
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LANGFUSE_HOST=https://cloud.langfuse.com
```

配置后**重启 Streamlit**（容器重启或 `Ctrl+C` 重跑），下次运行 agent 时自动开始追踪。  
**不配置则完全静默跳过**，不影响现有任何功能。

### 3.3 追踪数据示例

运行一次 `plan_deep_analysis` 后，在 Langfuse 控制台可以看到：

```
Trace: test_agent                          总耗时: 42.3s
├── step_01_search                          12.1s
│   ├── LLM Call #1  → tool: mock_literature_search   2.1s  421 tokens
│   ├── LLM Call #2  → tool: mock_literature_search   2.3s  389 tokens
│   └── LLM Call #3  → Final Answer                   1.8s  312 tokens
├── step_02_fetch                           15.4s
│   ├── LLM Call #1  → tool: mock_fetch_details       2.0s  445 tokens
│   ├── LLM Call #2  → tool: mock_fetch_details       2.2s  401 tokens
│   └── LLM Call #3  → Final Answer                   1.9s  298 tokens
├── step_03_analyze                          8.2s
│   └── LLM Call #1  → tool: mock_binding_analysis    3.1s  892 tokens
└── step_04_report                           6.6s
    └── LLM Call #1  → tool: mock_generate_report     2.4s  754 tokens

Total tokens: 4,912  |  Estimated cost: $0.0031
```

**多轮轮询验证**：在 Langfuse trace 树中可以直观看到 step_01 和 step_02 各有 3 次 LLM Call，其中前 2 次都调用了工具（分页/轮询），第 3 次是最终回答。这就是 agent 自主决策的完整记录。

### 3.4 在 Langfuse 控制台操作

| 功能 | 操作路径 |
|------|----------|
| 查看 trace 列表 | 控制台 → Traces（按 session_id = run_id 分组） |
| 查看某次 run 的完整调用树 | 点击 Trace → 展开 Session 折叠 |
| 按 agent 过滤 | Tags 筛选（`test`、`search` 等） |
| 按 plan 过滤 | Tags 筛选（`plan_deep_analysis` 等） |
| Token 用量统计 | Dashboard → Usage（按日/周/月汇总） |
| 费用估算 | Dashboard → Cost（按模型分列） |
| 延迟分布 | Dashboard → Latency（p50 / p95 / p99） |

### 3.5 自建 Langfuse（完全免费，无上限）

如果不想用云服务，可以用官方 Docker Compose 自建：

```bash
# 克隆官方仓库
git clone https://github.com/langfuse/langfuse
cd langfuse

# 启动（需要 Docker Compose）
docker compose up -d
```

然后访问 `http://localhost:3000` 完成初始化，将 `.env` 中的 `LANGFUSE_HOST` 改为：

```env
LANGFUSE_HOST=http://localhost:3000
```

自建需要额外一个 PostgreSQL 实例（Langfuse 自带一个测试用的，生产建议单独挂载）。

---

## 4. 平台页面完整操作指南

启动后浏览器打开 `http://localhost:8501`，左侧边栏可切换页面。

---

### 4.1 主页（快捷运行）

**适用场景**：不需要调整配置，快速跑一次 test_agent 看框架是否通。

**操作步骤**：

1. 在"选择 Plan"下拉框选择测试场景（见下方 Plan 说明）
2. "模型"框默认读取 `.env` 中的 `DEFAULT_LLM_MODEL`，可直接修改
3. 点击 **▶ 运行**
4. 右侧实时出现 step 卡片，绿色 ✅ = 成功，红色 ❌ = 失败，蓝色 🔄 = 执行中

**侧边栏状态区**：
- "当前查看"：最近通过"查看详情"按钮跳转的 run_id
- "对比列表"：已加入对比的 run_id，最多3条，可一键清空
- "最近运行"：最后一次从主页或编辑器运行的结果状态

---

### 4.2 📋 01 运行历史

**适用场景**：查看所有历史 agent 运行记录，快速定位成功/失败的运行。

> **前提**：必须配置 `TRACE_DB_URL`，否则此页显示警告并停止。

**界面说明**：

| 区域 | 说明 |
|------|------|
| 左侧筛选栏 | 按 Stage（agent 类型）、状态（success/failed）、时间范围（24h/7d/30d/全部）筛选 |
| 主表格 | 显示 run_id、stage、状态徽章、总耗时、step 数、时间 |
| 每行末尾按钮 | **查看详情** → 跳转到 02 页；**加入对比** → 加入对比列表 |
| 底部统计 | 今日运行数、成功率 metric；历史趋势 bar chart |

**状态颜色约定**：
- 🟢 teal (`#00D4AA`) = success
- 🔴 red (`#FF4B4B`) = failed
- 🟠 orange = running（实时流式时）
- 灰色 = skipped
- 🟣 purple (`#A78BFA`) = replanned（MODIFY_STEP：LLM 改写过指令）

**常见用法**：
- 时间范围选"24h"，快速定位今天的异常运行
- 点击失败记录的"查看详情"，进入 02 页看哪个 step 出了问题

---

### 4.3 🔍 02 运行详情

**适用场景**：深入分析某次具体运行，逐 step 检查输入/输出/LLM 思考链。

> **前提**：必须配置 `TRACE_DB_URL`。

**进入方式**：
- 从 01 页点击"查看详情"（自动带入 run_id）
- 直接在左侧 run_id 输入框填入 run_id

**界面说明**：

| 区域 | 说明 |
|------|------|
| 顶部4列 | run_id / stage / 总状态 / 总耗时 |
| 配置折叠区 | Plan ID、Step 列表、agent_run_id |
| Step 卡片（每个 step 一个 expander） | 工具名 / 成功标准 / 输入摘要 / 输出 / 耗时 / retry 次数 |
| 🧠 LLM 思考链（step 内折叠） | 逐次 LLM 调用的输入摘要、工具调用入参/返回、最终回答 |
| 底部耗时图 | 各 step 耗时横向 bar chart |

**LLM 思考链展开方式**：点击每个 step 卡片内的"🧠 LLM 思考链（ReAct 详情）"即可展开，看到：
- `🤖 LLM Call #1` — 第几次推理
- `🔧 调用工具: mock_success` — 工具调用及入参
- `📥 工具返回` — 工具输出
- `💬 最终回答` — LLM 最终输出的文本

**用于 debug 的典型操作**：
1. 找到 status=failed 的 step → 展开 LLM 思考链
2. 看 LLM 是否正确理解了 instruction（"LLM Call #1"的输入摘要）
3. 看工具调用的入参是否正确（🔧 调用工具行）
4. 看工具返回是否符合预期（📥 工具返回行）
5. 看 LLM 最终回答是否满足 success_criteria

---

### 4.4 ⚡ 03 对比实验

**适用场景**：对比不同模型/配置/plan 下同一个 agent 的运行结果，量化调优效果。

> **前提**：必须配置 `TRACE_DB_URL`，且有至少2条历史运行记录。

**操作步骤**：

1. 从01页"加入对比"，或直接在03页下拉框选择 run_id（最多3个）
2. 顶部配置对比区：并排显示各运行的 Model / Plan / 总状态 / 总耗时，**差异自动黄色高亮**
3. Step 对比表：每行一个 step，各列显示对应运行的 状态/耗时/重试次数/工具，差异标红
4. 底部自动生成文字摘要：例如"B 比 A 快 2.3s，重试次数少1次"

**典型场景**：
- 同一 plan，换模型 A vs 模型 B，看哪个执行更稳定
- 同一模型，plan v1 vs plan v2，看调整指令后成功率是否提升
- 排查某次偶发 retry，与正常运行对比，看哪个 LLM 调用差异最大

---

### 4.5 ⚙️ 04 运行编辑器（核心）

**适用场景**：调参实验的主工作台。左侧调配置，右侧实时看结果，是使用最频繁的页面。

**左栏：配置面板**

| 配置项 | 说明 |
|--------|------|
| **Agent 下拉** | 选择要运行的 agent。screen/extract 目前锁定（见第4节） |
| **Plan 下拉**（test_agent 专属） | 选择5个预设测试场景之一 |
| **模型** | LiteLLM 格式字符串，如 `openai/gpt-4o`、`anthropic/claude-3-opus-20240229`，留空用 `.env` 默认值 |
| **Identity YAML（折叠）** | 在内存中覆盖 agent 的 identity 定义，不写回文件。用于实验性修改 agent 角色 |
| **Skills（折叠）** | 在内存中覆盖某个 skill 文件内容，填入 skill 名称（不含 .md）和 Markdown 内容 |
| **user_query** | 传给 search_agent 等接受用户查询的 agent |

**右栏：实时结果**

点击 **▶ 运行** 后：

1. 后台线程启动 agent
2. 每个 step 开始时出现蓝色"执行中"提示，实时显示已完成的 LLM 调用次数
3. step 完成后变为完整卡片（绿色/红色），可展开看输出和思考链
4. 所有 step 完成后顶部状态条显示最终结果

**💾 保存为实验**：

运行完成后，点"保存为实验"可将本次配置（模型/plan/identity覆盖等）保存为 `experiments/{文件名}.yaml`，默认文件名为 `{agent}_{时间戳}`，可在弹出框自定义。下次可从实验文件还原配置。

> **注意**：Identity 和 Skills 的内联编辑**只在内存中生效**，刷新页面或重启后恢复为文件原始内容。如需永久修改，直接编辑对应 YAML/MD 文件（见第5节）。

---

## 4. Agent 状态说明

| Agent | 状态 | 说明 |
|-------|------|------|
| `test_agent` | ✅ **完整可用** | 所有 plan 均可运行，工具全部为 mock，无需外部 API |
| `search_agent` | ✅ **框架已实现，工具待接** | 框架层完整，`pubmed_search` 工具当前为 mock，真实搜索需注册真实工具 |
| `screen_agent` | 🔒 **锁定**（NotImplementedError） | 工厂函数未实现，选中后点运行会报错 |
| `extract_agent` | 🔒 **锁定**（NotImplementedError） | 同上 |

**锁定的含义**：选中 screen/extract 并运行时，后台线程会立即抛出 `NotImplementedError`，右栏显示红色错误提示。这是**设计行为**，不是 bug——保护编排层不被误操作。

**解锁 screen_agent / extract_agent** 的步骤见第6节。

---

## 5. 调整 Agent 真实配置

agent 的真实配置文件在 `backend/src/agents/{agent_name}/` 目录下，直接编辑后重新运行即可生效（无需重启 Streamlit，下次点"运行"时自动读取新文件）。

### 5.1 修改 Plan（步骤 / 工具 / 重试逻辑）

**位置**：`backend/src/agents/{agent_name}/plans/` 或 `backend/src/agents/{agent_name}/plan.yaml`

**test_agent Plan 文件说明**：

| 文件 | 场景 | 核心设计 |
|------|------|----------|
| `plan_happy_path.yaml` | 全成功 3 步 | 全用 `mock_success`，验证基本控制流 |
| `plan_retry_scenario.yaml` | 失败→重试→成功 | `step_02` 用 `mock_flaky(fail_count=1)`，第1次失败，第2次成功 |
| `plan_abort_scenario.yaml` | 持续失败→中止 | `step_02` 用 `mock_fail`，超过 max_retries 后整体 abort |
| `plan_full_coverage.yaml` | 全分支串联 4 步 | success → flaky重试 → slow延迟 → rich_output嵌套输出 |
| `plan_modify_step.yaml` | LLM 改写指令→重试→成功 | `step_02` 用 `mock_flaky(fail_count=2)`；需配合 `replan_strategy="llm_on_exhaustion"` + `replan_threshold=1` 使用，触发 MODIFY_STEP replan |

**Plan YAML 结构**：

```yaml
plan_id: "my_plan_v01"        # 唯一标识，出现在历史页面的 Plan ID 列
agent_name: "test_agent"
version: "1.0"

steps:
  - step_id: "step_01"         # 步骤唯一 ID（出现在 UI 卡片标题）
    name: "步骤名称"            # 人读名称（UI 卡片副标题）
    instruction: |             # LLM 收到的具体执行指令（多行 Markdown）
      调用 mock_success 工具获取输出。
      输出 JSON 格式：{"result": "ok"}
    tools_required:            # 此 step 允许调用的工具白名单
      - "mock_success"
    success_criteria:          # validator 用于判断 step 是否成功的规则
      required_fields:
        - "result"             # LLM 输出必须包含这些 key
      min_count:
        candidate_ids: 1       # 某个列表字段至少有 N 个元素（可选）
    max_retries: 2             # 此 step 最多重试几次（0 = 不重试）
    db_write_policy: "none"    # 是否写业务库（none / on_success / always）
```

**调整要点**：
- `instruction` 写得越具体，LLM 越少"发挥"，输出越可预测
- `tools_required` 必须与 `tools/registry.py` 中注册的工具名完全一致
- `max_retries` 建议 search_agent 设 2，screen/extract 视工具可靠性而定
- `success_criteria.required_fields` 是最低保证：LLM 输出 JSON 里必须有这些 key

---

### 5.2 修改 Identity（角色定义）

**位置**：`backend/src/agents/{agent_name}/identity.yaml`

```yaml
agent_name: "test_agent"

role: "BioForge 框架测试代理"     # 一句话角色定位，出现在 system prompt 开头

objective: |                      # 详细目标（多行），告诉 LLM 它在做什么
  验证 AgentTemplate 框架的核心控制流...

responsibilities:                 # 职责列表（bullet points）
  - "按指定 plan 执行预设测试场景"
  - "使用 mock tools 产出可预测输出"

constraints:                      # 约束（不能做什么）
  - "不连接任何真实外部 API"
  - "不写入业务数据库"

output_contract:                  # 期望的最终输出格式说明
  test_result: "success/partial/failed"
  steps_executed: "实际执行步骤数"
```

**调整要点**：
- `constraints` 对约束 LLM 行为很有效，如"不要自行推测数据，只使用工具返回的结果"
- `output_contract` 仅是描述，不是强制约束——强制约束在各 step 的 `success_criteria` 里
- 在平台 04 编辑器的"Identity YAML（内联编辑）"区域可先临时测试修改效果，满意后再写入文件

---

### 5.3 修改 Skills（操作指南）

**位置**：`backend/src/agents/{agent_name}/skills/` 目录下的 `.md` 文件

Skills 是 Markdown 格式的操作指南，会被拼接进 system prompt，告诉 LLM 如何操作具体工具或领域知识。

**test_agent skills**：

| 文件 | 内容 |
|------|------|
| `test_protocol.md` | 各 plan 验证什么、期望哪些行为 |
| `expected_behaviors.md` | 各场景下 validate_plan 的参考标准 |

**search_agent skills 示例结构**（供参考，新 agent 可复制此结构）：

```markdown
# PubMed Search Protocol

## 何时调用 pubmed_search
- 每个 step 的 instruction 中有"搜索"或"检索"字样时调用
- 每次调用后必须检查返回的 `total_count` 字段...

## 参数格式
- `query`: 英文检索式，MeSH 术语 + Boolean 操作符...
- `max_results`: 默认 20，筛选阶段可调至 50...
```

**调整要点**：
- Skills 越具体越好——与其写"使用工具搜索"，不如写"调用 pubmed_search，query 参数格式为 `(Peptide[MeSH]) AND (Hydroxyapatite[MeSH])`"
- 平台 04 编辑器的"Skills（内联编辑）"可临时覆盖测试，满意后写入 `.md` 文件

---

### 5.4 修改模型和运行参数

**方式一：.env（全局默认）**

```env
DEFAULT_LLM_MODEL=openai/gpt-4o   # 修改后重启 Streamlit 生效
```

**方式二：04 编辑器模型输入框（单次实验，不持久化）**

直接在模型文本框输入，点运行立即生效，不影响配置文件。

**方式三：修改 agent.py 工厂函数（永久更改该 agent 的默认模型）**

```python
# backend/src/agents/search_agent/agent.py
def create_search_agent(
    model: str = "openai/gpt-4o",   # 改这里
    temperature: float = 0.0,
    ...
```

**LiteLLM 模型字符串格式**（`provider/model-name`）：

```
openai/gpt-4o
openai/gpt-4o-mini
anthropic/claude-3-5-sonnet-20241022
minimax/MiniMax-M2.7-highspeed
openai/glm-5.1        ← 华为云 MAAS（OpenAI 兼容）
```

---

## 6. 解锁未实现的 Agent

`screen_agent` 和 `extract_agent` 目前处于锁定状态（调用时 raise `NotImplementedError`）。解锁分两步：

**第一步：实现工厂函数**

在对应目录下创建 `agent.py`，参考 `test_agent/agent.py` 的结构：

```python
# backend/src/agents/screen_agent/agent.py
from backend.src.agents.agent_template import AgentTemplate
from backend.src.agents.agent_template.config import AgentTemplateConfig
from backend.src.agents.agent_template.schemas import SummaryMode
from pathlib import Path

_AGENT_DIR = Path(__file__).parent

def create_screen_agent(
    model: str = "openai/gpt-4o",
    temperature: float = 0.0,
    summary_mode: SummaryMode = SummaryMode.TEMPLATE,
) -> AgentTemplate:
    config = AgentTemplateConfig(
        agent_name="screen_agent",
        plan_path=_AGENT_DIR / "plan.yaml",       # 需先创建
        identity_path=_AGENT_DIR / "identity.yaml", # 需先创建
        skills_dir=_AGENT_DIR / "skills",           # 需先创建
        model=model,
        temperature=temperature,
        tools=["pubmed_search"],   # 替换为此 agent 实际需要的工具
        max_step_retries=2,
        max_plan_retries=1,
        summary_mode=summary_mode,
        enable_trace=True,
        enable_memory=False,
    )
    return AgentTemplate(config)
```

**第二步：注册到调试平台**

编辑 `scripts/debugger/components/agent_runner.py`，更新 `_AGENT_FACTORIES`：

```python
_AGENT_FACTORIES: dict[str, str | None] = {
    "search":  "backend.src.agents.search_agent.agent:create_search_agent",
    "screen":  "backend.src.agents.screen_agent.agent:create_screen_agent",  # ← 从 None 改为路径
    "extract": None,   # 仍未实现
    "test":    "backend.src.agents.test_agent.agent:create_test_agent",
}
```

修改后**无需重启 Streamlit**，刷新页面即可在 Agent 下拉中选中 screen 并正常运行。

---

## 7. 新增一个 Agent

**第一步：从骨架模具复制**

```bash
cp -r backend/src/agents/_template backend/src/agents/my_new_agent
```

**第二步：填写配置文件**

```
my_new_agent/
├── plan.yaml           ← 步骤定义（instruction / tools_required / success_criteria）
├── identity.yaml       ← 角色定义（role / objective / constraints / output_contract）
├── skills/
│   └── how_to_use_tools.md  ← 工具使用操作指南（自然语言）
└── agent.py            ← 工厂函数（照抄 test_agent/agent.py，改参数）
```

**第三步：注册工具**

如果新 agent 需要新工具，在 `backend/src/tools/registry.py` 注册：

```python
from backend.src.tools.my_new_agent.my_tool import my_tool_func

_REGISTRY["my_tool_name"] = my_tool_func
```

**第四步：注册到调试平台**

在 `scripts/debugger/components/agent_runner.py` 的 `_AGENT_FACTORIES` 中添加一行：

```python
"my_new": "backend.src.agents.my_new_agent.agent:create_my_new_agent",
```

同时在 `04_editor.py` 的 `AGENT_OPTIONS` 中增加显示名称：

```python
AGENT_OPTIONS: dict[str, str] = {
    "test":    "🧪 test_agent（框架测试）",
    "search":  "🔍 search_agent（搜索）",
    "my_new":  "🆕 my_new_agent（新 agent）",  # ← 新增
    ...
}
```

**第五步：运行测试**

```bash
# 先用 test_agent 验证框架没坏
cd scripts/debugger && streamlit run app.py
# 选 test_agent → plan_happy_path → ▶ 运行，确认 ✅

# 再切换到 my_new_agent 测试
```

---

## 常见问题

**Q：运行后右栏一直显示"执行中"，没有卡片出现**

LLM API 可能超时或 Key 错误。检查：
1. `.env` 中 `OPENAI_API_KEY` 是否正确
2. `DEFAULT_LLM_MODEL` 的 provider 前缀是否与 API Key 匹配（如用华为云 MAAS 必须加 `OPENAI_API_BASE`）
3. 查看 Docker 容器终端（`docker logs`）看有无报错

**Q：历史页面（01/02/03）显示"TRACE_DB_URL 未配置"**

在 `.env` 中添加 `TRACE_DB_URL=sqlite:///data/traces.db`，重启容器后生效。

**Q：选了 screen/extract agent 运行后立刻报错**

正常现象，这两个 agent 处于锁定状态，见第6节解锁步骤。

**Q：修改了 plan.yaml 但运行结果没变**

Streamlit 的 `@st.cache_resource` 可能缓存了旧的 engine，在页面右上角 `⋮` 菜单选"Clear cache"，或按 `Ctrl+Shift+R` 强制刷新页面后重新运行。

**Q：data/traces.db 越来越大怎么办**

SQLite 文件只增不减（append-only）。清空历史：

```bash
# 在项目根目录
rm data/traces.db
# 下次运行时会自动重建
```
