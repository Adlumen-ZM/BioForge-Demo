import sqlite3
import uuid
import os
from datetime import datetime, timezone

# Trace 数据库路径，优先读取环境变量，默认写入 data/ 目录
TRACE_DB_PATH = os.getenv('TRACE_DB_PATH', 'data/hap_trace.db')

# update_step / update_run 允许更新的字段白名单，防止调用方意外覆盖系统字段
_UPDATABLE_STEP_FIELDS = {'parsed_output', 'llm_reasoning', 'step_status', 'error_detail'}
_UPDATABLE_RUN_FIELDS  = {
    'records_extracted', 'records_inserted',
    'integrity_check_status', 'integrity_check_detail', 'error_message'
}


class TraceLogger:
    """记录每次 LLM 抽取任务（extraction_runs）及其每步 API 调用（trace_steps）。

    职责：可观测性基础设施，不承担业务逻辑。
    Text Agent 通过调用本类方法完成 Trace 写入，不直接操作 hap_trace.db。

    典型调用顺序：
        logger = TraceLogger(...)           # __init__：生成 run_id，INSERT extraction_runs
        step_id = logger.insert_step(...)   # 收到 LLM 响应后立即调用
        logger.update_step(step_id, ...)    # 解析完成后补充 parsed_output / llm_reasoning
        logger.update_step(step_id, ...)    # 校验完成后写入最终 step_status
        logger.update_run(...)              # 业务写入完成后更新 records_extracted 等
        logger.finalize(...)                # 全流程结束后汇总 token，写入最终状态
    """

    def __init__(self, paper_id: str, model_name: str,
                 prompt_version: str, schema_version: str):
        """生成 run_id 并 INSERT extraction_runs（run_status = 'running'）。

        run_id 格式：run_YYYYMMDD_HHMMSS_xxxxxx（时间戳 + UUID hex 前 6 位）
        此方法是唯一允许抛出异常的方法——数据库未初始化属于配置错误。

        参数：
            paper_id       : 本次任务处理的论文编号，关联业务库 paper_record.paper_id
            model_name     : 实际调用的模型名称，如 'gpt-4o'
            prompt_version : System Prompt 版本号，如 'v0.1.0'
            schema_version : 字段字典版本号，如 'v0.05'
        """
        self._db_path = TRACE_DB_PATH

        # run_id：时间戳确保大致有序，UUID hex 前 6 位防止同秒碰撞
        self._run_id = (
            f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            f"_{uuid.uuid4().hex[:6]}"
        )
        # step_counter：同一 run 内的步骤序号，从 1 开始自增
        self._step_counter = 0

        # INSERT 占位记录，后续各阶段通过 update_run / finalize 逐步补充字段
        conn = self._connect()
        conn.execute(
            """INSERT INTO extraction_runs
               (run_id, paper_id, model_name, prompt_version, schema_version,
                started_at, run_status)
               VALUES (?, ?, ?, ?, ?, ?, 'running')""",
            (self._run_id, paper_id, model_name, prompt_version, schema_version,
             datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Step 级别操作
    # ------------------------------------------------------------------

    def insert_step(self, *, prompt_system: str, prompt_user: str,
                    raw_response: str, input_tokens: int, output_tokens: int,
                    model_name: str, called_at: str, response_at: str,
                    http_status_code: int = 200) -> tuple[str | None, str | None]:
        """收到 LLM 响应后立即 INSERT trace_steps（step_status = 'processing'）。

        called_at 和 response_at 均在收到响应后才传入，避免 DB 写入耗时干扰
        response_time_ms 的计算（两个时间戳在调用方内存中用 time.time() 记录）。

        参数：
            prompt_system    : System Prompt 完整内容，不截断
            prompt_user      : User Prompt 完整内容（含论文全文），不截断
            raw_response     : LLM 原始输出字符串，无论解析成功与否都保存
            input_tokens     : 本次调用输入 token 数（来自 response.usage.prompt_tokens）
            output_tokens    : 本次调用输出 token 数（来自 response.usage.completion_tokens）
            model_name       : 本次 API 调用实际使用的模型名称
            called_at        : API 调用发起时间，ISO 8601 UTC 字符串
            response_at      : 收到 LLM 响应的时间，ISO 8601 UTC 字符串
            http_status_code : HTTP 状态码，默认 200

        返回 (step_id, None) 表示成功；(None, 错误描述) 表示写入失败。
        """
        self._step_counter += 1
        step_id = f"{self._run_id}_step_{self._step_counter:02d}"

        # response_time_ms：只反映 LLM 纯响应时间，排除 DB 写入、JSON 解析等操作耗时
        delta = (
            datetime.fromisoformat(response_at) - datetime.fromisoformat(called_at)
        ).total_seconds()
        response_time_ms = int(delta * 1000)

        try:
            conn = self._connect()
            conn.execute(
                """INSERT INTO trace_steps
                   (step_id, run_id, step_index, prompt_system, prompt_user,
                    raw_response, input_tokens, output_tokens, model_name,
                    called_at, response_at, response_time_ms,
                    http_status_code, step_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'processing')""",
                (step_id, self._run_id, self._step_counter,
                 prompt_system, prompt_user, raw_response,
                 input_tokens, output_tokens, model_name,
                 called_at, response_at, response_time_ms, http_status_code)
            )
            conn.commit()
            conn.close()
            return step_id, None
        except sqlite3.Error as e:
            # step_counter 已自增，写入失败时回退，防止序号跳空
            self._step_counter -= 1
            return None, f"INSERT trace_steps 失败：{e}"

    def update_step(self, step_id: str, **kwargs) -> tuple[bool, str | None]:
        """逐步补充 trace_steps 字段（解析完成后、校验完成后各调用一次）。

        只更新白名单内的字段（parsed_output / llm_reasoning / step_status / error_detail），
        忽略非白名单字段，防止调用方意外覆盖系统字段。

        返回 (True, None) 表示成功；(False, 错误描述) 表示失败。
        """
        # 过滤非白名单字段
        fields = {k: v for k, v in kwargs.items() if k in _UPDATABLE_STEP_FIELDS}
        if not fields:
            return True, None  # 无有效字段，视为成功（无需操作）

        set_clause = ', '.join(f'{k} = ?' for k in fields)
        try:
            conn = self._connect()
            conn.execute(
                f'UPDATE trace_steps SET {set_clause} WHERE step_id = ?',
                (*fields.values(), step_id)
            )
            conn.commit()
            conn.close()
            return True, None
        except sqlite3.Error as e:
            return False, f"UPDATE trace_steps 失败（step_id={step_id}）：{e}"

    # ------------------------------------------------------------------
    # Run 级别操作
    # ------------------------------------------------------------------

    def update_run(self, **kwargs) -> tuple[bool, str | None]:
        """逐步补充 extraction_runs 字段（业务写入完成后调用）。

        只更新白名单内的字段（records_extracted / records_inserted /
        integrity_check_status / integrity_check_detail / error_message）。

        返回 (True, None) 表示成功；(False, 错误描述) 表示失败。
        """
        fields = {k: v for k, v in kwargs.items() if k in _UPDATABLE_RUN_FIELDS}
        if not fields:
            return True, None

        set_clause = ', '.join(f'{k} = ?' for k in fields)
        try:
            conn = self._connect()
            conn.execute(
                f'UPDATE extraction_runs SET {set_clause} WHERE run_id = ?',
                (*fields.values(), self._run_id)
            )
            conn.commit()
            conn.close()
            return True, None
        except sqlite3.Error as e:
            return False, f"UPDATE extraction_runs 失败（run_id={self._run_id}）：{e}"

    def finalize(self, run_status: str, error_message: str = None) -> tuple[bool, str | None]:
        """汇总 token 消耗并写入最终运行状态，在全部流程结束后调用。

        total_input_tokens / total_output_tokens / total_tokens 由本方法从
        trace_steps 执行 SUM 聚合计算，不依赖调用方传入，确保统计准确。

        参数：
            run_status    : 最终状态，'success' 或 'failed'
            error_message : run 级别的顶层错误信息（成功时传 None）

        返回 (True, None) 表示成功；(False, 错误描述) 表示失败。
        """
        try:
            conn = self._connect()

            # 从 trace_steps 聚合本 run 的全部 token 消耗
            row = conn.execute(
                """SELECT COALESCE(SUM(input_tokens), 0),
                          COALESCE(SUM(output_tokens), 0)
                   FROM trace_steps WHERE run_id = ?""",
                (self._run_id,)
            ).fetchone()
            total_input, total_output = row

            conn.execute(
                """UPDATE extraction_runs SET
                   total_input_tokens  = ?,
                   total_output_tokens = ?,
                   total_tokens        = ?,
                   finished_at         = ?,
                   run_status          = ?,
                   error_message       = ?
                   WHERE run_id = ?""",
                (total_input, total_output, total_input + total_output,
                 datetime.now(timezone.utc).isoformat(),
                 run_status, error_message, self._run_id)
            )
            conn.commit()
            conn.close()
            return True, None
        except sqlite3.Error as e:
            return False, f"finalize 写入失败（run_id={self._run_id}）：{e}"

    def get_run_id(self) -> str:
        """返回当前 run_id，供业务写入时存入 paper_record.extraction_run_id。

        这是业务记录反向追溯 Trace 的唯一跨库链接字段。
        """
        return self._run_id

    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """创建并返回一个开启了外键约束的数据库连接。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute('PRAGMA foreign_keys = ON;')
        return conn
