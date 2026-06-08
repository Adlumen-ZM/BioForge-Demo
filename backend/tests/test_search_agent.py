"""
tests/test_search_agent.py — SearchAgent 单元测试

覆盖范围：
  - agent.py: create_search_agent 函数
  - plan.yaml 加载验证
  - identity.yaml 加载验证
  - 工具列表匹配

运行方式：
  cd backend && python -m pytest tests/test_search_agent.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 backend/src 可被 import
_BACKEND_ROOT = Path(__file__).parent.parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


class TestSearchAgent:
    """SearchAgent 测试用例"""

    def test_create_agent(self):
        """测试创建 Agent 实例"""
        from backend.src.agents.search_agent.agent import create_search_agent
        
        agent = create_search_agent()
        assert agent is not None
        assert agent.config.agent_name == "search_agent"

    def test_config_values(self):
        """测试配置值"""
        from backend.src.agents.search_agent.agent import create_search_agent
        
        agent = create_search_agent(model="openai/gpt-4o")
        
        # 验证配置
        assert agent.config.model == "openai/gpt-4o"
        assert agent.config.max_step_retries == 2
        assert agent.config.enable_trace is True
        
        # 验证工具列表
        assert "pubmed_search" in agent.config.tools

    def test_plan_steps(self):
        """测试计划步骤数量和名称"""
        from backend.src.agents.search_agent.agent import create_search_agent
        
        agent = create_search_agent()
        steps = agent.plan.steps
        
        # 验证步骤数量（4 步：task_understanding + query_build + search_execute + dedup_filter）
        assert len(steps) == 4
        
        # 验证步骤 ID
        step_ids = [step.step_id for step in steps]
        assert "task_understanding" in step_ids
        assert "query_build" in step_ids
        assert "search_execute" in step_ids
        assert "dedup_filter" in step_ids

    def test_identity_config(self):
        """测试身份配置"""
        from backend.src.agents.search_agent.agent import create_search_agent
        
        agent = create_search_agent()
        identity = agent.identity
        
        # 验证角色和目标（identity 是 dict 类型）
        assert identity["role"] == "生物医学文献检索专家"
        assert "肽-矿物相互作用" in identity["objective"]
        
        # 验证职责和约束
        assert len(identity["responsibilities"]) >= 1
        assert len(identity["constraints"]) >= 1
        
        # 验证输出契约
        assert "candidate_paper_ids" in identity["output_contract"]
        assert "search_summary" in identity["output_contract"]

    def test_plan_step_requirements(self):
        """测试各步骤的工具要求"""
        from backend.src.agents.search_agent.agent import create_search_agent
        
        agent = create_search_agent()
        
        # 查找各步骤
        query_build_step = next(s for s in agent.plan.steps if s.step_id == "query_build")
        search_execute_step = next(s for s in agent.plan.steps if s.step_id == "search_execute")
        dedup_filter_step = next(s for s in agent.plan.steps if s.step_id == "dedup_filter")
        
        # 验证工具要求
        assert query_build_step.tools_required == []
        assert "pubmed_search" in search_execute_step.tools_required
        assert dedup_filter_step.tools_required == []

    def test_custom_model(self):
        """测试自定义模型"""
        from backend.src.agents.search_agent.agent import create_search_agent
        
        agent = create_search_agent(model="anthropic/claude-3-sonnet")
        assert agent.config.model == "anthropic/claude-3-sonnet"

    def test_plan_file_exists(self):
        """测试计划文件存在"""
        from backend.src.agents.search_agent.agent import _AGENT_DIR
        
        plan_path = _AGENT_DIR / "plan.yaml"
        identity_path = _AGENT_DIR / "identity.yaml"
        skills_dir = _AGENT_DIR / "skills"
        
        assert plan_path.exists(), f"plan.yaml 不存在: {plan_path}"
        assert identity_path.exists(), f"identity.yaml 不存在: {identity_path}"
        assert skills_dir.exists() and skills_dir.is_dir(), f"skills 目录不存在: {skills_dir}"