"""
PepClaw v0.1 批量运行入口

使用方式：
    1. 在 .env 文件中填写 MINIMAX_API_KEY_1 ~ MINIMAX_API_KEY_4
    2. 将待处理 PDF 放入 v0_1PDF/ 目录
    3. 在项目根目录执行：python3 run_batch.py

输出：
    - 数据库写入：db/data/hap_v01.db（业务结果）、db/data/hap_trace.db（执行日志）
    - txt 报告：v0_1results/<pdf文件名>.txt（每篇论文一个，可读格式）
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── 加载 .env ─────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
except ImportError:
    print('[错误] 缺少 python-dotenv，请执行：pip3 install python-dotenv')
    sys.exit(1)

_ENV_PATH = Path(__file__).parent / '.env'
if not _ENV_PATH.exists():
    print(f'[错误] 未找到 .env 文件：{_ENV_PATH}')
    sys.exit(1)

load_dotenv(_ENV_PATH)

# ── 校验 API Key ──────────────────────────────────────────────
_valid_keys = [os.getenv(f'MINIMAX_API_KEY_{i}', '').strip() for i in range(1, 5)]
_valid_keys = [k for k in _valid_keys if k]
if not _valid_keys:
    print('[错误] .env 中未填写任何有效的 MINIMAX_API_KEY_1 ~ MINIMAX_API_KEY_4')
    sys.exit(1)

print(f'[配置] 已加载 {len(_valid_keys)} 个 API Key，将轮转使用')

# ── 初始化数据库 ──────────────────────────────────────────────
from db import init_biz_database, init_trace_database

_biz_db = os.getenv('BIZ_DB_PATH', 'db/data/hap_v01.db')
_trace_db = os.getenv('TRACE_DB_PATH', 'db/data/hap_trace.db')
print(f'[配置] 业务数据库：{_biz_db}')
print(f'[配置] Trace 数据库：{_trace_db}')

init_biz_database()
init_trace_database()

# ── 扫描 PDF 目录 ─────────────────────────────────────────────
_pdf_dir = Path(os.getenv('PDF_INPUT_DIR', 'v0_1PDF'))
if not _pdf_dir.exists():
    print(f'[错误] PDF 输入目录不存在：{_pdf_dir}')
    sys.exit(1)

_pdf_files = sorted(_pdf_dir.glob('*.pdf'))
if not _pdf_files:
    print(f'[警告] {_pdf_dir}/ 目录下没有 .pdf 文件，退出')
    sys.exit(0)

print(f'\n[扫描] 在 {_pdf_dir}/ 下找到 {len(_pdf_files)} 个 PDF 文件：')
for i, f in enumerate(_pdf_files, 1):
    print(f'  {i:>3}. {f.name}')

# ── 准备 txt 输出目录 ─────────────────────────────────────────
_results_dir = Path('v0_1results')
_results_dir.mkdir(exist_ok=True)
print(f'\n[配置] txt 报告将写入：{_results_dir}/')


# ── Trace 数据查询 ────────────────────────────────────────────

def query_trace_data(run_id: str, include_full_text: bool = False) -> dict | None:
    """从 hap_trace.db 查询指定 run_id 的 Trace 数据。

    include_full_text=False：跳过长文本字段（prompt_system/prompt_user/raw_response/parsed_output）
    include_full_text=True ：包含全部字段，用于生成完整 trace txt
    查询失败时返回 None。
    """
    try:
        conn = sqlite3.connect(_trace_db)
        conn.row_factory = sqlite3.Row

        run_row = conn.execute(
            'SELECT * FROM extraction_runs WHERE run_id = ?', (run_id,)
        ).fetchone()
        if run_row is None:
            conn.close()
            return None

        if include_full_text:
            step_cols = '*'
        else:
            step_cols = (
                'step_id, run_id, step_index, step_type, '
                'input_tokens, output_tokens, model_name, '
                'called_at, response_at, response_time_ms, '
                'http_status_code, step_status, error_detail, llm_reasoning'
            )

        step_rows = conn.execute(
            f'SELECT {step_cols} FROM trace_steps '
            f'WHERE run_id = ? ORDER BY step_index ASC',
            (run_id,)
        ).fetchall()
        conn.close()

        return {
            'run': dict(run_row),
            'steps': [dict(r) for r in step_rows],
        }
    except sqlite3.Error:
        return None


# ── txt 格式化函数 ────────────────────────────────────────────

def _fmt(val, fallback='—'):
    """格式化字段值，None 显示为 fallback。"""
    if val is None:
        return fallback
    if isinstance(val, list):
        return '; '.join(str(v) for v in val)
    return str(val)


def write_result_txt(pdf_name: str, result: dict, output_path: Path):
    """将抽取结果与 Trace 数据格式化为可读 txt 文件。

    result 包含 parsed_output 的全部字段（已注入 paper_id / record_id / fae_id）
    以及 _run_id（来自 TraceLogger）。Trace 数据从 hap_trace.db 实时查询。
    """
    sep  = '═' * 62
    sep2 = '─' * 40
    now  = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    run_id = result.get('_run_id', '')

    lines = [
        sep,
        f'PepClaw v0.1 抽取报告',
        f'生成时间：{now}',
        f'来源 PDF：{pdf_name}',
        f'paper_id：{_fmt(result.get("paper_id"))}',
        f'record_id：{_fmt(result.get("record_id"))}',
        f'run_id：{_fmt(run_id)}',
        sep,
        '',
        '【论文信息】',
        f'  标题：{_fmt(result.get("title"))}',
        f'  DOI：{_fmt(result.get("doi"))}',
        f'  PMID：{_fmt(result.get("pmid"))}',
        f'  期刊：{_fmt(result.get("journal_title"))}',
        f'  发表年份：{_fmt(result.get("publication_year"))}',
        '',
        '【肽段信息】',
        f'  原文名称：{_fmt(result.get("entity_name_raw"))}',
        f'  标准名称：{_fmt(result.get("entity_name_normalized"))}',
        f'  氨基酸序列：{_fmt(result.get("sequence_raw"))}',
        f'  作用对象：{_fmt(result.get("interaction_target"))}',
        f'  主要功能：{_fmt(result.get("summary_functions"))}',
        f'  总体证据层级：{_fmt(result.get("evidence_overall_level"))}',
        f'  实验体系：{_fmt(result.get("model_system_summary"))}',
        '',
        '【溯源信息】',
        f'  溯源状态：{_fmt(result.get("trace_status"))}',
        f'  序列来源：{_fmt(result.get("text_to_sequence"))}',
        f'  功能来源：{_fmt(result.get("text_to_function_summary"))}',
        f'  证据来源：{_fmt(result.get("text_to_evidence_summary"))}',
    ]

    if result.get('curator_note'):
        lines += ['', '【备注】', f'  {result["curator_note"]}']

    # ── FAE 子记录 ────────────────────────────────────────────
    fae_list = result.get('fae_records', [])
    if fae_list:
        lines += ['', f'【功能证据记录（FAE，共 {len(fae_list)} 条）】']
        for fae in fae_list:
            lines += [
                '',
                f'  {sep2}',
                f'  FAE ID：{_fmt(fae.get("fae_id"))}',
                f'  功能标签：{_fmt(fae.get("function_label"))}',
                f'  实验类别：{_fmt(fae.get("assay_category"))}',
                f'  实验方法：{_fmt(fae.get("validation_method"))}',
                f'  测量指标：{_fmt(fae.get("readout_main"))}',
                f'  证据层级：{_fmt(fae.get("evidence_level"))}',
                f'  结果摘要：{_fmt(fae.get("result_text_summary"))}',
                f'  证据来源：{_fmt(fae.get("text_to_evidence"))}',
                f'  溯源状态：{_fmt(fae.get("trace_status"))}',
            ]

    # ── Trace 数据 ────────────────────────────────────────────
    trace = query_trace_data(run_id) if run_id else None
    if trace:
        r = trace['run']

        # 计算总耗时
        try:
            t_start = datetime.fromisoformat(r['started_at'])
            t_end   = datetime.fromisoformat(r['finished_at'])
            elapsed = f'{(t_end - t_start).total_seconds():.1f} 秒'
        except Exception:
            elapsed = '—'

        lines += [
            '',
            sep,
            '【Trace — 任务执行摘要（extraction_runs）】',
            f'  run_id：{_fmt(r.get("run_id"))}',
            f'  运行状态：{_fmt(r.get("run_status"))}',
            f'  模型：{_fmt(r.get("model_name"))}',
            f'  Prompt 版本：{_fmt(r.get("prompt_version"))}  |  字段字典版本：{_fmt(r.get("schema_version"))}',
            f'  开始时间：{_fmt(r.get("started_at"))}',
            f'  结束时间：{_fmt(r.get("finished_at"))}',
            f'  总耗时：{elapsed}',
            f'  Token 消耗：输入 {_fmt(r.get("total_input_tokens"))} + 输出 {_fmt(r.get("total_output_tokens"))} = 合计 {_fmt(r.get("total_tokens"))}',
            f'  抽取记录数：{_fmt(r.get("records_extracted"))}  |  写入记录数：{_fmt(r.get("records_inserted"))}',
            f'  完整性检查：{_fmt(r.get("integrity_check_status"))}'
            + (f'  ({r["integrity_check_detail"]})' if r.get('integrity_check_detail') else ''),
        ]
        if r.get('error_message'):
            lines.append(f'  错误信息：{r["error_message"]}')

        # trace_steps
        for step in trace['steps']:
            # 格式化响应时间
            ms = step.get('response_time_ms')
            resp_time = f'{ms / 1000:.2f} 秒（{ms} ms）' if ms else '—'

            lines += [
                '',
                f'【Trace — LLM 调用详情（trace_steps / step {step.get("step_index")}）】',
                f'  step_id：{_fmt(step.get("step_id"))}',
                f'  调用类型：{_fmt(step.get("step_type"))}',
                f'  调用模型：{_fmt(step.get("model_name"))}',
                f'  HTTP 状态码：{_fmt(step.get("http_status_code"))}',
                f'  步骤状态：{_fmt(step.get("step_status"))}',
                f'  调用时间：{_fmt(step.get("called_at"))}',
                f'  响应时间：{_fmt(step.get("response_at"))}',
                f'  LLM 响应耗时：{resp_time}',
                f'  输入 token：{_fmt(step.get("input_tokens"))}',
                f'  输出 token：{_fmt(step.get("output_tokens"))}',
            ]
            if step.get('error_detail'):
                lines.append(f'  错误详情：{step["error_detail"]}')

            # llm_reasoning：解析 JSON 后逐字段展示
            reasoning_raw = step.get('llm_reasoning')
            if reasoning_raw:
                try:
                    reasoning = json.loads(reasoning_raw)
                    lines.append('')
                    lines.append('  【LLM 判断依据（llm_reasoning）】')
                    label_map = {
                        'interaction_target_reason':   'interaction_target 判断依据',
                        'summary_functions_reason':    'summary_functions 判断依据',
                        'evidence_overall_level_reason': 'evidence_overall_level 判断依据',
                        'trace_status_reason':         'trace_status 判断依据',
                    }
                    for key, label in label_map.items():
                        if key in reasoning:
                            lines.append(f'  [{label}]')
                            lines.append(f'  {reasoning[key]}')
                            lines.append('')
                except (json.JSONDecodeError, TypeError):
                    lines.append(f'  llm_reasoning（原始）：{reasoning_raw[:200]}')

    lines += ['', sep, '']
    output_path.write_text('\n'.join(lines), encoding='utf-8')


# ── Think txt（LLM <think> 推理块全文）──────────────────────

def write_think_txt(pdf_name: str, run_id: str, think_content: str, output_path: Path):
    """将 LLM <think>...</think> 推理块内容写入独立 txt 文件。

    think_content 由 parse_response() 从原始响应中提取，多个 think 块以双换行拼接。
    """
    sep = '═' * 62
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    lines = [
        sep,
        'PepClaw v0.1 LLM Think 推理过程',
        f'生成时间：{now}',
        f'来源 PDF：{pdf_name}',
        f'run_id：{run_id}',
        sep,
        '',
        think_content,
        '',
        sep,
        '',
    ]
    output_path.write_text('\n'.join(lines), encoding='utf-8')


# ── 完整 Trace txt（包含 prompt/response 全文）────────────────

def write_trace_txt(pdf_name: str, run_id: str, output_path: Path):
    """将完整 Trace 数据写入独立 txt 文件，包含 prompt 和 LLM 输出全文。

    查询 hap_trace.db 中指定 run_id 的完整字段（include_full_text=True），
    按 step 顺序依次输出：extraction_runs 摘要、各 step 的 prompt_system、
    prompt_user、raw_response、parsed_output 全文。
    查询失败时写入错误说明，不抛出异常。
    """
    sep  = '═' * 62
    sep2 = '─' * 62
    now  = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    trace = query_trace_data(run_id, include_full_text=True)

    lines = [
        sep,
        f'PepClaw v0.1 完整 Trace 记录',
        f'生成时间：{now}',
        f'来源 PDF：{pdf_name}',
        f'run_id：{run_id}',
        sep,
    ]

    if trace is None:
        lines += ['', f'[错误] 未能从 Trace 数据库中查询到 run_id={run_id} 的记录', '']
        output_path.write_text('\n'.join(lines), encoding='utf-8')
        return

    r = trace['run']

    try:
        t_start = datetime.fromisoformat(r['started_at'])
        t_end   = datetime.fromisoformat(r['finished_at'])
        elapsed = f'{(t_end - t_start).total_seconds():.1f} 秒'
    except Exception:
        elapsed = '—'

    lines += [
        '',
        '【extraction_runs — 任务摘要】',
        f'  run_id：{_fmt(r.get("run_id"))}',
        f'  paper_id：{_fmt(r.get("paper_id"))}',
        f'  run_status：{_fmt(r.get("run_status"))}',
        f'  model_name：{_fmt(r.get("model_name"))}',
        f'  prompt_version：{_fmt(r.get("prompt_version"))}',
        f'  schema_version：{_fmt(r.get("schema_version"))}',
        f'  started_at：{_fmt(r.get("started_at"))}',
        f'  finished_at：{_fmt(r.get("finished_at"))}',
        f'  总耗时：{elapsed}',
        f'  total_input_tokens：{_fmt(r.get("total_input_tokens"))}',
        f'  total_output_tokens：{_fmt(r.get("total_output_tokens"))}',
        f'  total_tokens：{_fmt(r.get("total_tokens"))}',
        f'  records_extracted：{_fmt(r.get("records_extracted"))}',
        f'  records_inserted：{_fmt(r.get("records_inserted"))}',
        f'  integrity_check_status：{_fmt(r.get("integrity_check_status"))}',
        f'  integrity_check_detail：{_fmt(r.get("integrity_check_detail"))}',
    ]
    if r.get('error_message'):
        lines.append(f'  error_message：{r["error_message"]}')

    for step in trace['steps']:
        ms = step.get('response_time_ms')
        resp_time = f'{ms / 1000:.2f} 秒（{ms} ms）' if ms else '—'

        lines += [
            '',
            sep,
            f'【trace_steps — Step {step.get("step_index")}】',
            f'  step_id：{_fmt(step.get("step_id"))}',
            f'  step_type：{_fmt(step.get("step_type"))}',
            f'  model_name：{_fmt(step.get("model_name"))}',
            f'  http_status_code：{_fmt(step.get("http_status_code"))}',
            f'  step_status：{_fmt(step.get("step_status"))}',
            f'  called_at：{_fmt(step.get("called_at"))}',
            f'  response_at：{_fmt(step.get("response_at"))}',
            f'  response_time_ms：{resp_time}',
            f'  input_tokens：{_fmt(step.get("input_tokens"))}',
            f'  output_tokens：{_fmt(step.get("output_tokens"))}',
        ]
        if step.get('error_detail'):
            lines.append(f'  error_detail：{step["error_detail"]}')

        # ── prompt_system ────────────────────────────────────
        lines += [
            '',
            sep2,
            '【prompt_system（完整）】',
            sep2,
            step.get('prompt_system') or '（空）',
        ]

        # ── prompt_user ──────────────────────────────────────
        lines += [
            '',
            sep2,
            '【prompt_user（完整）】',
            sep2,
            step.get('prompt_user') or '（空）',
        ]

        # ── raw_response ─────────────────────────────────────
        lines += [
            '',
            sep2,
            '【raw_response（LLM 原始输出，完整）】',
            sep2,
            step.get('raw_response') or '（空）',
        ]

        # ── parsed_output ────────────────────────────────────
        parsed_raw = step.get('parsed_output')
        if parsed_raw:
            try:
                parsed_pretty = json.dumps(
                    json.loads(parsed_raw), ensure_ascii=False, indent=2
                )
            except (json.JSONDecodeError, TypeError):
                parsed_pretty = parsed_raw
        else:
            parsed_pretty = '（空）'

        lines += [
            '',
            sep2,
            '【parsed_output（解析后业务字段，完整）】',
            sep2,
            parsed_pretty,
        ]

        # ── llm_reasoning ────────────────────────────────────
        reasoning_raw = step.get('llm_reasoning')
        if reasoning_raw:
            try:
                reasoning_pretty = json.dumps(
                    json.loads(reasoning_raw), ensure_ascii=False, indent=2
                )
            except (json.JSONDecodeError, TypeError):
                reasoning_pretty = reasoning_raw
            lines += [
                '',
                sep2,
                '【llm_reasoning（判断依据，完整）】',
                sep2,
                reasoning_pretty,
            ]

    lines += ['', sep, '']
    output_path.write_text('\n'.join(lines), encoding='utf-8')


# ── 批量运行 ──────────────────────────────────────────────────
from text_agent import TextAgent

agent = TextAgent()

results = {'success': [], 'skipped': [], 'failed': []}

print(f'\n{"=" * 62}')
print(f'开始处理，共 {len(_pdf_files)} 篇论文')
print(f'{"=" * 62}\n')

for idx, pdf_path in enumerate(_pdf_files, 1):
    print(f'[{idx}/{len(_pdf_files)}] 处理：{pdf_path.name}')

    ok, msg = agent.run(str(pdf_path))

    if ok:
        if msg and 'DOI' in msg and '已存在' in msg:
            print(f'  → 跳过（{msg}）')
            results['skipped'].append(pdf_path.name)
        else:
            # 写 txt 报告
            txt_name = pdf_path.stem + '.txt'
            txt_path = _results_dir / txt_name
            if agent.last_result:
                write_result_txt(pdf_path.name, agent.last_result, txt_path)
                # 写完整 Trace txt（含 prompt/response 全文）
                trace_txt_path = _results_dir / (pdf_path.stem + '_trace.txt')
                run_id = agent.last_result.get('_run_id', '')
                if run_id:
                    write_trace_txt(pdf_path.name, run_id, trace_txt_path)
                    # 写 think txt（如有 think 内容）
                    think_content = agent.last_result.get('_think_content')
                    if think_content:
                        think_txt_path = _results_dir / (pdf_path.stem + '_think.txt')
                        write_think_txt(pdf_path.name, run_id, think_content, think_txt_path)
                        print(f'  → 成功  |  txt 报告：{txt_path}  |  trace：{trace_txt_path}  |  think：{think_txt_path}')
                    else:
                        print(f'  → 成功  |  txt 报告：{txt_path}  |  trace：{trace_txt_path}')
                else:
                    print(f'  → 成功  |  txt 报告：{txt_path}')
            else:
                print(f'  → 成功')
            results['success'].append(pdf_path.name)
    else:
        print(f'  → 失败：{msg}')
        results['failed'].append((pdf_path.name, msg))

    print()

# ── 汇总 ─────────────────────────────────────────────────────
print(f'{"=" * 62}')
print(f'运行完成')
print(f'  成功：{len(results["success"])} 篇  →  txt 报告在 {_results_dir}/')
print(f'  跳过：{len(results["skipped"])} 篇（DOI 已存在）')
print(f'  失败：{len(results["failed"])} 篇')

if results['failed']:
    print('\n失败列表：')
    for name, err in results['failed']:
        print(f'  - {name}：{err}')

print(f'{"=" * 62}')
