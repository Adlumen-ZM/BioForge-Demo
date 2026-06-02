"""
scripts/run_minimal_agent.py — AgentTemplate 最小链路冒烟脚本

用途：验证 AgentTemplate 端到端链路（plan 加载 → context 组装 → executor → trace → output_adapter）。
本脚本仅用于开发调试，不依赖真实数据库，不写入任何持久化存储。

使用方式：
    1. 在根目录 .env 中填写真实 LLM API Key（示例见 .env.example）
    2. 在项目根目录执行：
       python scripts/run_minimal_agent.py
    3. 或指定模型字符串：
       python scripts/run_minimal_agent.py --model "openai/gpt-4o"

输出：
    - 控制台打印 NullBackend trace 事件（4 个固定位置的 plan/step start/end）
    - 打印 AgentRunResult（status + 各 step 摘要 + final_output）
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("\n" + "=" * 60)
    print("BioForge AgentTemplate 最小链路冒烟")
    print(f"模型：{args.model}")
    print(f"摘要模式：{args.summary_mode}")
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

    print(f"[INFO] SearchAgent 初始化成功，plan_id={agent.plan.plan_id}")
    print(f"[INFO] Plan 共 {len(agent.plan.steps)} 个 step：")
    for step in agent.plan.steps:
        print(f"         - {step.step_id}: {step.name}")

    print("\n[INFO] 开始执行 run()...\n")

    # ── 执行 run（NullBackend 会打印 trace 事件）─────────────────────────
    try:
        state_patch = agent.run(pipeline_state={})
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

    print("\n[INFO] run_id：", agent.last_run_id)
    print("[INFO] 冒烟完成。如需真实 LLM 输出，请确保 .env 中配置了正确的 API Key。")
    print()


if __name__ == "__main__":
    main()
