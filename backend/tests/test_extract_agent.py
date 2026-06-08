"""
tests/test_extract_agent.py — ExtractAgent 单元测试

覆盖范围：
  - agent.py: create_extract_agent 函数
  - plan.yaml 加载验证
  - identity.yaml 加载验证
  - 步骤配置验证

运行方式：
  cd backend && python -m pytest tests/test_extract_agent.py -v

注意：RAG 相关测试已注释，等待 FlagEmbedding 依赖安装后启用。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 backend/src 可被 import
_BACKEND_ROOT = Path(__file__).parent.parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


class TestExtractAgent:
    """ExtractAgent 测试用例"""

    def test_create_agent(self):
        """测试创建 Agent 实例"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        
        agent = create_extract_agent()
        assert agent is not None
        assert agent.config.agent_name == "extract_agent"

    def test_config_values(self):
        """测试配置值"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        
        agent = create_extract_agent(model="openai/gpt-4o")
        
        # 验证配置
        assert agent.config.model == "openai/gpt-4o"
        assert agent.config.max_step_retries == 2
        assert agent.config.enable_trace is True
        
        # 验证工具列表（当前使用基础模式，无 RAG 工具）
        # RAG 工具待 FlagEmbedding 安装后启用
        assert agent.config.tools == []

    def test_plan_steps(self):
        """测试计划步骤数量和名称"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        
        agent = create_extract_agent()
        steps = agent.plan.steps
        
        # 验证步骤数量（基础模式：2 个步骤）
        # RAG 模式下为 5 个步骤：chunk + embed + retrieve + llm_extract + validate
        assert len(steps) == 2
        
        # 验证步骤 ID
        step_ids = [step.step_id for step in steps]
        assert "llm_extract" in step_ids
        assert "validate_output" in step_ids

    def test_identity_config(self):
        """测试身份配置"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        
        agent = create_extract_agent()
        identity = agent.identity
        
        # 验证角色和目标（identity 是 dict 类型）
        assert identity["role"] == "生物医学文献信息提取专家"
        assert "FAE" in identity["objective"]
        
        # 验证职责和约束
        assert len(identity["responsibilities"]) >= 1
        assert len(identity["constraints"]) >= 1
        
        # 验证输出契约
        assert "extracted_papers" in identity["output_contract"]
        assert "extraction_summary" in identity["output_contract"]

    def test_plan_step_requirements(self):
        """测试各步骤的工具要求"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        
        agent = create_extract_agent()
        
        # 查找各步骤（基础模式）
        llm_extract_step = next(s for s in agent.plan.steps if s.step_id == "llm_extract")
        validate_output_step = next(s for s in agent.plan.steps if s.step_id == "validate_output")
        
        # 验证工具要求（基础模式下均无需工具）
        assert llm_extract_step.tools_required == []
        assert validate_output_step.tools_required == []

    def test_step_instructions(self):
        """测试步骤指令包含关键内容"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        
        agent = create_extract_agent()
        
        # 验证 llm_extract 步骤指令
        llm_extract_step = next(s for s in agent.plan.steps if s.step_id == "llm_extract")
        instruction = llm_extract_step.instruction
        assert "FAE" in instruction or "peptide" in instruction.lower()
        assert "JSON" in instruction
        
        # 验证 validate_output 步骤指令
        validate_step = next(s for s in agent.plan.steps if s.step_id == "validate_output")
        val_instruction = validate_step.instruction
        assert "JSON" in val_instruction
        assert "校验" in val_instruction

    def test_custom_model(self):
        """测试自定义模型"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        
        agent = create_extract_agent(model="anthropic/claude-3-sonnet")
        assert agent.config.model == "anthropic/claude-3-sonnet"

    def test_plan_file_exists(self):
        """测试计划文件存在"""
        from backend.src.agents.extract_agent.agent import _AGENT_DIR
        
        plan_path = _AGENT_DIR / "plan.yaml"
        identity_path = _AGENT_DIR / "identity.yaml"
        skills_dir = _AGENT_DIR / "skills"
        
        assert plan_path.exists(), f"plan.yaml 不存在: {plan_path}"
        assert identity_path.exists(), f"identity.yaml 不存在: {identity_path}"
        assert skills_dir.exists() and skills_dir.is_dir(), f"skills 目录不存在: {skills_dir}"

    def test_skills_files_exist(self):
        """测试技能文件存在"""
        from backend.src.agents.extract_agent.agent import _AGENT_DIR
        
        skills_dir = _AGENT_DIR / "skills"
        skill_files = list(skills_dir.glob("*.md"))
        
        assert len(skill_files) >= 1, "至少需要一个 skill 文件"

    def test_success_criteria(self):
        """测试成功标准配置"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        
        agent = create_extract_agent()
        
        # 验证 llm_extract 步骤的成功标准
        llm_extract_step = next(s for s in agent.plan.steps if s.step_id == "llm_extract")
        assert "papers" in llm_extract_step.success_criteria["required_fields"]
        
        # 验证 validate_output 步骤的成功标准
        validate_step = next(s for s in agent.plan.steps if s.step_id == "validate_output")
        assert "validation_result" in validate_step.success_criteria["required_fields"]

    def test_max_retries(self):
        """测试最大重试次数配置"""
        from backend.src.agents.extract_agent.agent import create_extract_agent
        
        agent = create_extract_agent()
        
        llm_extract_step = next(s for s in agent.plan.steps if s.step_id == "llm_extract")
        validate_step = next(s for s in agent.plan.steps if s.step_id == "validate_output")
        
        assert llm_extract_step.max_retries == 2
        assert validate_step.max_retries == 1