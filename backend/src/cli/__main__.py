"""
backend/src/cli/__main__.py

对话式 CLI 入口点。

启动方式：
  python -m backend.src.cli              # 正常启动
  python -m backend.src.cli --check-only # 仅运行 system_check 后退出（用于 CI）

环境变量需求：参考 .env.example
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── sys.path 设置：确保能 import backend 模块 ──────────────────────────────
# 将项目根目录加入 sys.path，优先于系统路径
_project_root = Path(__file__).parent.parent.parent.parent  # backend_src_cli_main → root
sys.path.insert(0, str(_project_root))

# ── .env 加载 ───────────────────────────────────────────────────────────────
# 在所有业务 import 前加载 .env，使 API Key 等环境变量生效
from dotenv import load_dotenv

_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# ── 主程序 ──────────────────────────────────────────────────────────────────

def main():
    """CLI 主函数入口。"""
    from backend.src.cli.app import main as app_main
    app_main()


if __name__ == "__main__":
    # ── 检查命令行参数 ──────────────────────────────────────────────────────
    if "--check-only" in sys.argv:
        # 仅运行 system_check（用于 CI 验证环境）
        from backend.src.cli.system_check import run_system_check
        results = run_system_check()
        print("System Check Results:")
        for r in results:
            status_icon = {
                "ok": "✅",
                "warn": "⚠️",
                "error": "❌",
            }.get(r["status"], "❓")
            print(f"  {status_icon} {r['name']:15} {r['detail']}")
        sys.exit(0)

    # ── 正常启动 CLI ────────────────────────────────────────────────────────
    main()
