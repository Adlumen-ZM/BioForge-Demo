# Demo 输出脚本（严格指令）
# 所属：backend/src/agents/guide_agent/skills/demo_script.md
# 用途：约束 Demo 模式下 guide_agent 的三步固定输出格式，LLM 必须严格遵守

---

## 重要说明

这是 **Demo 模式** 的约束文件。你必须严格按照以下三步格式输出，不得偏离。
每步先输出思考过程，再输出严格格式的 JSON，**JSON 之外不加任何内容**，**不加 markdown 代码块**。

---

## 步骤一：生成任务描述

**触发时机**：用户提供了研究诉求（user_query）后，生成第一步产出。

**输出格式**：

先输出思考过程：
```
<think>
分析用户诉求：[简要分析]
确定研究方向：[研究方向]
任务描述要点：[3-5个要点]
</think>
```

然后严格输出以下 JSON（不加代码块标记，直接输出花括号）：
```
{"task_description": "在此填入3-5句话的自然语言任务描述，说明研究目标、关注的肽段类型、涉及的材料体系（HAp/磷酸钙/矿化相关）和数据类型（in vitro/in vivo等）。"}
```

**关键要求**：
- task_description 必须包含：研究对象（肽段类型）+ 材料体系（HAp等）+ 数据要求
- 字数控制在3-5句话，约80-150字
- 只输出这一个 JSON，不加其他文字

---

## 步骤二：生成数据库字段模板

**触发时机**：任务描述已确认，生成第二步产出。

**输出格式**：

先输出思考过程：
```
<think>
基于任务描述，需要抽取的核心字段：
- 文献元数据字段：[列举]
- 实体字段：[列举]
- 功能/证据字段：[列举]
</think>
```

然后严格输出以下 JSON（字段从 schema_template.md 中选取最相关的子集）：
```
{"db_schema": {"字段名": {"type": "数据类型", "description": "中文说明", "example": "示例值"}, ...}}
```

**关键要求**：
- 必须包含至少以下核心字段：paper_id, doi, title, entity_name_normalized, sequence_raw, interaction_target, summary_functions, evidence_overall_level
- 每个字段必须有 type、description、example 三个子字段
- 只输出这一个 JSON，不加其他文字

---

## 步骤三：生成文献准入/排除标准

**触发时机**：字段模板已确认，生成第三步产出。

**输出格式**：

先输出思考过程：
```
<think>
基于任务描述和字段模板，准入标准应关注：[分析]
需要排除的文献类型：[分析]
</think>
```

然后严格输出以下 JSON：
```
{"inclusion_criteria": {"inclusion": ["准入标准1", "准入标准2", ...], "exclusion": ["排除标准1", "排除标准2", ...]}}
```

**关键要求**：
- inclusion 列表：5-8条准入标准，每条一句话
- exclusion 列表：4-6条排除标准，每条一句话
- 标准内容参考 criteria_template.md，根据具体任务适当调整
- 只输出这一个 JSON，不加其他文字

---

## 严格禁止

- ❌ 不得在 JSON 之前或之后添加额外文字（如"好的，以下是..."）
- ❌ 不得使用 markdown 代码块（不加 ``` 标记）
- ❌ 不得改变 JSON 的顶层 key 名称（task_description / db_schema / inclusion_criteria）
- ❌ 不得合并或拆分三步（每步独立输出，等待确认后再输出下一步）
