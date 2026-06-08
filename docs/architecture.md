# BioForge 系统架构

## 一句话定位

BioForge 是面向生物医学文献（肽-矿物相互作用/HAp/磷酸钙/牙体矿化）的多智能体结构化数据抽取流水线，产出证据可溯源的结构化数据库。

## 三段式批处理流水线

```
Input: 研究目标（HAp/磷酸钙/矿化领域）
   │
   ▼
┌─────────────────┐
│  Search Agent   │  检索 PubMed，产出候选文献 ID 列表
│  (search_agent) │  输出：candidate_paper_ids
└────────┬────────┘
         │  PipelineState
         ▼
┌─────────────────┐
│  Screen Agent   │  相关性筛选，过滤无关文献
│  (screen_agent) │  输出：screened_paper_ids
└────────┬────────┘
         │  PipelineState
         ▼
┌─────────────────┐
│ Extract Agent   │  结构化抽取（实体/功能/证据）
│ (extract_agent) │  输出：extracted_record_ids
└────────┬────────┘
         │
         ▼
Output: 结构化数据库（business DB，graph 层写入）
```

各阶段之间只传轻量结构化结果 + 压缩摘要，不传完整 ReAct messages 历史。

## AgentTemplate 内部结构

每个 Agent 节点是一个 `AgentTemplate(config).run()` 调用：

```
AgentTemplate.run()
    │
    ├─ planner.load_plan(plan.yaml) → Plan
    ├─ planner.load_identity(identity.yaml) → dict
    ├─ TraceHook(NullBackend)
    │
    └─ PlanRunner.run(plan)
           │
           ├─ hook.on_plan_start(plan)                    ← trace 固定位置 1
           │
           ├─ for step in plan.steps:
           │      hook.on_step_start(step)                ← trace 固定位置 2
           │      context = context_builder.build_context(...)
           │                  ├─ identity → system prompt 头部
           │                  ├─ skills/*.md → system prompt 技能段
           │                  └─ 已完成 step 摘要 → 上下文层 B
           │      result = executor.run_step(step, context, config)
           │                  └─ create_react_agent(ChatLiteLLM, tools, state_modifier)
           │                         └─ ReAct 循环（LangGraph prebuilt）
           │      ok = validator.validate_step(result, step)   ← 纯规则，不调 LLM
           │      [失败] replanner.decide() → RETRY / MODIFY_STEP / ABORT
           │              ├─ RETRY：原指令重试（rule_only 模式或未达阈值）
           │              ├─ MODIFY_STEP：LLM 改写 instruction 后重试
           │              │      hook.on_step_end(failed)       ← trace 固定位置 3
           │              │      hook.on_step_replanned(...)    ← trace 固定位置 3.5（新增）
           │              │      plan.steps[i] = updated_step  ← 只改内存，不写 YAML
           │              └─ ABORT：终止整个 run
           │      hook.on_step_end(step, result)              ← trace 固定位置 3
           │      # TODO(graph层): db_write_policy 扩展点（非 template 范围）
           │
           ├─ validator.validate_plan(run_result, output_contract, model)  ← LLM 校验
           ├─ hook.on_plan_end(run_result)                    ← trace 固定位置 4
           └─ return AgentRunResult
    │
    └─ output_adapter.adapt(run_result, config) → PipelineState patch
```

## Trace 系统（Sink 模式）

```
plan_runner → TraceHook → TraceBackend（抽象）
                               ├─ NullBackend（当前：只 print，不写入）
                               └─ PostgresBackend（未来：写 trace 事件表）
```

TraceEvent 结构：`run_id / agent_run_id / stage / event_type / step_id / payload / status / duration_ms`

**event_type 合法值（AgentTemplate 层）：**
- `plan_start` / `plan_end` — plan 级事件
- `step_start` / `step_end` — step 级事件（含重试时每次都写）
- `step_replanned` — MODIFY_STEP 决策后写入，payload 含 original/new instruction、replan_reason

替换后端时 template 代码零改动：
```python
# 在 agent.py 或调用方中
agent.hook.backend = PostgresBackend(session=db_session)
```

## Context Engineering 三层

| 层 | 范围 | 实现 |
|---|---|---|
| A | step 内 ReAct messages | create_react_agent 自管，step 结束即丢 |
| B | step 间上下文 | context_builder：取已完成 step 的 StepSummary，不传完整 messages |
| C | agent 间上下文 | output_adapter：生成摘要写入 PipelineState，传入侧可选注入 |

## 模块依赖图（有向无环）

```
schemas.py   errors.py   stopping.py        ← 无依赖（最底层）
    └───────────┬───────────┘
           config.py                         ← 依赖 schemas, stopping
               │
           state.py                          ← 依赖 schemas, config
               │
      planner.py  context_builder.py         ← 依赖 schemas, config, errors
               │
      executor.py  validator.py  replanner.py  ← 依赖 schemas, errors + 外部工具
               │
      hooks.py  output_adapter.py           ← 依赖 schemas, errors
               │
           plan_runner.py                    ← 依赖以上全部
               │
         template_agent.py                  ← 依赖以上全部
```

## Replan 策略

`AgentTemplateConfig` 通过两个字段控制 step 失败后的行为：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `replan_strategy` | `"rule_only"` | `rule_only`：只做 RETRY/ABORT；`llm_on_exhaustion`：达到阈值后调 LLM 改写 instruction |
| `replan_threshold` | `1` | retry_count 达到此值时升级到 LLM 修改（仅 `llm_on_exhaustion` 有效） |

**两阶段决策（示例：threshold=1, max_step_retries=2）：**
```
第1次失败 → retry_count=0 < threshold=1  → RETRY（原指令）
第2次失败 → retry_count=1 >= threshold=1 → MODIFY_STEP（LLM 改写指令）→ step_replanned 事件
第3次失败 → retry_count=2 >= max=2       → ABORT
```

**关键不变量：**
- `rule_only`（默认）时行为与 v0.1 完全一致，零回归
- LLM 改写失败时静默降级为普通 RETRY，主流程不感知
- `plan.yaml` 永远不变，MODIFY_STEP 只修改内存中的 Plan 对象

## 业务数据库写入（非 AgentTemplate 范围）

```
AgentTemplate.run() → PipelineState patch
                             │
                    graph/pipeline.py（编排负责人）
                             │
                    business DB writer（db_access 负责人）
```

Template 只产出 PipelineState patch，写库由 graph 层在拿到 state 后决定。
