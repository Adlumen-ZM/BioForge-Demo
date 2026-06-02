# PubMed 检索式构建指南

## 核心检索策略

构建 HAp/磷酸钙/矿化领域文献检索式时，遵循以下原则：

### 1. 核心材料概念同义词组

```
(hydroxyapatite OR "hydroxy apatite" OR HAp OR HA OR 
 "calcium phosphate" OR "tricalcium phosphate" OR TCP OR 
 "biphasic calcium phosphate" OR BCP OR
 "calcium hydroxyapatite" OR "calcium phosphate cement")
```

### 2. 调控因子概念同义词组

```
(peptide OR polypeptide OR protein OR "amino acid" OR 
 "biomimetic" OR "self-assembling" OR "self-assembly" OR
 "mineralization peptide" OR "crystal growth" OR nucleation)
```

### 3. 生物系统/应用场景同义词组

```
(bone OR dentin OR enamel OR dental OR 
 "bone regeneration" OR "bone repair" OR osseointegration OR
 "biomineralization" OR "bioinspired" OR scaffold)
```

### 4. 检索式组合模板

```
(<材料概念组>) AND (<调控因子概念组>) AND (<生物系统组>)
```

## PubMed 检索语法要点

- **短语检索**：用双引号括起（如 `"calcium phosphate"`）
- **字段限定**：Title/Abstract 可用 `[tiab]`；MeSH 术语可用 `[MeSH]`
- **布尔运算符**：AND、OR、NOT 必须大写
- **括号分组**：同义词组必须加括号，避免逻辑歧义
- **日期过滤**：可加 `AND 2010:2024[dp]` 限制发表年份

## 常见问题

- **检索量过少**：放宽 AND 连接，改为两两组合
- **检索量过多（>500）**：增加字段限定（`[tiab]` 代替全文检索）
- **相关性低**：检查同义词是否偏离主题，考虑加入 NOT 排除无关概念
