# Graph 编排模块 README

## 定位

Graph 模块是 BioForge 的外层状态机，负责节点顺序、状态传递和错误传播。

## 文件

```text
backend/src/graph/state.py      # PipelineState
backend/src/graph/pipeline.py   # build_graph()
backend/src/graph/nodes.py      # node functions
backend/src/graph/factory.py    # create_agent()
```

## 技术选型

- LangGraph `StateGraph`：构建有状态流程图。
- `TypedDict`：定义跨节点状态。
- checkpointer：Guide interrupt/resume 必需，CLI 中用 `MemorySaver()`。

## 节点顺序

```text
START → guide → init_business_db → search → screen → extract → write_rag_csv_to_db → END
```

## 关键接口

```python
from backend.src.graph.pipeline import build_graph
graph = build_graph(mode="demo", checkpointer=MemorySaver())
```

## 状态字段

Guide 写入 `refined_task_prompt/refined_screening_criteria/schema_template`；Search 写入 `candidate_paper_ids/candidates`；Screen 写入 `screened_paper_ids/pdf_path/paper_key`；Extract 写入 `rag_csv_dir/rag_csv_files/extraction`；Write DB 写入 `db_write_result`。

## 扩展规范

新增节点时，先在 `PipelineState` 增加字段，再在 `nodes.py` 写 node，返回 patch，不覆盖全量 state；最后在 `pipeline.py` 加 node 和 edge，并更新 CLI 进度展示。
