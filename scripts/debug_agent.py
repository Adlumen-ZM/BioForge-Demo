"""
scripts/debug_agent.py — BioForge 算子调试 CLI 工具

位置：scripts/
依赖：backend/src/agents/（各 agent 工厂函数）、backend/src/db_access/trace/reader.py
职责：在命令行运行任意 agent，支持参数覆盖、trace 落库、历史查询、对比实验。
      不依赖 rich 等第三方库，使用 Python 内置 print + Unicode 框线字符输出结构化界面。

使用示例：
    # 基本运行
    python scripts/debug_agent.py --agent test --plan plan_happy_path
    python scripts/debug_agent.py --agent test --plan plan_retry_scenario
    python scripts/debug_agent.py --agent search --model openai/gpt-4o

    # 参数覆盖
    python scripts/debug_agent.py --agent search --model minimax/MiniMax-Text-01
    python scripts/debug_agent.py --agent test --skill test_protocol=/path/to/v2.md

    # 指定 run_id
    python scripts/debug_agent.py --agent test --run-id debug_test_001

    # 实验配置文件（多参数覆盖）
    python scripts/debug_agent.py --experiment scripts/debugger/experiments/exp_001.yaml

    # 查询历史
    python scripts/debug_agent.py --list --agent search --limit 5

    # 对比两次运行
    python scripts/debug_agent.py --compare run_aaa111 run_bbb222
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# ── 路径设置（确保 backend/src 可被 import）─────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

# ── 加载 .env ────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = _ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # dotenv 不可用时静默跳过，依赖环境变量直接设置


# ─────────────────────────────────────────────
# UI 辅助函数（Unicode 框线，不依赖 rich）
# ─────────────────────────────────────────────

STATUS_ICONS = {
    "success": "✅",
    "failed":  "❌",
    "running": "🔄",
    "skipped": "⏭ ",
    "abort":   "🛑",
}


def _icon(status: str | None) -> str:
    """返回状态对应的图标，未知状态用 ❓。"""
    return STATUS_ICONS.get(status or "", "❓")


def _print_header(agent_name: str, run_id: str, model: str, plan: str) -> None:
    """打印运行信息框线头部。"""
    line = "═" * 56
    print(f"\n╔{line}╗")
    print(f"║  BioForge Agent Debugger{' ' * 31}║")
    print(f"║  agent={agent_name:<20} run_id={run_id:<14}║")
    print(f"║  model={model:<47}║")
    print(f"║  plan={plan:<48}║")
    print(f"╚{line}╝\n")


def _print_step_start(idx: int, total: int, step_id: str, tools: list[str]) -> None:
    """打印 step 开始行。"""
    tools_str = ", ".join(tools) if tools else "（无工具）"
    print(f"▶ STEP {idx}/{total}: {step_id}")
    print(f"  工具: {tools_str}")
    print(f"  {'─' * 50}")


def _print_step_end(status: str, duration_ms: float | None, retry: int, output: dict) -> None:
    """打印 step 结束行（含输出摘要）。"""
    icon = _icon(status)
    dur = f"{duration_ms/1000:.1f}s" if duration_ms else "?"
    retry_str = f"（重试{retry}次）" if retry > 0 else ""
    print(f"  {icon} {status}{retry_str}  耗时: {dur}")
    # 输出摘要（限制长度）
    out_str = json.dumps(output, ensure_ascii=False)
    if len(out_str) > 200:
        out_str = out_str[:197] + "..."
    print(f"  输出: {out_str}\n")


def _print_footer(status: str, total_ms: float, run_id: str, has_db: bool) -> None:
    """打印运行总结尾部。"""
    line = "─" * 56
    print(line)
    icon = _icon(status)
    print(f"validate_plan: {icon} 整体状态: {status}")
    print(f"总耗时: {total_ms/1000:.1f}s  |  run_id: {run_id}")
    if has_db:
        print("trace 已落库（agent_trace_events）")
    else:
        print("trace 已打印（未配置 TRACE_DB_URL，未落库）")
    print(line + "\n")


# ─────────────────────────────────────────────
# Agent 工厂加载
# ─────────────────────────────────────────────

# 已实现 agent 的工厂函数路径（None 表示尚未实现，调用时抛 NotImplementedError）
_AGENT_FACTORIES: dict[str, str | None] = {
    "search":  "backend.src.agents.search_agent.agent.create_search_agent",
    "screen":  None,   # TODO(编排负责人): screen_agent 实现后填入工厂函数路径
    "extract": None,   # TODO(编排负责人): extract_agent 实现后填入工厂函数路径
    "test":    "backend.src.agents.test_agent.agent.create_test_agent",
}


def _load_agent(agent_name: str, overrides: dict[str, Any]) -> Any:
    """加载指定 agent 并应用 overrides 参数。

    Args:
        agent_name: agent 标识（search / screen / extract / test）。
        overrides: 覆盖参数 dict（model / plan_path / temperature 等）。

    Returns:
        AgentTemplate 实例。

    Raises:
        NotImplementedError: screen / extract 尚未实现时。
        SystemExit: agent_name 不在已知列表时。
    """
    factory_path = _AGENT_FACTORIES.get(agent_name)

    if factory_path is None:
        if agent_name in _AGENT_FACTORIES:
            raise NotImplementedError(
                f"agent '{agent_name}' 尚未实现工厂函数，"
                f"请等待对应负责人完成 create_{agent_name}_agent() 后再使用。"
            )
        else:
            print(f"[错误] 未知 agent: '{agent_name}'。可选：{list(_AGENT_FACTORIES.keys())}")
            sys.exit(1)

    # 动态 import 工厂函数
    module_path, func_name = factory_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    factory_fn = getattr(module, func_name)

    # 根据 agent 类型决定参数
    if agent_name == "test":
        plan_name = overrides.pop("plan_name", "plan_happy_path")
        return factory_fn(plan_name=plan_name, overrides=overrides)
    else:
        return factory_fn(
            model=overrides.get("model", os.getenv("DEFAULT_LLM_MODEL", "minimax/MiniMax-M2.7-highspeed")),
        )


# ─────────────────────────────────────────────
# 运行逻辑（含流式 trace 打印）
# ─────────────────────────────────────────────

def _run_agent(args: argparse.Namespace) -> None:
    """执行 agent run 并实时打印进度。"""
    from backend.src.tools.test_agent.mock_flaky import reset_flaky_counters
    reset_flaky_counters()  # 每次 run 前重置 flaky 计数器，防止跨 run 污染

    # 生成 run_id
    run_id = args.run_id or f"debug_{uuid.uuid4().hex[:8]}"

    # 构建 overrides dict
    overrides: dict[str, Any] = {}
    if args.model:
        overrides["model"] = args.model
    if args.plan:
        # test_agent 用 plan_name，其他 agent 用 plan_path
        if args.agent == "test":
            overrides["plan_name"] = args.plan
        else:
            overrides["plan_path"] = args.plan
    if args.identity:
        overrides["identity_path"] = args.identity
    if args.skill:
        overrides["skills_override"] = dict(kv.split("=", 1) for kv in args.skill)

    # 加载实验配置（覆盖上面的参数）
    if args.experiment:
        exp_path = Path(args.experiment)
        if not exp_path.exists():
            print(f"[错误] 实验配置文件不存在: {exp_path}")
            sys.exit(1)
        import yaml
        with open(exp_path, encoding="utf-8") as f:
            exp = yaml.safe_load(f)
        if "overrides" in exp:
            overrides.update(exp["overrides"])
        if args.agent == "default" and "agent" in exp:
            args.agent = exp["agent"]

    # 加载 agent
    try:
        agent = _load_agent(args.agent, overrides)
    except NotImplementedError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    # 决定 trace backend
    trace_db_url = os.getenv("TRACE_DB_URL")
    has_db = bool(trace_db_url)
    if has_db:
        try:
            from backend.src.db_access.trace.postgres_backend import PostgresBackend
            agent.hook.backend = PostgresBackend()
        except Exception as e:
            print(f"[警告] PostgresBackend 初始化失败，回退 NullBackend：{e}")
            has_db = False
    else:
        print("[提示] 未配置 TRACE_DB_URL，trace 只打印到控制台，不落库。\n")

    # 打印头部
    plan_display = overrides.get("plan_name", overrides.get("plan_path", agent.plan.plan_id))
    model_display = overrides.get("model", os.getenv("DEFAULT_LLM_MODEL", "default"))
    _print_header(args.agent, run_id, model_display, str(plan_display))

    # 拦截 NullBackend 输出，改为格式化打印
    _step_tracker: dict[str, dict] = {}
    total_steps = len(agent.plan.steps)
    step_index = [0]

    # 注入自定义打印 backend（同时保留 DB 写入）
    from backend.src.agents.agent_template.hooks import TraceBackend, TraceEvent

    class CLIPrintBackend(TraceBackend):
        """把 TraceEvent 格式化为 CLI 结构化输出。"""
        def write(self, event: TraceEvent) -> None:
            et = event.event_type
            if et == "step_start":
                step_index[0] += 1
                sid = event.step_id or "?"
                _step_tracker[sid] = {"start_ms": time.monotonic() * 1000}
                tools = event.payload.get("tools_required", [])
                _print_step_start(step_index[0], total_steps, sid, tools)
            elif et == "step_end":
                sid = event.step_id or "?"
                retry = event.payload.get("retry_count", 0)
                output_keys = event.payload.get("output_keys", [])
                output_preview = {k: "..." for k in output_keys[:5]}
                _print_step_end(event.status or "?", event.duration_ms, retry, output_preview)

    # 根据是否有 DB 决定 backend 组合
    if has_db:
        # 同时写 DB 和打印
        from scripts.debugger.components.streamlit_backend import CompositeBackend
        from backend.src.db_access.trace.postgres_backend import PostgresBackend
        agent.hook.backend = CompositeBackend(PostgresBackend(), CLIPrintBackend())
    else:
        agent.hook.backend = CLIPrintBackend()

    # 执行 run
    start_ms = time.monotonic() * 1000
    try:
        _patch = agent.run(run_id=run_id)
        total_ms = time.monotonic() * 1000 - start_ms
        run_result = agent._last_run_result if hasattr(agent, "_last_run_result") else None
        status = "success"
        if run_result and hasattr(run_result, "status"):
            status = run_result.status
    except Exception as e:
        total_ms = time.monotonic() * 1000 - start_ms
        print(f"\n[错误] run() 执行失败：{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    _print_footer(status, total_ms, run_id, has_db)


# ─────────────────────────────────────────────
# --list 命令
# ─────────────────────────────────────────────

def _list_runs(args: argparse.Namespace) -> None:
    """列出最近的运行历史（从 trace DB 读取）。"""
    trace_db_url = os.getenv("TRACE_DB_URL")
    if not trace_db_url:
        print("[错误] --list 需要配置 TRACE_DB_URL 环境变量。")
        sys.exit(1)

    try:
        from backend.src.db_access.trace.postgres_backend import get_trace_engine
        from backend.src.db_access.trace.reader import get_recent_failed_steps, get_run_summary
        engine = get_trace_engine()
        if engine is None:
            print("[错误] 无法连接 trace DB，请检查 TRACE_DB_URL。")
            sys.exit(1)
    except ImportError as e:
        print(f"[错误] 无法加载 trace reader：{e}")
        sys.exit(1)

    stage_filter = args.agent if args.agent != "default" else None
    limit = args.limit or 10

    from sqlalchemy import text as sa_text
    with engine.connect() as conn:
        # 查最近 N 条 plan_end 事件（代表一次完整 run）
        sql = """
            SELECT run_id, agent_run_id, stage, status, duration_ms, created_at
            FROM agent_trace_events
            WHERE event_type = 'plan_end'
            {stage_clause}
            ORDER BY created_at DESC
            LIMIT :limit
        """.format(
            stage_clause="AND stage = :stage" if stage_filter else ""
        )
        params: dict = {"limit": limit}
        if stage_filter:
            params["stage"] = stage_filter
        rows = conn.execute(sa_text(sql), params).fetchall()

    if not rows:
        print("（无运行记录）")
        return

    print(f"\n{'─'*80}")
    print(f"{'run_id':<20} {'stage':<15} {'status':<10} {'耗时':>8}  {'时间'}")
    print(f"{'─'*80}")
    for row in rows:
        run_id, agent_run_id, stage, status, duration_ms, created_at = row
        icon = _icon(status)
        dur = f"{duration_ms/1000:.1f}s" if duration_ms else "  ?"
        ts = str(created_at)[:19]
        print(f"{run_id:<20} {stage:<15} {icon}{status:<9} {dur:>7}  {ts}")
    print(f"{'─'*80}\n")


# ─────────────────────────────────────────────
# --compare 命令
# ─────────────────────────────────────────────

def _compare_runs(args: argparse.Namespace) -> None:
    """对比两次运行的 trace（从 trace DB 读取）。"""
    trace_db_url = os.getenv("TRACE_DB_URL")
    if not trace_db_url:
        print("[错误] --compare 需要配置 TRACE_DB_URL 环境变量。")
        sys.exit(1)

    run_id_a, run_id_b = args.compare

    try:
        from backend.src.db_access.trace.postgres_backend import get_trace_engine
        from backend.src.db_access.trace.reader import get_run_events, get_run_summary
        engine = get_trace_engine()
        if engine is None:
            print("[错误] 无法连接 trace DB。")
            sys.exit(1)
    except ImportError as e:
        print(f"[错误] 无法加载 trace reader：{e}")
        sys.exit(1)

    events_a = get_run_events(engine, run_id_a)
    events_b = get_run_events(engine, run_id_b)
    summary_a = get_run_summary(engine, run_id_a)
    summary_b = get_run_summary(engine, run_id_b)

    print(f"\n{'═'*70}")
    print(f"  对比实验：{run_id_a}  vs  {run_id_b}")
    print(f"{'═'*70}")

    # 汇总行
    def _fmt_summary(s: dict, run_id: str) -> str:
        total_ms = sum(s.get("stage_duration_ms", {}).values() or [0])
        counts = s.get("status_counts", {})
        ok = counts.get("success", 0)
        fail = counts.get("failed", 0)
        return f"  run={run_id}  总耗时={total_ms/1000:.1f}s  成功={ok}步  失败={fail}步"

    print(_fmt_summary(summary_a, run_id_a))
    print(_fmt_summary(summary_b, run_id_b))

    # step 级对比
    def _events_by_step(events: list[dict]) -> dict[str, dict]:
        result = {}
        for ev in events:
            if ev.get("event_type") == "step_end":
                sid = ev.get("step_id") or "?"
                result[sid] = ev
        return result

    steps_a = _events_by_step(events_a)
    steps_b = _events_by_step(events_b)
    all_step_ids = sorted(set(list(steps_a.keys()) + list(steps_b.keys())))

    if all_step_ids:
        print(f"\n  {'step_id':<22} {'A 状态':<10} {'A 耗时':>8}   {'B 状态':<10} {'B 耗时':>8}  差异")
        print(f"  {'─'*75}")
        for sid in all_step_ids:
            ev_a = steps_a.get(sid)
            ev_b = steps_b.get(sid)
            sta = ev_a["status"] if ev_a else "N/A"
            stb = ev_b["status"] if ev_b else "N/A"
            dur_a = ev_a["duration_ms"] if ev_a else None
            dur_b = ev_b["duration_ms"] if ev_b else None
            dur_a_str = f"{dur_a/1000:.1f}s" if dur_a else "  N/A"
            dur_b_str = f"{dur_b/1000:.1f}s" if dur_b else "  N/A"
            # 差异描述
            diff = ""
            if dur_a and dur_b:
                delta = dur_b - dur_a
                diff = f"B {'快' if delta < 0 else '慢'} {abs(delta)/1000:.1f}s"
            if sta != stb:
                diff += f" | 状态不同"
            print(f"  {sid:<22} {_icon(sta)}{sta:<9} {dur_a_str:>8}   "
                  f"{_icon(stb)}{stb:<9} {dur_b_str:>8}  {diff}")

    print(f"{'═'*70}\n")


# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="BioForge Agent Debugger — 算子调优 CLI 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python scripts/debug_agent.py --agent test --plan plan_happy_path
  python scripts/debug_agent.py --agent test --plan plan_retry_scenario
  python scripts/debug_agent.py --agent search --model openai/gpt-4o
  python scripts/debug_agent.py --list --agent search --limit 5
  python scripts/debug_agent.py --compare run_aaa111 run_bbb222
  python scripts/debug_agent.py --experiment scripts/debugger/experiments/exp_001.yaml
        """,
    )

    # 核心参数
    parser.add_argument(
        "--agent",
        default="default",
        choices=["search", "screen", "extract", "test", "default"],
        help="要运行的 agent（default 用于 --experiment 模式）",
    )
    parser.add_argument(
        "--plan",
        default=None,
        help="plan 文件路径 或 plan 名（test_agent 专用，如 plan_retry_scenario）",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="覆盖模型字符串（LiteLLM 格式，如 openai/gpt-4o）",
    )
    parser.add_argument(
        "--identity",
        default=None,
        help="覆盖 identity.yaml 的文件路径",
    )
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        metavar="KEY=PATH",
        help="覆盖单个 skill 文件（可多次使用）：--skill pubmed_query=/path/v2.md",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="指定 run_id（默认自动生成 debug_<8hex>）",
    )
    parser.add_argument(
        "--experiment",
        default=None,
        metavar="YAML_PATH",
        help="实验配置文件路径（多参数覆盖时使用）",
    )

    # 查询命令
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出最近的运行历史（需配置 TRACE_DB_URL）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="--list 时返回的最大条数（默认 10）",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("RUN_ID_A", "RUN_ID_B"),
        help="对比两次运行的 trace（需配置 TRACE_DB_URL）",
    )

    return parser.parse_args()


def main() -> None:
    """CLI 主入口。"""
    args = parse_args()

    if args.list:
        _list_runs(args)
    elif args.compare:
        _compare_runs(args)
    else:
        if args.agent == "default" and not args.experiment:
            print("[错误] 请指定 --agent 或 --experiment。")
            print("       运行 python scripts/debug_agent.py --help 查看帮助。")
            sys.exit(1)
        _run_agent(args)


if __name__ == "__main__":
    main()
