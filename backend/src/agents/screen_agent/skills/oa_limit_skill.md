---
skill_id: oa_limit_skill
version: v2
applies_to_steps: [screen_papers, download_papers]
agent: ScreenAgent
---

## 筛选数量上限与 OA 优先原则

### 核心约束（必须遵守）

1. **最终筛选结果 5~10 篇**：`screened_paper_ids` 列表长度目标 5~10 篇，最多 10 篇。
   若 BM25 相关度筛选后超过 10 篇，按相关度从高到低保留前 10 篇。
   若相关文献不足 5 篇，返回实际数量（不得降低相关性标准凑数）。

2. **优先选择 Open Access（OA）文献**：
   - 免费全文可下载的文献优先入选（PubMed Central PMC 全文、作者开放版本等）
   - 付费墙（Elsevier、Wiley、Springer 等非开放权限）文献，在有足够 OA 文献的情况下排后
   - 对所有 screened_paper_ids 均尝试下载 PDF，成功下载几篇算几篇

3. **下载失败不影响筛选结果**：
   `screened_paper_ids` 是筛选通过的文献，与是否能成功下载 PDF 无关。
   下载失败时记录原因并继续尝试下一篇，不中止流程。

### 执行要点

- **screen_papers 步骤**：调用 `screen_paper` 工具后，若结果 > 10 篇，截取前 10 篇（按相关度）
- **download_papers 步骤**：对每篇 screened_paper_ids 逐篇调用 download_paper，失败则继续
- **不得为凑数量而降低相关性标准**：宁可返回 3 篇高相关，也不强行凑到 10 篇

### 输出格式提醒

```json
{
  "screened_paper_ids": ["pmid1", "pmid2", "..."],
  "screened_count": 8,
  "excluded": [...],
  "screen_summary": "共筛选 N 篇候选，相关 M 篇（OA 优先，取前 10 篇），下载成功 K 篇"
}
```
