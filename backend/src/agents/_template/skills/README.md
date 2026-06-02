# skills/ — 操作技能指南目录

## 什么是 Skills？

Skills 是**自然语言操作文档**（.md 文件），由 `context_builder.py` 加载并注入 executor 的 system prompt。
LLM 读取 Skills 了解「如何做」，但 Skills 本身不是函数，不能被 tool-calling 触发。

**Skills vs Tools 区别：**
| | Skills | Tools |
|---|---|---|
| 形态 | .md 文档（自然语言） | @tool 装饰的 Python 函数 |
| LLM 感知 | 注入 system prompt（读了就懂） | tool-calling 接口（调了才执行） |
| 存放位置 | `skills/` 目录下 | `backend/src/tools/` 目录下 |
| 示例 | `pubmed_query.md`（如何构建检索式） | `pubmed_search`（实际执行检索） |

## 创建 Skills 的建议

1. **一个文件对应一个操作领域**（如 `data_cleaning.md`、`quality_filter.md`）
2. **使用具体示例和代码块**，LLM 更容易理解
3. **明确输入输出格式**，减少 LLM 的猜测
4. **文件名即技能名**（`context_builder` 会以文件名为标题展示）

## 示例结构

```markdown
# <技能名称>

## 核心原则
...

## 步骤说明
...

## 示例
...

## 注意事项
...
```
