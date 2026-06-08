"""
graph_integration.py — ExtractAgent Graph 层集成示例

展示如何将 extract_agent 集成到 LangGraph StateGraph 工作流中。

流程：
  search_agent → extract_agent → classification_agent

使用方式：
  from backend.src.agents.extract_agent.graph_integration import create_extract_workflow
  app = create_extract_workflow()
  result = app.invoke({"query": "HAp biomineralization"})
"""

from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from backend.src.agents.search_agent.agent import create_search_agent
from backend.src.agents.extract_agent.agent import create_extract_agent


# ─────────────────────────────────────────────
# 1. 定义 PipelineState
# ─────────────────────────────────────────────

class WorkflowState(TypedDict):
    """简化的 workflow 状态"""
    query: str
    candidate_paper_ids: list[str]
    extracted_papers: list[dict]
    workflow_summary: str


# ─────────────────────────────────────────────
# 2. 定义节点函数
# ─────────────────────────────────────────────

def search_node(state: WorkflowState) -> WorkflowState:
    """搜索节点：调用 search_agent"""
    agent = create_search_agent()
    
    result = agent.run(
        pipeline_state={"query": state["query"]},
    )
    
    return {
        **state,
        "candidate_paper_ids": result.final_output.get("candidate_paper_ids", []),
    }


def extract_node(state: WorkflowState) -> WorkflowState:
    """抽取节点：调用 extract_agent"""
    agent = create_extract_agent()
    
    # 准备输入：candidate_paper_ids 转为 paper_texts 格式
    # 注：实际使用时需要先获取 PDF 文本，这里简化处理
    pipeline_input = {
        "candidate_paper_ids": state["candidate_paper_ids"],
    }
    
    result = agent.run(pipeline_state=pipeline_input)
    
    return {
        **state,
        "extracted_papers": result.final_output.get("papers", []),
    }


# ─────────────────────────────────────────────
# 3. 构建 StateGraph
# ─────────────────────────────────────────────

def create_extract_workflow():
    """创建 extract_agent 工作流（示例，未连接真实数据源）"""
    
    workflow = StateGraph(WorkflowState)
    
    # 添加节点
    workflow.add_node("search", search_node)
    workflow.add_node("extract", extract_node)
    
    # 定义边
    workflow.add_edge(START, "search")
    workflow.add_edge("search", "extract")
    workflow.add_edge("extract", END)
    
    return workflow.compile()


# ─────────────────────────────────────────────
# 4. 执行示例
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # 创建工作流
    app = create_extract_workflow()
    
    # 执行
    result = app.invoke({
        "query": "HAp peptide biomineralization",
        "candidate_paper_ids": [],
        "extracted_papers": [],
        "workflow_summary": "",
    })
    
    print("=" * 50)
    print("工作流执行结果")
    print("=" * 50)
    print(f"查询: {result['query']}")
    print(f"候选文献数: {len(result['candidate_paper_ids'])}")
    print(f"抽取记录数: {len(result['extracted_papers'])}")
