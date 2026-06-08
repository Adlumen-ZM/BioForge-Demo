# BioForge CLI 使用指南

对话式命令行接口，支持三步式 interrupt 对话和实时流水线进度显示。

## 快速开始

### 本地运行（需 Python 3.10+）

```bash
# 1. 安装依赖
cd backend
pip install -r requirements.txt

# 2. 配置 .env（复制 .env.example）
cp .env.example .env
# 编辑 .env，填写 API Key 和数据库配置

# 3. 启动 CLI
python -m backend.src.cli

# 4. 检查环境（不启动主程序）
python -m backend.src.cli --check-only
```

### Docker 运行（推荐）

```bash
# 构建镜像
docker build -t bioforge:latest .

# 运行 CLI（交互模式）
docker-compose run pepclaw python -m backend.src.cli

# 仅检查环境
docker-compose run pepclaw python -m backend.src.cli --check-only
```

## CLI 10 步流程

### 第 1-2 步：环境检测和状态显示

CLI 启动时自动运行 5 项环境检测：

| 检测项 | 说明 | 示例 |
|--------|------|------|
| **LLM** | API Key 和默认模型 | ✅ OPENAI_API_KEY=C1MKl0*** · 模型=openai/gpt-4o |
| **TraceDB** | Trace 数据库连接 | ✅ sqlite (TRACE_DB_URL) |
| **BizDB** | 业务数据库配置 | ⚠️ SQLite /app/data/hap_v01.db（文件未找到）|
| **Mode** | 运行模式（mock/real） | ✅ mock (GRAPH_AGENT_MODE) |
| **Checkpoint** | LangGraph 检查点目录 | ✅ data/ (可写，SqliteSaver 可用) |

status 符号：
- ✅ **ok** — 配置正确，功能可用
- ⚠️ **warn** — 配置缺失或不完整，功能受限但不阻塞
- ❌ **error** — 重大错误，需要修复

### 第 3 步：会话初始化

CLI 生成会话标识符：

```
Session: run_93185596  |  Thread: thread_64d1ccf5
```

- **run_id**：当前运行的唯一 ID，用于 trace 和日志关联
- **thread_id**：LangGraph 检查点线程 ID，支持 interrupt/resume

### 第 4-6 步：三步 interrupt 对话

#### Step 1: 任务描述确认

```
╭────────────────────────────╮
│ Step 1: 任务描述           │
│                            │
│ 挖掘 HAp 与肽段相互作用的  │
│ 文献                       │
╰────────────────────────────╯

按 Enter 继续...
```

输入任意内容后回车确认。

#### Step 2: 推荐数据库字段

```
           Step 2: 推荐数据库字段
┏━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ 字段名       ┃ 类型    ┃ 说明             ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ source_title │ str     │ 论文标题         │
│ abstract     │ str     │ 摘要             │
│ doi          │ str     │ DOI 标识         │
│ pub_date     │ date    │ 发表日期         │
│ hap_type     │ str     │ HAp 类型         │
...
└──────────────┴─────────┴──────────────────┘

按 Enter 继续...
```

Guide Agent 基于任务描述推荐数据库字段。

#### Step 3: 纳入/排除标准

```
╭────────────────────────────────────────────╮
│ Step 3: 纳入/排除标准                     │
│                                            │
│ 纳入标准（Inclusion）:                    │
│   1. 有 HAp: 论文涉及羟基磷灰石（HAp）   │
│   2. 有肽段: 论文涉及肽段分子             │
│   3. 有相互作用数据: 包含结合能或吸附数据 │
│                                            │
│ 排除标准（Exclusion）:                    │
│   1. 综述文献: 仅限原始研究               │
│   2. 非英文: 仅限英文文献                 │
╰────────────────────────────────────────────╯

按 Enter 继续...
```

### 第 7-9 步：流水线执行

```
▶ 启动流水线（Search → Screen → Extract）

                    Pipeline Progress
┏━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Node  ┃ Status   ┃ Progress        ┃ Time   ┃
┡━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ GUIDE │ ✅ ok    │ —               │ —      │
│SEARCH│ 🔄 running│ 50% (5/10)      │ 2.3 s  │
│SCREEN│ ⏳ pending│ —               │ —      │
│EXTRACT│ ⏳ pending│ —               │ —      │
└───────┴──────────┴─────────────────┴────────┘
```

实时显示每个节点的状态和处理进度：
- **⏳ pending** — 等待执行
- **🔄 running** — 正在处理，显示百分比进度
- **✅ success** — 完成，显示处理条目总数
- **❌ error** — 失败，显示错误信息

按 **CTRL+C** 可优雅中止流水线。

### 第 10 步：REPL 交互（规划中）

完成流水线后进入交互式 REPL：

```
REPL 模式（输入 'help' 查看命令）
当前功能：display/export（开发中）

> help
Available commands:
  display  — 显示结果摘要
  export   — 导出结果为 CSV/JSON
  detail   — 查看单条结果详情
  tag      — 标记或编辑标签
  quit     — 退出
```

## 环境变量配置

### 必需配置

```env
# LLM API Key（至少配置一个）
OPENAI_API_KEY=sk_...
# 或 MINIMAX_API_KEY=... / ANTHROPIC_API_KEY=...

# 可选：默认模型
DEFAULT_LLM_MODEL=openai/gpt-4o
```

### 数据库配置

```env
# 业务数据库（二选一）
DATABASE_URL=postgresql://bioforge:pass@localhost/bioforge
BIZ_DB_PATH=./data/hap_v01.db

# Trace 数据库
TRACE_DB_URL=sqlite:///./data/hap_trace.db

# LangGraph 检查点（支持 interrupt/resume）
LANGGRAPH_CHECKPOINT_DB_URL=sqlite:///./data/demo_checkpoint.db
```

### CLI 配置

```env
# 运行模式
GRAPH_AGENT_MODE=mock  # mock（固定输出）或 real（真实 LLM 调用）
```

## 常见问题

### Q: "LLM API Key 未找到" 怎么办？

**A:** 编辑 `.env` 文件，添加 API Key：

```env
OPENAI_API_KEY=sk_your_actual_key_here
```

然后重新启动 CLI。如果使用 Docker，确保 `.env` 已挂载：

```bash
docker-compose run pepclaw python -m backend.src.cli
```

### Q: "业务数据库未找到" 是否会阻塞？

**A:** 否。这只是警告（⚠️），流水线仍会执行，但结果无法持久化到数据库。可以使用 `--check-only` 验证其他配置。

### Q: 如何恢复中断的会话？

**A:** 使用 thread_id 恢复：

```bash
# 获取 thread_id（例如 thread_64d1ccf5）
# 重新启动 CLI，LangGraph 会自动恢复中断点
python -m backend.src.cli
```

完整的恢复接口在 Step 10 规划中。

### Q: 如何在 CI 中运行 CLI？

**A:** 使用 `--check-only` 模式检查环境，无需交互：

```bash
python -m backend.src.cli --check-only
```

此命令执行 5 项检测并输出 JSON 格式结果，适合 CI 自动化。

## 架构细节

### 会话管理（session.py）

```python
from backend.src.cli.session import CLISession

session = CLISession()
run_id = session.new_run_id()  # 生成 run_id 和 thread_id
session.add_history({
    "run_id": run_id,
    "status": "success",
    "summary": "...",
})
summary = session.summary()  # 获取统计信息
```

### 环境检测（system_check.py）

```python
from backend.src.cli.system_check import run_system_check

results = run_system_check()
for r in results:
    print(f"{r['name']}: {r['status']} — {r['detail']}")
```

### 三步对话（conversation.py）

```python
from backend.src.cli.conversation import run_guide_conversation

final_state, was_confirmed = run_guide_conversation(
    graph=graph,
    input_data=input_data,
    session=session,
)
```

### 流水线进度（pipeline_view.py）

```python
from backend.src.cli.pipeline_view import run_pipeline_view

final_state = run_pipeline_view(graph, final_state)
```

## 开发路线图

- [ ] Step 10: REPL 交互命令（display/export/tag）
- [ ] Step 11: 真实 LangGraph graph 集成（当前使用模拟数据）
- [ ] Step 12: 结果持久化到业务数据库
- [ ] Step 13: 并发处理（多线程 Search/Screen）
- [ ] Step 14: Web UI 版本

## 许可证

Apache 2.0
