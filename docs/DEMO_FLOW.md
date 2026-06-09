# Demo 流程与运行实例

## 1. 用户输入

示例：

```text
我想构建 HAp/牙釉质再矿化相关肽段数据库。纳入有明确肽段序列或可追溯序列来源的原创实验研究；排除综述、纯计算、无明确序列、无矿化/吸附/再矿化证据的文献。
```

## 2. Guide Agent 输出

Guide Agent 将用户输入转成：

```json
{
  "refined_task_prompt": "系统检索和抽取 HAp/牙釉质矿化相关肽段研究...",
  "refined_screening_criteria": {
    "version": "hap_peptide_v1",
    "inclusion": ["..."],
    "exclusion": ["..."],
    "borderline_rules": ["..."]
  },
  "schema_template": {
    "template_id": "hap_peptide_v1",
    "schema_template_path": "docs/schema_templates/hap_peptide_v1/schema.yaml",
    "schema_file": "schema.yaml",
    "filling_rules_file": "filling_rules.md"
  }
}
```

## 3. CLI 运行实例

```bash
python -m backend.src.cli
```

预期阶段：

```text
BioForge Banner
System Status
Session/run_id/thread_id
Q1 研究目标确认
Q2 纳排标准确认
Q3 字段模板确认
Q4 进入 pipeline
Search running/success
Screen running/success
Extract running/success
Write DB success/skipped/error
```

## 4. 每个节点做什么

### Search

- 读 `refined_task_prompt`。
- 生成 PubMed 检索式。
- 调用 `pubmed_search`。
- 去重并输出 `candidate_paper_ids/candidates`。

### Screen

- 读 `candidates` 和 `refined_screening_criteria`。
- 调用 `screen_paper`。
- 调用 `download_paper`。
- 输出 `screened_paper_ids/pdf_path/paper_key`。

### Extract

- 读 `pdf_path/schema_template`。
- 调用 RAG 工具。
- 输出 `rag_csv_dir/rag_csv_files/extraction`。

### Write DB

- 如果 `rag_csv_dir` 存在，读取五表 CSV 写入业务库。
- 如果不存在，则跳过写库并记录 skipped。

## 5. 结果检查

```bash
ls data/runs/*/run_*/trace/events.jsonl
find data/projects/hap_peptide_v1 -name '*.csv'
sqlite3 data/projects/hap_peptide_v1/db/business.sqlite '.tables'
```

## 6. Demo 成功标准

- Guide 四步可完成。
- Graph 节点顺序正确。
- Search/Screen/Extract 至少在 demo/mock 模式完成状态流转。
- Trace 文件产生。
- 业务数据库初始化成功。
- RAG 有真实依赖时可输出五表 CSV。
