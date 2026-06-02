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
│   ├── agent_template/      ← 通用模板层（本次核心开发内容）
│   │   ├── schemas.py       ← 全部数据契约（最底层，无依赖）
│   │   ├── errors.py        ← 异常类型
│   │   ├── stopping.py      ← ReAct 停止配置
│   │   ├── config.py        ← AgentTemplateConfig
│   │   ├── state.py         ← TemplateAgentState（运行时内存）
│   │   ├── planner.py       ← YAML → Plan 对象
│   │   ├── context_builder.py ← identity/skills/摘要 → system prompt
│   │   ├── executor.py      ← create_react_agent 封装
│   │   ├── validator.py     ← validate_step（规则）+ validate_plan（LLM）
│   │   ├── replanner.py     ← 失败时决策 retry/abort
│   │   ├── hooks.py         ← Trace Sink（TraceHook + NullBackend）
│   │   ├── output_adapter.py ← AgentRunResult → PipelineState patch
│   │   ├── plan_runner.py   ← 核心 Runtime（step 循环）
│   │   └── template_agent.py ← 对外入口 AgentTemplate
│   ├── search_agent/        ← SearchAgent 配套（plan/identity/skills/agent.py）
│   ├── screen_agent/        ← TODO（各 agent 负责人实现）
│   ├── extract_agent/       ← 旧 MVP（TextAgent，保持原样不动）
│   └── _template/           ← 起新 agent 的骨架模具（复制此目录）
├── tools/
│   └── registry.py          ← get_tools(names) 工具注册表（v0.1 mock）
├── graph/
│   ├── state.py             ← PipelineState TypedDict
│   ├── pipeline.py          ← TODO（编排负责人）
│   └── factory.py           ← TODO（编排负责人）
├── config/                  ← TODO
└── db_access/
    ├── trace/               ← ⚠️ trace_logger.py DEPRECATED（见 hooks.py）
    ├── memory/              ← TODO（v0.1 不接线）
    └── business/            ← BusinessDBWriter（旧 MVP，不在本次范围）
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
