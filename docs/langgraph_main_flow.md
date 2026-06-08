# LangGraph 主流程接入说明

## 1. 主流程只注册三个业务 Agent

LangGraph 外层 pipeline 只负责业务阶段编排：

```text
START -> search -> screen -> extract -> END
```

对应代码：

- `backend/src/graph/pipeline.py`：构建 `StateGraph`
- `backend/src/graph/nodes.py`：每个 LangGraph node 的适配层
- `backend/src/graph/factory.py`：根据 `agent_name + mode` 创建业务 Agent
- `backend/src/graph/state.py`：定义跨 Agent 传递的 `PipelineState`

`template_agent` 不作为 LangGraph 节点出现。它只是业务 Agent 内部可以复用的开发模板。

## 2. graph node 和业务 Agent 的接口

每个 node 做三件事：

1. 从 `PipelineState` 读取上游字段；
2. 通过 `factory.create_agent(agent_name, mode)` 创建业务 Agent；
3. 调用 `agent.run(input_data)`，再把输出整理成新的 `PipelineState` patch。

例如：

```text
search_node(state)
  -> create_agent("search_agent", mode)
  -> agent.run({"query": ..., "run_id": ...})
  -> return {"candidate_paper_ids": ..., "search_summary": ...}
```

## 3. template_agent 的位置

`template_agent` 位于：

```text
backend/src/agents/agent_template/
```

它和外层 graph 的关系是：

```text
LangGraph node -> 业务 Agent -> 可选复用 AgentTemplate
```

所以需要对齐的是业务 Agent 的输入输出字段，而不是把 `template_agent` 放进 graph 主流程。

## 4. 当前 mock 流程

当前默认 `mode="mock"`，可以离线跑通：

```text
search_agent  -> 输出 candidate_paper_ids / candidates / search_summary
screen_agent  -> 输出 screened_paper_ids / selected_paper / screen_summary
extract_agent -> 输出 extracted_record_ids / extraction / extract_summary
```

`run_id` 会在 pipeline 开始时生成，并传给每个业务 Agent，方便后续 trace 串联。

## 5. 后续需要继续对齐

- `RealSearchAgent` 已经可以调用 `AgentTemplate`
- `RealScreenAgent` 和 `RealExtractAgent` 目前还是占位
- `AgentTemplate.output_adapter` 后续需要确保能稳定输出 graph 需要的字段
- 真正接数据库时，State 里仍然只传轻量 ID 和摘要，完整记录写入 `db_access`
