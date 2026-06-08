# Guide Agent + 对话式 CLI 技术方案
# docs/guide_cli_technical_spec.md
# Claude Code 开发的参考基准文档

---

## 0. 阅读本文件的前提

在开始任何实现前，先读：
- `CLAUDE.md`（仓库约定：中文注释、append-only、import 规范）
- `docs/architecture.md`（系统架构总览）
- `backend/src/graph/pipeline.py`（当前 build_graph 签名）
- `backend/src/graph/state.py`（PipelineState 字段）
- `backend/src/agents/agent_template/hooks.py`（TraceHook，理解 NullBackend）
- `backend/src/agents/search_agent/agent.py`（参考 agent 工厂函数格式）

---

## 1. 核心设计决策（不容改动）

### 1.1 Guide Agent 使用 LangGraph interrupt() 机制

Guide Agent 是"用户对话型 agent"，需要在 LLM 思考过程中暂停等待用户输入。
使用 `langgraph.types.interrupt()` 是标准做法，而非自建 ask_user tool。

**机制**：
```
graph.stream(state, config)
  guide_node 运行 → interrupt(payload) → 保存到 checkpointer → 抛 GraphInterrupt
  CLI 收到流事件 {"__interrupt__": [...]} → 渲染给用户 → 等待输入
  CLI 调用 graph.stream(Command(resume=用户答案), config) → 从断点恢复
  interrupt() 的返回值 = 用户答案 → 继续执行
```

**必要条件**：必须有 checkpointer，否则无法 resume。
Demo 使用 SqliteSaver（`data/demo_checkpoint.db`），生产换 PostgresSaver。
`build_graph()` 签名增加可选 `checkpointer=None` 参数。

### 1.2 Guide Agent 不走 AgentTemplate（Plan-and-Execute 模板）

原因：guide 没有多步 plan、不调用业务工具（interrupt 不是 @tool）。
形态：内部 `create_react_agent(model, tools=[], prompt=system_msg)`，
通过 skills 驱动 LLM 产出，通过 interrupt() 与用户交互。

### 1.3 Demo 版约束：LLM 真实调用 + Skills 固定输出 + 用户只能 OK

- LLM 真实调用（不 mock 思考过程）
- skills 中的 `demo_script.md` 约束输出格式到固定模板，LLM 按模板填充
- 三个 interrupt 点用户只有"确认，继续"一个选项（不允许修改）
- 未来扩展：改 skills + CLI 渲染，不动 agent 内部逻辑

### 1.4 CLI 使用 rich 库

rich 已是 requirements 的间接依赖（streamlit → rich），显式加入 requirements.txt。
提供 Live 进度面板、Table、Panel，自动处理 Windows ANSI 和 UTF-8 降级。

---

## 2. 三个 interrupt 点的 payload 格式

所有 interrupt payload 是 dict，type 字段决定 CLI 如何渲染：

```python
# 第一个 interrupt：任务描述确认
{
    "type": "task_confirm",
    "label": "任务描述",
    "content": "str，自然语言任务描述，3-5句话",
    "options": ["确认，继续"],
    "default": 0
}

# 第二个 interrupt：数据库字段模板确认
{
    "type": "schema_confirm",
    "label": "数据库字段模板",
    "content": {
        "字段名": {"type": "str/list/float", "description": "说明", "example": "示例值"},
        ...
    },
    "options": ["确认，使用此模板"],
    "default": 0
}

# 第三个 interrupt：文献准入/排除标准确认
{
    "type": "criteria_confirm",
    "label": "文献准入/排除标准",
    "content": {
        "inclusion": ["准入标准1", "准入标准2", ...],
        "exclusion": ["排除标准1", "排除标准2", ...]
    },
    "options": ["确认，进入检索"],
    "default": 0
}
```

---

## 3. PipelineState 新增字段

```python
# 在现有字段之后追加，total=False 保证向后兼容

# guide_agent 产出（三件核心物，也是跨领域 data mining 的关键接口）
task_description: str        # 自然语言任务描述（search/screen/extract 均可读）
db_schema: dict              # 数据库字段模板（extract 读取，决定抽取哪些字段）
inclusion_criteria: dict     # 文献准入/排除标准（screen 读取）
user_confirmed: bool         # 用户是否完成引导阶段确认

# guide_agent 已有字段（上次已加，保留）
guide_summary: str
guidance_message: str
io_contract: dict
```

---

## 4. guide_agent 目录结构

```
backend/src/agents/guide_agent/
├── __init__.py              ← 导出 MockGuideAgent, RealGuideAgent
├── agent.py                 ← 主实现（见 §5）
├── identity.yaml            ← 与 search/screen/extract 格式完全一致（见 §6）
├── skills/
│   ├── dialogue_guide.md    ← 核心：何时追问/何时结束/一次只问一个问题
│   ├── demo_script.md       ← Demo 约束：三步固定结构/输出格式要求
│   ├── schema_template.md   ← HAp 领域字段模板（复用 field_dict.json 核心字段）
│   └── criteria_template.md ← HAp 领域文献准入/排除标准模板
└── README.md
```

**没有 plan.yaml**（纯 ReAct，无预定义步骤）。
**没有本地 tools/ 子目录**（当前不配工具，interrupt 不是 @tool）。

---

## 5. agent.py 核心逻辑（伪代码，Claude Code 参考实现）

```
class RealGuideAgent:
    run(input_data) -> dict:
        # 1. 构造 system_message（identity + skills 拼接，与 context_builder 思路一致）
        # 2. 初始化 create_react_agent(model, tools=[], prompt=system_msg)
        # 3. 直接在 guide_node 内调用 interrupt()，不通过 agent.invoke
        #    （因为 interrupt 必须在 graph 节点的调用栈内才有效）

# guide_node 是真正调用 interrupt() 的地方
def guide_node(state: PipelineState) -> dict:
    # step 1: 构造 system_message（加载 identity + skills）
    # step 2: 用 litellm 做一次 LLM 调用，生成 task_description
    # step 3: interrupt(task_confirm_payload) → resume → 用户已确认
    # step 4: 用 litellm 做一次 LLM 调用，生成 db_schema
    # step 5: interrupt(schema_confirm_payload) → resume → 用户已确认
    # step 6: 用 litellm 做一次 LLM 调用，生成 inclusion_criteria
    # step 7: interrupt(criteria_confirm_payload) → resume → 用户已确认
    # step 8: return 更新后的 PipelineState patch
```

**注意**：LLM 调用直接用 `litellm.completion()`（与 validator.py / replanner.py 一致），
不用 create_react_agent invoke（guide 的"ReAct"体现在 skills 驱动 LLM 思考，
而不是真正的 tool-calling 循环，因为没有工具）。

**MockGuideAgent**：不调 LLM，直接构造固定的三个 payload，
interrupt() 在 mock 模式下由 graph 的 checkpointer 正常处理（CLI 仍然渲染）。

---

## 6. identity.yaml 格式（与其它 agent 完全一致）

```yaml
agent_name: "guide_agent"
role: "BioForge 文献数据挖掘任务引导员"
objective: |
  通过结构化对话，帮助用户明确三件核心物：
  (1) 自然语言任务描述（pipeline 各阶段参考）
  (2) 目标数据库字段模板（extract agent 抽取依据）
  (3) 文献准入/排除标准（screen agent 筛选依据）
responsibilities:
  - "理解用户研究诉求，补全领域上下文（HAp/矿化/肽段）"
  - "基于 skills 中的模板推荐合适的字段设计和准入标准"
  - "以对话形式与用户确认每一步产出"
constraints:
  - "一次对话只聚焦一件事（任务描述/字段模板/准入标准之一）"
  - "不臆造用户未表达的研究意图"
  - "Demo 版：每步只提供默认选项，不要求用户自由修改"
  - "LLM 输出必须严格符合 skills/demo_script.md 规定的 JSON 格式"
output_contract:
  task_description: "自然语言任务描述（str，3-5句话）"
  db_schema: "字段模板（dict，字段名→{type,description,example}）"
  inclusion_criteria: "准入/排除标准（dict，inclusion:list, exclusion:list）"
  query: "收敛后的检索意图（str，供 search_agent 使用）"
  user_confirmed: "用户已完成所有确认（bool）"
```

---

## 7. skills 文件内容要求

### dialogue_guide.md
核心内容：
- **何时追问**：用户诉求包含多个潜在方向 / 领域词不在支持范围 / 目标过于宽泛（如"做个文献综述"）
- **何时停止追问**：用户给出了可执行的研究目标 / 用户明确说"就这样" / 已澄清三件核心物
- **追问原则**：一次只问一个问题；问题要简短、给出例子；不要连续问超过3个问题
- **范围限制说明**：不是拒绝，而是"目前调通的是 HAp/矿化/肽段领域，其它在开发中，仍可继续但结果可能不完整"

### demo_script.md
核心内容（约束 Demo 版 LLM 输出格式）：
- **步骤1 任务描述**：必须输出纯 JSON `{"task_description": "..."}`,不要其它内容
- **步骤2 字段模板**：必须输出纯 JSON `{"db_schema": {...}}`，字段来自 schema_template.md
- **步骤3 准入标准**：必须输出纯 JSON `{"inclusion_criteria": {"inclusion":[...],"exclusion":[...]}}`
- 每步都要先输出 `<think>` 内容（思考过程），再输出 JSON

### schema_template.md
核心内容：
- HAp/肽段领域的推荐字段列表（从 `db/business/field_dict.json` 的 hap_v01.db 部分提取核心字段）
- 每个字段：字段名 / 类型 / 说明 / 示例值
- 注明：这是当前 Demo 支持的字段，未来可按领域扩展

### criteria_template.md
核心内容：
- HAp/矿化/肽段领域的推荐准入标准（如：研究对象为合成肽/天然肽；实验涉及 HAp/钙磷矿化；有定量结果）
- 推荐排除标准（如：综述类文章；无实验数据；非英文；发表年份<2000）
- 注明：这是 Demo 模板，未来可按用户诉求动态生成

---

## 8. CLI 目录结构

```
backend/src/cli/
├── __init__.py              ← 导出 main
├── __main__.py              ← python -m backend.src.cli 入口（设 sys.path + load .env）
├── app.py                   ← 主入口：banner → system_check → 对话阶段 → 流水线阶段 → REPL
├── conversation.py          ← 引导对话阶段（处理 interrupt 事件，渲染三种 payload）
├── pipeline_view.py         ← 流水线运行阶段（rich.Live 实时更新节点状态）
├── trace_view.py            ← /trace 命令（读 reader.get_run_events，rich.Table）
├── system_check.py          ← 启动 system check（探测 env var + 连通性）
├── session.py               ← 会话状态（run_id 历史、thread_id、最近 state）
└── README.md
```

---

## 9. system_check.py 检测项

| 检测项 | 方法 | 通过条件 |
|---|---|---|
| LLM | 检查 `MINIMAX_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` 等 | 任意一个非空 |
| TraceDB | `get_trace_engine()` 是否返回非 None | 返回 Engine |
| BizDB | `DATABASE_URL` 或 `BIZ_DB_PATH` | 任意一个存在 |
| Mode | `GRAPH_AGENT_MODE` env var | 读取显示，不判断对错 |
| Checkpointer | `data/demo_checkpoint.db` 目录是否可写 | `data/` 目录存在且可写 |

---

## 10. Banner 规格

使用 `rich.Panel` + `rich.Text`，不用 ASCII art 字符拼字母（避免字母残缺）：

```
╭─────────────────────────────────────────────────────────╮
│                                                         │
│   BioForge                                              │
│   Agentic Framework for Biomedical Literature Mining    │
│   v0.1  Demo Mode                                       │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  System Status                                          │
│   LLM         ✅  MiniMax-M2.7  (MINIMAX_API_KEY)      │
│   Trace DB    ✅  PostgreSQL     (TRACE_DB_URL)         │
│   Business DB ⚠️   SQLite        (BIZ_DB_PATH)          │
│   Mode        🎮   mock          (GRAPH_AGENT_MODE)     │
│   Checkpoint  ✅  data/demo_checkpoint.db               │
╰─────────────────────────────────────────────────────────╯
  输入 /help 查看命令  ·  /demo 一键体验  ·  /quit 退出
```

每行状态：✅ 绿色 / ⚠️ 黄色 / ❌ 红色。动态由 `system_check.py` 结果填充。

---

## 11. Docker 集成

docker-compose.yml 新增字段（对现有 `pepclaw` service 追加，不替换）：
```yaml
stdin_open: true    # 保持 stdin 开启（否则 input() 立即 EOF）
tty: true           # 分配伪终端（rich 颜色 / Live 面板需要 TTY）
```

入口脚本（entrypoint.sh，挂载进容器）：
```bash
#!/bin/bash
# 根据环境变量选择启动模式
if [ "$BIOFORGE_MODE" = "cli" ]; then
    exec python -m backend.src.cli
else
    echo "请设置 BIOFORGE_MODE=cli 以启动对话式 CLI"
    exec bash
fi
```

---

## 12. 中文注释规范（CLAUDE.md 已有，此处强调关键位置）

每个新文件必须在以下位置写中文注释：
- 文件顶部 docstring：说明「位置」「依赖」「职责」「与哪些模块交互」
- 每个类/函数的 docstring：说明参数、返回值、异常
- interrupt() 调用前：注释说明此处暂停的原因和期望用户做什么
- resume 之后：注释说明 resume 带回了什么、如何使用

---

## 13. 验证清单（每条提示词执行完后必须跑）

```bash
# 基础语法
python -m py_compile backend/src/agents/guide_agent/agent.py
python -m py_compile backend/src/cli/app.py

# guide agent 离线（Mock）
python -c "
from backend.src.agents.guide_agent import MockGuideAgent
a = MockGuideAgent()
print(a.get_system_prompt()[:100])   # 确认 skills 加载
"

# CLI 启动页（不进入 REPL）
BIOFORGE_CLI_ASCII=1 timeout 3 python -m backend.src.cli --check-only || true

# graph 导入（langgraph 已安装时）
python -c "from backend.src.graph import build_graph; print('graph ok')"
```
