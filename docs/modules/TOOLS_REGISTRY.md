# Tools 注册与工具协议 README

## 定位

Tools 模块把外部能力注册给 Agent。Agent 在 config 中声明工具名，executor 通过 `get_tools(names)` 获取函数对象。

## 当前工具

```text
pubmed_search
screen_paper
download_paper
run_bio_paper_extraction_pipeline
parse_pdf_with_ragflow
retrieve_pdf_evidence
mock_*
```

## 新工具规范

```python
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class Input(BaseModel):
    query: str = Field(..., description="...")

@tool("tool_name", args_schema=Input)
def tool_name(query: str) -> dict:
    """清晰说明何时使用、参数和返回值。"""
    return {"status": "ok"}
```

然后在 `registry.py` 条件导入并注册。工具应返回结构化 dict/list，不直接写业务库。
