# test_agent 预期行为参考

## framework_behaviors_verified 标准词汇表

以下是各 plan 中 `framework_behaviors_verified` 字段应包含的标准词汇，供 validate_plan 的 LLM 判断和人工核查使用。

### 基础框架行为

| 行为标识 | 说明 | 触发 plan |
|---|---|---|
| `basic_step_execution` | step 按顺序依次执行，工具调用成功 | happy_path |
| `context_passing` | 上一步的 summary 正确注入下一步 system prompt | happy_path, full_coverage |
| `output_format` | step output 符合 success_criteria.required_fields 定义 | happy_path |
| `multi_step_context` | 多步 context 累积传递，不丢失关键信息 | full_coverage |

### 错误处理行为

| 行为标识 | 说明 | 触发 plan |
|---|---|---|
| `retry_on_failure` | step 失败时触发 replanner，选择 retry | retry_scenario, full_coverage |
| `replanner_retry_decision` | replanner.decide 在 retry 次数未耗尽时选择 retry | retry_scenario |
| `recovery_after_retry` | retry 后成功，plan 继续执行后续 step | retry_scenario, full_coverage |
| `abort_on_max_retries` | retry 次数耗尽后，replanner 选择 abort | abort_scenario |
| `plan_status_failed_on_abort` | abort 后 AgentRunResult.status = "failed" | abort_scenario |
| `unreachable_step_skipped` | abort 后的后续 step 不被执行 | abort_scenario |

### 高级框架行为

| 行为标识 | 说明 | 触发 plan |
|---|---|---|
| `duration_tracking` | trace 中 duration_ms 字段正确记录耗时 | full_coverage |
| `rich_output_parsing` | output_adapter 正确处理 3 层嵌套 dict | full_coverage |
| `trace_event_sequence` | plan_start/step_start/step_end/plan_end 事件顺序正确 | 所有 |

---

## validate_plan 判断标准

当 `summary_mode=LLM` 时，validate_plan 会将 output_contract 和 final_output 发给 LLM 判断。
LLM 应判断以下内容：

**必须满足（hard requirements）：**
- `test_result` 字段存在且值为 "success" / "partial" / "failed" 之一
- `steps_executed` 字段存在且为正整数
- `framework_behaviors_verified` 字段存在且为非空列表

**soft requirements（降低评分但不强制失败）：**
- `framework_behaviors_verified` 中的词汇尽量使用上表中的标准词汇
- `steps_executed` 的值与实际执行的 step 数量（含重试）吻合

---

## 各场景的 trace 期望

### happy_path
```
plan_start (status=running)
step_start: step_01_basic (status=running)
step_end:   step_01_basic (status=success, duration_ms>0)
step_start: step_02_with_ids (status=running)
step_end:   step_02_with_ids (status=success)
step_start: step_03_summary (status=running)
step_end:   step_03_summary (status=success)
plan_end (status=success)
```

### retry_scenario
```
plan_start (status=running)
step_start: step_01_normal → step_end (success)
step_start: step_02_flaky  → step_end (failed, retry_count=0)  ← 第1次
step_start: step_02_flaky  → step_end (success, retry_count=1) ← retry后成功
step_start: step_03_verify → step_end (success)
plan_end (status=success)
```

### abort_scenario
```
plan_start (status=running)
step_start: step_01_normal        → step_end (success)
step_start: step_02_always_fail   → step_end (failed) × 3次
plan_end (status=failed)
# step_03_unreachable 不出现在 trace 中
```
