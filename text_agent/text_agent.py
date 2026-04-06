import json

from db import BusinessDBWriter, TraceLogger
from text_agent.pdf_extractor import extract_text_from_pdf
from text_agent.prompt_builder import build_system_prompt, build_user_prompt, PROMPT_VERSION, SCHEMA_VERSION
from text_agent.llm_client import call_llm, MODEL_NAME
from text_agent.response_parser import parse_response
from text_agent.id_generator import (
    generate_paper_id, find_paper_id_by_doi,
    generate_record_id, generate_fae_id,
)


class TextAgent:
    """HAp 肽数据库 Text Agent。

    负责将一篇论文 PDF 经由 LLM 抽取转化为数据库记录，
    并全程记录 Trace 供可观测性分析。

    典型调用：
        agent = TextAgent()
        ok, err = agent.run('/path/to/paper.pdf')

    职责边界：
        - 本类只做流程编排，不处理具体的 DB 写入或 LLM 调用细节
        - DB 写入由 BusinessDBWriter 负责，Trace 记录由 TraceLogger 负责
        - LLM 调用由 llm_client.call_llm 负责
        - 全流程任意阶段失败均通过 TraceLogger.finalize('failed') 记录，不抛出异常
    """

    def __init__(self):
        """初始化 BusinessDBWriter（检查数据库表是否已就绪）。

        若业务数据库未初始化，BusinessDBWriter.__init__() 会抛出 RuntimeError，
        此时 TextAgent 初始化也将失败——这是预期行为，属于配置错误。
        """
        self._writer = BusinessDBWriter()
        # 最近一次成功 run 的结果，供外部（如 run_batch.py）生成 txt 报告使用
        self._last_result: dict | None = None

    @property
    def last_result(self) -> dict | None:
        """最近一次成功处理的结果字典，包含所有业务字段和 fae_records。
        未运行或上次失败时为 None。
        """
        return self._last_result

    def run(self, pdf_path: str) -> tuple[bool, str | None]:
        """执行完整的论文抽取流程。

        流程分为 10 个阶段，任意阶段失败均提前终止，记录 Trace 后返回 (False, 错误描述)。
        成功时返回 (True, None)。

        参数：
            pdf_path : 论文 PDF 文件的绝对路径

        阶段说明：
          阶段 1  PDF 文本提取
          阶段 2  DOI 预查重（检查论文是否已处理过）
          阶段 3  生成 paper_id
          阶段 4  初始化 TraceLogger（生成 run_id，INSERT extraction_runs）
          阶段 5  构建 System/User Prompt
          阶段 6  调用 LLM（MiniMax-M2.5）
          阶段 7  INSERT trace_step（收到响应后立即写入）
          阶段 8  解析 LLM 响应（JSON 解析 + 提取 reasoning）
          阶段 9  业务字段校验（BusinessDBWriter.validate_record）
          阶段 10 写入业务数据库（write_paper_record + write_fae_records）+ 完整性检查 + finalize
        """
        # ══════════════════════════════════════════════════════════════
        # 阶段 1：PDF 文本提取
        # ══════════════════════════════════════════════════════════════
        paper_text, err = extract_text_from_pdf(pdf_path)
        if err:
            # PDF 提取失败，尚未初始化 TraceLogger，只能直接返回
            return False, f'[阶段1] PDF 提取失败：{err}'

        # ══════════════════════════════════════════════════════════════
        # 阶段 2：DOI 预查重（快速扫描，减少不必要的 LLM 调用）
        # 注意：此阶段无法在 PDF 提取前获取 DOI，需要先提取再判断
        # 实际 DOI 查重发生在解析出 LLM 结果后（阶段 8.5），这里仅做标记占位
        # ══════════════════════════════════════════════════════════════
        # （DOI 查重逻辑在阶段 10 写入前执行，因为 DOI 需要从 LLM 输出中获取）

        # ══════════════════════════════════════════════════════════════
        # 阶段 3：生成 paper_id（从业务数据库 MAX 自增）
        # ══════════════════════════════════════════════════════════════
        paper_id = generate_paper_id()

        # ══════════════════════════════════════════════════════════════
        # 阶段 4：初始化 TraceLogger（生成 run_id，INSERT extraction_runs）
        # 从此阶段起，所有后续失败均通过 TraceLogger 记录
        # ══════════════════════════════════════════════════════════════
        logger = TraceLogger(
            paper_id=paper_id,
            model_name=MODEL_NAME,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
        )
        run_id = logger.get_run_id()

        # ══════════════════════════════════════════════════════════════
        # 阶段 5：构建 System/User Prompt
        # ══════════════════════════════════════════════════════════════
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(paper_text)

        # ══════════════════════════════════════════════════════════════
        # 阶段 6：调用 LLM（MiniMax-M2.5）
        # ══════════════════════════════════════════════════════════════
        llm_result, err = call_llm(system_prompt, user_prompt)
        if err:
            # API 调用失败：记录错误到 Trace，不写业务数据
            logger.finalize('failed', error_message=f'[阶段6] LLM 调用失败：{err}')
            return False, f'[阶段6] LLM 调用失败：{err}'

        # ══════════════════════════════════════════════════════════════
        # 阶段 7：INSERT trace_step（收到 LLM 响应后立即写入，无论后续解析是否成功）
        # step_status 初始为 'processing'，后续阶段通过 update_step 更新
        # ══════════════════════════════════════════════════════════════
        step_id, err = logger.insert_step(
            prompt_system=system_prompt,
            prompt_user=user_prompt,
            raw_response=llm_result['raw_response'],
            input_tokens=llm_result['input_tokens'],
            output_tokens=llm_result['output_tokens'],
            model_name=llm_result['model_name'],
            called_at=llm_result['called_at'],
            response_at=llm_result['response_at'],
            http_status_code=llm_result['http_status_code'],
        )
        if err:
            # Trace 写入失败不中断主流程，但记录警告（已无法通过 step 记录此错误）
            # 继续执行，用 run 级别的 error_message 记录
            step_id = None

        # ══════════════════════════════════════════════════════════════
        # 阶段 8：解析 LLM 响应
        # parsed_output : 业务字段字典（去除 reasoning 字段）
        # llm_reasoning : reasoning 字段 JSON 字符串
        # ══════════════════════════════════════════════════════════════
        parsed_output, llm_reasoning, err = parse_response(llm_result['raw_response'])
        if err:
            # JSON 解析失败：更新 step_status 为 parse_error，终止流程
            if step_id:
                logger.update_step(
                    step_id,
                    step_status='parse_error',
                    error_detail=err,
                )
            logger.finalize('failed', error_message=f'[阶段8] LLM 输出解析失败：{err}')
            return False, f'[阶段8] LLM 输出解析失败：{err}'

        # 解析成功，写入 parsed_output 和 llm_reasoning 到 trace_step
        if step_id:
            logger.update_step(
                step_id,
                parsed_output=json.dumps(parsed_output, ensure_ascii=False),
                llm_reasoning=llm_reasoning,
            )

        # ══════════════════════════════════════════════════════════════
        # 阶段 8.5：DOI 查重（检查该论文是否已写入过业务数据库）
        # 若已存在：复用已有的 paper_id，跳过写入，记录 Trace 后结束
        # ══════════════════════════════════════════════════════════════
        doi = parsed_output.get('doi')
        if doi:
            existing_paper_id = find_paper_id_by_doi(doi)
            if existing_paper_id:
                # 论文已存在：不重复写入业务数据，以 success 状态结束 run
                note = (
                    f'论文 DOI={doi} 已存在（paper_id={existing_paper_id}），'
                    f'跳过业务写入，Trace run 仍正常记录'
                )
                if step_id:
                    logger.update_step(step_id, step_status='success')
                logger.update_run(records_extracted=0, records_inserted=0)
                logger.finalize('success', error_message=note)
                return True, note

        # ══════════════════════════════════════════════════════════════
        # 阶段 9：业务字段校验（BusinessDBWriter.validate_record 是唯一校验入口）
        # ══════════════════════════════════════════════════════════════

        # 注入系统分配的 ID 字段（LLM 不填写这些字段，由 TextAgent 在写入前注入）
        record_id = generate_record_id(paper_id)
        parsed_output['paper_id'] = paper_id
        parsed_output['record_id'] = record_id

        # 注入 FAE ID（fae_records 中每条记录的 fae_id 由系统分配）
        fae_list = parsed_output.get('fae_records', [])
        for i, fae in enumerate(fae_list, start=1):
            fae['fae_id'] = generate_fae_id(record_id, i)

        # 执行校验
        ok, err = self._writer.validate_record(parsed_output)
        if not ok:
            # 校验失败：更新 step_status 为 schema_error，终止流程
            if step_id:
                logger.update_step(
                    step_id,
                    step_status='schema_error',
                    error_detail=err,
                )
            logger.update_run(records_extracted=len(fae_list))
            logger.finalize('failed', error_message=f'[阶段9] 字段校验失败：{err}')
            return False, f'[阶段9] 字段校验失败：{err}'

        # 校验通过，更新 step_status 为 success
        if step_id:
            logger.update_step(step_id, step_status='success')

        # ══════════════════════════════════════════════════════════════
        # 阶段 10a：写入业务数据库（paper_record + fae_records）
        # ══════════════════════════════════════════════════════════════
        ok, err = self._writer.write_paper_record(parsed_output, run_id)
        if not ok:
            logger.update_run(records_extracted=len(fae_list), records_inserted=0)
            logger.finalize('failed', error_message=f'[阶段10] paper_record 写入失败：{err}')
            return False, f'[阶段10] paper_record 写入失败：{err}'

        ok, err = self._writer.write_fae_records(fae_list, record_id)
        if not ok:
            logger.update_run(records_extracted=len(fae_list), records_inserted=0)
            logger.finalize('failed', error_message=f'[阶段10] FAE 写入失败：{err}')
            return False, f'[阶段10] FAE 写入失败：{err}'

        # ══════════════════════════════════════════════════════════════
        # 阶段 10b：完整性检查（反向验证写入结果与预期一致）
        # ══════════════════════════════════════════════════════════════
        check_status, check_detail = self._writer.integrity_check(
            paper_id=paper_id,
            expected_fae_count=len(fae_list),
        )

        # 将完整性检查结果写入 Trace run
        logger.update_run(
            records_extracted=len(fae_list),
            records_inserted=len(fae_list),
            integrity_check_status=check_status,
            integrity_check_detail=check_detail,
        )

        # ══════════════════════════════════════════════════════════════
        # 阶段 10c：finalize（聚合 token 统计，写入最终 run_status）
        # ══════════════════════════════════════════════════════════════
        if check_status == 'passed':
            logger.finalize('success')
            self._last_result = {**parsed_output, '_run_id': run_id}
            return True, None
        else:
            # 完整性检查失败：数据已写入但存在异常，以 failed 状态记录
            error_msg = f'[阶段10] 完整性检查失败：{check_detail}'
            logger.finalize('failed', error_message=error_msg)
            return False, error_msg
