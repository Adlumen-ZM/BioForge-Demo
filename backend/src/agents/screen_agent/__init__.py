"""
screen_agent — 生物医学文献筛选与获取 Agent

职责：接收 search_agent 产出的候选文献元数据列表，根据研究目标构造筛选标准，
      调用 screen_paper 工具判断每篇文献的相关性，产出精选 PMID 列表，
      并下载论文全文 PDF 及补充材料。

流程：screen_papers（相关性筛选）→ download_papers（批量下载 + 失败重试）

对外暴露：
  - MockScreenAgent  ：轻量 mock，供 graph 层快速集成测试
  - RealScreenAgent  ：真实实现占位（待 graph 层集成后替换）
  - create_screen_agent()：基于 AgentTemplate 的正式实现（Plan-and-Execute + ReAct）
"""

from .agent import MockScreenAgent, RealScreenAgent, create_screen_agent

__all__ = ["MockScreenAgent", "RealScreenAgent", "create_screen_agent"]
