import sqlite3
import os

# 业务数据库路径，优先读取环境变量，默认写入 data/ 目录
BIZ_DB_PATH = os.getenv('BIZ_DB_PATH', 'db/data/hap_v01.db')


def generate_paper_id() -> str:
    """从业务数据库查询当前最大 paper_id，自动生成下一个编号。

    格式：P000001（P + 6 位零填充数字）
    查询逻辑：MAX(paper_id) 利用字典序与数值序一致的性质（均为 P + 6位定长数字）。
    若数据库中尚无记录，从 P000001 开始。

    注意：此函数只生成 ID，不写入数据库。生成后到实际 INSERT 之间存在竞态窗口，
    v0.1 单进程运行场景下可忽略；v0.2 并发处理时需改为数据库行锁或序列机制。

    返回新的 paper_id 字符串，如 'P000001'。
    """
    conn = sqlite3.connect(BIZ_DB_PATH)
    row = conn.execute(
        'SELECT MAX(paper_id) FROM paper_record_v01_min'
    ).fetchone()
    conn.close()

    max_id = row[0]
    if max_id is None:
        # 数据库为空，从 P000001 开始
        return 'P000001'

    # 提取数字部分（去掉首字母 P）并加 1
    num = int(max_id[1:]) + 1
    return f'P{num:06d}'


def find_paper_id_by_doi(doi: str) -> str | None:
    """按 DOI 在业务数据库中查找已存在的 paper_id。

    若该 DOI 的论文已被处理过，返回其 paper_id；否则返回 None。
    用于「复用已有 paper_record」的判断逻辑：避免同一篇论文被重复写入。

    参数：
        doi : 论文 DOI 字符串

    返回 paper_id 字符串（若存在）；或 None（若不存在）。
    """
    conn = sqlite3.connect(BIZ_DB_PATH)
    row = conn.execute(
        'SELECT paper_id FROM paper_record_v01_min WHERE doi = ?',
        (doi,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def generate_record_id(paper_id: str, index: int = 1) -> str:
    """生成对象级记录编号。

    格式：{paper_id}-R{index:02d}，如 P000001-R01
    v0.1 阶段每篇论文只有一个对象，index 固定为 1。
    v0.2 多对象扩展时，按抽取顺序从 1 开始递增。

    参数：
        paper_id : 论文编号，如 'P000001'
        index    : 对象序号，从 1 开始，默认为 1

    返回 record_id 字符串，如 'P000001-R01'。
    """
    return f'{paper_id}-R{index:02d}'


def generate_fae_id(record_id: str, index: int) -> str:
    """生成 FAE 子记录编号。

    格式：{record_id}-FAE{index:02d}，如 P000001-R01-FAE01
    index 从 1 开始，按 FAE 列表顺序编号。

    参数：
        record_id : 对象级记录编号，如 'P000001-R01'
        index     : FAE 序号，从 1 开始

    返回 fae_id 字符串，如 'P000001-R01-FAE01'。
    """
    return f'{record_id}-FAE{index:02d}'
