# PubMed 检索式构建指南（hap_peptide_v1 专用）

## 研究背景

本检索任务聚焦于 **HAp / 磷酸钙矿化领域的功能性肽段**：
- 与羟基磷灰石（HAp）、磷酸钙（CaP）、牙釉质或骨矿物结合的肽段
- 参与生物矿化 / 仿生矿化的多肽或蛋白质片段
- 具有明确氨基酸序列的矿化肽（通过合理设计或噬菌体展示筛选得到）

---

## 五条标准检索式模板

### q1_precise（高精准）
目标：命中核心文献，假阳性少。

```
(hydroxyapatite[tiab] OR "HAp"[tiab] OR "calcium phosphate"[tiab]) 
AND (peptide[tiab] OR polypeptide[tiab]) 
AND (adsorption[tiab] OR binding[tiab] OR affinity[tiab]) 
AND (sequence[tiab] OR "amino acid sequence"[tiab])
```

### q2_recall（高召回）
目标：扩大命中范围，覆盖"矿化肽"同义词。

```
(hydroxyapatite OR "calcium phosphate" OR "calcium apatite" 
 OR biomineralization OR remineralization OR "dental mineralization") 
AND (peptide OR protein fragment OR biomimetic OR "self-assembling peptide" 
     OR "mineralizing peptide" OR "crystal growth peptide")
```

### q3_sequence（序列设计专项）
目标：命中通过序列设计、噬菌体展示、从头设计筛选的矿化肽。

```
("phage display"[tiab] OR "rational design"[tiab] OR "de novo"[tiab] 
 OR "combinatorial peptide"[tiab]) 
AND (hydroxyapatite[tiab] OR "calcium phosphate"[tiab] OR 
     biomineralization[tiab] OR apatite[tiab]) 
AND (peptide[tiab] OR sequence[tiab])
```

### q4_enamel（牙釉质 / 牙本质专项）
目标：命中牙科矿化相关肽段文献。

```
(enamel[tiab] OR dentin[tiab] OR "dental enamel"[tiab] OR 
 "enamel remineralization"[tiab] OR "dentin remineralization"[tiab]) 
AND (peptide[tiab] OR protein[tiab] OR amelogenin[tiab] OR 
     "amelogenin-derived"[tiab] OR "enamel matrix protein"[tiab])
```

### q5_broad（宽泛备用，召回量不足时使用）
目标：兜底检索，覆盖领域相关长尾文献。

```
(hydroxyapatite OR apatite OR "calcium phosphate") 
AND (peptide OR amino acid) 
AND (mineralization OR biomineralization OR crystal OR scaffold OR coating)
AND 2010:2025[dp]
```

---

## PubMed 语法要点

| 语法 | 说明 | 示例 |
|------|------|------|
| `[tiab]` | 仅搜索 Title/Abstract | `peptide[tiab]` |
| `[MeSH]` | MeSH 主题词 | `"Hydroxyapatites"[MeSH]` |
| `[dp]` | 发表年份范围 | `2010:2025[dp]` |
| `"短语"` | 精确短语匹配 | `"calcium phosphate"` |
| `OR` | 同义词扩展（必须大写） | `HAp OR hydroxyapatite` |
| `AND` | 概念交叉（必须大写） | `peptide AND binding` |
| `NOT` | 排除概念（必须大写） | `NOT review[pt]` |

---

## 构建原则

1. **同义词全覆盖**：HAp = hydroxyapatite = HA = calcium phosphate = apatite
2. **肽段同义词**：peptide = polypeptide = protein fragment = biomimetic peptide = binding peptide
3. **功能同义词**：adsorption = binding = affinity = interaction = recognition
4. **不要过度限定**：初始检索不加年份限制；在召回量 > 500 时才加 `[tiab]` 或年份过滤
5. **每条检索式独立**：q1~q5 各自独立调用 pubmed_search，不合并为一条

---

## 常见问题处理

| 问题 | 处理方法 |
|------|---------|
| 检索量 < 10 | 切换到 q2_recall 或 q5_broad，放宽同义词 |
| 检索量 > 500 | 在 q1_precise 上加 `[tiab]` 或年份限制 |
| 大量综述/非实验文献 | 加 NOT `review[pt]` NOT `meta-analysis[pt]` |
| 工具返回 `_stub: true` | pubmed_search 真实实现未加载；检查 NCBI_EMAIL 环境变量 |
