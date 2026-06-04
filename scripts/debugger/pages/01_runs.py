"""
scripts/debugger/pages/01_runs.py — 运行历史列表页

位置：scripts/debugger/pages/
依赖：components/trace_reader.py（list_recent_runs）
      components/ui_helpers.py（render_status_badge、format_ms）
职责：
  - 从 trace DB 拉取最近 N 条 plan_end 事件，构造运行历史列表
  - 支持按 stage / 状态 / 时间范围筛选
  - 每行末尾提供「查看详情」和「加入对比」快捷按钮
  - 底部展示今日运行统计 metric 和历史趋势图

使用方式：通过 app.py 侧边栏导航进入，或直接访问 /01_runs
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── 路径设置 ──────────────────────────────────────────────────────────────────
_DEBUGGER_DIR = Path(__file__).parent.parent
_SCRIPTS_DIR  = _DEBUGGER_DIR.parent
_ROOT         = _SCRIPTS_DIR.parent

for _p in [str(_ROOT), str(_SCRIPTS_DIR), str(_DEBUGGER_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import os

import streamlit as st

from components.ui_helpers import format_ms, render_status_badge

# ─────────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="运行历史 — BioForge Debugger",
    page_icon="📋",
    layout="wide",
)

st.title("📋 运行历史")
st.caption("查看所有历史 agent 运行记录。点击「查看详情」跳转单次运行页面。")


# ─────────────────────────────────────────────
# 检查 TRACE_DB_URL
# ─────────────────────────────────────────────

if not os.getenv("TRACE_DB_URL"):
    st.warning(
        "⚠️ **TRACE_DB_URL 未配置**，无法查询历史运行记录。\n\n"
        "请在 `.env` 中配置 `TRACE_DB_URL=postgresql://...`，然后重启 Streamlit。\n\n"
        "如需直接运行 agent，请前往 **⚙️ 运行编辑器** 页面。"
    )
    st.stop()


# ─────────────────────────────────────────────
# 侧边栏筛选器
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🔍 筛选条件")

    stage_options = ["（全部）", "search_agent", "test_agent", "screen_agent", "extract_agent"]
    selected_stage = st.selectbox("Agent 类型", stage_options, index=0)
    stage_filter = None if selected_stage == "（全部）" else selected_stage

    status_options = ["（全部）", "success", "failed", "partial"]
    selected_status = st.selectbox("运行状态", status_options, index=0)
    status_filter = None if selected_status == "（全部）" else selected_status

    time_options = {"全部时间": None, "最近 24 小时": 24, "最近 7 天": 168, "最近 30 天": 720}
    selected_time = st.selectbox("时间范围", list(time_options.keys()), index=0)
    time_range_hours = time_options[selected_time]

    limit = st.slider("最大显示条数", min_value=10, max_value=200, value=50, step=10)

    st.markdown("---")
    if st.button("🔄 刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ─────────────────────────────────────────────
# 查询运行列表
# ─────────────────────────────────────────────

from components.trace_reader import list_recent_runs

with st.spinner("查询运行历史..."):
    runs = list_recent_runs(
        stage=stage_filter,
        status_filter=status_filter,
        time_range_hours=time_range_hours,
        limit=limit,
    )


# ─────────────────────────────────────────────
# 顶部统计 Metrics
# ─────────────────────────────────────────────

if runs:
    total_runs   = len(runs)
    success_runs = sum(1 for r in runs if r.get("status") == "success")
    failed_runs  = sum(1 for r in runs if r.get("status") == "failed")
    success_rate = f"{success_runs / total_runs * 100:.0f}%" if total_runs > 0 else "—"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📊 显示条数", total_runs)
    col2.metric("✅ 成功", success_runs)
    col3.metric("❌ 失败", failed_runs)
    col4.metric("📈 成功率", success_rate)

    st.markdown("---")


# ─────────────────────────────────────────────
# 运行列表
# ─────────────────────────────────────────────

if not runs:
    st.info("📭 没有符合条件的运行记录。请尝试调整筛选条件，或先在「运行编辑器」页面运行一个 agent。")
else:
    # 表头
    hcols = st.columns([3, 2, 2, 2, 2, 1, 1])
    headers = ["Run ID", "Stage", "状态", "耗时", "时间", "详情", "对比"]
    for hcol, header in zip(hcols, headers):
        hcol.markdown(f"**{header}**")

    st.markdown("---")

    for run in runs:
        run_id    = run.get("run_id", "")
        stage     = run.get("stage", "—")
        status    = run.get("status", "unknown")
        dur_ms    = run.get("duration_ms")
        created   = run.get("created_at", "—")

        # 截断过长的 run_id / 时间
        run_id_short = run_id[:24] + "…" if len(run_id) > 24 else run_id
        created_short = created[:19] if len(created) > 19 else created  # 截断毫秒部分

        rcols = st.columns([3, 2, 2, 2, 2, 1, 1])

        with rcols[0]:
            st.code(run_id_short, language=None)
        with rcols[1]:
            st.text(stage)
        with rcols[2]:
            st.markdown(render_status_badge(status), unsafe_allow_html=True)
        with rcols[3]:
            st.text(format_ms(dur_ms))
        with rcols[4]:
            st.caption(created_short)
        with rcols[5]:
            if st.button("🔍", key=f"detail_{run_id}", help="查看详情"):
                st.session_state["selected_run_id"] = run_id
                st.switch_page("pages/02_detail.py")
        with rcols[6]:
            compare_list = st.session_state.get("compare_list", [])
            already_in = run_id in compare_list
            btn_label = "✓" if already_in else "+"
            btn_help  = "已加入对比列表" if already_in else "加入对比列表（最多3条）"
            if st.button(btn_label, key=f"compare_{run_id}", help=btn_help):
                if not already_in and len(compare_list) < 3:
                    st.session_state["compare_list"] = compare_list + [run_id]
                    st.rerun()
                elif already_in:
                    st.session_state["compare_list"] = [r for r in compare_list if r != run_id]
                    st.rerun()
                else:
                    st.warning("对比列表最多支持 3 条，请先移除一条。")


# ─────────────────────────────────────────────
# 底部趋势图（按 stage 分组的运行数量）
# ─────────────────────────────────────────────

if runs and len(runs) > 2:
    st.markdown("---")
    st.markdown("### 📊 耗时分布")

    import pandas as pd

    chart_data = {
        r.get("run_id", "")[:12]: (r.get("duration_ms") or 0)
        for r in runs[:20]  # 最多展示20条
    }
    if chart_data:
        df_chart = pd.DataFrame.from_dict(
            {"duration_ms": chart_data},
            orient="columns",
        )
        st.bar_chart(df_chart, color="#00D4AA")

    # 按状态统计
    st.markdown("### 📈 状态分布")
    status_counts: dict[str, int] = {}
    for r in runs:
        s = r.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    if status_counts:
        df_status = pd.DataFrame.from_dict(
            {"count": status_counts},
            orient="columns",
        )
        st.bar_chart(df_status)
