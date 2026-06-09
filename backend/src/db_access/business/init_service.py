# backend/src/db_access/business/init_service.py
"""
业务数据库初始化接口

供 graph 节点（init_db_node）调用，封装数据库路径推导和初始化逻辑。
"""

import os
from pathlib import Path
from typing import Any

# 项目根：init_service.py → business → db_access → src → backend → 项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[5]


def _default_db_path(extraction_profile: str, data_root: str | None = None) -> str:
    """推导默认数据库路径。"""
    root = data_root or os.getenv("DATA_ROOT") or str(_PROJECT_ROOT / "data")
    return str(Path(root) / "projects" / extraction_profile / "db" / "business.sqlite")


def ensure_business_db(
    template_id: str = "hap_peptide_v1",
    extraction_profile: str | None = None,
    db_path: str | None = None,
    data_root: str | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    """
    确保业务 SQLite 数据库已初始化，幂等可重复调用。

    Args:
        template_id:         schema 模板 ID（决定加载哪个 schema.yaml）。
        extraction_profile:  提取配置名，决定文件路径分层；None 时与 template_id 相同。
        db_path:             明确指定数据库路径；None 时自动推导。
        data_root:           数据根目录；None 时取环境变量或默认。
        reset:               True 时强制重建（删除旧库）。

    Returns:
        {
          status, db_path, template_id,
          tables_created, vocab_count, already_existed
        }
    """
    from db.business.sqlite_init import init_sqlite_business_db

    profile = extraction_profile or template_id

    # 环境变量优先，再自动推导
    resolved_db_path = (
        db_path
        or os.getenv("BIZ_DB_PATH")
        or _default_db_path(profile, data_root)
    )

    return init_sqlite_business_db(
        template_id=template_id,
        db_path=resolved_db_path,
        data_root=data_root,
        reset=reset,
    )
