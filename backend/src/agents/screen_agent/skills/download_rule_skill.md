---
skill_id: download_paper_skill
version: v1
applies_to_tools: [download_paper]
agent: ScreenAgent
---

## 目的

指导 LLM 正确使用 `download_paper` 工具，将筛选后的文献 PDF 全文及补充材料批量下载到本地。

## 规则

- **前置依赖**：必须在 `screen_papers` 步骤完成、获得 `screened_paper_ids` 后才能调用。
- **批量传入**：将全部 `screened_paper_ids` 一次性传入。工具内部负责分批（每批 ≤ 20 个 PMID，适配 NCBI E-utilities 频率限制），LLM 不应自行循环调用。
- **输入校验**：传入的 PMID 必须是纯数字字符串（如 "34265844"），不含 "PMID" 前缀。
- **补充材料**：工具会自动检测并下载论文的补充材料（Supplementary Materials），无需单独指定附件链接。
- **重试策略**：工具返回结果后，若 `fail_count > 0`，仅将 `failed_pmids` 作为参数再次调用（工具内部会跳过付费墙等不可重试的错误类型）。

## 重试流程

```
第 1 次调用：传入全部 screened_paper_ids
    ↓
检查返回的 failed_pmids
    ↓  (若有失败且可重试)
第 2 次调用：仅传入 failed_pmids 中可重试的 PMID
    ↓  (若仍有失败)
第 3 次调用：同上，最后一轮
    ↓
最终输出 download_status，含所有轮次的汇总
```

以下情况不应重试：
- 付费墙限制（论文需付费或机构订阅才能获取）
- 论文已撤稿
- PMID 无效或已从 PubMed 删除

## 禁止

- **严禁虚构**：不得传入任何虚构的 PMID。
- **严禁传非标参数**：不得将论文标题、DOI 或作者名传入 `pmids` 列表。
- **严禁循环调用**：不得在 LLM 侧循环逐篇调用 download_paper。批量传入，工具内部做分批和频率控制。

## 输出说明

工具返回格式：

```json
{
  "download_status": {
    "total": 50,
    "success_count": 42,
    "fail_count": 8,
    "supplementary_count": 15,
    "total_attempts": 2,
    "failed_pmids": [
      {"pmid": "12345678", "reason": "付费墙限制", "retryable": false, "attempts": 1},
      {"pmid": "87654321", "reason": "超时", "retryable": true, "attempts": 2}
    ]
  }
}
```
