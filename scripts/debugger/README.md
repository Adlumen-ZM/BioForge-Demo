# BioForge Debugger — 算子调优工具

AgentTemplate 算子调优调试工具，提供 CLI 和 Streamlit 两种界面。

## 快速启动

### Streamlit UI（推荐）

```bash
# 安装依赖（首次）
pip install streamlit>=1.35.0

# 启动（在 scripts/debugger/ 目录下）
cd scripts/debugger
streamlit run app.py
```

浏览器自动打开 `http://localhost:8501`。

### CLI 工具

```bash
# 从项目根目录运行
python scripts/debug_agent.py --agent test --plan plan_happy_path
python scripts/debug_agent.py --agent test --plan plan_retry_scenario
python scripts/debug_agent.py --agent search --model openai/gpt-4o

# 列出最近运行历史（需配置 TRACE_DB_URL）
python scripts/debug_agent.py --list --agent test --limit 10

# 对比两次运行
python scripts/debug_agent.py --compare run_aaa111 run_bbb222
```

## 页面说明

| 页面 | 功能 |
|---|---|
| **📋 01_runs** | 运行历史列表，支持按 stage / 状态 / 时间筛选 |
| **🔍 02_detail** | 单次运行详情，逐 step 展示工具调用输入输出 |
| **⚡ 03_compare** | 并排对比最多3次运行，差异自动高亮 |
| **⚙️ 04_editor** | 配置编辑 + 流式运行，step 卡片实时出现 |

## 环境变量

```env
# 必须（LLM 调用）
MINIMAX_API_KEY=your_key
DEFAULT_LLM_MODEL=minimax/MiniMax-M2.7-highspeed

# 可选（trace 落库，启用后历史页面可用）
TRACE_DB_URL=postgresql://bioforge:password@localhost:5432/bioforge
```

## 支持的 Agent

| Agent | 状态 | Plan 文件 |
|---|---|---|
| `test_agent` | ✅ 已实现 | plan_happy_path / plan_retry_scenario / plan_abort_scenario / plan_full_coverage |
| `search_agent` | ✅ 已实现 | （使用其默认 plan） |
| `screen_agent` | 🚧 未实现 | — |
| `extract_agent` | 🚧 未实现 | — |

## test_agent Plan 说明

| Plan | 场景 | 验证内容 |
|---|---|---|
| `plan_happy_path` | 全成功 | 基本控制流、输出适配 |
| `plan_retry_scenario` | 失败→重试→成功 | max_retries、重试计数 |
| `plan_abort_scenario` | 持续失败→中止 | abort 决策、错误传播 |
| `plan_full_coverage` | 全分支串联 | success + flaky + slow + rich_output |

## 目录结构

```
scripts/
├── debug_agent.py              # CLI 工具
└── debugger/
    ├── app.py                  # Streamlit 主入口
    ├── .streamlit/
    │   └── config.toml         # 深色主题配置
    ├── components/
    │   ├── agent_runner.py     # AgentTemplate 运行封装（同步/流式）
    │   ├── streamlit_backend.py # StreamlitProgressBackend + CompositeBackend
    │   ├── trace_reader.py     # Streamlit 缓存的 trace DB 查询
    │   └── ui_helpers.py       # 可复用 UI 组件（徽章/卡片/图表）
    ├── pages/
    │   ├── 01_runs.py          # 运行历史
    │   ├── 02_detail.py        # 单次详情
    │   ├── 03_compare.py       # 对比实验
    │   └── 04_editor.py        # 配置编辑 + 流式运行
    └── experiments/            # 保存的实验配置（.yaml 或 .json）
```

## 注意事项

- `agent_template/` 和 `db_access/trace/` 目录**零改动**（只 import）
- `screen_agent` / `extract_agent` 调用时会抛 `NotImplementedError`（待编排负责人实现）
- Streamlit 页面不做自动化测试，需手动验证
- 实验配置保存在 `experiments/` 目录，已加入 `.gitkeep` 保持目录存在
