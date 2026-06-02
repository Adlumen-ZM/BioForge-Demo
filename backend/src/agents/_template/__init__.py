"""
_template — 新 agent 骨架模具（复制此目录起新 agent，不被任何代码 import）

开发新 agent 步骤：
  1. cp -r backend/src/agents/_template backend/src/agents/<your_agent_name>
  2. 重命名 _template → <your_agent_name>（目录名）
  3. 编辑 plan.yaml：填写 agent_name、steps（step_id/name/instruction/tools_required/success_criteria）
  4. 编辑 identity.yaml：填写 role/objective/responsibilities/constraints/output_contract
  5. 在 skills/ 下创建 .md 文件（操作指南，非函数，注入 system prompt）
  6. 在 agent.py 中更新 agent_name、model、tools 参数
  7. 在 tools/registry.py 注册本 agent 需要的 tool 函数
  8. 更新本文件的导出
"""
