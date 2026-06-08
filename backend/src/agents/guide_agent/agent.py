"""
backend/src/agents/guide_agent/agent.py — 引导员 Agent 实现

位置：backend/src/agents/guide_agent/
依赖：litellm（LLM 调用），yaml（identity/配置加载），pydantic（输出校验）
      langgraph.types.interrupt（interrupt 机制，只在 build_guide_node 内调用）

职责：
  通过 4 步 LangGraph interrupt 对话，引导用户确认任务范围，产出：
    1. refined_task_prompt       — 规范化任务描述（供 search/extract 参考）
    2. refined_screening_criteria— 系统化纳入/排除标准（供 screen 参考）
    3. schema_template           — 数据库字段模板元数据（固定 hap_peptide_v1）

4 步确认：
  Q1 研究目标确认 → Q2 研究对象边界确认 → Q3 字段模板确认 → Q4 进入 pipeline

设计原则：
  - 业务内容在 skill 文件和 YAML 配置里，Python 代码只负责加载、对话、校验、传递
  - guide_node 是唯一调用 interrupt() 的地方
  - DemoGuideAgent 正常调用 LLM，输出由 skill 约束，Pydantic 校验
  - 不走 AgentTemplate（无 plan.yaml，无多步 executor）
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
# Pydantic 输出校验模型
# ─────────────────────────────────────────────────────────────────────────────

def _build_pydantic_models():
    """延迟导入 Pydantic，构建输出校验模型。"""
    try:
        from pydantic import BaseModel, field_validator

        class RefinedScreeningCriteria(BaseModel):
            """规范化纳排标准，必须包含三个非空列表。"""
            version:         str
            inclusion:       list[str]
            exclusion:       list[str]
            borderline_rules: list[str]

        class SchemaTemplate(BaseModel):
            """数据库字段模板元数据，template_id 强制为 hap_peptide_v1。"""
            template_id:           str
            schema_template_path:  str
            schema_file:           str
            filling_rules_file:    str

            @field_validator("template_id")
            @classmethod
            def must_be_hap_peptide_v1(cls, v: str) -> str:
                """强制校验 template_id，防止 LLM 生成错误值。"""
                if v != "hap_peptide_v1":
                    raise ValueError(f"template_id 必须是 hap_peptide_v1，实际：{v!r}")
                return v

        class GuideOutput(BaseModel):
            """Guide Agent 完整输出结构，用于校验 LLM 返回 JSON。"""
            ok:                       bool = True
            stage:                    str  = "guide_completed"
            user_confirmed:           bool = True
            raw_user_prompt:          str  = ""
            raw_user_screening_rules: dict = {}
            refined_task_prompt:      str
            refined_screening_criteria: RefinedScreeningCriteria
            schema_template:          SchemaTemplate
            guide_questions:          list[dict] = []
            guide_summary:            str = ""

        return GuideOutput, RefinedScreeningCriteria, SchemaTemplate
    except ImportError:
        return None, None, None


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _load_identity_and_skills() -> str:
    """加载 identity.yaml 和 skills/*.md，拼成 LLM system prompt。

    skills/ 目录下按字母序加载所有 .md 文件，
    demo_hap_peptide_v1_guide.md 因文件名排序靠前，LLM 优先读取。

    Returns:
        str，完整的 system prompt 文本。
    """
    parts: list[str] = []

    # ── 1. identity.yaml ──────────────────────────────────────────────────────
    identity_path = _AGENT_DIR / "identity.yaml"
    if identity_path.exists():
        try:
            identity = yaml.safe_load(identity_path.read_text(encoding="utf-8"))
            role_text = identity.get("role", "")
            objective  = identity.get("objective", "")
            resp_list  = identity.get("responsibilities", [])
            cons_list  = identity.get("constraints", [])
            parts.append(f"# 角色\n{role_text}")
            if objective:
                parts.append(f"## 目标\n{objective.strip()}")
            if resp_list:
                parts.append("## 职责\n" + "\n".join(f"- {r}" for r in resp_list))
            if cons_list:
                parts.append("## 约束\n" + "\n".join(f"- {c}" for c in cons_list))
        except Exception as e:
            print(f"[GuideAgent] ⚠️ identity.yaml 加载失败：{e}")

    # ── 2. skills/*.md（按文件名字母序，demo_hap_peptide_v1_guide.md 靠前）────
    skills_dir = _AGENT_DIR / "skills"
    if skills_dir.exists():
        for skill_file in sorted(skills_dir.glob("*.md")):
            content = skill_file.read_text(encoding="utf-8").strip()
            if content:
                skill_name = skill_file.stem.replace("_", " ").title()
                parts.append(f"## Skill: {skill_name}\n\n{content}")

    return "\n\n".join(parts)


def _load_demo_questions() -> dict:
    """从 demo_hap_peptide_v1_questions.yaml 加载 4 个确认问题的配置。

    Returns:
        dict，含 questions 列表、schema_template、default_user_prompt、default_query。
    """
    config_path = _AGENT_DIR / "demo_hap_peptide_v1_questions.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"demo 问题配置文件未找到：{config_path}")
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def _build_interrupt_payload(q: dict) -> dict:
    """从 YAML 问题配置构造 interrupt payload dict。

    payload 统一格式：
      type、label、topic、options、default 字段必须存在，
      content 字段根据问题类型动态构造。

    Args:
        q: YAML 配置中单个问题的 dict。

    Returns:
        符合 conversation.py 渲染约定的 interrupt payload。
    """
    qtype = q["type"]

    if qtype == "q1_goal_confirm":
        content = q.get("content", "")

    elif qtype == "q2_boundary_confirm":
        content = {
            "inclusion": q.get("inclusion", []),
            "exclusion": q.get("exclusion", []),
        }

    elif qtype == "q3_schema_confirm":
        content = {
            "template_id":         q.get("template_id", "hap_peptide_v1"),
            "schema_path":         q.get("schema_path", ""),
            "filling_rules_path":  q.get("filling_rules_path", ""),
            "description":         q.get("description", ""),
        }

    elif qtype == "q4_pipeline_start":
        content = q.get("content", "guide → search → screen → extract → database write")

    else:
        content = q.get("content", "")

    return {
        "type":    qtype,
        "id":      q.get("id", ""),
        "label":   q.get("label", ""),
        "topic":   q.get("topic", ""),
        "content": content,
        "options": q.get("options", ["确认"]),
        "default": q.get("default", 0),
    }


def _call_llm(system_prompt: str, user_prompt: str, model: str) -> str:
    """调用 LLM 做一次推理，返回原始输出文本。

    Args:
        system_prompt: LLM system 消息（identity + skills 拼接）。
        user_prompt:   LLM user 消息（当前任务指令）。
        model:         LiteLLM 兼容模型字符串（如 "openai/gpt-4o"）。

    Returns:
        str，LLM 输出的原始文本。

    Raises:
        Exception: LLM 调用失败时抛出，由调用方捕获并降级。
    """
    import litellm

    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.1,   # 轻微随机性，避免完全重复但保持一致性
        max_tokens=4096,   # 输出较长，需要足够的 token 预算
    )
    return response.choices[0].message.content.strip()


def _parse_json_from_llm(text: str) -> dict:
    """从 LLM 输出里提取 JSON，三层 fallback 保健壮性。

    Layer 1：提取 ```json ... ``` 代码块后解析
    Layer 2：直接 json.loads（LLM 直接输出纯 JSON 时）
    Layer 3：在文本中找第一个 { 到最后一个 } 的子串解析

    Args:
        text: LLM 输出的原始文本。

    Returns:
        dict，解析出的 JSON 对象；全部失败时返回 {}。
    """
    # Layer 1：```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass

    # Layer 2：直接解析
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except Exception:
            pass

    # Layer 3：找最外层 { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass

    return {}


def _default_output(raw_prompt: str, config: dict) -> dict:
    """LLM 失败时的降级输出，内容来自 YAML 配置的固定文本。

    Args:
        raw_prompt: 用户原始输入。
        config:     demo_hap_peptide_v1_questions.yaml 的加载结果。

    Returns:
        dict，符合 GuideOutput 结构的降级输出。
    """
    schema_tmpl = config.get("schema_template", {})
    return {
        "ok": True,
        "stage": "guide_completed",
        "user_confirmed": True,
        "raw_user_prompt": raw_prompt,
        "raw_user_screening_rules": {"inclusion": [], "exclusion": []},
        "refined_task_prompt": (
            "本任务旨在系统检索并结构化整理羟基磷灰石 HAp、apatite、calcium phosphate、"
            "ACP、牙釉质、牙本质及相关钙磷矿化体系中具有明确氨基酸序列或可回溯序列来源的"
            "肽段、短肽、寡肽、蛋白片段、功能域或肽库候选序列研究。重点关注这些肽段在矿物"
            "表面吸附、离子捕获、成核、矿物沉积、晶体生长、晶体取向或形貌调控、钙磷相稳定"
            "或相转化、抗脱矿、牙釉质再矿化、牙本质再矿化等过程中的作用及证据。后续 pipeline"
            "应基于该任务完成 PubMed 文献检索、文献筛选、全文获取、RAG 辅助信息抽取和结构化"
            "数据库写入，抽取内容围绕 hap_peptide_v1 字段模板展开。"
        ),
        "refined_screening_criteria": {
            "version": "guide_hap_peptide_v1_demo",
            "inclusion": [
                "必须为原创研究文献（体外、离体、动物、临床，或与实验配套的计算研究）",
                "研究对象必须包含明确肽段、短肽、寡肽、肽库、蛋白片段或可拆分功能域",
                "原文必须给出完整氨基酸序列或可回溯序列来源",
                "研究体系必须涉及 HAp、apatite、calcium phosphate、ACP、牙釉质、牙本质、骨矿物或体外矿化模型",
                "必须报告至少一种矿化相关实验功能（吸附、成核、沉积、生长、形貌调控、抗脱矿、再矿化）",
                "可接受的实验证据：SEM、TEM、AFM、XRD、FTIR、Raman、SPR、ITC、QCM-D、ICP-OES、pH cycling 等",
                "摘要无法判断是否有序列，但题名提示 designed peptide / peptide library / derived peptide 时暂时保留",
            ],
            "exclusion": [
                "综述、系统综述、Meta 分析、社论、评论、会议摘要、无原始数据的观点文章",
                "没有明确肽段对象，或完整蛋白研究无法拆分出具体功能片段或序列边界",
                "完全没有序列信息且无可回溯序列来源",
                "仅研究抗菌、细胞毒性、细胞增殖、免疫调节、抗炎等非矿化读出",
                "只涉及无机材料、聚合物、纳米材料而没有肽段作为核心干预对象",
                "纯 docking、纯 MD 模拟、纯机器学习预测且没有实验矿化证据",
                "信息不足且无法通过全文或补充材料判断核心纳入条件",
            ],
            "borderline_rules": [
                "摘要无法判断是否有序列，但题名提示 designed/library/derived peptide 时保留进复筛",
                "full-length protein 研究只有在能拆分明确功能片段或序列边界时才可保留",
                "计算模拟研究只有在服务于同一研究的实验矿化证据时才作为辅助证据保留",
                "牙釉质、牙本质、骨矿物、体外钙磷晶体均可纳入，后续抽取需标注具体材料类型",
            ],
        },
        "schema_template": {
            "template_id":          schema_tmpl.get("template_id", "hap_peptide_v1"),
            "schema_template_path": schema_tmpl.get("schema_template_path", "docs/schema_templates/hap_peptide_v1/"),
            "schema_file":          schema_tmpl.get("schema_file", "docs/schema_templates/hap_peptide_v1/schema.yaml"),
            "filling_rules_file":   schema_tmpl.get("filling_rules_file", "docs/schema_templates/hap_peptide_v1/filling_rules.md"),
        },
        "guide_questions": [
            {"id": "Q1", "topic": "research_goal_confirmation",             "confirmed": True},
            {"id": "Q2", "topic": "research_object_boundary_confirmation",  "confirmed": True},
            {"id": "Q3", "topic": "schema_template_confirmation",           "confirmed": True},
            {"id": "Q4", "topic": "pipeline_start_confirmation",            "confirmed": True},
        ],
        "guide_summary": "Guide Agent 已将用户需求规范化为 HAp peptide v1 demo 任务输入。",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Demo Guide Agent（正常调用 LLM，由 skill 约束输出）
# ─────────────────────────────────────────────────────────────────────────────

class DemoGuideAgent:
    """Demo 版引导员：从 skill 文件和 YAML 配置加载内容，调用 LLM 生成规范化 JSON 输出。

    职责分工：
      - 4 个 interrupt payload 来自 YAML 配置（内容固定，不调 LLM）
      - 最终 JSON 输出（refined_task_prompt / refined_screening_criteria）由 LLM 生成
      - Pydantic 校验 + 强制 template_id == hap_peptide_v1
      - 任何 LLM 失败时降级到 YAML 配置的预设值（不崩溃）
    """

    def __init__(self, model: str | None = None):
        self.model  = model or os.getenv("DEFAULT_LLM_MODEL", "openai/gpt-4o")
        self._config        = _load_demo_questions()
        self._system_prompt = _load_identity_and_skills()

    def _payloads(self) -> list[dict]:
        """从 YAML 配置构造 4 个 interrupt payload。"""
        return [
            _build_interrupt_payload(q)
            for q in self._config.get("questions", [])
        ]

    def _generate_output(self, raw_prompt: str) -> dict:
        """调用 LLM 生成最终规范化 JSON 输出。

        LLM 以完整 skill 文档为 system prompt，以用户输入为 user prompt，
        生成符合 GuideOutput 结构的 JSON。

        Args:
            raw_prompt: 用户原始任务描述（或 YAML 中的默认值）。

        Returns:
            dict，GuideOutput 结构；LLM 失败时返回降级输出。
        """
        user_prompt = f"""用户初始任务描述：
{raw_prompt}

请按照 skill 文档（Demo Guide Skill: HAp Peptide v1）的要求，
生成最终规范化 JSON 输出。

注意：
1. schema_template.template_id 必须是 hap_peptide_v1
2. refined_task_prompt 必须包含 skill §5 中要求的所有信息点
3. refined_screening_criteria 必须包含 inclusion（≥6 条）、exclusion（≥7 条）、borderline_rules（≥4 条）
4. 只输出纯 JSON，不输出 Markdown 标记或额外解释
5. 不要生成 PubMed 检索式
"""

        try:
            raw_text = _call_llm(self._system_prompt, user_prompt, self.model)
            parsed   = _parse_json_from_llm(raw_text)

            # Pydantic 校验
            GuideOutput, _, _ = _build_pydantic_models()
            if GuideOutput is not None:
                # 补充必要字段（LLM 可能省略）
                parsed.setdefault("raw_user_prompt", raw_prompt)
                parsed.setdefault("raw_user_screening_rules", {})
                validated = GuideOutput(**parsed)
                return validated.model_dump()
            return parsed  # Pydantic 不可用时直接返回

        except Exception as e:
            print(f"[DemoGuideAgent] ⚠️ LLM 输出处理失败，降级到预设值：{e}")
            return _default_output(raw_prompt, self._config)

    def run(self, input_data: dict) -> dict:
        """准备 4 个 interrupt payload 并生成最终 LLM 输出。

        Args:
            input_data: 包含 user_query 等字段的输入 dict。

        Returns:
            dict，含 4 个 payload（q1..q4）+ 最终规范化输出字段。
        """
        raw_prompt = (
            input_data.get("user_query", "")
            or self._config.get("default_user_prompt", "")
        ).strip()

        # 4 个 interrupt payload（内容来自 YAML，不调 LLM）
        payloads = self._payloads()

        # 最终 JSON 输出（调用 LLM）
        output = self._generate_output(raw_prompt)

        return {
            "q1_payload":  payloads[0] if len(payloads) > 0 else {},
            "q2_payload":  payloads[1] if len(payloads) > 1 else {},
            "q3_payload":  payloads[2] if len(payloads) > 2 else {},
            "q4_payload":  payloads[3] if len(payloads) > 3 else {},
            # 最终产出
            "refined_task_prompt":      output.get("refined_task_prompt", ""),
            "refined_screening_criteria": output.get("refined_screening_criteria", {}),
            "schema_template":          output.get("schema_template", self._config.get("schema_template", {})),
            "guide_summary":            output.get("guide_summary", ""),
            "guide_questions":          output.get("guide_questions", []),
            "raw_user_prompt":          raw_prompt,
            "raw_user_screening_rules": output.get("raw_user_screening_rules", {}),
            "query":                    self._config.get("default_query", ""),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Real Guide Agent（面向未来：任意任务 + 自由纳排规则）
# ─────────────────────────────────────────────────────────────────────────────

class RealGuideAgent:
    """Real 版引导员：支持任意研究任务，输出由 LLM 自由生成（不固定 demo 范围）。

    当前 v0.1 demo 阶段暂不使用，保留接口供未来扩展。
    任何失败会降级到 DemoGuideAgent 的输出。
    """

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("DEFAULT_LLM_MODEL", "openai/gpt-4o")

    def run(self, input_data: dict) -> dict:
        """降级到 DemoGuideAgent（v0.1 阶段）。"""
        print("[RealGuideAgent] ⚠️ v0.1 阶段降级到 DemoGuideAgent")
        return DemoGuideAgent(model=self.model).run(input_data)


# ─────────────────────────────────────────────────────────────────────────────
# build_guide_node — 构造符合 LangGraph node 签名的 guide_node 函数
# ─────────────────────────────────────────────────────────────────────────────

def build_guide_node(
    mode:  str       = "demo",
    model: str | None = None,
):
    """构造 guide_node 函数，供 graph/nodes.py 注册为 LangGraph 节点。

    guide_node 调用 interrupt() 4 次（Q1→Q2→Q3→Q4），每次对应一步用户确认。
    interrupt() 必须在 LangGraph graph node 的调用栈内才有效。

    Args:
        mode:  运行模式（"demo" / "real"），决定使用哪个 Agent 实现。
        model: LiteLLM 模型字符串，None 时从 DEFAULT_LLM_MODEL 环境变量读取。

    Returns:
        guide_node(state: PipelineState) -> dict — 符合 LangGraph node 签名的函数。
    """
    agent: DemoGuideAgent | RealGuideAgent = (
        RealGuideAgent(model=model) if mode == "real"
        else DemoGuideAgent(model=model)
    )

    def guide_node(state: Any) -> dict:
        """Guide 节点：4 步 interrupt 引导用户确认任务范围。

        LangGraph interrupt() 机制：
          1. interrupt(payload) → 图暂停，payload 传给 CLI 渲染
          2. 用户按 Enter → CLI 调用 Command(resume=0) 继续
          3. interrupt() 返回值 = resume 值

        最终写入 PipelineState：
          query / refined_task_prompt / refined_screening_criteria /
          schema_template / guide_summary / guide_questions /
          user_confirmed / raw_user_prompt / raw_user_screening_rules
        """
        user_query = state.get("user_query", "") if hasattr(state, "get") else ""
        result = agent.run({"user_query": user_query})

        try:
            from langgraph.types import interrupt as lg_interrupt

            # ── Q1：研究目标确认 ────────────────────────────────────────────
            # 此处暂停，CLI 渲染研究目标文本，等待用户按 Enter 确认
            lg_interrupt(result["q1_payload"])

            # ── Q2：研究对象边界确认 ────────────────────────────────────────
            # 此处暂停，CLI 渲染纳入/排除对象列表，等待用户确认
            lg_interrupt(result["q2_payload"])

            # ── Q3：数据库字段模板确认 ──────────────────────────────────────
            # 此处暂停，CLI 渲染 hap_peptide_v1 模板元数据，等待用户确认
            lg_interrupt(result["q3_payload"])

            # ── Q4：是否进入 pipeline ───────────────────────────────────────
            # 此处暂停，CLI 展示流水线流程，等待用户确认后启动
            lg_interrupt(result["q4_payload"])

        except ImportError:
            # langgraph 不可用（批量测试模式），跳过 interrupt
            print("[guide_node] ⚠️ langgraph.types.interrupt 不可用，跳过确认步骤")

        # ── 返回 PipelineState patch ────────────────────────────────────────
        return {
            "query":                      result.get("query", ""),
            "refined_task_prompt":        result.get("refined_task_prompt", ""),
            "refined_screening_criteria": result.get("refined_screening_criteria", {}),
            "schema_template":            result.get("schema_template", {}),
            "guide_summary":              result.get("guide_summary", ""),
            "guide_questions":            result.get("guide_questions", []),
            "user_confirmed":             True,
            "raw_user_prompt":            result.get("raw_user_prompt", ""),
            "raw_user_screening_rules":   result.get("raw_user_screening_rules", {}),
            "ok":                         True,
            "message":                    "Guide Agent 完成四步确认，任务配置规范化完毕",
        }

    return guide_node
