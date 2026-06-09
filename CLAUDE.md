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
│   ├── registry.py          ← get_tools(names) 工具注册表（懒加载，ImportError 降级为 stub）
│   ├── search/              ← PubMed 检索工具
│   │   ├── __init__.py
│   │   └── pubmed_search.py ← pubmed_search()，Biopython Entrez，多批次 efetch，0.35s 节流
│   └── rag_paper/           ← RAG 端到端抽取工具（一键 PDF → 五表 CSV）
│       ├── __init__.py
│       ├── schemas.py        ← RunBioPaperPipelineInput / ParsePDFInput / RetrieveEvidenceInput
│       ├── service_factory.py ← get_rag_service() 单例工厂
│       ├── tools.py          ← @tool 包装（run_bio_paper_extraction_pipeline / parse_pdf_with_ragflow / retrieve_pdf_evidence）
│       ├── template_contract.py ← load_extraction_contract()（委托 db_access.reader，回退 YAML）
│       ├── normalizer.py     ← normalize_to_five_tables()（枚举归一化 + 稳定 ID sha256[:12]）
│       └── csv_writer.py     ← write_tables_to_csv()（overwrite=False → 跳过已有文件）
├── graph/
│   ├── state.py             ← PipelineState TypedDict（+ guide / file_asset / DB / finalize 字段）
│   ├── pipeline.py          ← build_graph()，StateGraph 7 节点：
│   │                            START→guide→init_business_db→search→screen
│   │                                →extract→write_rag_csv_to_db→finalize→END
│   │                            条件边：search/screen/extract 均可短路到 finalize
│   │                            重试：search/screen 节点内置指数退避重试（最多 3 次）
│   ├── factory.py           ← _AGENTS dict，create_agent()；_wrap_screen() demo/real 使用真实 AgentTemplate
│   └── nodes.py             ← guide_node / prepare_extraction_context_node（=init_business_db）/
│                                search_node / screen_node / extract_node /
│                                write_db_node / finalize_node（+ init_db_node 向后兼容保留）
├── cli/                     ← CLI 入口集合
│   ├── __init__.py          ← 导出 main()
│   ├── __main__.py          ← 入口点（python -m backend.src.cli [--check-only]）
│   ├── run_demo_pipeline.py ← 非交互式 Demo 入口（自动确认 Guide interrupt）：
│   │                            python -m backend.src.cli.run_demo_pipeline \
│   │                              --profile hap_peptide_v1 --mode demo
│   ├── app.py               ← 10 步编排流程（交互式）；pipeline 由 pipeline_view 驱动：
│   │                            1-2. system_check + banner 显示
│   │                            3. 初始化 CLISession
│   │                            4-6. 三步 interrupt 对话
│   │                            7-9. 流水线执行（search/screen/extract）
│   │                            10. REPL 交互模式（规划中）
│   ├── system_check.py      ← 环境检测（5 项：LLM/TraceDB/BizDB/Mode/Checkpoint）
│   ├── session.py           ← CLISession 状态管理（run_id/thread_id/历史）
│   ├── conversation.py      ← 三步 interrupt 对话处理：
│   │                            - wait_for_ok(): 确认点阻塞
│   │                            - _render_task_panel(): 任务描述面板
│   │                            - _render_schema_table(): 字段表格
│   │                            - _render_criteria_panel(): 过滤规则面板
│   │                            - run_guide_conversation(): 完整三步流程
│   └── pipeline_view.py     ← 流水线实时进度面板（驱动真实 graph.stream）：
│                                - NodeStatus/NodeMetrics: 状态和度量
│                                - run_pipeline_view(graph, session, trace_manager):
│                                    调用 graph.stream(Command(resume=0)) 驱动执行
│                                    Live 实时更新进度，结束后打印摘要 Panel
│                                    （检索式、候选数、PDF 路径、DB 路径）
├── config/                  ← 配置层（TODO）
└── db_access/
    ├── trace/               ← Trace 数据库（hooks.py 替代旧 trace_logger.py）
    ├── memory/              ← 内存数据库（v0.1 TODO）
    └── business/            ← 业务 SQLite 接口层
        ├── __init__.py      ← 导出三类操作（ensure_business_db / get_rag_extraction_contract / write_rag_csv_to_business_db）
        ├── schemas.py       ← Pydantic 数据契约（DbInitResult / CsvWriteResult / RagExtractionContract / PaperContext）
        ├── init_service.py  ← ensure_business_db()（路径推导 + 委托 db/business/sqlite_init.py）
        ├── reader.py        ← get_rag_extraction_contract() / get_paper_context()
        └── csv_writer.py    ← write_rag_csv_to_business_db()（overwrite=False → INSERT OR IGNORE；True → INSERT OR REPLACE）
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

完整示例见 `.env.example`，以下列出关键变量：

```env
# ── LLM 配置 ──────────────────────────────────────────────────────────────
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
LLM_MODEL=ark-code-latest

# ── 运行模式 ──────────────────────────────────────────────────────────────
# demo：guide/search/screen/extract 全部真实 LLM；extract 使用 mock（无 RAGFlow）
# real：全链路真实
GRAPH_AGENT_MODE=demo

# ── 业务数据库（SQLite demo 用）────────────────────────────────────────────
BIZ_DB_PATH=/app/data/hap_v01.db
BIZ_DB_BACKEND=sqlite          # sqlite | postgresql（未来扩展）

# ── 提取配置（schema 模板）────────────────────────────────────────────────
EXTRACTION_PROFILE=hap_peptide_v1
TEMPLATE_VERSION=v1
SCHEMA_TEMPLATE_PATH=           # 显式指定时覆盖自动推导路径

# ── 数据目录 ──────────────────────────────────────────────────────────────
DATA_ROOT=/app/data             # 容器内路径；宿主机通过 volume 映射

# ── NCBI（PubMed 检索）────────────────────────────────────────────────────
NCBI_EMAIL=your@email.com       # 必填；NCBI 用于联系滥用者
NCBI_API_KEY=                   # 可选；有 key 时速率提升 10 req/s

# ── RAGFlow（视觉 PDF 解析）────────────────────────────────────────────────
RAGFLOW_API_BASE_URL=https://your-ragflow-host
RAGFLOW_API_KEY=ragflow-xxxxx

# ── LangGraph 检查点 ──────────────────────────────────────────────────────
LANGGRAPH_CHECKPOINT_DB_URL=sqlite:///./data/demo_checkpoint.db
```

## Running CLI

```bash
# 本地启动（需 .env 配置）
python -m backend.src.cli

# 仅检查环境（用于 CI）
python -m backend.src.cli --check-only

# Docker 启动（交互模式）
docker-compose run pepclaw python -m backend.src.cli

# Docker 检查环境
docker-compose run pepclaw python -m backend.src.cli --check-only
```

CLI 10 步流程：
1. System Check — 检测 LLM/DB/Checkpoint 等
2. Banner — 显示系统状态
3. Session Init — 生成 run_id/thread_id
4-6. Guide Conversation — 三步 interrupt 对话（任务/字段/规则）
7-9. Pipeline — 流水线执行进度（Search/Screen/Extract）
10. REPL — 交互式查询结果（规划中）

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
