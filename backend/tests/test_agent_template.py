"""
tests/test_agent_template.py — AgentTemplate 各模块单元测试

覆盖范围（全 mock，无真实 LLM / 无 Docker）：
  - schemas：Pydantic 模型实例化与约束
  - errors：异常继承链
  - stopping：默认值与 recursion_limit 计算
  - config：合法/非法参数
  - state：初始化与状态更新
  - planner：YAML 加载（合法/缺字段/文件不存在）
  - context_builder：context 拼接（无/有上游 step 摘要）
  - executor：mock LLM 返回 StepResult
  - validator：validate_step 规则路径 + validate_plan mock LLM
  - replanner：retry/abort 路径
  - hooks：NullBackend 不报错、TraceHook 四方法调用顺序、_write 失败不传播
  - output_adapter：TEMPLATE / LLM 双模式输出结构
  - plan_runner：全成功路径、单步失败后 retry、abort 路径（end-to-end mock）

运行方式：
  cd backend && python -m pytest tests/test_agent_template.py -v
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
import tempfile
import os

import pytest

# ── 确保 backend/src 可被 import（本地运行时）──────────────────────────────
_BACKEND_ROOT = Path(__file__).parent.parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


# =============================================================================
# 辅助工厂函数
# =============================================================================

def make_plan_step(**kwargs):
    from backend.src.agents.agent_template.schemas import PlanStep
    defaults = {
        "step_id": "step_01",
        "name": "测试 Step",
        "instruction": "做某件事",
        "tools_required": [],
        "success_criteria": {},
        "max_retries": 2,
    }
    defaults.update(kwargs)
    return PlanStep(**defaults)


def make_plan(steps=None):
    from backend.src.agents.agent_template.schemas import Plan, PlanStep
    if steps is None:
        steps = [make_plan_step()]
    return Plan(plan_id="plan_test", agent_name="test_agent", version="0.1", steps=steps)


def make_step_result(step_id="step_01", status="success", output=None):
    from backend.src.agents.agent_template.schemas import StepResult, StepSummary
    if output is None:
        output = {"result": "ok"}
    return StepResult(
        step_id=step_id,
        status=status,
        output=output,
        summary=StepSummary(
            what_was_done="做了某件事",
            what_was_produced="产出了结果",
        ),
        error_message=None if status == "success" else "模拟错误",
    )


def make_config(tmp_path: Path = None, **kwargs):
    from backend.src.agents.agent_template.config import AgentTemplateConfig
    from backend.src.agents.agent_template.schemas import SummaryMode

    if tmp_path is None:
        tmp_path = Path(tempfile.mkdtemp())

    # 创建必要的空文件
    plan_path = tmp_path / "plan.yaml"
    identity_path = tmp_path / "identity.yaml"
    skills_dir = tmp_path / "skills"

    if not plan_path.exists():
        plan_path.write_text(_MINIMAL_PLAN_YAML, encoding="utf-8")
    if not identity_path.exists():
        identity_path.write_text(_MINIMAL_IDENTITY_YAML, encoding="utf-8")
    skills_dir.mkdir(exist_ok=True)

    defaults = {
        "agent_name": "test_agent",
        "plan_path": plan_path,
        "identity_path": identity_path,
        "skills_dir": skills_dir,
        "model": "openai/gpt-4o-mini",
        "tools": ["pubmed_search"],
        "enable_trace": False,  # 测试中默认关闭 trace
    }
    defaults.update(kwargs)
    return AgentTemplateConfig(**defaults)


_MINIMAL_PLAN_YAML = """
plan_id: "test_plan"
agent_name: "test_agent"
version: "0.1"
steps:
  - step_id: "step_01"
    name: "测试 Step"
    instruction: "执行测试任务，输出 {\"result\": \"ok\"}"
    tools_required: []
    success_criteria:
      required_fields:
        - "result"
    max_retries: 2
    db_write_policy: "none"
"""

_MINIMAL_IDENTITY_YAML = """
agent_name: "test_agent"
role: "测试 Agent"
objective: "用于单元测试"
responsibilities:
  - "测试职责"
constraints:
  - "测试约束"
output_contract:
  result: "字符串类型"
"""


# =============================================================================
# 1. schemas.py 测试
# =============================================================================

class TestSchemas:
    def test_step_summary_defaults(self):
        from backend.src.agents.agent_template.schemas import StepSummary
        s = StepSummary(what_was_done="done", what_was_produced="produced")
        assert s.key_numbers == {}
        assert s.issues_encountered is None

    def test_plan_step_defaults(self):
        step = make_plan_step()
        assert step.max_retries == 2
        assert step.db_write_policy == "none"
        assert step.db_write_target is None
        assert step.tools_required == []

    def test_plan_must_have_steps(self):
        from backend.src.agents.agent_template.schemas import Plan
        plan = Plan(plan_id="p1", agent_name="a", version="0.1", steps=[make_plan_step()])
        assert len(plan.steps) == 1

    def test_step_result_failed_status(self):
        result = make_step_result(status="failed")
        assert result.status == "failed"
        assert result.error_message is not None

    def test_replan_action_values(self):
        from backend.src.agents.agent_template.schemas import ReplanAction
        assert ReplanAction.RETRY == "retry"
        assert ReplanAction.ABORT == "abort"

    def test_summary_mode_enum(self):
        from backend.src.agents.agent_template.schemas import SummaryMode
        assert SummaryMode.TEMPLATE == "template"
        assert SummaryMode.LLM == "llm"


# =============================================================================
# 2. errors.py 测试
# =============================================================================

class TestErrors:
    def test_inheritance(self):
        from backend.src.agents.agent_template.errors import (
            AgentTemplateError, PlanLoadError, StepExecutionError,
            ValidationError, ReplanError, TraceError, OutputAdapterError,
        )
        for cls in [PlanLoadError, StepExecutionError, ValidationError,
                    ReplanError, TraceError, OutputAdapterError]:
            assert issubclass(cls, AgentTemplateError)

    def test_step_execution_error_carries_step_id(self):
        from backend.src.agents.agent_template.errors import StepExecutionError
        err = StepExecutionError("step_x", "some error", cause=ValueError("root"))
        assert err.step_id == "step_x"
        assert "step_x" in str(err)
        assert isinstance(err.cause, ValueError)

    def test_raise_and_catch(self):
        from backend.src.agents.agent_template.errors import AgentTemplateError, PlanLoadError
        with pytest.raises(AgentTemplateError):
            raise PlanLoadError("file not found")


# =============================================================================
# 3. stopping.py 测试
# =============================================================================

class TestStopping:
    def test_defaults(self):
        from backend.src.agents.agent_template.stopping import StoppingConfig
        cfg = StoppingConfig()
        assert cfg.max_iterations == 10
        assert cfg.early_stopping_method == "force"

    def test_recursion_limit(self):
        from backend.src.agents.agent_template.stopping import StoppingConfig
        cfg = StoppingConfig(max_iterations=5)
        assert cfg.recursion_limit == 5 * 3 + 2

    def test_max_iterations_bounds(self):
        from backend.src.agents.agent_template.stopping import StoppingConfig
        from pydantic import ValidationError as PydanticValidationError
        with pytest.raises(PydanticValidationError):
            StoppingConfig(max_iterations=0)  # ge=1


# =============================================================================
# 4. config.py 测试
# =============================================================================

class TestConfig:
    def test_valid_config(self, tmp_path):
        cfg = make_config(tmp_path)
        assert cfg.agent_name == "test_agent"
        assert cfg.temperature == 0.0
        assert cfg.enable_memory is False

    def test_missing_required_field(self):
        from backend.src.agents.agent_template.config import AgentTemplateConfig
        from pydantic import ValidationError as PydanticValidationError
        with pytest.raises(PydanticValidationError):
            AgentTemplateConfig(
                # agent_name 缺失
                plan_path=Path("/tmp/plan.yaml"),
                identity_path=Path("/tmp/identity.yaml"),
                skills_dir=Path("/tmp/skills"),
                model="openai/gpt-4o",
                tools=[],
            )

    def test_temperature_bounds(self, tmp_path):
        from pydantic import ValidationError as PydanticValidationError
        with pytest.raises(PydanticValidationError):
            make_config(tmp_path, temperature=3.0)  # le=2.0


# =============================================================================
# 5. state.py 测试
# =============================================================================

class TestState:
    def test_init(self):
        from backend.src.agents.agent_template.state import TemplateAgentState
        state = TemplateAgentState(agent_name="test")
        assert state.run_id.startswith("run_")
        assert state.step_results == []
        assert state.current_step_index == 0

    def test_record_result(self):
        from backend.src.agents.agent_template.state import TemplateAgentState
        state = TemplateAgentState()
        result = make_step_result()
        state.record_result(result)
        assert len(state.step_results) == 1
        assert state.current_step_index == 1

    def test_increment_retry(self):
        from backend.src.agents.agent_template.state import TemplateAgentState
        state = TemplateAgentState()
        assert state.get_retry_count("step_01") == 0
        count = state.increment_retry("step_01")
        assert count == 1
        assert state.get_retry_count("step_01") == 1

    def test_completed_summaries_only_success(self):
        from backend.src.agents.agent_template.state import TemplateAgentState
        state = TemplateAgentState()
        state.step_results.append(make_step_result("s1", "success"))
        state.step_results.append(make_step_result("s2", "failed"))
        summaries = state.completed_summaries()
        assert len(summaries) == 1
        assert summaries[0]["step_id"] == "s1"


# =============================================================================
# 6. planner.py 测试
# =============================================================================

class TestPlanner:
    def test_load_valid_plan(self, tmp_path):
        from backend.src.agents.agent_template.planner import load_plan
        plan_file = tmp_path / "plan.yaml"
        plan_file.write_text(_MINIMAL_PLAN_YAML, encoding="utf-8")
        plan = load_plan(plan_file)
        assert plan.plan_id == "test_plan"
        assert plan.agent_name == "test_agent"
        assert len(plan.steps) == 1
        assert plan.steps[0].step_id == "step_01"

    def test_auto_generate_plan_id(self, tmp_path):
        from backend.src.agents.agent_template.planner import load_plan
        yaml_content = """
agent_name: "a"
version: "0.1"
steps:
  - step_id: "s1"
    name: "S1"
    instruction: "do it"
"""
        plan_file = tmp_path / "plan.yaml"
        plan_file.write_text(yaml_content, encoding="utf-8")
        plan = load_plan(plan_file)
        assert plan.plan_id.startswith("plan_")

    def test_file_not_found(self):
        from backend.src.agents.agent_template.planner import load_plan
        from backend.src.agents.agent_template.errors import PlanLoadError
        with pytest.raises(PlanLoadError, match="不存在"):
            load_plan(Path("/nonexistent/plan.yaml"))

    def test_missing_required_field(self, tmp_path):
        from backend.src.agents.agent_template.planner import load_plan
        from backend.src.agents.agent_template.errors import PlanLoadError
        plan_file = tmp_path / "plan.yaml"
        plan_file.write_text("agent_name: 'a'\nversion: '0.1'\n", encoding="utf-8")
        with pytest.raises(PlanLoadError):
            load_plan(plan_file)

    def test_empty_steps_raises(self, tmp_path):
        from backend.src.agents.agent_template.planner import load_plan
        from backend.src.agents.agent_template.errors import PlanLoadError
        plan_file = tmp_path / "plan.yaml"
        plan_file.write_text(
            "plan_id: 'p1'\nagent_name: 'a'\nversion: '0.1'\nsteps: []\n",
            encoding="utf-8",
        )
        with pytest.raises(PlanLoadError, match="steps.*为空"):
            load_plan(plan_file)

    def test_load_identity(self, tmp_path):
        from backend.src.agents.agent_template.planner import load_identity
        identity_file = tmp_path / "identity.yaml"
        identity_file.write_text(_MINIMAL_IDENTITY_YAML, encoding="utf-8")
        identity = load_identity(identity_file)
        assert identity["agent_name"] == "test_agent"
        assert "role" in identity
        assert "objective" in identity


# =============================================================================
# 7. context_builder.py 测试
# =============================================================================

class TestContextBuilder:
    def _make_identity(self):
        return {
            "agent_name": "test_agent",
            "role": "测试 Agent",
            "objective": "测试目标",
            "responsibilities": ["职责1"],
            "constraints": ["约束1"],
            "output_contract": {"result": "字符串"},
        }

    def test_no_upstream_no_skills(self, tmp_path):
        from backend.src.agents.agent_template import context_builder as cb
        cfg = make_config(tmp_path)
        step = make_plan_step()
        identity = self._make_identity()
        ctx = cb.build_context(cfg, identity, step, completed_summaries=[])
        assert "system_prompt" in ctx
        assert "user_prompt" in ctx
        assert "测试 Agent" in ctx["system_prompt"]
        assert step.step_id in ctx["user_prompt"]

    def test_with_completed_summaries(self, tmp_path):
        from backend.src.agents.agent_template import context_builder as cb
        cfg = make_config(tmp_path)
        step = make_plan_step(step_id="step_02")
        identity = self._make_identity()
        summaries = [
            {
                "step_id": "step_01",
                "summary": {
                    "what_was_done": "完成了检索",
                    "what_was_produced": "找到 10 篇文献",
                    "key_numbers": {"count": 10},
                },
                "output_keys": ["paper_ids"],
            }
        ]
        ctx = cb.build_context(cfg, identity, step, completed_summaries=summaries)
        assert "已完成步骤摘要" in ctx["system_prompt"]
        assert "step_01" in ctx["system_prompt"]

    def test_skills_loaded(self, tmp_path):
        from backend.src.agents.agent_template import context_builder as cb
        # 在 skills_dir 中创建一个 skill 文件
        cfg = make_config(tmp_path)
        skill_file = cfg.skills_dir / "test_skill.md"
        skill_file.write_text("# 测试技能\n\n这是一个测试技能。", encoding="utf-8")
        step = make_plan_step()
        identity = self._make_identity()
        ctx = cb.build_context(cfg, identity, step, completed_summaries=[])
        assert "测试技能" in ctx["system_prompt"]

    def test_upstream_context_injected(self, tmp_path):
        from backend.src.agents.agent_template import context_builder as cb
        cfg = make_config(tmp_path)
        step = make_plan_step()
        identity = self._make_identity()
        upstream = {"candidate_paper_ids": ["P001", "P002"]}
        ctx = cb.build_context(cfg, identity, step, completed_summaries=[], upstream_context=upstream)
        assert "上游 Agent 输出" in ctx["system_prompt"]


# =============================================================================
# 8. executor.py 测试（mock LLM）
# =============================================================================

class TestExecutor:
    def _mock_agent_result(self, content='{"result": "ok"}'):
        """构造 create_react_agent 的 mock 返回值。"""
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content=content)]}

    @patch("backend.src.agents.agent_template.executor._get_filtered_tools", return_value=[])
    @patch("backend.src.agents.agent_template.executor.create_react_agent")
    @patch("backend.src.agents.agent_template.executor.ChatLiteLLM")
    def test_run_step_success(self, mock_llm_cls, mock_create_agent, mock_tools, tmp_path):
        from backend.src.agents.agent_template.executor import run_step
        # 设置 mock agent 返回 JSON 输出
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = self._mock_agent_result('{"result": "ok"}')
        mock_create_agent.return_value = mock_agent

        cfg = make_config(tmp_path)
        step = make_plan_step()
        context = {"system_prompt": "sys", "user_prompt": "usr"}

        result = run_step(step, context, cfg)
        assert result.status == "success"
        assert result.step_id == "step_01"
        assert "result" in result.output

    @patch("backend.src.agents.agent_template.executor._get_filtered_tools", return_value=[])
    @patch("backend.src.agents.agent_template.executor.create_react_agent")
    @patch("backend.src.agents.agent_template.executor.ChatLiteLLM")
    def test_run_step_exception_returns_failed(self, mock_llm_cls, mock_create_agent, mock_tools, tmp_path):
        from backend.src.agents.agent_template.executor import run_step
        mock_agent = MagicMock()
        mock_agent.invoke.side_effect = RuntimeError("LLM 连接超时")
        mock_create_agent.return_value = mock_agent

        cfg = make_config(tmp_path)
        step = make_plan_step()
        context = {"system_prompt": "sys", "user_prompt": "usr"}

        result = run_step(step, context, cfg)
        assert result.status == "failed"
        assert result.error_message is not None
        assert "LLM 连接超时" in result.error_message

    @patch("backend.src.agents.agent_template.executor._get_filtered_tools", return_value=[])
    @patch("backend.src.agents.agent_template.executor.create_react_agent")
    @patch("backend.src.agents.agent_template.executor.ChatLiteLLM")
    def test_run_step_raw_output_fallback(self, mock_llm_cls, mock_create_agent, mock_tools, tmp_path):
        from backend.src.agents.agent_template.executor import run_step
        mock_agent = MagicMock()
        # 非 JSON 输出，走 fallback
        mock_agent.invoke.return_value = self._mock_agent_result("这是纯文本输出")
        mock_create_agent.return_value = mock_agent

        cfg = make_config(tmp_path)
        step = make_plan_step()
        context = {"system_prompt": "sys", "user_prompt": "usr"}

        result = run_step(step, context, cfg)
        assert "raw_output" in result.output


# =============================================================================
# 9. validator.py 测试
# =============================================================================

class TestValidator:
    def test_validate_step_success(self):
        from backend.src.agents.agent_template.validator import validate_step
        step = make_plan_step(success_criteria={
            "required_fields": ["result"],
            "min_count": {},
        })
        result = make_step_result(output={"result": "ok"})
        ok, msg = validate_step(result, step)
        assert ok is True
        assert msg == ""

    def test_validate_step_failed_status(self):
        from backend.src.agents.agent_template.validator import validate_step
        step = make_plan_step()
        result = make_step_result(status="failed")
        ok, msg = validate_step(result, step)
        assert ok is False
        assert "failed" in msg

    def test_validate_step_missing_required_field(self):
        from backend.src.agents.agent_template.validator import validate_step
        step = make_plan_step(success_criteria={"required_fields": ["missing_field"]})
        result = make_step_result(output={"other_field": "value"})
        ok, msg = validate_step(result, step)
        assert ok is False
        assert "missing_field" in msg

    def test_validate_step_min_count_fail(self):
        from backend.src.agents.agent_template.validator import validate_step
        step = make_plan_step(success_criteria={"min_count": {"items": 3}})
        result = make_step_result(output={"items": ["a", "b"]})  # 只有 2 个
        ok, msg = validate_step(result, step)
        assert ok is False
        assert "min_count" in msg

    def test_validate_step_min_count_pass(self):
        from backend.src.agents.agent_template.validator import validate_step
        step = make_plan_step(success_criteria={"min_count": {"items": 2}})
        result = make_step_result(output={"items": ["a", "b", "c"]})  # 3 个 >= 2
        ok, msg = validate_step(result, step)
        assert ok is True

    def test_validate_step_skipped(self):
        from backend.src.agents.agent_template.validator import validate_step
        step = make_plan_step(success_criteria={"required_fields": ["x"]})
        result = make_step_result(status="skipped", output={})
        ok, msg = validate_step(result, step)
        assert ok is True  # skipped 视为通过

    @patch("backend.src.agents.agent_template.validator.litellm.completion")
    def test_validate_plan_pass(self, mock_completion):
        from backend.src.agents.agent_template.validator import validate_plan
        from backend.src.agents.agent_template.schemas import AgentRunResult
        mock_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="yes，输出符合要求"))]
        )
        run_result = AgentRunResult(
            agent_name="test", run_id="r1", status="success",
            step_results=[], final_output={"result": "ok"},
        )
        ok, msg = validate_plan(run_result, {"result": "字符串"}, "openai/gpt-4o")
        assert ok is True

    @patch("backend.src.agents.agent_template.validator.litellm.completion")
    def test_validate_plan_fail(self, mock_completion):
        from backend.src.agents.agent_template.validator import validate_plan
        from backend.src.agents.agent_template.schemas import AgentRunResult
        mock_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="no，result 字段为空"))]
        )
        run_result = AgentRunResult(
            agent_name="test", run_id="r1", status="failed",
            step_results=[], final_output={},
        )
        ok, msg = validate_plan(run_result, {"result": "字符串"}, "openai/gpt-4o")
        assert ok is False
        assert "result" in msg or len(msg) > 0

    def test_validate_plan_empty_contract(self):
        from backend.src.agents.agent_template.validator import validate_plan
        from backend.src.agents.agent_template.schemas import AgentRunResult
        run_result = AgentRunResult(
            agent_name="test", run_id="r1", status="success",
            step_results=[], final_output={},
        )
        ok, msg = validate_plan(run_result, {}, "openai/gpt-4o")
        assert ok is True  # 无 contract 直接通过


# =============================================================================
# 10. replanner.py 测试
# =============================================================================

class TestReplanner:
    def test_retry_when_under_limit(self, tmp_path):
        from backend.src.agents.agent_template.replanner import decide
        from backend.src.agents.agent_template.schemas import ReplanAction
        cfg = make_config(tmp_path, max_step_retries=2)
        step = make_plan_step(max_retries=2)
        result = make_step_result(status="failed")
        decision = decide(step, result, current_retry_count=0, config=cfg)
        assert decision.action == ReplanAction.RETRY

    def test_abort_when_at_limit(self, tmp_path):
        from backend.src.agents.agent_template.replanner import decide
        from backend.src.agents.agent_template.schemas import ReplanAction
        cfg = make_config(tmp_path, max_step_retries=2)
        step = make_plan_step(max_retries=2)
        result = make_step_result(status="failed")
        # 已重试 2 次，达到上限
        decision = decide(step, result, current_retry_count=2, config=cfg)
        assert decision.action == ReplanAction.ABORT
        assert "达到上限" in decision.reason

    def test_config_max_retries_overrides(self, tmp_path):
        from backend.src.agents.agent_template.replanner import decide
        from backend.src.agents.agent_template.schemas import ReplanAction
        # config.max_step_retries=1 比 step.max_retries=3 更严格
        cfg = make_config(tmp_path, max_step_retries=1)
        step = make_plan_step(max_retries=3)
        result = make_step_result(status="failed")
        # 重试 1 次后应 abort（effective_max_retries = min(3,1) = 1）
        decision = decide(step, result, current_retry_count=1, config=cfg)
        assert decision.action == ReplanAction.ABORT

    def test_decide_plan_failure(self):
        from backend.src.agents.agent_template.replanner import decide_plan_failure
        from backend.src.agents.agent_template.schemas import ReplanAction
        decision = decide_plan_failure("输出字段为空")
        assert decision.action == ReplanAction.ABORT
        assert "plan_validation" in decision.target_step_id


# =============================================================================
# 11. hooks.py 测试
# =============================================================================

class TestHooks:
    def test_null_backend_no_exception(self):
        from backend.src.agents.agent_template.hooks import NullBackend, TraceEvent
        backend = NullBackend()
        event = TraceEvent(run_id="r1", stage="a", event_type="plan_start", status="running")
        # NullBackend 只 print，不应抛异常
        backend.write(event)

    def test_trace_hook_four_methods(self, capsys):
        from backend.src.agents.agent_template.hooks import TraceHook
        hook = TraceHook(run_id="r1", stage="test", enabled=True)
        plan = make_plan()
        step = plan.steps[0]
        result = make_step_result()
        run_result = MagicMock()
        run_result.status = "success"
        run_result.step_results = [result]
        run_result.final_output = {}

        hook.on_plan_start(plan)
        hook.on_step_start(step)
        hook.on_step_end(step, result, retry_count=0)
        hook.on_plan_end(run_result)

        captured = capsys.readouterr()
        assert "plan_start" in captured.out
        assert "step_start" in captured.out
        assert "step_end" in captured.out
        assert "plan_end" in captured.out

    def test_write_failure_does_not_propagate(self):
        from backend.src.agents.agent_template.hooks import TraceHook, TraceBackend, TraceEvent

        class BrokenBackend(TraceBackend):
            def write(self, event: TraceEvent) -> None:
                raise RuntimeError("存储崩溃")

        hook = TraceHook(run_id="r1", stage="test", backend=BrokenBackend(), enabled=True)
        plan = make_plan()
        # 即使 backend 崩溃，on_plan_start 也不应抛异常
        hook.on_plan_start(plan)  # 不会抛异常

    def test_disabled_hook_no_output(self, capsys):
        from backend.src.agents.agent_template.hooks import TraceHook
        hook = TraceHook(run_id="r1", stage="test", enabled=False)
        plan = make_plan()
        hook.on_plan_start(plan)
        hook.on_step_start(plan.steps[0])
        captured = capsys.readouterr()
        assert captured.out == ""  # disabled 时不输出

    def test_step_end_calculates_duration(self, capsys):
        from backend.src.agents.agent_template.hooks import TraceHook
        hook = TraceHook(run_id="r1", stage="test", enabled=True)
        step = make_plan_step()
        result = make_step_result()
        hook.on_step_start(step)   # 记录开始时间
        hook.on_step_end(step, result, 0)
        captured = capsys.readouterr()
        assert "duration_ms" in captured.out

    def test_trace_event_has_agent_run_id(self):
        """TraceEvent 应包含 agent_run_id 字段，to_dict() 应输出该字段。"""
        from backend.src.agents.agent_template.hooks import TraceEvent
        event = TraceEvent(
            run_id="pipe_001",
            stage="search_agent",
            event_type="plan_start",
            status="running",
            agent_run_id="run_abc123def456",
        )
        d = event.to_dict()
        assert "agent_run_id" in d
        assert d["agent_run_id"] == "run_abc123def456"
        assert d["run_id"] == "pipe_001"
        assert d["stage"] == "search_agent"
        # 确认旧字段名不再出现
        assert "agent_name" not in d

    def test_trace_hook_stage_and_agent_run_id(self, capsys):
        """TraceHook 使用 stage= 构造，agent_run_id 正确传入 TraceEvent。"""
        from backend.src.agents.agent_template.hooks import TraceHook
        hook = TraceHook(run_id="pipe_001", stage="search_agent", enabled=True)
        hook.agent_run_id = "run_abc123def456"  # 模拟 PlanRunner 设置的 agent_run_id

        plan = make_plan()
        hook.on_plan_start(plan)
        captured = capsys.readouterr()

        # 输出应包含 stage 和 agent_run 信息
        assert "search_agent" in captured.out
        assert "run_abc123def456" in captured.out

    def test_run_id_propagation(self, tmp_path):
        """PlanRunner.run(pipeline_run_id='pipe_x') 后，hook.run_id 应为 'pipe_x'，
        hook.agent_run_id 应为内部生成的 'run_<hex>' 格式。"""
        from backend.src.agents.agent_template.plan_runner import PlanRunner
        from backend.src.agents.agent_template.hooks import TraceHook
        from unittest.mock import patch

        cfg = make_config(tmp_path)
        identity = {
            "agent_name": "test_agent",
            "role": "测试",
            "objective": "测试",
            "output_contract": {},
        }
        hook = TraceHook(run_id="__unset__", stage="test_agent", enabled=False)
        runner = PlanRunner(config=cfg, identity=identity, hook=hook)

        with patch("backend.src.agents.agent_template.plan_runner.exec_module.run_step") as mock_rs, \
             patch("backend.src.agents.agent_template.plan_runner.validate_plan", return_value=(True, "")):
            mock_rs.return_value = make_step_result("step_01", "success", {"result": "ok"})
            runner.run(make_plan(), pipeline_run_id="pipe_x")

        assert hook.run_id == "pipe_x"
        assert hook.agent_run_id is not None
        assert hook.agent_run_id.startswith("run_")
        assert hook.agent_run_id != "pipe_x"  # pipeline ID 与 agent ID 不同


# =============================================================================
# 12. output_adapter.py 测试
# =============================================================================

class TestOutputAdapter:
    def _make_run_result(self, status="success"):
        from backend.src.agents.agent_template.schemas import AgentRunResult
        return AgentRunResult(
            agent_name="search_agent",
            run_id="r1",
            status=status,
            step_results=[make_step_result()],
            final_output={"candidate_paper_ids": ["P001", "P002"]},
        )

    def test_template_mode(self, tmp_path):
        from backend.src.agents.agent_template.output_adapter import adapt
        from backend.src.agents.agent_template.schemas import SummaryMode
        cfg = make_config(tmp_path, summary_mode=SummaryMode.TEMPLATE)
        run_result = self._make_run_result()
        patch = adapt(run_result, cfg)
        assert "search_agent_summary" in patch or "test_agent_summary" in patch
        assert "run_metadata" in patch

    def test_candidate_ids_forwarded(self, tmp_path):
        from backend.src.agents.agent_template.output_adapter import adapt
        from backend.src.agents.agent_template.schemas import SummaryMode
        cfg = make_config(tmp_path, agent_name="search_agent", summary_mode=SummaryMode.TEMPLATE)
        run_result = self._make_run_result()
        patch = adapt(run_result, cfg)
        assert patch.get("candidate_paper_ids") == ["P001", "P002"]

    @patch("backend.src.agents.agent_template.output_adapter.litellm.completion")
    def test_llm_mode(self, mock_completion, tmp_path):
        from backend.src.agents.agent_template.output_adapter import adapt
        from backend.src.agents.agent_template.schemas import SummaryMode
        mock_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="检索到 2 篇文献，去重后保留 2 篇。"))]
        )
        cfg = make_config(tmp_path, summary_mode=SummaryMode.LLM)
        run_result = self._make_run_result()
        patch = adapt(run_result, cfg)
        assert "run_metadata" in patch
        # LLM 摘要应被写入 summary key
        summary_keys = [k for k in patch if k.endswith("_summary")]
        assert len(summary_keys) > 0


# =============================================================================
# 13. plan_runner.py 端到端 mock 测试
# =============================================================================

class TestPlanRunner:
    def _make_runner(self, tmp_path, **cfg_kwargs):
        from backend.src.agents.agent_template.plan_runner import PlanRunner
        from backend.src.agents.agent_template.hooks import TraceHook
        cfg = make_config(tmp_path, **cfg_kwargs)
        identity = {
            "agent_name": "test_agent",
            "role": "测试",
            "objective": "测试",
            "output_contract": {},
        }
        hook = TraceHook(run_id="r1", stage="test_agent", enabled=False)
        return PlanRunner(config=cfg, identity=identity, hook=hook)

    @patch("backend.src.agents.agent_template.plan_runner.exec_module.run_step")
    @patch("backend.src.agents.agent_template.plan_runner.validate_plan", return_value=(True, ""))
    def test_all_success(self, mock_vp, mock_run_step, tmp_path):
        from backend.src.agents.agent_template.schemas import AgentRunResult
        mock_run_step.return_value = make_step_result("step_01", "success", {"result": "ok"})
        runner = self._make_runner(tmp_path)
        plan = make_plan()
        result: AgentRunResult = runner.run(plan)
        assert result.status in ("success", "partial")
        assert len(result.step_results) == 1

    @patch("backend.src.agents.agent_template.plan_runner.exec_module.run_step")
    @patch("backend.src.agents.agent_template.plan_runner.validate_plan", return_value=(True, ""))
    def test_retry_then_success(self, mock_vp, mock_run_step, tmp_path):
        """第一次失败，第二次成功（retry 路径）。"""
        from backend.src.agents.agent_template.schemas import AgentRunResult
        call_count = [0]

        def side_effect(step, context, config):
            call_count[0] += 1
            if call_count[0] == 1:
                return make_step_result("step_01", "failed", {})
            return make_step_result("step_01", "success", {"result": "ok"})

        mock_run_step.side_effect = side_effect
        runner = self._make_runner(tmp_path, max_step_retries=2)
        plan = make_plan()
        result: AgentRunResult = runner.run(plan)
        assert call_count[0] == 2  # 执行了 2 次
        # 最终应有成功结果
        success_results = [r for r in result.step_results if r.status == "success"]
        assert len(success_results) >= 1

    @patch("backend.src.agents.agent_template.plan_runner.exec_module.run_step")
    @patch("backend.src.agents.agent_template.plan_runner.validate_plan", return_value=(True, ""))
    def test_abort_after_max_retries(self, mock_vp, mock_run_step, tmp_path):
        """超过 max_retries 后 abort。"""
        mock_run_step.return_value = make_step_result("step_01", "failed", {})
        # max_step_retries=1, step.max_retries=2 → effective=1
        runner = self._make_runner(tmp_path, max_step_retries=1)
        plan = make_plan()
        result = runner.run(plan)
        assert result.status == "failed"


# =============================================================================
# 14. tools/registry.py 测试
# =============================================================================

class TestRegistry:
    def test_get_tools_known(self):
        from backend.src.tools.registry import get_tools
        tools = get_tools(["pubmed_search"])
        assert len(tools) == 1

    def test_get_tools_unknown_skipped(self, capsys):
        from backend.src.tools.registry import get_tools
        tools = get_tools(["nonexistent_tool"])
        assert tools == []
        captured = capsys.readouterr()
        assert "警告" in captured.out

    def test_pubmed_search_stub(self):
        from backend.src.tools.registry import pubmed_search
        result = pubmed_search.invoke({"query": "HAp peptide", "max_results": 5})
        assert "paper_ids" in result
        assert isinstance(result["paper_ids"], list)
        assert result.get("_stub") is True

    def test_register_and_retrieve_custom_tool(self):
        from backend.src.tools.registry import register_tool, get_tools, list_registered_tools
        from langchain_core.tools import tool

        @tool
        def custom_test_tool(x: str) -> dict:
            """测试用自定义工具。"""
            return {"x": x}

        register_tool("custom_test_tool", custom_test_tool)
        assert "custom_test_tool" in list_registered_tools()
        tools = get_tools(["custom_test_tool"])
        assert len(tools) == 1


# =============================================================================
# 15. PostgresBackend 测试
# =============================================================================

class TestPostgresBackend:
    def test_write_no_raise_when_no_url(self, monkeypatch):
        """TRACE_DB_URL 未设置时，write() 应静默跳过，不抛异常。"""
        monkeypatch.delenv("TRACE_DB_URL", raising=False)
        # 清除 lru_cache，确保本次测试重新读取环境变量
        from backend.src.db_access.trace import postgres_backend as pb_mod
        pb_mod.get_trace_engine.cache_clear()

        from backend.src.db_access.trace.postgres_backend import PostgresBackend
        from backend.src.agents.agent_template.hooks import TraceEvent
        backend = PostgresBackend()
        event = TraceEvent(
            run_id="pipe_test",
            stage="search_agent",
            event_type="plan_start",
            status="running",
        )
        # 不应抛异常
        backend.write(event)

    def test_write_no_raise_on_db_error(self, monkeypatch):
        """DB 连接失败时，write() 应 print 警告并静默跳过，不抛异常。"""
        monkeypatch.setenv("TRACE_DB_URL", "postgresql://invalid:invalid@localhost:9999/nodb")
        from backend.src.db_access.trace import postgres_backend as pb_mod
        pb_mod.get_trace_engine.cache_clear()

        from backend.src.db_access.trace.postgres_backend import PostgresBackend
        from backend.src.agents.agent_template.hooks import TraceEvent
        backend = PostgresBackend()
        event = TraceEvent(
            run_id="pipe_test",
            stage="search_agent",
            event_type="step_end",
            status="failed",
        )
        # DB 连接必然失败，但 write() 不应抛异常
        backend.write(event)

        # 清理缓存（避免影响其他测试）
        pb_mod.get_trace_engine.cache_clear()


# =============================================================================
# 16. PipelineTraceHook 测试
# =============================================================================

class TestPipelineTraceHook:
    def test_four_methods_produce_events(self, capsys):
        """四个方法各产出一条 trace 事件，event_type 和 stage 正确。"""
        from backend.src.db_access.trace.pipeline_hook import PipelineTraceHook
        hook = PipelineTraceHook(run_id="pipe_001", enabled=True)

        hook.on_pipeline_start({"input_ids": ["A", "B"]})
        hook.on_node_start("search_node")
        hook.on_node_end("search_node", status="success", agent_run_id="run_abc123")
        hook.on_pipeline_end(status="success")

        captured = capsys.readouterr()
        assert "pipeline_start" in captured.out
        assert "node_start" in captured.out
        assert "node_end" in captured.out
        assert "pipeline_end" in captured.out
        assert "search_node" in captured.out
        assert "pipeline" in captured.out

    def test_node_end_includes_agent_run_id(self, capsys):
        """on_node_end 传入的 agent_run_id 应出现在 trace 输出中。"""
        from backend.src.db_access.trace.pipeline_hook import PipelineTraceHook
        hook = PipelineTraceHook(run_id="pipe_001", enabled=True)
        hook.on_node_start("search_node")
        hook.on_node_end("search_node", status="success", agent_run_id="run_deadbeef0001")
        captured = capsys.readouterr()
        assert "run_deadbeef0001" in captured.out

    def test_disabled_hook_no_output(self, capsys):
        """enabled=False 时所有方法不产生任何输出。"""
        from backend.src.db_access.trace.pipeline_hook import PipelineTraceHook
        hook = PipelineTraceHook(run_id="pipe_001", enabled=False)
        hook.on_pipeline_start()
        hook.on_node_start("search_node")
        hook.on_node_end("search_node", status="success")
        hook.on_pipeline_end(status="success")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_write_failure_does_not_propagate(self):
        """BrokenBackend 崩溃时，hook 方法不应向上抛异常。"""
        from backend.src.db_access.trace.pipeline_hook import PipelineTraceHook
        from backend.src.agents.agent_template.hooks import TraceBackend, TraceEvent

        class BrokenBackend(TraceBackend):
            def write(self, event: TraceEvent) -> None:
                raise RuntimeError("后端崩溃")

        hook = PipelineTraceHook(run_id="pipe_001", backend=BrokenBackend(), enabled=True)
        # 不应抛异常
        hook.on_pipeline_start()
        hook.on_node_start("search_node")
        hook.on_node_end("search_node", status="failed")
        hook.on_pipeline_end(status="failed")
