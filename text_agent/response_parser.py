import json
import re

# 从 LLM 输出 JSON 中提取的 reasoning 字段名列表
# 这些字段存入 trace_steps.llm_reasoning，不写入业务表
_REASONING_FIELDS = [
    'interaction_target_reason',
    'summary_functions_reason',
    'evidence_overall_level_reason',
    'trace_status_reason',
]


def parse_response(raw_response: str) -> tuple[dict | None, str | None, str | None, str | None]:
    """解析 LLM 原始输出字符串，提取业务字段字典、reasoning JSON 和 think 内容。

    解析策略（按优先级尝试）：
      1. 直接将原始字符串作为 JSON 解析
      2. 尝试从 ```json ... ``` markdown 代码块中提取
      3. 尝试从 ``` ... ``` 代码块中提取
      4. 尝试定位第一个 '{' 到最后一个 '}' 之间的内容

    参数：
        raw_response : LLM 原始输出字符串

    成功时返回 (parsed_output, llm_reasoning_json, llm_think, None)：
        parsed_output      : 去除 reasoning 字段后的业务字段字典，
                             可直接传给 BusinessDBWriter.validate_record()
        llm_reasoning_json : reasoning 字段的 JSON 字符串，
                             存入 trace_steps.llm_reasoning；
                             若 LLM 未提供任何 reasoning 字段则为 None
        llm_think          : <think>...</think> 块的完整内容（多块以双换行拼接）；
                             若 LLM 未输出 think 块则为 None

    失败时返回 (None, None, None, 错误描述)。
    """
    text = raw_response.strip()

    # 提取 <think>...</think> 推理块内容（保留供外部写入独立 txt）
    think_blocks = re.findall(r'<think>(.*?)</think>', text, flags=re.DOTALL)
    llm_think = '\n\n'.join(b.strip() for b in think_blocks) if think_blocks else None

    # 剥离 <think> 块后再解析 JSON
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    # 尝试各种方式提取 JSON 文本
    json_text = _extract_json_text(text)

    # 解析 JSON
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        return None, None, None, f'LLM 输出非合法 JSON：{e}'

    if not isinstance(data, dict):
        return None, None, None, f'LLM 输出解析结果不是 JSON 对象，实际类型：{type(data).__name__}'

    # 提取 reasoning 字段，从 data 中原地弹出（不写入业务表）
    reasoning = {}
    for field in _REASONING_FIELDS:
        if field in data:
            reasoning[field] = data.pop(field)

    # reasoning 序列化为 JSON 字符串存入 Trace；无 reasoning 字段时存 None
    llm_reasoning_json = json.dumps(reasoning, ensure_ascii=False) if reasoning else None

    return data, llm_reasoning_json, llm_think, None


def _extract_json_text(text: str) -> str:
    """从 LLM 输出中提取 JSON 字符串内容。

    按优先级依次尝试以下策略：
      1. 直接使用原始文本（LLM 可能已按要求只输出 JSON）
      2. 从 ```json ... ``` 中提取
      3. 从 ``` ... ``` 中提取
      4. 从第一个 '{' 到最后一个 '}' 截取（兜底策略）

    若所有策略均无法提取，返回原始文本（由调用方处理解析失败）。
    """
    # 策略 1：直接尝试原始文本（若 LLM 按要求只输出 JSON，这是最常见情况）
    stripped = text.strip()
    if stripped.startswith('{'):
        return stripped

    # 策略 2：从 ```json 代码块中提取
    if '```json' in text:
        start = text.find('```json') + len('```json')
        end = text.find('```', start)
        if end != -1:
            return text[start:end].strip()

    # 策略 3：从普通 ``` 代码块中提取
    if '```' in text:
        start = text.find('```') + 3
        # 跳过可能的语言标记（如 "json\n"）
        newline = text.find('\n', start)
        if newline != -1:
            start = newline + 1
        end = text.find('```', start)
        if end != -1:
            return text[start:end].strip()

    # 策略 4：定位第一个 '{' 到最后一个 '}' 之间的内容（兜底）
    brace_start = text.find('{')
    brace_end = text.rfind('}')
    if brace_start != -1 and brace_end != -1 and brace_start < brace_end:
        return text[brace_start:brace_end + 1]

    # 所有策略均失败，返回原始文本（将在 json.loads 阶段报错）
    return text
