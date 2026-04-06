"""
db/test_databases.py

业务数据库（hap_v01.db）与 Trace 数据库（hap_trace.db）全分支单元测试。

覆盖范围：
    TestInitBizDB               — init_biz_database() 初始化逻辑
    TestInitTraceDB             — init_trace_database() 初始化逻辑
    TestBusinessDBWriterInit    — BusinessDBWriter.__init__() 两条分支
    TestBusinessDBWriterValidation — validate_record() 全部校验分支（13 个用例）
    TestBusinessDBWriterWrite   — write_paper_record / write_fae_records / integrity_check
    TestTraceLoggerInit         — TraceLogger.__init__() 两条分支
    TestTraceLoggerInsertStep   — insert_step() 全部分支
    TestTraceLoggerUpdateStep   — update_step() 全部分支
    TestTraceLoggerUpdateRun    — update_run() 全部分支
    TestTraceLoggerFinalize     — finalize() 全部分支

运行方式（在项目根目录执行）：
    python -m pytest db/test_databases.py -v
    python -m unittest db.test_databases -v
"""

from datetime import datetime, timedelta, timezone
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# 导入被测模块
from db.init_biz_db import init_biz_database
from db.init_trace_db import init_trace_database
from db.business_writer import BusinessDBWriter
from db.trace_logger import TraceLogger


# =============================================================================
# 测试辅助工具
# =============================================================================

def _valid_parsed(paper_id: str = 'P000001',
                  record_id: str = 'P000001-R01',
                  fae_count: int = 2) -> dict:
    """构造一条完全合规的 parsed_output 字典，供各测试用例复用。

    参数：
        paper_id   : 论文编号
        record_id  : 对象级记录编号，必须以 paper_id 为前缀
        fae_count  : 生成的 FAE 子记录条数
    """
    fae_records = [
        {
            'fae_id':              f'{record_id}-FAE{str(i + 1).zfill(2)}',
            'function_label':      'adsorption',
            'evidence_level':      'in_vitro',
            'assay_category':      'adsorption_binding',
            'validation_method':   'CLSM',
            'readout_main':        'fluorescence localization',
            'result_text_summary': 'EBP 显著吸附于 HAp 表面，与对照组相比荧光强度明显增强',
            'text_to_evidence':    'Results > CLSM',
            'trace_status':        'complete',
        }
        for i in range(fae_count)
    ]
    return {
        'paper_id':                paper_id,
        'record_id':               record_id,
        'doi':                     '10.1234/test.2023',
        'pmid':                    '12345678',
        'title':                   'HAp Binding Peptide Study',
        'journal_title':           'Journal of Dental Research',
        'publication_year':        2023,
        'entity_name_raw':         'enamel binding peptide (EBP)',
        'entity_name_normalized':  'WGNYAYK',
        'sequence_raw':            'WGNYAYK',
        'interaction_target':      'HAp',
        'summary_functions':       ['adsorption', 'remineralization'],
        'evidence_overall_level':  'in_vitro',
        'model_system_summary':    'bovine enamel subsurface demineralization model',
        'text_to_sequence':        'Methods > 2.1 Peptide preparation',
        'text_to_function_summary':'Abstract > Results/Conclusion',
        'text_to_evidence_summary':'Abstract > Results; Results > CLSM',
        'trace_status':            'complete',
        'curator_note':            None,
        'fae_records':             fae_records,
    }


def _iso(offset_seconds: float = 0.0) -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串，offset_seconds 可用于模拟时间差。"""
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


# =============================================================================
# 基础测试类：提供临时目录与数据库初始化帮助方法
# =============================================================================

class _DBTestBase(unittest.TestCase):
    """所有测试类的基类。

    每个测试用例都拥有独立的临时目录（tmpdir），
    biz_db_path 和 trace_db_path 均指向该目录下的文件，
    确保不同测试之间完全隔离，setUp/tearDown 自动管理生命周期。
    """

    def setUp(self):
        # 为每个测试用例创建独立的临时目录
        self.tmpdir = tempfile.mkdtemp()
        self.biz_db_path   = os.path.join(self.tmpdir, 'hap_v01.db')
        self.trace_db_path = os.path.join(self.tmpdir, 'hap_trace.db')

    def tearDown(self):
        # 测试结束后删除临时目录（含其中的所有 .db 文件）
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 初始化帮助 ──────────────────────────────────────────────────────

    def _init_biz(self):
        """将业务数据库初始化到临时路径。"""
        with patch('db.init_biz_db.BIZ_DB_PATH', self.biz_db_path):
            init_biz_database()

    def _init_trace(self):
        """将 Trace 数据库初始化到临时路径。"""
        with patch('db.init_trace_db.TRACE_DB_PATH', self.trace_db_path):
            init_trace_database()

    # ── 实例创建帮助 ────────────────────────────────────────────────────

    def _make_writer(self) -> BusinessDBWriter:
        """前提：已调用 _init_biz()。
        返回指向临时业务数据库的 BusinessDBWriter 实例。
        patch 仅在 __init__ 期间生效，__init__ 会将路径存入 self._db_path，
        后续方法调用均使用该实例变量，不再依赖模块级常量。
        """
        with patch('db.business_writer.BIZ_DB_PATH', self.biz_db_path):
            return BusinessDBWriter()

    def _make_logger(self, paper_id: str = 'P000001') -> TraceLogger:
        """前提：已调用 _init_trace()。
        返回指向临时 Trace 数据库的 TraceLogger 实例。
        """
        with patch('db.trace_logger.TRACE_DB_PATH', self.trace_db_path):
            return TraceLogger(
                paper_id=paper_id,
                model_name='gpt-4o',
                prompt_version='v0.1.0',
                schema_version='v0.05',
            )

    def _direct_connect(self, path: str) -> sqlite3.Connection:
        """直接连接指定路径的 SQLite 数据库，用于测试中的数据注入与结果核验。"""
        conn = sqlite3.connect(path)
        conn.execute('PRAGMA foreign_keys = ON;')
        return conn


# =============================================================================
# 1. init_biz_db.py 测试
# =============================================================================

class TestInitBizDB(_DBTestBase):
    """测试业务数据库初始化脚本 init_biz_database()。"""

    def test_creates_tables(self):
        """初始化后，两张业务表应当存在于数据库中。"""
        self._init_biz()
        conn = self._direct_connect(self.biz_db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        # 断言两张核心业务表均已创建
        self.assertIn('paper_record_v01_min',            tables)
        self.assertIn('function_assay_evidence_v01_min', tables)

    def test_creates_indexes(self):
        """初始化后，两个查询加速索引应当存在。"""
        self._init_biz()
        conn = self._direct_connect(self.biz_db_path)
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        conn.close()
        self.assertIn('idx_pr_extraction_run', indexes)
        self.assertIn('idx_fae_record_id',     indexes)

    def test_idempotent(self):
        """重复初始化不应抛出异常，CREATE TABLE IF NOT EXISTS 保证幂等性。"""
        self._init_biz()
        # 第二次调用不应报错
        try:
            self._init_biz()
        except Exception as e:
            self.fail(f'重复初始化抛出了异常：{e}')

    def test_db_file_created(self):
        """初始化后数据库文件应实际存在于磁盘上。"""
        self._init_biz()
        self.assertTrue(os.path.exists(self.biz_db_path))


# =============================================================================
# 2. init_trace_db.py 测试
# =============================================================================

class TestInitTraceDB(_DBTestBase):
    """测试 Trace 数据库初始化脚本 init_trace_database()。"""

    def test_creates_tables(self):
        """初始化后，两张 Trace 表应当存在于数据库中。"""
        self._init_trace()
        conn = self._direct_connect(self.trace_db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        self.assertIn('extraction_runs', tables)
        self.assertIn('trace_steps',     tables)

    def test_creates_indexes(self):
        """初始化后，两个查询加速索引应当存在。"""
        self._init_trace()
        conn = self._direct_connect(self.trace_db_path)
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        conn.close()
        self.assertIn('idx_er_paper_id', indexes)
        self.assertIn('idx_ts_run_id',   indexes)

    def test_idempotent(self):
        """重复初始化不应抛出异常。"""
        self._init_trace()
        try:
            self._init_trace()
        except Exception as e:
            self.fail(f'重复初始化抛出了异常：{e}')

    def test_db_file_created(self):
        """初始化后数据库文件应实际存在于磁盘上。"""
        self._init_trace()
        self.assertTrue(os.path.exists(self.trace_db_path))


# =============================================================================
# 3. BusinessDBWriter.__init__() 测试
# =============================================================================

class TestBusinessDBWriterInit(_DBTestBase):
    """测试 BusinessDBWriter 初始化时的两条分支：表存在 vs 表不存在。"""

    def test_init_success_when_tables_exist(self):
        """数据库已初始化（两张表存在）时，__init__ 应当成功，不抛出异常。"""
        self._init_biz()
        try:
            writer = self._make_writer()
            # 验证 _db_path 已正确设置为临时路径
            self.assertEqual(writer._db_path, self.biz_db_path)
        except RuntimeError as e:
            self.fail(f'不应抛出 RuntimeError：{e}')

    def test_init_raises_when_tables_missing(self):
        """数据库文件存在但表尚未创建时，__init__ 应抛出 RuntimeError，
        提示调用方先执行 init_biz_db.py。这是唯一允许抛出异常的方法，
        因为表不存在属于配置错误，不应静默忽略。
        """
        # 创建空数据库文件（不建表）
        sqlite3.connect(self.biz_db_path).close()
        with self.assertRaises(RuntimeError) as ctx:
            self._make_writer()
        # 错误信息中应包含缺失的表名
        self.assertIn('init_biz_db.py', str(ctx.exception))


# =============================================================================
# 4. BusinessDBWriter.validate_record() 测试（全校验分支）
# =============================================================================

class TestBusinessDBWriterValidation(_DBTestBase):
    """测试 validate_record() 的全部校验分支。

    validate_record 不抛出异常，全部通过返回 (True, None)，
    任意不通过返回 (False, 错误描述字符串)。
    """

    def setUp(self):
        super().setUp()
        self._init_biz()
        self.writer = self._make_writer()

    # ── 正常路径 ────────────────────────────────────────────────────────

    def test_valid_record_returns_true(self):
        """合规的 parsed_output（list 格式 summary_functions）应通过全部校验。"""
        ok, err = self.writer.validate_record(_valid_parsed())
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_valid_record_semicolon_functions(self):
        """summary_functions 使用分号字符串格式（数据库存储格式）同样应通过校验。
        BusinessDBWriter 兼容 list 和分号字符串两种输入，确保读取后再校验的场景也能工作。
        """
        data = _valid_parsed()
        data['summary_functions'] = 'adsorption;remineralization'  # 分号字符串格式
        ok, err = self.writer.validate_record(data)
        self.assertTrue(ok)
        self.assertIsNone(err)

    # ── 主表必填字段缺失 ────────────────────────────────────────────────

    def test_missing_required_field_returns_false(self):
        """主表必填字段为 None 时，应返回 (False, 含字段名的错误描述)。
        此处以 doi 字段为例，其他必填字段同理。
        """
        data = _valid_parsed()
        data['doi'] = None  # 将必填字段置为 None
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('doi', err)  # 错误信息中应指明是哪个字段

    # ── 枚举值校验 ──────────────────────────────────────────────────────

    def test_invalid_interaction_target(self):
        """interaction_target 填入不在枚举白名单中的值时，应返回 False。
        测试值 'coral' 不属于允许的作用对象。
        """
        data = _valid_parsed()
        data['interaction_target'] = 'coral'
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('interaction_target', err)

    def test_invalid_summary_functions_list(self):
        """summary_functions 中包含不合法值（list 格式）时，应返回 False。
        'binding' 不在允许的功能标签枚举中。
        """
        data = _valid_parsed()
        data['summary_functions'] = ['adsorption', 'binding']  # 'binding' 不合法
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('summary_functions', err)

    def test_invalid_summary_functions_semicolon(self):
        """summary_functions 中包含不合法值（分号字符串格式）时，同样应返回 False。
        验证两种格式的错误路径都能被正确拦截。
        """
        data = _valid_parsed()
        data['summary_functions'] = 'adsorption;binding'  # 'binding' 不合法
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('summary_functions', err)

    def test_invalid_evidence_overall_level(self):
        """evidence_overall_level 填入不合法枚举值时，应返回 False。"""
        data = _valid_parsed()
        data['evidence_overall_level'] = 'human_trial'  # 不在允许列表中
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('evidence_overall_level', err)

    def test_invalid_trace_status(self):
        """trace_status 填入不合法枚举值时，应返回 False。"""
        data = _valid_parsed()
        data['trace_status'] = 'unknown'  # 不在允许的溯源状态中
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('trace_status', err)

    # ── ID 格式校验 ─────────────────────────────────────────────────────

    def test_record_id_not_starting_with_paper_id(self):
        """record_id 不以 paper_id 为前缀时，应返回 False。
        此约束确保 ID 格式的层级一致性（paper_id 是 record_id 的前缀）。
        """
        data = _valid_parsed()
        data['record_id'] = 'P999999-R01'  # 与 paper_id='P000001' 不匹配
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('record_id', err)

    # ── FAE 子记录校验 ──────────────────────────────────────────────────

    def test_fae_missing_required_field(self):
        """FAE 子记录中必填字段为 None 时，应返回 False，错误信息包含 FAE 索引和字段名。"""
        data = _valid_parsed(fae_count=1)
        data['fae_records'][0]['result_text_summary'] = None  # 必填字段置为 None
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('FAE[0]', err)
        self.assertIn('result_text_summary', err)

    def test_fae_invalid_function_label(self):
        """FAE 子记录的 function_label 不合法时，应返回 False。"""
        data = _valid_parsed(fae_count=1)
        data['fae_records'][0]['function_label'] = 'binding'  # 不合法值
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('function_label', err)

    def test_fae_invalid_evidence_level(self):
        """FAE 子记录的 evidence_level 不合法时，应返回 False。"""
        data = _valid_parsed(fae_count=1)
        data['fae_records'][0]['evidence_level'] = 'cell_culture'  # 不合法值
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('evidence_level', err)

    def test_fae_invalid_assay_category(self):
        """FAE 子记录的 assay_category 不合法时，应返回 False。"""
        data = _valid_parsed(fae_count=1)
        data['fae_records'][0]['assay_category'] = 'fluorescence'  # 不合法值
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('assay_category', err)

    def test_fae_invalid_trace_status(self):
        """FAE 子记录的 trace_status 不合法时，应返回 False。"""
        data = _valid_parsed(fae_count=1)
        data['fae_records'][0]['trace_status'] = 'verified'  # 不合法值
        ok, err = self.writer.validate_record(data)
        self.assertFalse(ok)
        self.assertIn('trace_status', err)


# =============================================================================
# 5. BusinessDBWriter 写入与完整性检查测试
# =============================================================================

class TestBusinessDBWriterWrite(_DBTestBase):
    """测试 write_paper_record、write_fae_records、integrity_check 的全部分支。"""

    def setUp(self):
        super().setUp()
        self._init_biz()
        self.writer = self._make_writer()

    # ── write_paper_record ──────────────────────────────────────────────

    def test_write_paper_record_success(self):
        """合规数据写入主表应成功，返回 (True, None)，并可从数据库中查到对应记录。"""
        data = _valid_parsed()
        ok, err = self.writer.write_paper_record(data, run_id='run_test_001')
        self.assertTrue(ok)
        self.assertIsNone(err)
        # 直接查询数据库，验证记录确实已写入
        conn = self._direct_connect(self.biz_db_path)
        row = conn.execute(
            'SELECT paper_id, extraction_run_id, summary_functions '
            'FROM paper_record_v01_min WHERE paper_id = ?',
            ('P000001',)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[1], 'run_test_001')
        # summary_functions 应已被序列化为分号字符串
        self.assertEqual(row[2], 'adsorption;remineralization')

    def test_write_paper_record_serializes_list_to_semicolon(self):
        """summary_functions 为 list 格式时，写入数据库前应自动序列化为分号字符串。
        这一转换对 Text Agent 透明，由 BusinessDBWriter 内部完成。
        """
        data = _valid_parsed()
        data['summary_functions'] = ['adsorption', 'mineralization', 'remineralization']
        self.writer.write_paper_record(data, run_id='run_test_001')
        conn = self._direct_connect(self.biz_db_path)
        row = conn.execute(
            'SELECT summary_functions FROM paper_record_v01_min WHERE paper_id = ?',
            ('P000001',)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 'adsorption;mineralization;remineralization')

    def test_write_paper_record_validates_fields_before_insert(self):
        """write_paper_record 内部应先调用 validate_record 校验字段，
        不合规的数据（如非法枚举值）应在进入数据库之前被拦截，返回 (False, 错误描述)。
        确认校验是写入逻辑的第一道防线，不依赖调用方手动调用 validate_record。
        """
        data = _valid_parsed()
        data['interaction_target'] = 'coral'  # 非法枚举值
        ok, err = self.writer.write_paper_record(data, run_id='run_test_001')
        self.assertFalse(ok)
        # 错误信息应来自字段校验层（包含"校验"字样），而非数据库层
        self.assertIn('校验', err)
        self.assertIn('interaction_target', err)
        # 确认数据库中没有写入任何记录
        conn = self._direct_connect(self.biz_db_path)
        count = conn.execute('SELECT COUNT(*) FROM paper_record_v01_min').fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_write_paper_record_duplicate_paper_id_returns_false(self):
        """重复写入相同 paper_id（PRIMARY KEY 冲突）时，应在 INSERT 前被主键检查拦截，
        返回 (False, 含 '已存在' 的错误描述)，不抛出未捕获异常。
        """
        data = _valid_parsed()
        self.writer.write_paper_record(data, run_id='run_test_001')
        # 第二次写入同一 paper_id 应被主键预检查拦截
        ok, err = self.writer.write_paper_record(data, run_id='run_test_002')
        self.assertFalse(ok)
        self.assertIn('已存在', err)
        self.assertIn('paper_id', err)


    # ── write_fae_records ───────────────────────────────────────────────

    def test_write_fae_records_success(self):
        """FAE 子记录批量写入应成功，返回 (True, None)，并可从数据库中查到对应记录。"""
        data = _valid_parsed(fae_count=3)
        # 先写入主表（FAE 子表依赖主表的 record_id 外键）
        self.writer.write_paper_record(data, run_id='run_test_001')
        ok, err = self.writer.write_fae_records(data['fae_records'], record_id='P000001-R01')
        self.assertTrue(ok)
        self.assertIsNone(err)
        # 直接查询子表，验证 3 条记录均已写入
        conn = self._direct_connect(self.biz_db_path)
        count = conn.execute(
            'SELECT COUNT(*) FROM function_assay_evidence_v01_min WHERE record_id = ?',
            ('P000001-R01',)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 3)

    def test_write_fae_records_empty_list(self):
        """传入空 FAE 列表时，应成功返回 (True, None)，子表中无新增记录。
        空列表是合法输入（论文可能没有细粒度实验证据）。
        """
        data = _valid_parsed(fae_count=0)
        self.writer.write_paper_record(data, run_id='run_test_001')
        ok, err = self.writer.write_fae_records([], record_id='P000001-R01')
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_write_fae_records_validates_fields_before_insert(self):
        """write_fae_records 内部应先校验每条 FAE 的字段，
        不合规数据（如非法枚举值）应在进入数据库之前被拦截，返回 (False, 错误描述)。
        """
        data = _valid_parsed(fae_count=2)
        self.writer.write_paper_record(data, run_id='run_test_001')
        # 将第二条 FAE 的 function_label 改为非法值
        bad_fae_list = [fae.copy() for fae in data['fae_records']]
        bad_fae_list[1]['function_label'] = 'binding'  # 不合法
        ok, err = self.writer.write_fae_records(bad_fae_list, record_id='P000001-R01')
        self.assertFalse(ok)
        self.assertIn('FAE[1]', err)
        self.assertIn('function_label', err)
        # 确认整批均未写入（原子性）
        conn = self._direct_connect(self.biz_db_path)
        count = conn.execute(
            'SELECT COUNT(*) FROM function_assay_evidence_v01_min WHERE record_id = ?',
            ('P000001-R01',)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_write_fae_records_duplicate_fae_id_returns_false(self):
        """重复写入相同 fae_id（PRIMARY KEY 冲突）时，应被主键预检查拦截，
        返回 (False, 含 '已存在' 的错误描述)，不依赖数据库抛出 IntegrityError。
        """
        data = _valid_parsed(fae_count=2)
        self.writer.write_paper_record(data, run_id='run_test_001')
        self.writer.write_fae_records(data['fae_records'], record_id='P000001-R01')
        # 第二次写入同一批 fae_id 应被预检查拦截
        ok, err = self.writer.write_fae_records(data['fae_records'], record_id='P000001-R01')
        self.assertFalse(ok)
        self.assertIn('已存在', err)
        self.assertIn('fae_id', err)

    # ── integrity_check ─────────────────────────────────────────────────

    def test_integrity_check_passed(self):
        """主表记录存在、核心字段非 null、FAE 数量与预期一致时，应返回 ('passed', None)。"""
        data = _valid_parsed(fae_count=2)
        self.writer.write_paper_record(data, run_id='run_test_001')
        self.writer.write_fae_records(data['fae_records'], record_id='P000001-R01')
        status, detail = self.writer.integrity_check('P000001', expected_fae_count=2)
        self.assertEqual(status, 'passed')
        self.assertIsNone(detail)

    def test_integrity_check_record_not_found(self):
        """查询一个从未写入的 paper_id 时，应返回 ('failed', 含提示的字符串)。"""
        status, detail = self.writer.integrity_check('P999999', expected_fae_count=0)
        self.assertEqual(status, 'failed')
        self.assertIn('P999999', detail)

    def test_integrity_check_null_core_field(self):
        """核心字段存在 NULL 时，应返回 ('failed', 含 NULL 描述的字符串)。

        SQLite 的 NOT NULL 约束阻止了直接注入含 NULL 的脏数据，
        因此采用 mock 拦截"NULL 检查"的数据库查询，让其返回 count=1，
        直接验证 integrity_check 第二个检查分支（核心字段非 null 检查）的逻辑正确性。
        """
        # 先写入一条正常记录，确保通过第一项检查（paper_record 存在）
        data = _valid_parsed(fae_count=0)
        self.writer.write_paper_record(data, run_id='run_test_001')

        # 包装 _connect() 的返回值：sqlite3.Connection.execute 是只读属性，
        # 不能直接替换，因此使用包装类（Wrapper）代理全部方法，
        # 仅在检测到 NULL 检查 SQL 时拦截并返回 count=1 的 mock 游标。
        original_connect = self.writer._connect

        def mock_connect():
            real_conn = original_connect()

            class _ConnWrapper:
                """代理真实连接，仅拦截 NULL 检查查询。"""
                def execute(self, sql, params=()):
                    if 'doi IS NULL' in sql:
                        # 模拟查到 1 条核心字段为 NULL 的记录，触发失败分支
                        mock_cursor = MagicMock()
                        mock_cursor.fetchone.return_value = (1,)
                        return mock_cursor
                    return real_conn.execute(sql, params)

                def close(self):
                    real_conn.close()

                def __getattr__(self, name):
                    # 其余属性（commit 等）透传给真实连接
                    return getattr(real_conn, name)

            return _ConnWrapper()

        with patch.object(self.writer, '_connect', side_effect=mock_connect):
            status, detail = self.writer.integrity_check('P000001', expected_fae_count=0)

        self.assertEqual(status, 'failed')
        self.assertIn('NULL', detail)

    def test_integrity_check_fae_count_mismatch(self):
        """实际写入的 FAE 数量与预期不符时，应返回 ('failed', 含数量描述的字符串)。
        这是最常见的完整性失败场景：LLM 输出了 N 条 FAE 但只有 M 条写入成功。
        """
        data = _valid_parsed(fae_count=2)
        self.writer.write_paper_record(data, run_id='run_test_001')
        self.writer.write_fae_records(data['fae_records'], record_id='P000001-R01')
        # 实际写入 2 条，但告诉 integrity_check 预期是 4 条
        status, detail = self.writer.integrity_check('P000001', expected_fae_count=4)
        self.assertEqual(status, 'failed')
        self.assertIn('2', detail)  # 实际数量应出现在错误描述中
        self.assertIn('4', detail)  # 预期数量也应出现在错误描述中

    def test_integrity_check_db_error_returns_failed(self):
        """数据库连接异常时，integrity_check 应返回 ('failed', 错误描述)，
        不抛出未捕获异常，保证系统可用性。
        """
        # mock _connect 方法，模拟数据库连接失败场景
        with patch.object(self.writer, '_connect', side_effect=sqlite3.Error('mock db error')):
            status, detail = self.writer.integrity_check('P000001', expected_fae_count=0)
        self.assertEqual(status, 'failed')
        self.assertIn('mock db error', detail)


# =============================================================================
# 6. TraceLogger.__init__() 测试
# =============================================================================

class TestTraceLoggerInit(_DBTestBase):
    """测试 TraceLogger 初始化的两条分支：数据库已初始化 vs 未初始化。"""

    def test_init_success_inserts_run_record(self):
        """Trace 数据库已初始化时，__init__ 应成功在 extraction_runs 中插入一条
        run_status = 'running' 的占位记录，并生成合法格式的 run_id。
        """
        self._init_trace()
        logger = self._make_logger()
        # 验证 run_id 格式：以 'run_' 开头
        self.assertTrue(logger.get_run_id().startswith('run_'))
        # 直接查询数据库，验证记录已插入
        conn = self._direct_connect(self.trace_db_path)
        row = conn.execute(
            'SELECT run_status, paper_id, model_name FROM extraction_runs WHERE run_id = ?',
            (logger.get_run_id(),)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'running')
        self.assertEqual(row[1], 'P000001')
        self.assertEqual(row[2], 'gpt-4o')

    def test_init_raises_when_db_not_initialized(self):
        """Trace 数据库表不存在时（如忘记执行 init_trace_db.py），
        __init__ 的 INSERT 操作应触发 OperationalError，
        这是配置错误，应立即暴露。
        """
        # 创建空数据库（无表结构），不调用 init_trace_database()
        sqlite3.connect(self.trace_db_path).close()
        with self.assertRaises(Exception):
            self._make_logger()


# =============================================================================
# 7. TraceLogger.insert_step() 测试
# =============================================================================

class TestTraceLoggerInsertStep(_DBTestBase):
    """测试 insert_step() 的全部分支：成功写入、response_time_ms 计算、
    step_counter 管理、以及 DB 错误时的回退机制。
    """

    def setUp(self):
        super().setUp()
        self._init_trace()
        self.logger = self._make_logger()

    def _call_insert(self, delay_seconds: float = 1.5) -> tuple:
        """封装一次标准的 insert_step 调用，delay_seconds 控制模拟的 LLM 响应时间。"""
        called  = _iso(0)
        responded = _iso(delay_seconds)
        return self.logger.insert_step(
            prompt_system   = 'You are a biomedical extraction agent.',
            prompt_user     = 'Please extract HAp peptide info from this paper...',
            raw_response    = '{"records": [...]}',
            input_tokens    = 1000,
            output_tokens   = 300,
            model_name      = 'gpt-4o',
            called_at       = called,
            response_at     = responded,
            http_status_code= 200,
        )

    def test_insert_step_success(self):
        """正常插入应返回 (step_id, None)，step_id 不为 None。"""
        step_id, err = self._call_insert()
        self.assertIsNotNone(step_id)
        self.assertIsNone(err)

    def test_insert_step_increments_counter(self):
        """连续插入两个 step 时，step_counter 应依次自增，生成不同的 step_id。"""
        step_id_1, _ = self._call_insert()
        step_id_2, _ = self._call_insert()
        self.assertNotEqual(step_id_1, step_id_2)
        # step_id 格式：run_xxx_step_01, run_xxx_step_02
        self.assertTrue(step_id_1.endswith('_step_01'))
        self.assertTrue(step_id_2.endswith('_step_02'))

    def test_insert_step_calculates_response_time(self):
        """response_time_ms 应正确反映 LLM 纯响应时间（called_at 到 response_at 的毫秒差）。
        本测试使用固定延迟 2 秒，允许 ±100ms 的误差（datetime 精度导致）。
        """
        step_id, _ = self._call_insert(delay_seconds=2.0)
        conn = self._direct_connect(self.trace_db_path)
        row = conn.execute(
            'SELECT response_time_ms FROM trace_steps WHERE step_id = ?',
            (step_id,)
        ).fetchone()
        conn.close()
        # 允许 100ms 误差
        self.assertAlmostEqual(row[0], 2000, delta=100)

    def test_insert_step_db_error_returns_none_and_rolls_back_counter(self):
        """DB 写入失败时，应返回 (None, 错误描述)，不抛出异常，
        且 step_counter 应回退（防止序号跳空，下次成功时序号能正常延续）。
        """
        counter_before = self.logger._step_counter
        with patch.object(self.logger, '_connect', side_effect=sqlite3.Error('disk full')):
            step_id, err = self._call_insert()
        self.assertIsNone(step_id)
        self.assertIsNotNone(err)
        self.assertIn('disk full', err)
        # step_counter 应已回退到失败前的值
        self.assertEqual(self.logger._step_counter, counter_before)


# =============================================================================
# 8. TraceLogger.update_step() 测试
# =============================================================================

class TestTraceLoggerUpdateStep(_DBTestBase):
    """测试 update_step() 的全部分支：成功更新、白名单过滤、空参数、DB 错误。"""

    def setUp(self):
        super().setUp()
        self._init_trace()
        self.logger = self._make_logger()
        # 预先插入一条 step 记录，后续测试在此基础上执行 update
        self.step_id, _ = self.logger.insert_step(
            prompt_system='sys', prompt_user='user', raw_response='{}',
            input_tokens=100, output_tokens=50, model_name='gpt-4o',
            called_at=_iso(0), response_at=_iso(1),
        )

    def test_update_step_success(self):
        """更新白名单字段（step_status、parsed_output）应成功，返回 (True, None)，
        数据库中对应字段的值应发生变化。
        """
        ok, err = self.logger.update_step(
            self.step_id,
            step_status='success',
            parsed_output='{"records": [{"sequence": "WGNYAYK"}]}',
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        # 从数据库直接核验字段已更新
        conn = self._direct_connect(self.trace_db_path)
        row = conn.execute(
            'SELECT step_status, parsed_output FROM trace_steps WHERE step_id = ?',
            (self.step_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 'success')
        self.assertIsNotNone(row[1])

    def test_update_step_filters_non_whitelist_fields(self):
        """传入白名单之外的字段（如 step_index、run_id）时，这些字段应被过滤掉，
        不会写入数据库，防止调用方意外覆盖系统字段。
        """
        ok, err = self.logger.update_step(
            self.step_id,
            step_status='success',
            step_index=999,   # 非白名单字段，应被忽略
            run_id='fake_run' # 非白名单字段，应被忽略
        )
        self.assertTrue(ok)
        # 验证 step_index 和 run_id 未被修改
        conn = self._direct_connect(self.trace_db_path)
        row = conn.execute(
            'SELECT step_index, run_id FROM trace_steps WHERE step_id = ?',
            (self.step_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 1)                    # step_index 保持原值 1
        self.assertEqual(row[1], self.logger.get_run_id())  # run_id 保持原值

    def test_update_step_all_non_whitelist_returns_true(self):
        """传入的 kwargs 全部不在白名单中时，无任何实际操作，直接返回 (True, None)。
        这是'无操作成功'的情况，调用方无需关心是否真正执行了 UPDATE。
        """
        ok, err = self.logger.update_step(self.step_id, step_index=99, run_id='fake')
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_update_step_db_error_returns_false(self):
        """DB 更新失败时，应返回 (False, 错误描述)，不抛出未捕获异常。"""
        with patch.object(self.logger, '_connect', side_effect=sqlite3.Error('table locked')):
            ok, err = self.logger.update_step(self.step_id, step_status='success')
        self.assertFalse(ok)
        self.assertIn('table locked', err)


# =============================================================================
# 9. TraceLogger.update_run() 测试
# =============================================================================

class TestTraceLoggerUpdateRun(_DBTestBase):
    """测试 update_run() 的全部分支：成功更新、白名单过滤、DB 错误。"""

    def setUp(self):
        super().setUp()
        self._init_trace()
        self.logger = self._make_logger()

    def test_update_run_success(self):
        """更新白名单字段（records_extracted 等）应成功，返回 (True, None)，
        数据库中的对应字段值应发生变化。
        """
        ok, err = self.logger.update_run(
            records_extracted=1,
            records_inserted=1,
            integrity_check_status='passed',
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        # 直接查询数据库核验
        conn = self._direct_connect(self.trace_db_path)
        row = conn.execute(
            'SELECT records_extracted, records_inserted, integrity_check_status '
            'FROM extraction_runs WHERE run_id = ?',
            (self.logger.get_run_id(),)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 1)
        self.assertEqual(row[2], 'passed')

    def test_update_run_filters_non_whitelist_fields(self):
        """传入非白名单字段（如 run_status）时，这些字段应被过滤，不影响数据库。
        run_status 只能通过 finalize() 写入，防止调用方绕过正常流程修改最终状态。
        """
        ok, err = self.logger.update_run(
            records_extracted=5,
            run_status='success',  # 非白名单字段，应被忽略
        )
        self.assertTrue(ok)
        # run_status 应保持初始值 'running'
        conn = self._direct_connect(self.trace_db_path)
        row = conn.execute(
            'SELECT run_status, records_extracted FROM extraction_runs WHERE run_id = ?',
            (self.logger.get_run_id(),)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 'running')  # 未被修改
        self.assertEqual(row[1], 5)           # 白名单字段正常写入

    def test_update_run_db_error_returns_false(self):
        """DB 更新失败时，应返回 (False, 错误描述)，不抛出异常。"""
        with patch.object(self.logger, '_connect', side_effect=sqlite3.Error('disk full')):
            ok, err = self.logger.update_run(records_extracted=1)
        self.assertFalse(ok)
        self.assertIn('disk full', err)


# =============================================================================
# 10. TraceLogger.finalize() 测试
# =============================================================================

class TestTraceLoggerFinalize(_DBTestBase):
    """测试 finalize() 的全部分支：token 聚合、成功/失败状态写入、无 step 时的 COALESCE、DB 错误。"""

    def setUp(self):
        super().setUp()
        self._init_trace()
        self.logger = self._make_logger()

    def _insert_step_with_tokens(self, input_tokens: int, output_tokens: int):
        """辅助方法：插入一条 step 记录并指定 token 数量，用于测试 token 聚合逻辑。"""
        self.logger.insert_step(
            prompt_system='sys', prompt_user='user', raw_response='{}',
            input_tokens=input_tokens, output_tokens=output_tokens,
            model_name='gpt-4o', called_at=_iso(0), response_at=_iso(1),
        )

    def test_finalize_success_aggregates_tokens(self):
        """插入两条 step 记录后调用 finalize()，token 应正确聚合：
        total_input = 两条 step 的 input_tokens 之和，total_tokens = input + output。
        """
        self._insert_step_with_tokens(1000, 300)
        self._insert_step_with_tokens(500,  150)
        ok, err = self.logger.finalize('success')
        self.assertTrue(ok)
        self.assertIsNone(err)
        # 从数据库核验聚合结果
        conn = self._direct_connect(self.trace_db_path)
        row = conn.execute(
            'SELECT total_input_tokens, total_output_tokens, total_tokens, run_status '
            'FROM extraction_runs WHERE run_id = ?',
            (self.logger.get_run_id(),)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 1500)   # 1000 + 500
        self.assertEqual(row[1], 450)    # 300 + 150
        self.assertEqual(row[2], 1950)   # 1500 + 450
        self.assertEqual(row[3], 'success')

    def test_finalize_failed_writes_error_message(self):
        """finalize('failed', error_message=...) 时，错误信息应正确写入数据库，
        run_status 应为 'failed'。
        """
        ok, err = self.logger.finalize('failed', error_message='Schema 校验失败：evidence_level 不合法')
        self.assertTrue(ok)
        conn = self._direct_connect(self.trace_db_path)
        row = conn.execute(
            'SELECT run_status, error_message FROM extraction_runs WHERE run_id = ?',
            (self.logger.get_run_id(),)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 'failed')
        self.assertIn('Schema', row[1])

    def test_finalize_no_steps_coalesce_to_zero(self):
        """没有任何 step 记录时，COALESCE(SUM(...), 0) 应确保 token 字段为 0，
        而不是 NULL，防止后续的数字运算出错。
        """
        ok, err = self.logger.finalize('success')
        self.assertTrue(ok)
        conn = self._direct_connect(self.trace_db_path)
        row = conn.execute(
            'SELECT total_input_tokens, total_output_tokens, total_tokens '
            'FROM extraction_runs WHERE run_id = ?',
            (self.logger.get_run_id(),)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 0)
        self.assertEqual(row[1], 0)
        self.assertEqual(row[2], 0)

    def test_finalize_db_error_returns_false(self):
        """DB 操作失败时，finalize 应返回 (False, 错误描述)，不抛出异常。"""
        with patch.object(self.logger, '_connect', side_effect=sqlite3.Error('connection lost')):
            ok, err = self.logger.finalize('success')
        self.assertFalse(ok)
        self.assertIn('connection lost', err)


# =============================================================================
# 11. get_run_id() 测试
# =============================================================================

class TestTraceLoggerGetRunId(_DBTestBase):
    """测试 get_run_id() 的格式与唯一性。"""

    def setUp(self):
        super().setUp()
        self._init_trace()

    def test_run_id_format(self):
        """run_id 应符合 run_YYYYMMDD_HHMMSS_xxxxxx 格式。"""
        logger = self._make_logger()
        run_id = logger.get_run_id()
        parts = run_id.split('_')
        # 格式：['run', 'YYYYMMDD', 'HHMMSS', 'xxxxxx']
        self.assertEqual(parts[0], 'run')
        self.assertEqual(len(parts[1]), 8)   # YYYYMMDD
        self.assertEqual(len(parts[2]), 6)   # HHMMSS
        self.assertEqual(len(parts[3]), 6)   # UUID hex 前 6 位

    def test_run_ids_are_unique(self):
        """同一秒内创建两个 TraceLogger 实例，其 run_id 也应不同
        （UUID 后缀确保同秒碰撞极低概率发生）。
        """
        logger1 = self._make_logger(paper_id='P000001')
        logger2 = self._make_logger(paper_id='P000002')
        self.assertNotEqual(logger1.get_run_id(), logger2.get_run_id())


# =============================================================================
# 12. BusinessDBWriter 查询方法测试
# =============================================================================

class TestBusinessDBWriterQuery(_DBTestBase):
    """测试 BusinessDBWriter 的四个查询方法：
    get_paper_record_by_paper_id / get_paper_record_by_record_id /
    get_fae_record_by_fae_id / get_fae_records_by_record_id
    """

    def setUp(self):
        super().setUp()
        self._init_biz()
        self.writer = self._make_writer()
        # 预先写入一条主表记录和 2 条 FAE 子记录，供各查询测试使用
        self.data = _valid_parsed(fae_count=2)
        self.writer.write_paper_record(self.data, run_id='run_query_001')
        self.writer.write_fae_records(self.data['fae_records'], record_id='P000001-R01')

    # ── get_paper_record_by_paper_id ────────────────────────────────────

    def test_get_paper_record_by_paper_id_found(self):
        """按已存在的 paper_id 查询，应返回 (dict, None)，dict 包含所有主表字段。
        summary_functions 应已从分号字符串反序列化为 list，与写入前的格式一致。
        """
        record, err = self.writer.get_paper_record_by_paper_id('P000001')
        self.assertIsNotNone(record)
        self.assertIsNone(err)
        # 验证关键字段值正确
        self.assertEqual(record['paper_id'], 'P000001')
        self.assertEqual(record['doi'], '10.1234/test.2023')
        self.assertEqual(record['extraction_run_id'], 'run_query_001')
        # 验证 summary_functions 已反序列化为 list
        self.assertIsInstance(record['summary_functions'], list)
        self.assertIn('adsorption', record['summary_functions'])

    def test_get_paper_record_by_paper_id_not_found(self):
        """按不存在的 paper_id 查询，应返回 (None, None)，不报错。"""
        record, err = self.writer.get_paper_record_by_paper_id('P999999')
        self.assertIsNone(record)
        self.assertIsNone(err)

    def test_get_paper_record_by_paper_id_db_error(self):
        """数据库异常时，应返回 (None, 错误描述)，不抛出未捕获异常。"""
        with patch.object(self.writer, '_connect', side_effect=sqlite3.Error('read error')):
            record, err = self.writer.get_paper_record_by_paper_id('P000001')
        self.assertIsNone(record)
        self.assertIsNotNone(err)
        self.assertIn('read error', err)

    # ── get_paper_record_by_record_id ───────────────────────────────────

    def test_get_paper_record_by_record_id_found(self):
        """按已存在的 record_id（UNIQUE 字段）查询，应返回正确的主表记录。"""
        record, err = self.writer.get_paper_record_by_record_id('P000001-R01')
        self.assertIsNotNone(record)
        self.assertIsNone(err)
        self.assertEqual(record['record_id'], 'P000001-R01')
        self.assertEqual(record['paper_id'], 'P000001')

    def test_get_paper_record_by_record_id_not_found(self):
        """按不存在的 record_id 查询，应返回 (None, None)。"""
        record, err = self.writer.get_paper_record_by_record_id('P000001-R99')
        self.assertIsNone(record)
        self.assertIsNone(err)

    def test_get_paper_record_by_record_id_db_error(self):
        """数据库异常时，应返回 (None, 错误描述)。"""
        with patch.object(self.writer, '_connect', side_effect=sqlite3.Error('lock')):
            record, err = self.writer.get_paper_record_by_record_id('P000001-R01')
        self.assertIsNone(record)
        self.assertIsNotNone(err)

    # ── get_fae_record_by_fae_id ────────────────────────────────────────

    def test_get_fae_record_by_fae_id_found(self):
        """按已存在的 fae_id（主键）查询，应返回正确的 FAE 子记录。"""
        target_fae_id = self.data['fae_records'][0]['fae_id']
        fae, err = self.writer.get_fae_record_by_fae_id(target_fae_id)
        self.assertIsNotNone(fae)
        self.assertIsNone(err)
        self.assertEqual(fae['fae_id'], target_fae_id)
        self.assertEqual(fae['record_id'], 'P000001-R01')
        self.assertEqual(fae['function_label'], 'adsorption')

    def test_get_fae_record_by_fae_id_not_found(self):
        """按不存在的 fae_id 查询，应返回 (None, None)。"""
        fae, err = self.writer.get_fae_record_by_fae_id('P000001-R01-FAE99')
        self.assertIsNone(fae)
        self.assertIsNone(err)

    def test_get_fae_record_by_fae_id_db_error(self):
        """数据库异常时，应返回 (None, 错误描述)。"""
        with patch.object(self.writer, '_connect', side_effect=sqlite3.Error('io error')):
            fae, err = self.writer.get_fae_record_by_fae_id('P000001-R01-FAE01')
        self.assertIsNone(fae)
        self.assertIsNotNone(err)

    # ── get_fae_records_by_record_id ────────────────────────────────────

    def test_get_fae_records_by_record_id_returns_all(self):
        """按 record_id 查询应返回该对象下的全部 FAE 子记录，按 fae_id 升序排列。"""
        fae_list, err = self.writer.get_fae_records_by_record_id('P000001-R01')
        self.assertIsNone(err)
        # 写入了 2 条，应全部返回
        self.assertEqual(len(fae_list), 2)
        # 验证排序：fae_id 应升序
        self.assertLessEqual(fae_list[0]['fae_id'], fae_list[1]['fae_id'])

    def test_get_fae_records_by_record_id_empty(self):
        """record_id 存在但无对应 FAE 记录时，应返回空列表而非报错。
        此场景合法（主表记录刚写入、FAE 尚未写入时可能发生）。
        """
        # 写入另一条主表记录，但不写 FAE
        data2 = _valid_parsed(paper_id='P000002', record_id='P000002-R01', fae_count=0)
        self.writer.write_paper_record(data2, run_id='run_query_002')
        fae_list, err = self.writer.get_fae_records_by_record_id('P000002-R01')
        self.assertIsNone(err)
        self.assertEqual(fae_list, [])

    def test_get_fae_records_by_record_id_not_found(self):
        """完全不存在的 record_id 查询，同样返回空列表而非报错。"""
        fae_list, err = self.writer.get_fae_records_by_record_id('P999999-R01')
        self.assertIsNone(err)
        self.assertEqual(fae_list, [])

    def test_get_fae_records_by_record_id_db_error(self):
        """数据库异常时，应返回 ([], 错误描述)。"""
        with patch.object(self.writer, '_connect', side_effect=sqlite3.Error('timeout')):
            fae_list, err = self.writer.get_fae_records_by_record_id('P000001-R01')
        self.assertEqual(fae_list, [])
        self.assertIsNotNone(err)


# =============================================================================
# 13. TraceLogger 查询方法测试
# =============================================================================

class TestTraceLoggerQuery(_DBTestBase):
    """测试 TraceLogger 的三个查询方法：
    get_run / get_step_by_step_id / get_steps
    """

    def setUp(self):
        super().setUp()
        self._init_trace()
        self.logger = self._make_logger()
        # 预先插入 2 条 step 记录供查询测试使用
        self.step_id_1, _ = self.logger.insert_step(
            prompt_system='sys', prompt_user='user1', raw_response='{}',
            input_tokens=800, output_tokens=200, model_name='gpt-4o',
            called_at=_iso(0), response_at=_iso(1),
        )
        self.step_id_2, _ = self.logger.insert_step(
            prompt_system='sys', prompt_user='user2', raw_response='{"repair": true}',
            input_tokens=400, output_tokens=100, model_name='gpt-4o',
            called_at=_iso(2), response_at=_iso(3),
        )

    # ── get_run ─────────────────────────────────────────────────────────

    def test_get_run_returns_current_run(self):
        """get_run() 应返回当前 run 的完整 extraction_runs 记录，
        包含 __init__ 时写入的配置字段和初始状态。
        """
        run, err = self.logger.get_run()
        self.assertIsNotNone(run)
        self.assertIsNone(err)
        self.assertEqual(run['run_id'], self.logger.get_run_id())
        self.assertEqual(run['paper_id'], 'P000001')
        self.assertEqual(run['model_name'], 'gpt-4o')
        self.assertEqual(run['run_status'], 'running')

    def test_get_run_after_finalize_reflects_final_state(self):
        """finalize() 完成后调用 get_run()，应能读到最终状态（run_status、token 汇总等）。
        验证查询能正确反映写入后的数据库状态。
        """
        self.logger.finalize('success')
        run, err = self.logger.get_run()
        self.assertIsNone(err)
        self.assertEqual(run['run_status'], 'success')
        # token 汇总应已聚合（800+400=1200 input，200+100=300 output）
        self.assertEqual(run['total_input_tokens'], 1200)
        self.assertEqual(run['total_output_tokens'], 300)
        self.assertEqual(run['total_tokens'], 1500)

    def test_get_run_db_error(self):
        """数据库异常时，get_run 应返回 (None, 错误描述)。"""
        with patch.object(self.logger, '_connect', side_effect=sqlite3.Error('connection lost')):
            run, err = self.logger.get_run()
        self.assertIsNone(run)
        self.assertIsNotNone(err)

    # ── get_step_by_step_id ─────────────────────────────────────────────

    def test_get_step_by_step_id_found(self):
        """按已存在的 step_id（主键）查询，应返回正确的 trace_steps 记录。"""
        step, err = self.logger.get_step_by_step_id(self.step_id_1)
        self.assertIsNotNone(step)
        self.assertIsNone(err)
        self.assertEqual(step['step_id'], self.step_id_1)
        self.assertEqual(step['step_index'], 1)
        self.assertEqual(step['input_tokens'], 800)
        self.assertEqual(step['prompt_user'], 'user1')

    def test_get_step_by_step_id_not_found(self):
        """按不存在的 step_id 查询，应返回 (None, None)，不报错。"""
        step, err = self.logger.get_step_by_step_id('run_fake_step_99')
        self.assertIsNone(step)
        self.assertIsNone(err)

    def test_get_step_by_step_id_db_error(self):
        """数据库异常时，应返回 (None, 错误描述)。"""
        with patch.object(self.logger, '_connect', side_effect=sqlite3.Error('disk error')):
            step, err = self.logger.get_step_by_step_id(self.step_id_1)
        self.assertIsNone(step)
        self.assertIsNotNone(err)

    # ── get_steps ───────────────────────────────────────────────────────

    def test_get_steps_returns_all_in_order(self):
        """get_steps() 应返回当前 run 下的全部 step，按 step_index 升序排列。"""
        steps, err = self.logger.get_steps()
        self.assertIsNone(err)
        self.assertEqual(len(steps), 2)
        # 验证排序：step_index 应升序
        self.assertEqual(steps[0]['step_index'], 1)
        self.assertEqual(steps[1]['step_index'], 2)
        # 验证内容正确
        self.assertEqual(steps[0]['step_id'], self.step_id_1)
        self.assertEqual(steps[1]['step_id'], self.step_id_2)

    def test_get_steps_empty_when_no_steps(self):
        """没有插入任何 step 时，get_steps() 应返回空列表而非报错。"""
        # 创建一个全新的 logger，没有任何 step
        fresh_logger = self._make_logger(paper_id='P000002')
        steps, err = fresh_logger.get_steps()
        self.assertIsNone(err)
        self.assertEqual(steps, [])

    def test_get_steps_db_error(self):
        """数据库异常时，应返回 ([], 错误描述)。"""
        with patch.object(self.logger, '_connect', side_effect=sqlite3.Error('timeout')):
            steps, err = self.logger.get_steps()
        self.assertEqual(steps, [])
        self.assertIsNotNone(err)


# =============================================================================
# 入口
# =============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
