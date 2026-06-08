"""
backend/src/agents/guide_agent/agent.py — 引导员 Agent 实现

位置：backend/src/agents/guide_agent/
依赖：litellm（LLM 调用），yaml（identity 加载），pathlib（文件系统）
      langgraph.types.interrupt（interrupt 机制，只在 build_guide_node 内调用）

职责：
  通过三步 LLM 调用 + LangGraph interrupt()，与用户确认"三件核心物"：
    1. task_description  — 自然语言任务描述（search/screen/extract 各阶段参考）
    2. db_schema         — 数据库字段模板（extract_agent 抽取依据）
    3. inclusion_criteria— 文献准入/排除标准（screen_agent 筛选依据）

与 graph 的关系：
  build_guide_node() 返回一个符合 LangGraph node 签名的函数 guide_node(state) -> dict。
  guide_node 是唯一调用 interrupt() 的地方（LangGraph 要求 interrupt 在 graph node 调用栈内）。
  MockGuideAgent / RealGuideAgent 只准备 payload 数据，不调用 interrupt。

为什么不走 AgentTemplate：
  AgentTemplate 是 Plan-and-Execute 模板，有 plan.yaml 和多步 executor。
  guide_agent 没有预定义步骤（无 plan.yaml），也没有业务工具（interrupt 不是 @tool），
  形态是直接 litellm.completion() 三次调用 + interrupt 暂停，与 AgentTemplate 不匹配。
  因此 guide_agent 独立实现，不引用 agent_template/ 的任何类。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

# 当前文件所在目录（guide_agent/）
_AGENT_DIR = Path(__file__).parent


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _load_identity_and_skills() -> str:
    """加载 identity.yaml 和 skills/*.md，拼成 system prompt 文本。

    逻辑复用 context_builder._load_skills() 思路：
      - 先加载 identity.yaml，拼成角色/职责/约束描述
      - 再按文件名字母序加载 skills/*.md，每个文件加 '### <文件名>' 标题
      - 拼接为完整 system prompt

    Returns:
        str，完整的 system prompt 文本。
    """
    parts: list[str] = []

    # ── 1. 加载 identity.yaml（角色定义）────────────────────────────────────
    identity_path = _AGENT_DIR / "identity.yaml"
    if identity_path.exists():
        try:
            identity = yaml.safe_load(identity_path.read_text(encoding="utf-8"))
            # 拼接 role + objective + responsibilities + constraints
            role_text = identity.get("role", "")
            objective  = identity.get("objective", "")
            resp_list  = identity.get("responsibilities", [])
            cons_list  = identity.get("constraints", [])

            parts.append(f"# 角色\n{role_text}")
            if objective:
                parts.append(f"## 目标\n{objective.strip()}")
            if resp_list:
                resp_str = "\n".join(f"- {r}" for r in resp_list)
                parts.append(f"## 职责\n{resp_str}")
            if cons_list:
                cons_str = "\n".join(f"- {c}" for c in cons_list)
                parts.append(f"## 约束\n{cons_str}")
        except Exception as e:
            # identity 加载失败不崩溃，继续加载 skills
            print(f"[GuideAgent] ⚠️ identity.yaml 加载失败：{e}")

    # ── 2. 加载 skills/*.md（按文件名字母序）────────────────────────────────
    skills_dir = _AGENT_DIR / "skills"
    if skills_dir.exists():
        skill_files = sorted(skills_dir.glob("*.md"))
        for skill_file in skill_files:
            content = skill_file.read_text(encoding="utf-8").strip()
            if content:
                # 文件名转为可读标题（如 demo_script → Demo Script）
                skill_name = skill_file.stem.replace("_", " ").title()
                parts.append(f"## Skills: {skill_name}\n\n{content}")

    return "\n\n".join(parts)


def _call_llm(system_prompt: str, user_prompt: str, model: str) -> str:
    """调用 LLM 做一次推理，返回模型输出文本。

    这是 guide_agent 三步对话中的每一次 LLM 调用（任务描述/字段模板/准入标准各一次）。
    temperature=0 保证输出的确定性（demo 模式下格式固定）。

    Args:
        system_prompt: 系统提示词（identity + skills 拼接结果）。
        user_prompt:   用户消息（当前步骤的具体指令）。
        model:         LiteLLM 兼容的模型字符串（如 "openai/gpt-4o"）。

    Returns:
        str，LLM 输出的原始文本。

    Raises:
        Exception: LLM 调用失败时抛出，由 RealGuideAgent.run() 捕获并降级。
    """
    import litellm  # 延迟导入，失败时不影响 MockGuideAgent

    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.0,
        max_tokens=1024,
    )
    return response.choices[0].message.content.strip()


def _parse_json_from_llm(text: str, key: str) -> Any:
    """从 LLM 输出里提取 JSON，三层 fallback 保健壮性。

    与 executor._extract_output() 思路一致：
    Layer 1：提取 ```json ... ``` 代码块后解析
    Layer 2：直接 json.loads（LLM 直接输出纯 JSON 时）
    Layer 3：在文本中找第一个 { 到最后一个 } 的子串解析

    Args:
        text: LLM 输出的原始文本。
        key:  期望的顶层 JSON key（如 "task_description"），用于提取嵌套值。

    Returns:
        解析出的 JSON 值（str/dict/list），失败返回原始 text。
    """
    # Layer 1：提取 ```json 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            parsed = json.loads(m.group(1).strip())
            return parsed.get(key, parsed) if isinstance(parsed, dict) else parsed
        except Exception:
            pass

    # Layer 2：直接解析（LLM 输出纯 JSON 时）
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            return parsed.get(key, parsed) if isinstance(parsed, dict) else parsed
        except Exception:
            pass

    # Layer 3：找 { ... } 子串解析
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            return parsed.get(key, parsed) if isinstance(parsed, dict) else parsed
        except Exception:
            pass

    # 全部失败：返回原始文本（downstream 会用 fallback 处理）
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Mock Guide Agent（离线开发/单元测试用，不调 LLM）
# ─────────────────────────────────────────────────────────────────────────────

class MockGuideAgent:
    """Mock 版引导员：不调 LLM，直接返回固定的三步 payload 数据。

    用途：
    - 本地开发时快速验证 guide_node 的 interrupt 流程
    - CI/CD 单元测试（不需要 LLM API Key）
    - pipeline 的 mock 模式

    注意：interrupt() 不在此类内调用，由 build_guide_node() 生成的 guide_node 负责。
         此类只负责准备 payload 数据。
    """

    def run(self, input_data: dict) -> dict:
        """返回固定的三步 interrupt payload 数据（不调 LLM）。

        Args:
            input_data: 包含 user_query 等初始输入的 dict。

        Returns:
            dict，含三个 payload（task_confirm / schema_confirm / criteria_confirm）
            和最终的三件核心物（task_description / db_schema / inclusion_criteria）。
        """
        user_query = input_data.get("user_query", "HAp 肽段矿化研究")

        # ── 固定的任务描述（根据 user_query 简单拼接）──────────────────────
        task_description = (
            f"针对 {user_query}，系统将从 PubMed 检索相关文献，"
            "重点关注与羟基磷灰石（HAp）或磷酸钙矿化体系相互作用的合成肽或天然肽段研究。"
            "将抽取肽段序列、功能标签、实验证据层级等结构化信息，"
            "构建 HAp 肽段功能数据库，支持后续的肽段设计和材料优化研究。"
        )

        # ── 固定的字段模板（HAp 肽段核心字段集）──────────────────────────
        db_schema = {
            "paper_id":               {"type": "str",  "description": "内部论文编号",      "example": "P000001"},
            "doi":                    {"type": "str",  "description": "论文 DOI",          "example": "10.1021/acs.biomac.2c00123"},
            "title":                  {"type": "str",  "description": "论文标题",           "example": "Peptide-HAp binding..."},
            "publication_year":       {"type": "int",  "description": "发表年份",           "example": "2023"},
            "entity_name_normalized": {"type": "str",  "description": "标准化肽段名称/序列", "example": "WGNYAYK"},
            "sequence_raw":           {"type": "str",  "description": "原始氨基酸序列",     "example": "RKLPDA"},
            "interaction_target":     {"type": "str",  "description": "作用靶底物",         "example": "HAp"},
            "summary_functions":      {"type": "str",  "description": "功能标签（分号分隔）","example": "adsorption;remineralization"},
            "evidence_overall_level": {"type": "str",  "description": "证据层级",           "example": "in_vitro"},
            "text_to_sequence":       {"type": "str",  "description": "序列来源定位",       "example": "Table 2"},
        }

        # ── 固定的准入/排除标准（HAp 肽段领域默认模板）────────────────────
        inclusion_criteria = {
            "inclusion": [
                "研究对象为合成肽或天然蛋白来源肽段",
                "实验涉及 HAp、磷酸钙（TCP/OCP/ACP）或牙体相关底物",
                "包含定性或定量的实验结果（结合亲和力、矿化促进/抑制等）",
                "英文原文，发表年份不早于 2000 年",
                "提供具体的肽段序列信息（单字母缩写或 IUPAC 命名）",
            ],
            "exclusion": [
                "综述、评论、会议摘要、编辑信函（无原始实验数据）",
                "纯计算或纯分子动力学模拟研究（无实验验证）",
                "研究对象明确排除肽段（仅研究无机矿物颗粒）",
                "无法获取全文或摘要信息不完整",
            ],
        }

        # 返回三步 payload + 最终产出
        return {
            # 三步 interrupt payload（由 guide_node 逐一传给 interrupt()）
            "task_confirm_payload": {
                "type":    "task_confirm",
                "label":   "任务描述",
                "content": task_description,
                "options": ["确认，继续"],
                "default": 0,
            },
            "schema_confirm_payload": {
                "type":    "schema_confirm",
                "label":   "数据库字段模板",
                "content": db_schema,
                "options": ["确认，使用此模板"],
                "default": 0,
            },
            "criteria_confirm_payload": {
                "type":    "criteria_confirm",
                "label":   "文献准入/排除标准",
                "content": inclusion_criteria,
                "options": ["确认，进入检索"],
                "default": 0,
            },
            # 最终三件核心物（guide_node 从 payload 里提取后写回 PipelineState）
            "task_description":   task_description,
            "db_schema":          db_schema,
            "inclusion_criteria": inclusion_criteria,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Real Guide Agent（真实 LLM 调用，三步对话产出三件核心物）
# ─────────────────────────────────────────────────────────────────────────────

class RealGuideAgent:
    """Real 版引导员：三次 LLM 调用产出三件核心物。

    每步调用 _call_llm()，再用 _parse_json_from_llm() 解析输出。
    任何步骤失败时，降级到 MockGuideAgent 的固定输出，并在返回值中标注 fallback=True。

    注意：interrupt() 不在此类内调用，由 build_guide_node() 生成的 guide_node 负责。
    """

    def __init__(self, model: str | None = None):
        """
        Args:
            model: LiteLLM 兼容的模型字符串。
                   默认从环境变量 DEFAULT_LLM_MODEL 读取。
        """
        self.model = model or os.getenv(
            "DEFAULT_LLM_MODEL", "minimax/MiniMax-M2.7-highspeed"
        )
        # 加载 system prompt（identity + skills），只加载一次
        self._system_prompt = _load_identity_and_skills()

    def run(self, input_data: dict) -> dict:
        """三次 LLM 调用，分别产出任务描述/字段模板/准入标准。

        Args:
            input_data: 包含 user_query 等初始输入的 dict。

        Returns:
            dict，含三步 payload 和最终三件核心物。
            若 LLM 调用失败，降级到 MockGuideAgent 并附加 fallback=True。
        """
        user_query = input_data.get("user_query", "")

        try:
            # ── Step 1：生成任务描述 ─────────────────────────────────────────
            # 告诉 LLM 当前是第一步，需要输出任务描述 JSON
            user_prompt_1 = (
                f"用户的研究诉求：{user_query}\n\n"
                "请严格按照 demo_script.md 步骤一的格式，生成任务描述。"
            )
            raw_1 = _call_llm(self._system_prompt, user_prompt_1, self.model)
            task_description = _parse_json_from_llm(raw_1, "task_description")
            if not isinstance(task_description, str):
                # 解析结果不是字符串，转为字符串
                task_description = str(task_description)

            # ── Step 2：生成字段模板 ─────────────────────────────────────────
            # 告诉 LLM 当前是第二步，需要基于任务描述输出字段模板 JSON
            user_prompt_2 = (
                f"任务描述已确认：{task_description}\n\n"
                "请严格按照 demo_script.md 步骤二的格式，基于上述任务描述，"
                "从 schema_template.md 中选取最相关的字段，生成字段模板 JSON。"
            )
            raw_2 = _call_llm(self._system_prompt, user_prompt_2, self.model)
            db_schema = _parse_json_from_llm(raw_2, "db_schema")
            if not isinstance(db_schema, dict):
                # 解析结果不是 dict，使用空 dict（降级到 mock 的字段模板）
                raise ValueError(f"db_schema 解析失败，原始输出：{raw_2[:100]}")

            # ── Step 3：生成准入/排除标准 ────────────────────────────────────
            # 告诉 LLM 当前是第三步，需要基于任务描述输出准入/排除标准 JSON
            user_prompt_3 = (
                f"任务描述：{task_description}\n"
                f"字段模板已确认（{len(db_schema)} 个字段）。\n\n"
                "请严格按照 demo_script.md 步骤三的格式，"
                "参考 criteria_template.md，生成文献准入/排除标准 JSON。"
            )
            raw_3 = _call_llm(self._system_prompt, user_prompt_3, self.model)
            inclusion_criteria = _parse_json_from_llm(raw_3, "inclusion_criteria")
            if not isinstance(inclusion_criteria, dict):
                raise ValueError(f"inclusion_criteria 解析失败，原始输出：{raw_3[:100]}")

        except Exception as e:
            # LLM 调用或解析失败：降级到 MockGuideAgent 的固定输出
            print(f"[RealGuideAgent] ⚠️ LLM 调用失败，降级到 mock 输出：{e}")
            mock_result = MockGuideAgent().run(input_data)
            mock_result["fallback"] = True  # 标注本次使用了 fallback
            mock_result["fallback_reason"] = str(e)
            return mock_result

        # ── 构造三步 interrupt payload（格式与 §2 一致）──────────────────────
        return {
            "task_confirm_payload": {
                "type":    "task_confirm",
                "label":   "任务描述",
                "content": task_description,
                "options": ["确认，继续"],
                "default": 0,
            },
            "schema_confirm_payload": {
                "type":    "schema_confirm",
                "label":   "数据库字段模板",
                "content": db_schema,
                "options": ["确认，使用此模板"],
                "default": 0,
            },
            "criteria_confirm_payload": {
                "type":    "criteria_confirm",
                "label":   "文献准入/排除标准",
                "content": inclusion_criteria,
                "options": ["确认，进入检索"],
                "default": 0,
            },
            # 最终三件核心物
            "task_description":   task_description,
            "db_schema":          db_schema,
            "inclusion_criteria": inclusion_criteria,
            "fallback": False,
        }


# ─────────────────────────────────────────────────────────────────────────────
# build_guide_node — 构造符合 LangGraph node 签名的 guide_node 函数
# ─────────────────────────────────────────────────────────────────────────────

def build_guide_node(
    mode: str = "mock",
    model: str | None = None,
):
    """构造 guide_node 函数，供 graph/nodes.py 注册为 LangGraph 节点。

    guide_node 是唯一调用 interrupt() 的地方（LangGraph 要求 interrupt 在 graph
    节点的调用栈内才有效），三次 interrupt 分别对应三件核心物的用户确认。

    Args:
        mode:  运行模式，"mock" 或 "real"。
        model: LiteLLM 模型字符串，None 时从 DEFAULT_LLM_MODEL 环境变量读取。

    Returns:
        guide_node(state: PipelineState) -> dict — 符合 LangGraph node 签名的函数。
    """
    # 根据 mode 实例化对应的 Agent
    if mode == "real":
        agent: MockGuideAgent | RealGuideAgent = RealGuideAgent(model=model)
    else:
        agent = MockGuideAgent()

    def guide_node(state: Any) -> dict:
        """Guide 节点：三步 interrupt 引导用户确认三件核心物。

        LangGraph interrupt() 机制：
          1. 调用 interrupt(payload) → 图暂停，payload 传给 CLI
          2. CLI 渲染 payload 给用户，等待确认（按 Enter）
          3. CLI 调用 graph.stream(Command(resume=0), config) → 图从断点继续
          4. interrupt() 的返回值 = resume 值（0 = 选项0，即"确认"）

        返回值写入 PipelineState 的字段：
          task_description, db_schema, inclusion_criteria, user_confirmed,
          guide_summary, query, ok, run_metadata, message
        """
        # 从 state 获取用户输入
        user_query = state.get("user_query", "") if hasattr(state, "get") else ""

        # 调用 agent.run() 准备三步 payload（不调 interrupt，只准备数据）
        result = agent.run({"user_query": user_query})

        # ── 第一个 interrupt：确认任务描述 ──────────────────────────────────
        # 此处暂停，等待用户确认「任务描述」（CLI 渲染 task_confirm_payload）
        try:
            from langgraph.types import interrupt as lg_interrupt
            # interrupt 返回用户的选择（Demo 版固定为 0）
            _resume_1 = lg_interrupt(result["task_confirm_payload"])
        except ImportError:
            # langgraph 不可用时跳过 interrupt（批量测试模式）
            print("[guide_node] ⚠️ langgraph.types.interrupt 不可用，跳过第一个 interrupt")
            _resume_1 = 0

        # ── 第二个 interrupt：确认数据库字段模板 ────────────────────────────
        # 此处暂停，等待用户确认「字段模板」（CLI 渲染 schema_confirm_payload）
        try:
            from langgraph.types import interrupt as lg_interrupt
            _resume_2 = lg_interrupt(result["schema_confirm_payload"])
        except ImportError:
            print("[guide_node] ⚠️ langgraph.types.interrupt 不可用，跳过第二个 interrupt")
            _resume_2 = 0

        # ── 第三个 interrupt：确认文献准入/排除标准 ─────────────────────────
        # 此处暂停，等待用户确认「准入/排除标准」（CLI 渲染 criteria_confirm_payload）
        try:
            from langgraph.types import interrupt as lg_interrupt
            _resume_3 = lg_interrupt(result["criteria_confirm_payload"])
        except ImportError:
            print("[guide_node] ⚠️ langgraph.types.interrupt 不可用，跳过第三个 interrupt")
            _resume_3 = 0

        # ── 三步全部确认完成，写回 PipelineState patch ───────────────────────
        task_description   = result.get("task_description", "")
        db_schema          = result.get("db_schema", {})
        inclusion_criteria = result.get("inclusion_criteria", {})
        is_fallback        = result.get("fallback", False)

        # 从 task_description 派生检索意图（取前80字作为 search_agent 的 query）
        query = task_description[:80] if task_description else user_query

        return {
            # ── 三件核心物（写入 PipelineState）
            "task_description":   task_description,
            "db_schema":          db_schema,
            "inclusion_criteria": inclusion_criteria,
            "user_confirmed":     True,   # 三步均已确认
            # ── Search Agent 使用的检索 query
            "query":              query,
            # ── 元数据（调试用）
            "guide_summary": (
                f"引导阶段完成（{'mock' if is_fallback or mode == 'mock' else 'real'} 模式），"
                f"任务描述已确认，字段模板含 {len(db_schema)} 个字段，"
                f"准入标准含 {len(inclusion_criteria.get('inclusion', []))} 条准入 / "
                f"{len(inclusion_criteria.get('exclusion', []))} 条排除。"
            ),
            "ok": True,
            "message": "guide_agent 完成，进入流水线",
            "run_metadata": {
                "agent_name": "guide_agent",
                "status":     "success",
                "mode":       mode,
                "fallback":   is_fallback,
            },
        }

    return guide_node


# ── 公开接口 ──────────────────────────────────────────────────────────────────
__all__ = ["MockGuideAgent", "RealGuideAgent", "build_guide_node"]
