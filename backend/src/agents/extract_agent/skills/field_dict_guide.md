# 字段字典使用指南

## 1. 字段字典概述

字段字典定义了论文抽取的输出规范，确保所有抽取记录的一致性和可解析性。

## 2. 主要字段说明

### 2.1 论文元数据字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| paper_id | string | 是 | 论文唯一标识符 |
| doi | string | 否 | 数字对象标识符 |
| title | string | 是 | 论文标题 |
| authors | list[string] | 是 | 作者列表 |
| journal | string | 否 | 期刊名称 |
| year | int | 是 | 发表年份 |

### 2.2 FAE 记录字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| sequence | string | 是 | 氨基酸序列 |
| length | int | 是 | 序列长度 |
| source_protein | string | 否 | 来源蛋白质 |
| mineral_type | string | 是 | 矿物类型 |
| interaction_description | string | 是 | 相互作用描述 |
| bioactivity | string | 否 | 生物活性 |

### 2.3 实验方法字段

| 字段 | 类型 | 说明 |
|------|------|------|
| methods | list[string] | 使用的表征/实验技术 |

### 2.4 结论字段

| 字段 | 类型 | 说明 |
|------|------|------|
| conclusions | string | 主要结论 |

## 3. JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["papers"],
  "properties": {
    "papers": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["title", "fae_records"],
        "properties": {
          "paper_id": {"type": "string"},
          "doi": {"type": ["string", "null"]},
          "title": {"type": "string"},
          "authors": {
            "type": "array",
            "items": {"type": "string"}
          },
          "journal": {"type": ["string", "null"]},
          "year": {
            "type": "integer",
            "minimum": 1990,
            "maximum": 2030
          },
          "fae_records": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["sequence", "interaction_description"],
              "properties": {
                "sequence": {
                  "type": "string",
                  "pattern": "^[ACDEFGHIKLMNPQRSTVWY]+$"
                },
                "length": {"type": "integer"},
                "source_protein": {"type": ["string", "null"]},
                "mineral_type": {"type": "string"},
                "interaction_description": {"type": "string"},
                "bioactivity": {"type": ["string", "null"]}
              }
            }
          },
          "methods": {
            "type": "array",
            "items": {"type": "string"}
          },
          "conclusions": {"type": "string"}
        }
      }
    }
  }
}
```

## 4. 验证规则

### 4.1 序列验证

```
有效序列：
  - 只包含标准氨基酸单字母代码
  - A, C, D, E, F, G, H, I, K, L, M, N, P, Q, R, S, T, V, W, Y

无效序列示例：
  - "AKKXRA" (X 不是标准氨基酸)
  - "AKK-ARA" (包含连字符)
  - "akkara" (小写)
```

### 4.2 矿物类型枚举

```
标准矿物类型：
  - "HAp" / "hydroxyapatite"
  - "TCP" / "tricalcium phosphate"
  - "BCP" / "biphasic calcium phosphate"
  - "CaP" / "calcium phosphate"
  - "other"
```

## 5. 错误代码

| 代码 | 说明 | 处理方式 |
|------|------|----------|
| E001 | JSON 解析失败 | 记录原始输出，标记失败 |
| E002 | 缺少必填字段 | 使用 null，继续处理 |
| E003 | 序列格式错误 | 尝试修正或标记 |
| E004 | 字段类型错误 | 尝试类型转换 |
| E005 | 校验整体失败 | 跳过该论文 |