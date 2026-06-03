"""
scripts/run_minimal_agent.py — AgentTemplate 最小链路冒烟脚本

用途：验证 AgentTemplate 端到端链路（plan 加载 → context 组装 → executor → trace → output_adapter）。
本脚本仅用于开发调试，不写入业务数据库。

Trace 行为（自动切换）：
  - 若 .env 中设置了 TRACE_DB_URL：使用 PostgresBackend，trace 事件写入 agent_trace_events 表
  - 否则：退回 NullBackend，trace 事件只 print 到控制台

使用方式：
    1. 在根目录 .env 中填写真实 LLM API Key（示例见 .env.example）
    2. （可选）在 .env 中填写 TRACE_DB_URL 以启用 Postgres trace 写入
    3. 在项目根目录执行：
       python scripts/run_minimal_agent.py
    4. 或指定模型字符串：
       python scripts/run_minimal_agent.py --model "openai/gpt-4o"
    5. 或指定 pipeline run_id（模拟 graph 层传入）：
       python scripts/run_minimal_agent.py --run-id "pipe_smoke_0001"

输出：
    - 控制台打印 trace 事件（NullBackend：4 个固定位置；PostgresBackend：写 DB 并打印确认）
    - 打印 PipelineState patch（output_adapter 产出）

注意：
    - executor 使用真实 LLM API（tools/registry.py 的 pubmed_search 为 stub，不发真实网络请求）
    - 旧版 run_minimal_agent.py（依赖 SQLite TextAgent）已被此脚本完全替代
    - Docker 端到端验证由用户手动执行本脚本
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ── 路径设置（确保 backend/src 可被 import）──────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

# ── 加载 .env ──────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
except ImportError:
    print("[错误] 缺少 python-dotenv，请执行：pip install python-dotenv")
    sys.exit(1)

_env_path = _ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
    print(f"[INFO] 已加载 .env：{_env_path}")
else:
    print(f"[警告] 未找到 .env 文件（{_env_path}），LLM API Key 需通过环境变量提供。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AgentTemplate 最小链路冒烟脚本")
    parser.add_argument(
        "--model",
        default=os.getenv("DEFAULT_LLM_MODEL", "minimax/MiniMax-M2.7-highspeed"),
        help="LiteLLM 兼容的模型字符串（默认从 DEFAULT_LLM_MODEL 环境变量读取）",
    )
    parser.add_argument(
        "--summary-mode",
        choices=["template", "llm"],
        default="template",
        help="output_adapter 摘要生成模式（默认 template，不调 LLM）",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="模拟 pipeline 级别 run_id（如 'pipe_smoke_0001'）。"
             "若不传，脚本自动生成一个冒烟用 ID。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ── 确定 pipeline run_id ───────────────────────────────────────────────
    import uuid
    smoke_run_id = args.run_id or f"pipe_smoke_{uuid.uuid4().hex[:8]}"

    print("\n" + "=" * 60)
    print("BioForge AgentTemplate 最小链路冒烟")
    print(f"模型：{args.model}")
    print(f"摘要模式：{args.summary_mode}")
    print(f"pipeline run_id：{smoke_run_id}")
    print("=" * 60 + "\n")

    # ── 导入 AgentTemplate 及 SearchAgent 工厂函数 ─────────────────────────
    try:
        from backend.src.agents.search_agent.agent import create_search_agent
        from backend.src.agents.agent_template.schemas import SummaryMode
    except ImportError as e:
        print(f"[错误] 导入失败，请确认已安装所有依赖：{e}")
        sys.exit(1)

    # ── 创建 SearchAgent 实例 ──────────────────────────────────────────────
    summary_mode = SummaryMode.LLM if args.summary_mode == "llm" else SummaryMode.TEMPLATE
    agent = create_search_agent(model=args.model, summary_mode=summary_mode)

    # ── 条件切换 Trace Backend ─────────────────────────────────────────────
    trace_db_url = os.getenv("TRACE_DB_URL")
    if trace_db_url:
        try:
            from backend.src.db_access.trace.postgres_backend import PostgresBackend
            agent.hook.backend = PostgresBackend()
            print(f"[INFO] Trace 后端：PostgresBackend（TRACE_DB_URL 已配置）")
            print(f"[INFO] trace 事件将写入 agent_trace_events 表，run_id={smoke_run_id}")
        except ImportError as e:
            print(f"[警告] PostgresBackend 导入失败，退回 NullBackend：{e}")
    else:
        print("[INFO] Trace 后端：NullBackend（TRACE_DB_URL 未设置，trace 只 print 不写 DB）")

    print(f"[INFO] SearchAgent 初始化成功，plan_id={agent.plan.plan_id}")
    print(f"[INFO] Plan 共 {len(agent.plan.steps)} 个 step：")
    for step in agent.plan.steps:
        print(f"         - {step.step_id}: {step.name}")

    print("\n[INFO] 开始执行 run()...\n")

    # ── 执行 run（传入 pipeline run_id，模拟 graph 层调用方式）──────────────
    try:
        state_patch = agent.run(pipeline_state={}, run_id=smoke_run_id)
    except Exception as e:
        print(f"\n[错误] run() 执行失败：{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # ── 打印结果 ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PipelineState patch（output_adapter 产出）：")
    print("=" * 60)
    print(json.dumps(state_patch, ensure_ascii=False, indent=2, default=str))

    print(f"\n[INFO] pipeline run_id：{smoke_run_id}")
    print(f"[INFO] agent run_id（内部）：{agent.last_run_id}")
    if trace_db_url:
        print(f"\n[INFO] 查询验证（在 Docker 中执行）：")
        print(f"  docker exec <db_container> psql -U bioforge -d bioforge \\")
        print(f"    -c \"SELECT stage, event_type, status, duration_ms FROM agent_trace_events")
        print(f"         WHERE run_id = '{smoke_run_id}' ORDER BY created_at;\"")
    print("[INFO] 冒烟完成。如需真实 LLM 输出，请确保 .env 中配置了正确的 API Key。")
    print()


if __name__ == "__main__":
    main()
