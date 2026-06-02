# Tool 开发协议

## 什么是 Tool？

Tool 是可被 LLM 通过 tool-calling 触发的 Python 函数，用 `@tool` 装饰器（来自 `langchain_core.tools`）定义。
executor 通过 `tools.registry.get_tools(names)` 按名称加载，注入 `create_react_agent`。

**Tools vs Skills 区别：**

| | Tools | Skills |
|---|---|---|
| 形态 | `@tool` 装饰的 Python 函数 | `.md` 自然语言文档 |
| LLM 感知 | tool-calling 接口（LLM 主动调用） | 注入 system prompt（LLM 读取理解） |
| 存放位置 | `backend/src/tools/` | `backend/src/agents/<name>/skills/` |
| 示例 | `pubmed_search`（执行网络检索） | `pubmed_query.md`（教 LLM 如何构建检索式） |

## 目录结构

```
backend/src/tools/
├── registry.py          ← 统一注册表，get_tools(names) 入口
├── shared/              ← 跨 agent 共享工具
│   ├── pubmed_search.py ← PubMed 检索（v0.1 为 stub）
│   └── ...
└── <agent_name>/        ← 某 agent 专用工具（如有）
    └── ...
```

## 实现新 Tool 的步骤

1. 在 `backend/src/tools/shared/` 或 `backend/src/tools/<agent_name>/` 创建 `.py` 文件。

2. 用 `@tool` 装饰器定义函数：

```python
from langchain_core.tools import tool

@tool
def my_tool(param_a: str, param_b: int = 10) -> dict:
    """工具功能描述（LLM 会读取此 docstring 决定何时调用）。

    Args:
        param_a: 参数说明。
        param_b: 参数说明，默认 10。

    Returns:
        dict，包含结果字段。
    """
    # 实现逻辑
    return {"result": ..., "count": ...}
```

3. 在 `tools/registry.py` 的 `_REGISTRY` dict 中注册：

```python
from backend.src.tools.shared.my_tool import my_tool
_REGISTRY["my_tool"] = my_tool
```

4. 在对应 agent 的 `agent.py` 的 `config.tools` 列表中声明：

```python
config = AgentTemplateConfig(
    ...
    tools=["my_tool", "pubmed_search"],
)
```

5. 在 `plan.yaml` 的对应 step 的 `tools_required` 中声明（executor 按此列表过滤）：

```yaml
- step_id: "my_step"
  tools_required:
    - "my_tool"
```

## 重要约束

- **DB 写入绝不作为 Tool 暴露给 LLM**：写库由 graph 层在固定位置触发，LLM 完全不感知。
- **Tool 函数要幂等**：同一参数多次调用结果一致（或有明确的去重策略）。
- **Tool docstring 要完整**：LLM 依赖 docstring 决定何时、如何调用 tool。
- **返回 dict 而非字符串**：executor 按 JSON 解析 tool 返回值。

## 当前已注册的 Tools（v0.1 stub）

| 名称 | 说明 | 状态 |
|---|---|---|
| `pubmed_search` | PubMed 文献检索 | stub（返回假数据） |
| `screen_paper` | 单篇文献相关性筛选 | stub（返回假数据） |
