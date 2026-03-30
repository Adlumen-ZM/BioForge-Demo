import sqlite3
import os

# 业务数据库路径，优先读取环境变量，默认写入 data/ 目录
BIZ_DB_PATH = os.getenv('BIZ_DB_PATH', 'data/hap_v01.db')

# ---------------------------------------------------------------------------
# 枚举值白名单（应用层执行校验，DB 层不设 CHECK 约束，保留 v0.2 扩展灵活性）
# ---------------------------------------------------------------------------
_INTERACTION_TARGET = {'HAp', 'enamel', 'dentin', 'collagen', 'ACP', 'other', 'unclear'}
_FUNCTIONS          = {'adsorption', 'remineralization', 'mineralization',
                       'anti_demineralization', 'other'}
_EVIDENCE_LEVEL     = {'in_vitro', 'ex_vivo', 'animal_in_vivo',
                       'clinical', 'in_silico', 'unclear'}
_TRACE_STATUS       = {'complete', 'partial', 'missing', 'disputed'}
_ASSAY_CATEGORY     = {'adsorption_binding', 'remineralization_outcome',
                       'mineral_morphology', 'mechanical_property', 'other'}

# 主表必填字段列表（extraction_run_id 由 write_paper_record 注入，不在此校验）
_REQUIRED_PAPER = [
    'paper_id', 'record_id', 'doi', 'title', 'journal_title', 'publication_year',
    'entity_name_raw', 'entity_name_normalized', 'sequence_raw',
    'interaction_target', 'summary_functions', 'evidence_overall_level',
    'model_system_summary', 'text_to_sequence', 'text_to_function_summary',
    'text_to_evidence_summary', 'trace_status',
]
# FAE 子表必填字段列表（record_id 由 write_fae_records 注入，不在此校验）
_REQUIRED_FAE = [
    'fae_id', 'function_label', 'evidence_level', 'assay_category',
    'validation_method', 'result_text_summary', 'text_to_evidence', 'trace_status',
]


class BusinessDBWriter:
    """封装 hap_v01.db 的全部写入与校验逻辑。

    Text Agent 通过调用本类方法完成业务写入，不直接操作数据库文件。

    调用方传入的 parsed_output 结构示例：
    {
        "paper_id": "P000001",
        "record_id": "P000001-R01",
        "doi": "10.xxxx/...",
        "pmid": "12345678",            # 可为 null
        "title": "...",
        "journal_title": "...",
        "publication_year": 2023,
        "entity_name_raw": "enamel binding peptide (EBP)",
        "entity_name_normalized": "WGNYAYK",
        "sequence_raw": "WGNYAYK",
        "interaction_target": "HAp",
        "summary_functions": ["adsorption", "remineralization"],  # list 或分号字符串均可
        "evidence_overall_level": "in_vitro",
        "model_system_summary": "bovine enamel subsurface demineralization model",
        "text_to_sequence": "Methods > 2.1 Peptide preparation",
        "text_to_function_summary": "Abstract > Results/Conclusion",
        "text_to_evidence_summary": "Abstract > Results; Results > CLSM",
        "trace_status": "complete",
        "curator_note": null,          # 可为 null
        "fae_records": [
            {
                "fae_id": "P000001-R01-FAE01",
                "function_label": "adsorption",
                "evidence_level": "in_vitro",
                "assay_category": "adsorption_binding",
                "validation_method": "CLSM",
                "readout_main": "fluorescence localization",   # 可为 null
                "result_text_summary": "EBP 显著吸附于 HAp 表面...",
                "text_to_evidence": "Results > CLSM",
                "trace_status": "complete"
            }
        ]
    }
    """

    def __init__(self):
        """连接 hap_v01.db，检查两张业务表是否已初始化。

        若表不存在则抛出 RuntimeError，提示先执行 init_biz_db.py。
        这是唯一允许抛出异常的方法——数据库未初始化属于配置错误，不应静默忽略。
        """
        self._db_path = BIZ_DB_PATH
        conn = self._connect()
        existing = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        missing = {'paper_record_v01_min', 'function_assay_evidence_v01_min'} - existing
        if missing:
            raise RuntimeError(
                f"业务数据库缺少表：{missing}，请先执行 init_biz_db.py"
            )

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def validate_record(self, parsed_output: dict) -> tuple[bool, str | None]:
        """写入前校验：枚举值合规性、必填字段非 null、ID 格式。

        校验通过返回 (True, None)；
        任意一项不通过返回 (False, 具体错误描述)，不抛出异常，由调用方决定如何处理。

        校验顺序：
          1. 主表必填字段是否为 null
          2. interaction_target 枚举值
          3. summary_functions 每个值的枚举合规性（支持 list 或分号字符串）
          4. evidence_overall_level 枚举值
          5. trace_status 枚举值
          6. record_id 必须以 paper_id 开头（格式约束）
          7. 每条 FAE 子记录的必填字段与枚举值
        """
        # ── 1. 主表必填字段 ──────────────────────────────────────────
        for field in _REQUIRED_PAPER:
            if parsed_output.get(field) is None:
                return False, f"主表必填字段缺失或为 null：'{field}'"

        # ── 2. interaction_target 枚举 ───────────────────────────────
        target = parsed_output['interaction_target']
        if target not in _INTERACTION_TARGET:
            return False, f"interaction_target 值不合法：'{target}'，允许值：{_INTERACTION_TARGET}"

        # ── 3. summary_functions 枚举（兼容 list 与分号字符串两种格式）──
        funcs = parsed_output['summary_functions']
        if isinstance(funcs, str):
            # 数据库存储格式，反序列化为列表进行校验
            funcs = [f.strip() for f in funcs.split(';') if f.strip()]
        for f in funcs:
            if f not in _FUNCTIONS:
                return False, f"summary_functions 包含不合法值：'{f}'，允许值：{_FUNCTIONS}"

        # ── 4. evidence_overall_level 枚举 ───────────────────────────
        level = parsed_output['evidence_overall_level']
        if level not in _EVIDENCE_LEVEL:
            return False, f"evidence_overall_level 值不合法：'{level}'，允许值：{_EVIDENCE_LEVEL}"

        # ── 5. trace_status 枚举 ─────────────────────────────────────
        status = parsed_output['trace_status']
        if status not in _TRACE_STATUS:
            return False, f"trace_status 值不合法：'{status}'，允许值：{_TRACE_STATUS}"

        # ── 6. ID 格式：record_id 必须以 paper_id 为前缀 ─────────────
        if not parsed_output['record_id'].startswith(parsed_output['paper_id']):
            return False, (
                f"record_id '{parsed_output['record_id']}' "
                f"必须以 paper_id '{parsed_output['paper_id']}' 开头"
            )

        # ── 7. FAE 子记录校验 ────────────────────────────────────────
        for i, fae in enumerate(parsed_output.get('fae_records', [])):
            # 必填字段
            for field in _REQUIRED_FAE:
                if fae.get(field) is None:
                    return False, f"FAE[{i}] 必填字段缺失或为 null：'{field}'"
            # 枚举校验
            if fae['function_label'] not in _FUNCTIONS:
                return False, f"FAE[{i}] function_label 值不合法：'{fae['function_label']}'"
            if fae['evidence_level'] not in _EVIDENCE_LEVEL:
                return False, f"FAE[{i}] evidence_level 值不合法：'{fae['evidence_level']}'"
            if fae['assay_category'] not in _ASSAY_CATEGORY:
                return False, f"FAE[{i}] assay_category 值不合法：'{fae['assay_category']}'"
            if fae['trace_status'] not in _TRACE_STATUS:
                return False, f"FAE[{i}] trace_status 值不合法：'{fae['trace_status']}'"

        return True, None

    def write_paper_record(self, parsed: dict, run_id: str) -> tuple[bool, str | None]:
        """将主表字段 INSERT 到 paper_record_v01_min，同时写入 extraction_run_id。

        写入前执行三层防护，任意一层不通过即提前返回 (False, 错误描述)，不执行 INSERT：
          1. 字段校验：调用 validate_record() 检查枚举值、必填字段、ID 格式
          2. 主键检查：paper_id 不得重复（PRIMARY KEY）
          3. 唯一键检查：record_id 不得重复（UNIQUE NOT NULL）

        run_id 由调用方从 TraceLogger.get_run_id() 获取后传入，是跨库溯源的唯一链接。
        summary_functions 若为 list，自动序列化为分号字符串再写入。

        成功返回 (True, None)；任意检查失败或数据库异常返回 (False, 错误描述)。
        """
        # ── 1. 字段校验：枚举值 / 必填字段 / ID 格式 ─────────────────────
        # 在任何数据库操作之前执行，拦截不合规数据，避免脏数据入库
        ok, err = self.validate_record(parsed)
        if not ok:
            return False, f"写入前字段校验失败：{err}"

        try:
            conn = self._connect()

            # ── 2. 主键重复检查：paper_id 不得已存在 ─────────────────────
            # 提前查询比依赖数据库抛 IntegrityError 更清晰，错误信息更具可读性
            if conn.execute(
                'SELECT 1 FROM paper_record_v01_min WHERE paper_id = ?',
                (parsed['paper_id'],)
            ).fetchone():
                conn.close()
                return False, f"paper_id '{parsed['paper_id']}' 已存在，拒绝重复写入"

            # ── 3. 唯一键重复检查：record_id 不得已存在 ──────────────────
            if conn.execute(
                'SELECT 1 FROM paper_record_v01_min WHERE record_id = ?',
                (parsed['record_id'],)
            ).fetchone():
                conn.close()
                return False, f"record_id '{parsed['record_id']}' 已存在，拒绝重复写入"

            # ── 4. 执行写入 ───────────────────────────────────────────────
            # summary_functions：将 JSON list 序列化为分号字符串（SQLite 无原生 list 类型）
            funcs = parsed['summary_functions']
            if isinstance(funcs, list):
                funcs = ';'.join(funcs)

            conn.execute(
                """INSERT INTO paper_record_v01_min
                   (paper_id, record_id, extraction_run_id,
                    doi, pmid, title, journal_title, publication_year,
                    entity_name_raw, entity_name_normalized, sequence_raw,
                    interaction_target, summary_functions, evidence_overall_level,
                    model_system_summary, text_to_sequence, text_to_function_summary,
                    text_to_evidence_summary, trace_status, curator_note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (parsed['paper_id'], parsed['record_id'], run_id,
                 parsed['doi'], parsed.get('pmid'),
                 parsed['title'], parsed['journal_title'], parsed['publication_year'],
                 parsed['entity_name_raw'], parsed['entity_name_normalized'],
                 parsed['sequence_raw'], parsed['interaction_target'], funcs,
                 parsed['evidence_overall_level'], parsed['model_system_summary'],
                 parsed['text_to_sequence'], parsed['text_to_function_summary'],
                 parsed['text_to_evidence_summary'], parsed['trace_status'],
                 parsed.get('curator_note'))
            )
            conn.commit()
            conn.close()
            return True, None
        except sqlite3.Error as e:
            return False, f"写入 paper_record 失败：{e}"

    def write_fae_records(self, fae_list: list, record_id: str) -> tuple[bool, str | None]:
        """批量 INSERT function_assay_evidence_v01_min，将所有 FAE 条目一次性写入。

        写入前执行两层防护，任意一层不通过即提前返回 (False, 错误描述)，不执行 INSERT：
          1. 字段校验：逐条检查 FAE 的必填字段与枚举值
          2. 主键检查：每条 fae_id 不得重复（PRIMARY KEY）

        使用 executemany 保证原子性：全部 FAE 成功才提交，任意一条失败则全部回滚。
        record_id 由调用方传入，与主表记录关联。

        成功返回 (True, None)；任意检查失败或数据库异常返回 (False, 错误描述)。
        """
        # 空列表是合法输入（论文可能没有细粒度实验证据），直接视为成功
        if not fae_list:
            return True, None

        try:
            conn = self._connect()

            for i, fae in enumerate(fae_list):

                # ── 1. 字段校验：必填字段与枚举值 ────────────────────────
                for field in _REQUIRED_FAE:
                    if fae.get(field) is None:
                        conn.close()
                        return False, f"FAE[{i}] 必填字段缺失或为 null：'{field}'"
                if fae['function_label'] not in _FUNCTIONS:
                    conn.close()
                    return False, f"FAE[{i}] function_label 值不合法：'{fae['function_label']}'"
                if fae['evidence_level'] not in _EVIDENCE_LEVEL:
                    conn.close()
                    return False, f"FAE[{i}] evidence_level 值不合法：'{fae['evidence_level']}'"
                if fae['assay_category'] not in _ASSAY_CATEGORY:
                    conn.close()
                    return False, f"FAE[{i}] assay_category 值不合法：'{fae['assay_category']}'"
                if fae['trace_status'] not in _TRACE_STATUS:
                    conn.close()
                    return False, f"FAE[{i}] trace_status 值不合法：'{fae['trace_status']}'"

                # ── 2. 主键重复检查：fae_id 不得已存在 ───────────────────
                if conn.execute(
                    'SELECT 1 FROM function_assay_evidence_v01_min WHERE fae_id = ?',
                    (fae['fae_id'],)
                ).fetchone():
                    conn.close()
                    return False, f"FAE[{i}] fae_id '{fae['fae_id']}' 已存在，拒绝重复写入"

            # ── 3. 全部校验通过，执行批量写入 ────────────────────────────
            # executemany 原子性保证：任意一条失败则整批回滚，不产生部分写入的脏数据
            conn.executemany(
                """INSERT INTO function_assay_evidence_v01_min
                   (fae_id, record_id, function_label, evidence_level, assay_category,
                    validation_method, readout_main, result_text_summary,
                    text_to_evidence, trace_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(fae['fae_id'], record_id,
                  fae['function_label'], fae['evidence_level'], fae['assay_category'],
                  fae['validation_method'], fae.get('readout_main'),
                  fae['result_text_summary'], fae['text_to_evidence'],
                  fae['trace_status'])
                 for fae in fae_list]
            )
            conn.commit()
            conn.close()
            return True, None
        except sqlite3.Error as e:
            return False, f"批量写入 FAE 记录失败：{e}"

    def integrity_check(self, paper_id: str, expected_fae_count: int) -> tuple[str, str | None]:
        """全部写入完成后对数据库进行反向校验，确认写入结果与预期一致。

        校验三项：
          1. paper_record_v01_min 中存在对应 paper_id 的记录
          2. 核心字段（doi / title / sequence_raw / extraction_run_id / trace_status）均非 null
          3. 对应 record_id 下的 FAE 记录数量与预期相符

        返回 ('passed', None) 或 ('failed', 具体原因)。
        结果应由调用方通过 TraceLogger.update_run() 写入 Trace 库。
        """
        try:
            conn = self._connect()

            # ── 1. 确认主表记录存在 ──────────────────────────────────
            row = conn.execute(
                'SELECT record_id FROM paper_record_v01_min WHERE paper_id = ?',
                (paper_id,)
            ).fetchone()
            if row is None:
                conn.close()
                return 'failed', f'未找到 paper_id={paper_id} 的主表记录'
            record_id = row[0]

            # ── 2. 核心字段非 null 检查 ──────────────────────────────
            null_count = conn.execute(
                """SELECT COUNT(*) FROM paper_record_v01_min
                   WHERE paper_id = ? AND (
                       doi IS NULL OR title IS NULL OR sequence_raw IS NULL
                       OR extraction_run_id IS NULL OR trace_status IS NULL
                   )""",
                (paper_id,)
            ).fetchone()[0]
            if null_count > 0:
                conn.close()
                return 'failed', '核心字段存在 NULL 值'

            # ── 3. FAE 记录数量核对 ──────────────────────────────────
            actual = conn.execute(
                'SELECT COUNT(*) FROM function_assay_evidence_v01_min WHERE record_id = ?',
                (record_id,)
            ).fetchone()[0]
            conn.close()

            if actual != expected_fae_count:
                return 'failed', f'FAE 记录数不符：预期 {expected_fae_count} 条，实际写入 {actual} 条'

            return 'passed', None

        except sqlite3.Error as e:
            return 'failed', f'完整性检查时数据库异常：{e}'

    # ------------------------------------------------------------------
    # 查询方法
    # ------------------------------------------------------------------

    def get_paper_record_by_paper_id(self, paper_id: str) -> tuple[dict | None, str | None]:
        """按 paper_id（主键）查询主表记录。

        paper_id 是论文级别的唯一标识，一次查询对应最多一条记录。
        summary_functions 在返回时自动反序列化为 list（写入时为分号字符串）。

        返回 (record_dict, None) 表示找到；(None, None) 表示不存在；(None, 错误描述) 表示异常。
        """
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row  # 使结果行可按列名访问
            row = conn.execute(
                'SELECT * FROM paper_record_v01_min WHERE paper_id = ?',
                (paper_id,)
            ).fetchone()
            conn.close()
            if row is None:
                return None, None
            return self._paper_row_to_dict(row), None
        except sqlite3.Error as e:
            return None, f"查询 paper_record（paper_id={paper_id}）失败：{e}"

    def get_paper_record_by_record_id(self, record_id: str) -> tuple[dict | None, str | None]:
        """按 record_id（UNIQUE 字段）查询主表记录。

        record_id 是对象级别的唯一标识，一次查询对应最多一条记录。
        summary_functions 在返回时自动反序列化为 list。

        返回 (record_dict, None) 表示找到；(None, None) 表示不存在；(None, 错误描述) 表示异常。
        """
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM paper_record_v01_min WHERE record_id = ?',
                (record_id,)
            ).fetchone()
            conn.close()
            if row is None:
                return None, None
            return self._paper_row_to_dict(row), None
        except sqlite3.Error as e:
            return None, f"查询 paper_record（record_id={record_id}）失败：{e}"

    def get_fae_record_by_fae_id(self, fae_id: str) -> tuple[dict | None, str | None]:
        """按 fae_id（主键）查询单条 FAE 子记录。

        返回 (fae_dict, None) 表示找到；(None, None) 表示不存在；(None, 错误描述) 表示异常。
        """
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM function_assay_evidence_v01_min WHERE fae_id = ?',
                (fae_id,)
            ).fetchone()
            conn.close()
            if row is None:
                return None, None
            return dict(row), None
        except sqlite3.Error as e:
            return None, f"查询 FAE 记录（fae_id={fae_id}）失败：{e}"

    def get_fae_records_by_record_id(self, record_id: str) -> tuple[list[dict], str | None]:
        """按 record_id（外键）查询该对象下的全部 FAE 子记录。

        record_id 与子表是一对多关系，返回结果列表按 fae_id 升序排列。
        记录不存在时返回空列表，而非报错。

        返回 (fae_list, None) 表示成功（列表可能为空）；([], 错误描述) 表示异常。
        """
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT * FROM function_assay_evidence_v01_min '
                'WHERE record_id = ? ORDER BY fae_id ASC',
                (record_id,)
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows], None
        except sqlite3.Error as e:
            return [], f"查询 FAE 记录列表（record_id={record_id}）失败：{e}"

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _paper_row_to_dict(self, row: sqlite3.Row) -> dict:
        """将主表的 sqlite3.Row 转为 dict，并将 summary_functions 反序列化为 list。

        写入时 list 被序列化为分号字符串（如 adsorption;remineralization），
        读取时还原为 list 以保持与 LLM 输出格式的一致性，调用方无需手动 split。
        """
        d = dict(row)
        if d.get('summary_functions'):
            d['summary_functions'] = [f.strip() for f in d['summary_functions'].split(';')]
        return d

    def _connect(self) -> sqlite3.Connection:
        """创建并返回一个开启了外键约束的数据库连接。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute('PRAGMA foreign_keys = ON;')
        return conn
