import json
import os

# field_dict_prompt.json 与本文件同目录
_FIELD_DICT_PATH = os.path.join(os.path.dirname(__file__), 'field_dict_prompt.json')

# Prompt 版本号（修改 System Prompt 内容时必须同步更新）
PROMPT_VERSION = 'v0.1.0'
# 字段字典版本号（修改 field_dict_prompt.json 时必须同步更新）
SCHEMA_VERSION = 'v0.1'


def build_system_prompt() -> str:
    """构建 System Prompt，嵌入字段字典 JSON 和抽取指令。

    System Prompt 包含：
    1. 任务描述（角色、目标、研究背景）
    2. 输出格式规范（JSON 结构要求）
    3. 字段定义（从 field_dict_prompt.json 加载）
    4. Reasoning 字段说明
    5. 关键规则（枚举约束、格式约束）

    返回完整 System Prompt 字符串。
    """
    with open(_FIELD_DICT_PATH, encoding='utf-8') as f:
        field_dict = json.load(f)

    # 提取各节内容用于嵌入 Prompt
    paper_fields = field_dict['paper_level_fields']
    fae_fields = field_dict['fae_record_fields']['fields']
    output_example = field_dict['output_example']

    # ── 构建字段说明文本 ─────────────────────────────────────────────
    paper_field_lines = []
    for fname, finfo in paper_fields.items():
        req_mark = '[必填]' if finfo.get('required', False) else '[可选]'
        allowed = ''
        if 'allowed_values' in finfo:
            allowed = f" 允许值：{finfo['allowed_values']}。"
        paper_field_lines.append(
            f"  - {fname} ({finfo['type']}) {req_mark}:{allowed} {finfo['description']}"
        )

    fae_field_lines = []
    for fname, finfo in fae_fields.items():
        req_mark = '[必填]' if finfo.get('required', False) else '[可选]'
        allowed = ''
        if 'allowed_values' in finfo:
            allowed = f" 允许值：{finfo['allowed_values']}。"
        elif 'standard_values' in finfo:
            allowed = f" 标准值（优先使用）：{finfo['standard_values']}。"
        fae_field_lines.append(
            f"  - {fname} ({finfo['type']}) {req_mark}:{allowed} {finfo['description']}"
        )

    paper_fields_text = '\n'.join(paper_field_lines)
    fae_fields_text = '\n'.join(fae_field_lines)
    example_json = json.dumps(output_example, ensure_ascii=False, indent=2)

    system_prompt = f"""你是一名专业的生物医学文献挖掘助手，专注于羟基磷灰石（HAp）结合肽的研究领域。你的任务是从提供的科学论文全文中，结构化地抽取 HAp 结合肽的相关信息。

## 输出要求

输出一个合法的 JSON 对象。不要使用 markdown 代码块包裹。JSON 前后不要有任何其他文字。

JSON 的顶层结构如下：
- 论文级字段（v0.1 阶段每篇论文对应一个肽段对象）
- "fae_records" 数组，包含一条或多条 FAE（功能-实验-证据）子记录

## 论文级字段

{paper_fields_text}

## FAE 子记录字段（fae_records 数组）

"fae_records" 中的每个元素对应一个功能 × 一种实验方法 × 一组结果。
若同一功能由两种不同方法支持，应拆成两条独立的 FAE 记录。
预期数量：根据论文内容，通常为 2-5 条。

{fae_fields_text}

## Reasoning 字段（必填）

对于以下字段，你必须同时提供一个配套的 reasoning 字段，说明判断依据：
- "interaction_target" → "interaction_target_reason"：引用论文中的关键句或章节位置
- "summary_functions" → "summary_functions_reason"：说明为何选取这些功能标签
- "evidence_overall_level" → "evidence_overall_level_reason"：引用论文中关键实验描述
- "trace_status" → "trace_status_reason"：说明三个 text_to_* 字段的溯源情况

## 关键规则

1. 所有必填字段必须存在且非 null。
2. 枚举字段必须且只能使用指定的允许值。无法确定时，使用 "other" 或 "unclear"。
3. "summary_functions" 必须是 JSON 数组（如 ["adsorption", "remineralization"]），最多 3 个值。
4. "publication_year" 必须是整数（如 2023），不能是字符串。
5. 章节锚点格式："章节 > 子章节"，如 "Results > 3.1 CLSM"。
6. "text_to_evidence_summary" 中多个锚点以分号分隔。
7. 若某字段值无法从论文中确定，可选字段填 null，适用枚举字段填 "unclear"。严禁编造信息。
8. "curator_note"：无特殊情况填 null。

## 输出示例

{example_json}
"""
    return system_prompt


def build_user_prompt(paper_text: str) -> str:
    """构建 User Prompt，将论文全文嵌入提示中。

    User Prompt 直接将论文全文作为待处理材料，指令简洁，
    避免重复 System Prompt 中已有的规则说明。

    参数：
        paper_text : 由 pdf_extractor.extract_text_from_pdf() 提取的论文全文字符串

    返回完整 User Prompt 字符串。
    """
    return f"""请从以下科学论文全文中抽取 HAp 结合肽信息，按 System Prompt 中的规范输出一个合法的 JSON 对象。

=== 论文全文开始 ===
{paper_text}
=== 论文全文结束 ===
"""
