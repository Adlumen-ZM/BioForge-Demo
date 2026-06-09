# Guide Agent README

## 定位

Guide Agent 把用户输入转成 pipeline 可执行的 `refined_task_prompt`、`refined_screening_criteria` 和 `schema_template`。它不走 AgentTemplate，而是使用 LangGraph `interrupt()` 做人机确认。

## 文件

```text
agent.py
identity.yaml
demo_hap_peptide_v1_questions.yaml
skills/*.md
```

## 流程

```text
加载 identity + skills + demo questions → Q1 任务确认 → Q2 纳排确认 → Q3 schema 确认 → Q4 pipeline 确认 → LLM 生成 GuideOutput → Pydantic 校验 → 返回 state patch
```

## 输出

```python
raw_user_prompt
raw_user_screening_rules
refined_task_prompt
refined_screening_criteria
schema_template
guide_questions
guide_summary
user_confirmed
```

## 扩展

后续可以允许用户编辑 Guide 输出、选择不同 schema 模板、将 Guide 输出保存为项目配置。
