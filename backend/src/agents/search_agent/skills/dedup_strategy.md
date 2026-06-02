# 文献去重策略指南

## 去重范围（当前阶段）

Search Agent 阶段的去重仅做 **ID 级去重**：
- 相同 PubMed ID 只保留一条
- 不跨数据库做标题/摘要相似度去重（由 Screen Agent 负责语义筛选）

## 去重步骤

1. 收集所有 candidate_ids（list[str]）
2. 转换为集合（set）自动去重
3. 转回有序列表（sort 保证结果可复现）
4. 记录去重前后数量

## 输出格式要求

```json
{
  "candidate_paper_ids": ["PMID12345678", "PMID87654321", ...],
  "dedup_stats": {
    "before_dedup": 150,
    "after_dedup": 143,
    "removed_duplicates": 7
  }
}
```

## 注意事项

- `candidate_paper_ids` 为最终输出的候选列表，供 Screen Agent 使用
- 去重后数量不得为 0（若为 0，说明检索步骤有问题，应标记 step 失败）
- 保持 ID 格式一致（统一不带前缀，如 `"12345678"` 而非 `"PMID12345678"`）
