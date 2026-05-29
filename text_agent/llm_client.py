import os
from datetime import datetime, timezone

# 模型常量，与 TraceLogger 初始化时传入的 model_name 保持一致
MODEL_NAME = 'MiniMax-M2.7-highspeed'

# ──────────────────────────────────────────────────────────────
# 多 API Key 轮转
# 从环境变量 MINIMAX_API_KEY_1 ~ MINIMAX_API_KEY_4 加载，
# 过滤掉未填写的空值，调用时依次轮转（round-robin）。
# ──────────────────────────────────────────────────────────────
def _load_api_keys() -> list[str]:
    """从环境变量中加载所有有效的 API Key。"""
    keys = []
    for i in range(1, 5):
        key = os.getenv(f'MINIMAX_API_KEY_{i}', '').strip()
        if key:
            keys.append(key)
    # 兼容旧版单 Key 变量名
    fallback = os.getenv('MINIMAX_API_KEY', '').strip()
    if fallback and fallback not in keys:
        keys.append(fallback)
    return keys


# 模块级轮转计数器（单进程顺序调用场景下线程安全不是问题）
_key_index = 0


def _next_api_key() -> tuple[str | None, str | None]:
    """按轮转顺序返回下一个可用 API Key。

    返回 (key, None) 表示成功；(None, 错误描述) 表示无可用 Key。
    """
    global _key_index
    keys = _load_api_keys()
    if not keys:
        return None, (
            '未找到有效的 MiniMax API Key。\n'
            '请在 .env 文件中填写 MINIMAX_API_KEY_1 ~ MINIMAX_API_KEY_4 中的至少一个。'
        )
    key = keys[_key_index % len(keys)]
    _key_index += 1
    return key, None


def call_llm(system_prompt: str, user_prompt: str) -> tuple[dict | None, str | None]:
    """调用 MiniMax-M2.7-highspeed，通过 OpenAI 兼容接口发送对话请求。

    多 Key 轮转：每次调用自动从 MINIMAX_API_KEY_1 ~ MINIMAX_API_KEY_4 中
    选取下一个 Key，均匀分配请求，规避单 Key 速率限制。

    called_at 和 response_at 均在内存中用 datetime.now() 记录，
    收到响应后再写入数据库，避免 DB 写入耗时干扰 response_time_ms 计算。

    参数：
        system_prompt : System Prompt 完整字符串
        user_prompt   : User Prompt 完整字符串（含论文全文）

    返回 (result_dict, None) 表示成功；(None, 错误描述) 表示失败。

    result_dict 结构：
    {
        'raw_response'    : str,   # LLM 原始输出字符串
        'input_tokens'    : int,   # 本次调用输入 token 数
        'output_tokens'   : int,   # 本次调用输出 token 数
        'model_name'      : str,   # 实际使用的模型名称
        'called_at'       : str,   # API 调用发起时间，ISO 8601 UTC
        'response_at'     : str,   # 收到响应时间，ISO 8601 UTC
        'http_status_code': int,   # HTTP 状态码，成功为 200
    }
    """
    # 获取本次调用使用的 API Key
    api_key, err = _next_api_key()
    if err:
        return None, err

    # 延迟导入：避免未安装 openai 时模块级别报错
    try:
        from openai import OpenAI
    except ImportError:
        return None, 'openai 包未安装，请执行 pip install openai'

    client = OpenAI(
        api_key=api_key,
        base_url='https://api.minimax.chat/v1',
    )

    # 在调用前记录时间（内存中），与 response_at 一同在收到响应后写入 DB
    called_at = datetime.now(timezone.utc).isoformat()

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            temperature=0.2,   # 低温度保证抽取结果的确定性
            max_tokens=65536,
        )

        # 收到响应后立即记录时间
        response_at = datetime.now(timezone.utc).isoformat()

        raw_response = response.choices[0].message.content
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens

        return {
            'raw_response': raw_response,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'model_name': MODEL_NAME,
            'called_at': called_at,
            'response_at': response_at,
            'http_status_code': 200,
        }, None

    except Exception as e:
        # 收到异常时也记录 response_at（供 step 写入 response_time_ms 计算）
        response_at = datetime.now(timezone.utc).isoformat()
        err_str = str(e)

        # 根据错误信息判断 HTTP 错误类型，辅助 step_status 的分类写入
        if '429' in err_str or 'rate limit' in err_str.lower():
            return None, f'API 速率限制（HTTP 429）：{e}'
        elif '500' in err_str or 'internal server' in err_str.lower():
            return None, f'API 服务器错误（HTTP 500）：{e}'
        elif 'timeout' in err_str.lower():
            return None, f'API 调用超时：{e}'
        elif '401' in err_str or 'unauthorized' in err_str.lower():
            return None, f'API Key 无效或无权限（HTTP 401）：{e}'
        else:
            return None, f'API 调用失败：{e}'
