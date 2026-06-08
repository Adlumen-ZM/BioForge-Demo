"""
tests/test_extract_agent.py — ExtractAgent 单元测试

覆盖范围：
  - agent.py: create_extract_agent 函数
  - plan.yaml 加载验证（5 步：chunk/embed/retrieve/llm_extract/validate）
  - identity.yaml 加载验证
  - 步骤配置验证
  - RAG 工具集成验证
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 PepClaw 目录在 path 中，使 rag 模块可导入
_PEPCLAW_ROOT = Path(__file__).parent.parent.parent
if str(_PEPCLAW_ROOT) not in sys.path:
    sys.path.insert(0, str(_PEPCLAW_ROOT))


class TestExtractAgent:
    """ExtractAgent 测试用例"""

    def test_create_agent(self):
        """测试创建 Agent 实例"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        agent = create_extract_agent()
        assert agent is not None
        assert agent.config.agent_name == "extract_agent"

    def test_config_values(self):
        """测试配置值（5 步 RAG 模式）"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        agent = create_extract_agent(model="deepseek/deepseek-chat")
        assert agent.config.model == "deepseek/deepseek-chat"
        assert agent.config.max_step_retries >= 1
        # 3 个 RAG 工具
        assert len(agent.config.tools) == 3
        assert "chunk_document" in agent.config.tools
        assert "build_rag_index" in agent.config.tools
        assert "retrieve_chunks" in agent.config.tools

    def test_plan_steps(self):
        """测试 5 步 plan 结构"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        agent = create_extract_agent()
        steps = agent.plan.steps
        assert len(steps) == 5
        step_ids = [step.step_id for step in steps]
        assert step_ids[0] == "chunk_documents"
        assert step_ids[1] == "embed_and_index"
        assert step_ids[2] == "retrieve_context"
        assert step_ids[3] == "llm_extract"
        assert step_ids[4] == "validate_output"

    def test_rag_step_tool_requirements(self):
        """测试 RAG 步骤的工具声明"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        agent = create_extract_agent()
        chunk_step = next(s for s in agent.plan.steps if s.step_id == "chunk_documents")
        embed_step = next(s for s in agent.plan.steps if s.step_id == "embed_and_index")
        retrieve_step = next(s for s in agent.plan.steps if s.step_id == "retrieve_context")
        llm_step = next(s for s in agent.plan.steps if s.step_id == "llm_extract")
        validate_step = next(s for s in agent.plan.steps if s.step_id == "validate_output")
        assert "chunk_document" in chunk_step.tools_required
        assert "build_rag_index" in embed_step.tools_required
        assert "retrieve_chunks" in retrieve_step.tools_required
        assert llm_step.tools_required == []
        assert validate_step.tools_required == []

    def test_step_success_criteria(self):
        """测试步骤 success_criteria"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        agent = create_extract_agent()
        # RAG 步骤都要求 status 字段
        for step_id in ["chunk_documents", "embed_and_index", "retrieve_context"]:
            step = next(s for s in agent.plan.steps if s.step_id == step_id)
            assert "status" in step.success_criteria.get("required_fields", [])
        # llm_extract 要求 papers
        llm_step = next(s for s in agent.plan.steps if s.step_id == "llm_extract")
        assert "papers" in llm_step.success_criteria.get("required_fields", [])
        assert llm_step.success_criteria.get("min_count", {}).get("papers", 0) >= 1

    def test_identity_config(self):
        """测试身份配置"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        agent = create_extract_agent()
        identity = agent.identity
        assert identity["role"] == "生物医学文献信息提取专家"
        assert "FAE" in identity["objective"]
        assert len(identity["responsibilities"]) >= 1
        assert "extracted_papers" in identity["output_contract"]

    def test_rag_tools_registered(self):
        """测试 RAG 工具是否在注册表中可用"""
        from backend.src.tools.registry import list_registered_tools
        registered = list_registered_tools()
        for tool_name in ["chunk_document", "build_rag_index", "retrieve_chunks"]:
            assert tool_name in registered, f"{tool_name} 未注册"
