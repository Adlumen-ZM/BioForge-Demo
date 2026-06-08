# LLM 信息抽取指南

## 1. 抽取目标

从生物医学论文 PDF 文本中抽取结构化信息，重点关注：

### 1.1 FAE 肽段信息

FAE（Functional Amino Acid Ensemble）是具有生物矿化功能的氨基酸集合。

```
关键字段：
- sequence: 肽段序列（标准氨基酸单字母缩写）
- length: 序列长度
- source_protein: 来源蛋白质
- mineral_type: 矿物类型（HAp、磷酸钙、TCP 等）
- interaction_description: 与矿物的相互作用描述
- bioactivity: 生物活性（成骨、抗菌、血管生成等）
```

### 1.2 标准氨基酸列表

```
A: Alanine
R: Arginine
N: Asparagine
D: Aspartic acid
C: Cysteine
E: Glutamic acid
Q: Glutamine
G: Glycine
H: Histidine
I: Isoleucine
L: Leucine
K: Lysine
M: Methionine
F: Phenylalanine
P: Proline
S: Serine
T: Threonine
W: Tryptophan
Y: Tyrosine
V: Valine
```

## 2. 论文结构识别

### 2.1 关键章节

```
I. 摘要 (Abstract)
   - 论文核心发现
   - 主要结论

II. 引言 (Introduction)
   - 研究背景
   - 研究目的

III. 材料与方法 (Materials and Methods)
   - 肽段合成方法
   - 矿化实验设计
   - 表征技术

IV. 结果 (Results)
   - 肽段表征数据
   - 矿化产物分析
   - 生物活性测试结果

V. 讨论 (Discussion)
   - 机制解释
   - 创新点
```

### 2.2 关键词识别

```
FAE 相关：
- "hydroxyapatite" / "HAp" / "HA"
- "calcium phosphate" / "CaP"
- "biomineralization"
- "self-assembled" / "self-assembly"
- "peptide" / "amino acid"
- "crystal growth" / "nucleation"

实验方法：
- "TEM" / "SEM" / "XRD" / "FTIR" / "Raman"
- "circular dichroism" / "CD"
- "MTT" / "ALP" / "cell viability"

生物活性：
- "osteogenic" / "成骨"
- "antibacterial" / "抗菌"
- "angiogenic" / "血管生成"
- "biomineralization" / "生物矿化"
```

## 3. 抽取策略

### 3.1 分层抽取

```
第一步：识别 FAE 相关内容
   - 扫描关键词
   - 定位相关段落

第二步：提取肽段序列
   - 从文本中识别氨基酸序列模式
   - 验证序列有效性

第三步：提取上下文信息
   - 来源蛋白质
   - 实验条件
   - 相互作用描述

第四步：构建完整记录
   - 填充所有字段
   - 处理缺失数据（使用 null）
```

### 3.2 序列识别模式

```
常见模式：
- "sequence: AKKARA"
- "peptide: AKKARA"
- "amino acid sequence: A-K-K-A-R-A"
- "peptide sequence (A)K(4)A(6)R(8)A"

注意事项：
- 注意大小写统一（大写）
- 排除非标准氨基酸
- 处理修饰符号（如 pS, pY for phosphorylated）
```

## 4. 质量控制

### 4.1 必填字段检查

| 字段 | 要求 |
|------|------|
| title | 必须有 |
| fae_records | 至少有一条记录 |
| fae_records[].sequence | 必须有且有效 |
| fae_records[].interaction_description | 必须有 |

### 4.2 数据合理性验证

```
sequence:
  - 只包含 20 种标准氨基酸字母
  - 长度 3-50 个氨基酸（常见范围）

year:
  - 1990 ≤ year ≤ 当前年份

mineral_type:
  - 必须是已知的矿物类型
```

## 5. 输出格式

### 5.1 JSON 结构

```json
{
  "papers": [
    {
      "paper_id": "PAPER_001",
      "doi": "10.1234/example",
      "title": "Example Paper Title",
      "authors": ["Author A", "Author B"],
      "journal": "Nature Materials",
      "year": 2023,
      "fae_records": [
        {
          "sequence": "AKKARA",
          "length": 6,
          "source_protein": "amelogenin",
          "mineral_type": "HAp",
          "interaction_description": "Promotes HAp nucleation...",
          "bioactivity": "Osteogenic differentiation"
        }
      ],
      "methods": ["TEM", "XRD", "CD"],
      "conclusions": "The peptide AKKARA demonstrates..."
    }
  ]
}
```

### 5.2 错误处理

```
缺失字段：
  - 使用 null，不要臆造数据

解析失败：
  - 记录错误信息
  - 跳过该论文继续处理其他论文

部分成功：
  - 尽可能提取有效信息
  - 标记不确定的字段
```

## 6. 示例

### 输入文本片段

```
The self-assembling peptide AKKARA (Ac-AKKARA-NH2) was designed based on 
the C-terminal of amelogenin. This hexapeptide forms β-sheet structures 
in solution and promotes hydroxyapatite (HAp) nucleation during 
biomineralization. Circular dichroism spectra confirmed the secondary 
structure formation. TEM images showed oriented HAp crystal growth 
along the peptide fibers.
```

### 期望输出

```json
{
  "sequence": "AKKARA",
  "length": 6,
  "source_protein": "amelogenin (C-terminal)",
  "mineral_type": "HAp",
  "interaction_description": "Promotes HAp nucleation during biomineralization; oriented crystal growth along peptide fibers",
  "bioactivity": "Self-assembling β-sheet formation",
  "methods": ["CD", "TEM"]
}
```