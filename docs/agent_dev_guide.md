# Agent 开发指南

## 总体原则

BioForge 的各 Agent（search/screen/extract）通过**配置注入**复用 `AgentTemplate`，不通过继承。
每个 agent 只需提供 4 样东西：

1. `plan.yaml` — 预定义的执行 plan（步骤列表）
2. `identity.yaml` — agent 身份/职责/约束/输出契约
3. `skills/*.md` — 自然语言操作指南（注入 system prompt）
4. `tools` 列表 — 本 agent 可使用的 tool 名称

## 快速起步：从 _template/ 开始

```bash
# 1. 复制骨架
cp -r backend/src/agents/_template backend/src/agents/my_agent

# 2. 进入目录
cd backend/src/agents/my_agent
```

## 文件说明

### plan.yaml

定义 agent 的执行步骤，`plan_runner` 按顺序执行：

```yaml
plan_id: ""           # 留空：planner.py 自动生成 UUID
agent_name: "my_agent"
version: "0.1"

steps:
  - step_id: "step_01"          # 唯一 ID，用于 trace 和 replanner
    name: "步骤名称"
    instruction: |
      详细的执行指令（注入 system prompt）。
      明确指定输出 JSON 格式：{"field_a": "...", "field_b": [...]}
    tools_required:             # 本 step 可调用的 tool（config.tools 的子集）
      - "pubmed_search"
    success_criteria:           # validate_step 执行的校验规则
      required_fields:
        - "field_a"
      min_count:
        field_b: 1
    max_retries: 2
    db_write_policy: "none"     # 目前固定 none（写库由 graph 层处理）
```

**success_criteria 支持的规则：**
- `required_fields: list[str]` — output 中必须存在且非空的 key
- `min_count: {field: int}` — list 类型字段的最小元素数量

### identity.yaml

```yaml
agent_name: "my_agent"         # 需与 plan.yaml 和 agent.py 一致
role: "角色描述"
objective: |
  核心目标（1-3 句话）

responsibilities:
  - "职责1"
  - "职责2"

constraints:
  - "约束1（不做什么）"
  - "约束2（输出格式限制）"

output_contract:                # validate_plan LLM 校验时使用
  field_a: "类型和数量要求"
  field_b: "格式说明"
```

### skills/*.md

每个 `.md` 文件是一个操作技能指南，context_builder 加载后注入 system prompt。
文件名即技能名（如 `query_building.md` 显示为「Query Building」）。

```markdown
# 技能名称

## 核心原则
...

## 步骤说明
...

## 示例
...

## 注意事项
...
```

### agent.py

```python
from pathlib import Path
from backend.src.agents.agent_template import AgentTemplate
from backend.src.agents.agent_template.config import AgentTemplateConfig

_AGENT_DIR = Path(__file__).parent

def create_my_agent(model: str = "minimax/MiniMax-M2.7-highspeed") -> AgentTemplate:
    config = AgentTemplateConfig(
        agent_name="my_agent",
        plan_path=_AGENT_DIR / "plan.yaml",
        identity_path=_AGENT_DIR / "identity.yaml",
        skills_dir=_AGENT_DIR / "skills",
        model=model,                  # 任意 LiteLLM 兼容字符串
        tools=["pubmed_search"],      # 本 agent 可用的 tool 白名单
        max_step_retries=2,
        enable_trace=True,
    )
    return AgentTemplate(config)
```

## 调用方式

```python
from backend.src.agents.my_agent.agent import create_my_agent

agent = create_my_agent(model="openai/gpt-4o")
patch = agent.run(pipeline_state={})
# patch = {'candidate_paper_ids': [...], 'my_agent_summary': '...', 'run_metadata': {...}}
```

## 接入 graph 层

graph 层（编排负责人负责）在 node 函数中调用：

```python
from langgraph.graph import StateGraph
from backend.src.graph.state import PipelineState
from backend.src.agents.my_agent.agent import create_my_agent

def my_agent_node(state: PipelineState) -> PipelineState:
    agent = create_my_agent()
    patch = agent.run(pipeline_state=state)
    return {**state, **patch}
```

## 替换 Trace Backend

```python
from backend.src.db_access.trace.postgres_backend import PostgresBackend  # 未来实现

agent = create_my_agent()
agent.hook.backend = PostgresBackend(session=db_session)
patch = agent.run()
```

## 常见问题

**Q：plan step 执行失败怎么办？**
A：replanner 会根据重试次数决定 retry 或 abort。retry 不修改 step 定义，
    超过 max_retries 后 abort 整个 run，返回 `status='failed'` 的 AgentRunResult。

**Q：如何让 step 间共享上下文？**
A：成功的 step 结果会通过 `StepResult.summary` 自动注入下一 step 的 context_builder，
    不需要手动传递。summary 由 executor._build_summary(output) 纯函数生成。

**Q：validate_plan 什么时候调用？**
A：所有 step 完成后，由 plan_runner 调用一次 validate_plan（LLM 判断），
    检查 final_output 是否满足 identity.yaml 的 output_contract。
