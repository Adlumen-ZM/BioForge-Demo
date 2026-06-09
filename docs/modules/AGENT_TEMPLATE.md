# AgentTemplate 通用运行时 README

## 定位

AgentTemplate 是 Search/Screen/Extract 的通用运行时，负责加载 plan、identity、skills，绑定工具，执行 step，校验结果，失败重试，记录 trace，并将结果适配成 PipelineState patch。

## 文件

```text
config.py          # AgentTemplateConfig
schemas.py         # Plan/StepResult/AgentRunResult
planner.py         # YAML → Plan
context_builder.py # identity + skills + summaries + upstream_context
executor.py        # step 内 LLM/ReAct/tool
validator.py       # success_criteria / output_contract
replanner.py       # RETRY / MODIFY_STEP / ABORT
hooks.py           # TraceHook
plan_runner.py     # 主循环
output_adapter.py  # run result → state patch
```

## 运行流程

```text
AgentTemplate.run(input) → load plan/identity → PlanRunner → for step: build_context → executor → validate_step → replan if failed → trace → validate_plan → output_adapter
```

## 配置

每个 Agent 在 `agent.py` 中构造 `AgentTemplateConfig(agent_name, plan_path, identity_path, skills_dir, model, tools, max_step_retries, enable_trace)`。

## Step 成功标准

`success_criteria` 支持 `required_fields` 和 `min_count`。失败后按 `replan_strategy` 选择 retry/modify/abort。

## 上下文原则

step 内 ReAct messages 不跨 step 传递；step 间只传 `StepSummary`；agent 间只通过 `PipelineState` 传递。
