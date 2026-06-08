# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**BioForge** is an agentic framework for bio-references and bio-data mining, focused on peptide-mineral interactions (HAp/calcium phosphate/dental mineralization). The system is a three-stage batch pipeline: **Search → Screen → Extract**, each implemented as an independent Plan-and-Execute + ReAct agent.

## Repository State

- **Branch**: `template_agent_dev` — AgentTemplate 通用模板层开发分支。
- **Main branch**: `main` — PR 合并目标。
- **架构文档**: `docs/architecture.md`（中文）

## Architecture Overview

```
LangGraph StateGraph（外层编排，graph/ 负责）
    └─ search_node / screen_node / extract_node
           └─ AgentTemplate(config).run()
                  └─ Plan-and-Execute（plan_runner.py，纯 Python while 循环）
                         └─ create_react_agent（每 step 内 ReAct，langgraph.prebuilt）
```

**核心原则：组合注入，非继承。** 各 agent 通过 `AgentTemplateConfig` 注入个性化配置，不改 template 代码。

## Module Map

```
backend/src/
├── agents/
│   ├── agent_template/      ← 通用模板层（Plan-Execute + ReAct）
│   │   ├── schemas.py       ← 全部数据契约（最底层，无依赖）
│   │   ├── errors.py        ← 异常类型
│   │   ├── stopping.py      ← ReAct 停止配置
│   │   ├── config.py        ← AgentTemplateConfig
│   │   ├── state.py         ← TemplateAgentState（运行时内存）
│   │   ├── planner.py       ← YAML → Plan 对象
│   │   ├── context_builder.py ← identity/skills/摘要 → system prompt
│   │   ├── executor.py      ← create_react_agent 封装
│   │   ├── validator.py     ← validate_step（规则）+ validate_plan（LLM）
│   │   ├── replanner.py     ← 失败时决策 retry/modify_step/abort（LLM 改写指令）
│   │   ├── hooks.py         ← Trace Sink（TraceHook + NullBackend），on_step_replanned
│   │   ├── output_adapter.py ← AgentRunResult → PipelineState patch
│   │   ├── plan_runner.py   ← 核心 Runtime（step 循环）
│   │   └── template_agent.py ← 对外入口 AgentTemplate
│   ├── guide_agent/         ← Guide Agent（LangGraph interrupt() + LLM）
│   │   ├── identity.yaml    ← 角色定义 + 三步输出规范
│   │   ├── skills/          ← 操作指南（dialogue_guide.md 等）
│   │   ├── agent.py         ← MockGuideAgent / RealGuideAgent（LLM 三步调用）
│   │   └── __init__.py      ← 导出 build_guide_node()
│   ├── search_agent/        ← SearchAgent（AgentTemplate 实例）
│   ├── screen_agent/        ← ScreenAgent（v0.1 stub）
│   ├── extract_agent/       ← ExtractAgent（旧 MVP，原样不动）
│   └── _template/           ← 新 agent 的骨架模具
├── tools/
│   └── registry.py          ← get_tools(names) 工具注册表
├── graph/
│   ├── state.py             ← PipelineState TypedDict（+ guide_agent 字段）
│   ├── pipeline.py          ← build_graph()，StateGraph（guide→search→screen→extract）
│   ├── factory.py           ← _AGENTS dict，get_agent()
│   └── nodes.py             ← guide_node / search_node / screen_node / extract_node
├── cli/                     ← 对话式 CLI（新增，Step 08）
│   ├── __init__.py          ← 导出 main()
│   ├── __main__.py          ← CLI 入口（python -m backend.src.cli）
│   ├── app.py               ← 10 步编排流程（system_check → banner → guide → pipeline）
│   ├── system_check.py      ← 环境检测（LLM/DB/Checkpoint）
│   ├── session.py           ← CLISession（run_id/thread_id 管理）
│   ├── conversation.py      ← 三步中断处理（wait_for_ok）
│   └── pipeline_view.py     ← 流水线进度面板（rich.Live）
├── config/                  ← 配置层（TODO）
└── db_access/
    ├── trace/               ← Trace 数据库（hooks.py 替代旧 trace_logger.py）
    ├── memory/              ← 内存数据库（v0.1 TODO）
    └── business/            ← 业务数据库（旧 MVP，原样不动）
```

## 起新 Agent 的步骤

```bash
# 1. 复制 _template/
cp -r backend/src/agents/_template backend/src/agents/my_new_agent

# 2. 编辑配置文件
#    - plan.yaml：填写 steps（instruction/tools_required/success_criteria）
#    - identity.yaml：填写 role/objective/constraints/output_contract
#    - skills/*.md：填写自然语言操作指南

# 3. 编辑 agent.py：更新 agent_name / model / tools

# 4. 在 tools/registry.py 注册本 agent 需要的 tool 函数

# 5. 运行测试
cd backend && python -m pytest tests/test_agent_template.py -v
```

## Key Design Decisions

1. **LLM provider-agnostic**：`config.model` 接受任意 LiteLLM 兼容字符串（如 `"minimax/MiniMax-M2.7-highspeed"`、`"openai/gpt-4o"`）。API Key 由 `.env` 提供，template 层零感知。

2. **DB 写入不在 template 范围**：写库由 graph 层（编排负责人）负责，template 只产出 PipelineState patch。

3. **Trace = Sink 模式**：`hooks.py` 的 `NullBackend` 当前只 print，未来换 `PostgresBackend` 时 template 代码零改动。

4. **Memory = 注释占位**：v0.1 不接线，`context_builder` 保留 `memory_refs=None` 接口。

5. **LangGraph interrupt() 用于用户交互**：Guide Agent 使用 `interrupt(payload)` 暂停执行并等待用户确认。
   - 每个 interrupt 返回一个确认消息（payload）
   - CLI 层（conversation.py）负责渲染和等待用户 OK
   - resume 时通过 Command(resume=user_input) 继续执行
   - 支持检查点恢复（thread_id 管理）

6. **CLI 的三层结构**：
   - **app.py**：10 步编排流程（system_check → banner → guide → pipeline → REPL）
   - **conversation.py**：处理 Guide Agent 的三步中断（task → schema → criteria）
   - **pipeline_view.py**：rich.Live 实时显示 Search/Screen/Extract 进度
   - **system_check.py**：启动时环境检测（LLM/DB/Checkpoint）
   - **session.py**：管理 run_id/thread_id（用于 trace 和中断恢复）

## Environment Variables（.env）

```env
# LLM（填写你实际使用的供应商 key，LiteLLM 自动读取）
MINIMAX_API_KEY=your_key_here
MINIMAX_GROUP_ID=your_group_id_here
# 或：OPENAI_API_KEY=...  ANTHROPIC_API_KEY=...

# 可选：指定默认模型（供 run_minimal_agent.py 使用）
DEFAULT_LLM_MODEL=minimax/MiniMax-M2.7-highspeed

# Database（LangGraph checkpoint，与 trace 无关）
LANGGRAPH_CHECKPOINT_DB_URL=postgresql://bioforge:password@localhost:5432/bioforge
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=bioforge
POSTGRES_PASSWORD=your_password
POSTGRES_DB=bioforge
```

## Running Tests

```bash
# 单元测试（无需 Docker / 无需真实 LLM）
cd backend && python -m pytest tests/test_agent_template.py -v

# 最小链路冒烟（需 .env 中配置 LLM API Key）
python scripts/run_minimal_agent.py
python scripts/run_minimal_agent.py --model "openai/gpt-4o"
```

## License

Apache 2.0
