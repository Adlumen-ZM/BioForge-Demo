# Screening Agent README

## 定位

Screen Agent 根据纳排规则筛选 Search 候选文献，并下载或定位 PDF。

## 文件

```text
backend/src/agents/screen_agent/plan.yaml
backend/src/agents/screen_agent/skills/*.md
backend/src/tools/screen/screen_paper.py
backend/src/tools/screen/download_paper.py
backend/src/tools/screen/download_paper_mock.py
```

## Plan

1. `screen_papers`：调用 `screen_paper`，输出入选文献和排除理由。
2. `download_papers`：调用 `download_paper`，输出 `paper_key/pdf_path/download_status`。

## 输出

```python
screened_paper_ids
selected_paper
paper_key
pdf_path
download_status
file_sha256
download_results
screen_summary
```

## demo/real

`GRAPH_AGENT_MODE=real` 使用真实下载，其余模式默认 mock，保证演示稳定。
