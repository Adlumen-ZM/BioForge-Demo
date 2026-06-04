# test_agent 测试协议

## 各 Plan 的测试目的

### plan_happy_path（全正常路径）

**测试什么：** AgentTemplate 框架的基础 step 执行流程

**预期行为：**
- 3 个 step 按顺序依次执行，全部返回 success
- 每个 step 的输出正确传递给下一个 step（通过 context_builder 注入上下文）
- `AgentRunResult.status == "success"`
- trace 记录 4 个事件：plan_start + 3×step_end

**验证重点：**
- `mock_success(output_template="with_ids")` 返回的 `candidate_ids` 满足 `min_count: 1`
- step_03 的 `test_result` 字段通过 `required_fields` 检查

---

### plan_retry_scenario（重试场景）

**测试什么：** replanner 的 retry 决策逻辑

**预期行为：**
- step_02 第 1 次调用 mock_flaky 返回失败 → replanner.decide 选择 retry
- step_02 第 2 次调用 mock_flaky 返回成功 → plan 继续执行
- `AgentRunResult.status == "success"`
- trace 中 step_02 出现 2 次 step_start / step_end 事件（1次失败 + 1次成功）

**关键约束：**
- 调用 mock_flaky 时必须传 `call_id="step_02_retry"`，不能用默认值
- max_retries=2 保证有足够容量重试

---

### plan_abort_scenario（中止场景）

**测试什么：** retry 耗尽后的 abort 路径

**预期行为：**
- step_02 使用 mock_fail（永远失败）
- max_retries=2 → 总计尝试 3 次（初次 + 2次 retry）后全部失败
- replanner.decide 选择 abort → plan 中止
- step_03 永远不被执行
- `AgentRunResult.status == "failed"`

**验证重点：**
- trace 中只有 step_01 和 step_02 的事件，没有 step_03 的任何事件
- plan_end 事件的 status 字段为 "failed"

---

### plan_full_coverage（全覆盖串联）

**测试什么：** 在一次 run 中串联所有框架分支

**预期行为：**
- step_01：success（基础流程）
- step_02：flaky retry（第1次失败→重试→成功）
- step_03：slow（验证 duration_ms ≥ 1500ms）
- step_04：rich_output（验证 output_adapter 对嵌套数据的处理）
- `AgentRunResult.status == "success"`

**注意：** mock_slow 延迟 1.5s，整体运行时间约 5-8s（含 LLM 推理时间）

---

## 使用 mock tools 的注意事项

1. **mock_flaky 计数器必须在每次 run 前重置**
   - `agent_runner.py` 的 `run_sync` 和 `run_streaming` 会自动调用 `reset_flaky_counters()`
   - 手动测试时需要显式调用：`from backend.src.tools.test_agent.mock_flaky import reset_flaky_counters; reset_flaky_counters()`

2. **mock_fail 的失败机制**
   - mock_fail 返回 `{"status": "failed", ...}`，validator 通过检查 `required_fields` 来判断是否失败
   - plan 中的 `success_criteria.required_fields` 应包含一个 mock_fail 不会返回的字段名

3. **mock_slow 的延迟上限**
   - 内部限制 max delay = 60s，plan 中建议不超过 5s，否则影响测试效率
