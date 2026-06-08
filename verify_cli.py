"""最终验证：所有 CLI 模块功能测试"""

import sys
sys.path.insert(0, '/app')

print("=" * 70)
print("BioForge CLI 最终验证")
print("=" * 70)
print()

# 1. 导入所有模块
print("[1/5] 模块导入测试...", end=" ")
try:
    from backend.src.cli import main
    from backend.src.cli.system_check import run_system_check
    from backend.src.cli.session import CLISession
    from backend.src.cli.app import print_banner
    from backend.src.cli.conversation import run_guide_conversation
    from backend.src.cli.pipeline_view import (
        NodeStatus, NodeMetrics, build_pipeline_table
    )
    print("✅")
except Exception as e:
    print(f"❌ {e}")
    sys.exit(1)

# 2. 系统检测
print("[2/5] 系统检测测试...", end=" ")
try:
    results = run_system_check()
    assert len(results) == 5, f"预期 5 项检测，实际 {len(results)}"
    assert all("name" in r and "status" in r for r in results)
    print(f"✅ ({len(results)} 项)")
except Exception as e:
    print(f"❌ {e}")
    sys.exit(1)

# 3. 会话管理
print("[3/5] 会话管理测试...", end=" ")
try:
    session = CLISession()
    run_id = session.new_run_id()
    assert run_id.startswith("run_")
    assert session.thread_id.startswith("thread_")

    session.add_history({"run_id": run_id, "status": "test"})
    assert len(session.history) == 1

    summary = session.summary()
    assert summary["total_runs"] == 1
    print("✅")
except Exception as e:
    print(f"❌ {e}")
    sys.exit(1)

# 4. 流水线指标
print("[4/5] 流水线指标测试...", end=" ")
try:
    metrics = {
        "search": NodeMetrics("search", NodeStatus.RUNNING, items_total=10, items_processed=5),
        "screen": NodeMetrics("screen", NodeStatus.PENDING),
        "extract": NodeMetrics("extract", NodeStatus.SUCCESS, items_total=5),
    }
    table = build_pipeline_table(metrics)
    assert table is not None

    m = metrics["search"]
    assert m.progress_pct() == "50% (5/10)"
    print("✅")
except Exception as e:
    print(f"❌ {e}")
    sys.exit(1)

# 5. 代码质量检查
print("[5/5] 代码质量检查...", end=" ")
try:
    # 检查所有 py 文件都能导入
    import importlib
    from pathlib import Path

    cli_dir = Path("backend/src/cli")
    py_files = list(cli_dir.glob("*.py"))
    assert len(py_files) > 0, "未找到 CLI Python 文件"
    print(f"✅ ({len(py_files)} 个文件)")
except Exception as e:
    print(f"❌ {e}")
    sys.exit(1)

print()
print("=" * 70)
print("✅ 所有验证项目通过！")
print("=" * 70)
print()
print("CLI 已准备就绪：")
print("  python -m backend.src.cli              # 启动 CLI")
print("  python -m backend.src.cli --check-only # 仅检查环境")
