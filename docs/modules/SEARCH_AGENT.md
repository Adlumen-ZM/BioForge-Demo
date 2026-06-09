# Search Agent README

## 定位

Search Agent 将研究目标转化为 PubMed 检索式，调用 PubMed 工具，合并去重候选文献。

## 文件

```text
backend/src/agents/search_agent/agent.py
backend/src/agents/search_agent/identity.yaml
backend/src/agents/search_agent/plan.yaml
backend/src/agents/search_agent/skills/pubmed_query.md
backend/src/agents/search_agent/skills/dedup_strategy.md
backend/src/tools/search/pubmed_search.py
```

## 技术选型

AgentTemplate + LiteLLM + LangChain tool + Biopython Entrez。

## Plan

1. `task_understanding`：理解核心实体、关系和实验体系。
2. `query_build`：生成精准、高召回、序列设计、牙釉质专项等 PubMed query。
3. `search_execute`：调用 `pubmed_search`。
4. `dedup_filter`：PMID/DOI/标题去重。

## 输出

```python
candidate_paper_ids: list[str]
candidates: list[dict]
queries: list[dict]
search_summary: str
```

## 改进

未来可改成循环式 query refinement：根据结果数量和相关性自动改写 query。
