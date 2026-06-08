---
skill_id: download_paper_skill
version: v2
applies_to_tools: [download_paper]
agent: ScreenAgent
---

## 目的

指导 LLM 正确使用 `download_paper` 工具，为每篇筛选后的文献逐篇下载 PDF 并生成文件资产。

## 接口说明

`download_paper` 每次只处理**一篇**文献，参数为：

| 参数 | 类型 | 说明 |
|------|------|------|
| `pmid` | str \| None | PubMed ID（如 "34265844"），优先使用 |
| `doi` | str \| None | 文献 DOI，pmid 不可用时使用 |
| `title` | str \| None | 文献标题，pmid/doi 均不可用时作为唯一键种子 |
| `extraction_profile` | str | 项目配置名（默认 "hap_peptide_v1"，通常不需修改） |
| `run_id` | str \| None | 当前 run_id，用于 manifest 追溯 |
| `force_redownload` | bool | True 时即使文件已存在也重新下载（默认 False） |

**至少提供 pmid、doi、title 之一，优先使用 pmid。**

## 返回字段

```json
{
  "status": "ok",
  "paper_key": "9f4c2a0d7b8e1c3a",
  "pdf_path": "/app/data/projects/hap_peptide_v1/papers/9f4c2a0d7b8e1c3a/raw/source.pdf",
  "download_status": "downloaded",
  "file_sha256": "abc123...",
  "file_size_bytes": 2048000,
  "source_url": "https://...",
  "message": "下载成功（2000 KB）"
}
```

`download_status` 取值：
- `downloaded`：本次下载成功
- `already_exists`：文件已存在，跳过
- `failed`：下载失败（不可重试或网络问题）

## 调用规则

- **逐篇调用**：对每篇 `screened_paper_ids` 中的 PMID 依次调用一次。
- **传入 run_id**：将 pipeline 的 run_id 传入 `run_id` 参数，写入 manifest 用于追溯。
- **失败不报错**：`download_status == "failed"` 时工具仍返回正常 JSON，不抛异常。
  继续处理下一篇，记录失败列表即可；后续步骤（extract）对失败文献自动跳过。
- **重试策略**：`failed` 的文献可重试一次（最多 1 轮），以下情况不重试：
  - 付费墙（message 中含"付费墙"）
  - PMID 无效
  - 已撤稿

## 禁止

- **严禁虚构**：不得传入任何虚构的 PMID 或 DOI。
- **严禁批量传参**：`download_paper` 只接受单篇，不接受列表参数。

## 汇总输出示例

完成所有文献下载后，将结果汇总为 step 输出：

```json
{
  "download_results": [
    {"pmid": "34265844", "paper_key": "9f4c2a0d", "download_status": "downloaded"},
    {"pmid": "38360817", "paper_key": "a1b2c3d4", "download_status": "failed", "message": "付费墙限制"}
  ],
  "download_summary": "共下载 2 篇，成功 1 篇，失败 1 篇（付费墙）。"
}
```
