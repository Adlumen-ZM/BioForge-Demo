"""
scripts/debugger/pages/02_detail.py — 单次运行详情页

位置：scripts/debugger/pages/
依赖：components/trace_reader.py（cached_get_run_events, cached_get_run_summary）
      components/ui_helpers.py（render_step_card, render_status_badge, format_ms,
                                render_run_summary_metrics, render_duration_chart）
职责：
  - 从 URL query_params 或 session_state 读取 run_id
  - 顶部4列展示 run_id / stage / 状态 / 总耗时
  - 配置折叠区：model / plan / agent_run_id
  - 各 step st.expander 卡片：工具 / 输入 / 输出 / 耗时 / 重试
  - 底部 st.bar_chart 耗时对比

使用方式：
  - 从 01_runs.py 点击「查看详情」跳转（run_id 写入 session_state）
  - 或直接访问 /02_detail?run_id=xxx
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

from components.ui_helpers import (
    format_ms,
    render_duration_chart,
    render_run_summary_metrics,
    render_status_badge,
    render_step_card,
)

# ─────────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="运行详情 — BioForge Debugger",
    page_icon="🔍",
    layout="wide",
)

st.title("🔍 运行详情")


# ─────────────────────────────────────────────
# 确定 run_id
# ─────────────────────────────────────────────

# 优先从 URL query_params 读取；其次从 session_state 读取
params = st.query_params
run_id: str | None = params.get("run_id") or st.session_state.get("selected_run_id")

if not run_id:
    st.warning(
        "⚠️ 未指定 run_id。\n\n"
        "请从 **📋 运行历史** 页面点击「查看详情」，或在下方手动输入 run_id。"
    )
    manual_id = st.text_input("手动输入 run_id", placeholder="debug_xxxxxxxx")
    if manual_id:
        run_id = manual_id.strip()
    else:
        st.stop()


# ─────────────────────────────────────────────
# 检查 TRACE_DB_URL
# ─────────────────────────────────────────────

if not os.getenv("TRACE_DB_URL"):
    st.warning(
        "⚠️ **TRACE_DB_URL 未配置**，无法从数据库查询事件。\n\n"
        "如果你刚完成一次流式运行，详情数据保存在 `st.session_state['last_result']`，"
        "但需要 DB 才能查看完整 trace 事件。"
    )
    # 尝试显示 session_state 中的最近结果
    last_result = st.session_state.get("last_result")
    if last_result:
        st.markdown("---")
        st.subheader("📦 最近运行结果（session_state）")
        st.json(last_result)
    st.stop()


# ─────────────────────────────────────────────
# 查询数据
# ─────────────────────────────────────────────

from components.trace_reader import cached_get_run_events, cached_get_run_summary

with st.spinner(f"查询 run_id=`{run_id}` 的事件..."):
    events  = cached_get_run_events(run_id)
    summary = cached_get_run_summary(run_id)

if not events:
    st.error(f"❌ 未找到 run_id=`{run_id}` 的任何事件记录。\n\n请确认 run_id 正确，或该 run 已写入 DB。")
    st.stop()


# ─────────────────────────────────────────────
# 顶部摘要行
# ─────────────────────────────────────────────

# 从 plan_end 事件提取基本信息
plan_end = next((e for e in events if e.get("event_type") == "plan_end"), None)
plan_start = next((e for e in events if e.get("event_type") == "plan_start"), None)
first_event = events[0] if events else {}

stage    = (plan_end or first_event).get("stage", "—")
status   = (plan_end or {}).get("status", "—")
dur_ms   = (plan_end or {}).get("duration_ms")
agent_run_id = first_event.get("agent_run_id", "—")

# 面包屑导航
st.caption(f"**Run ID：** `{run_id}`")

col1, col2, col3, col4 = st.columns(4)
col1.metric("🎯 Stage",  stage)
col2.markdown(f"**状态**<br>{render_status_badge(status)}", unsafe_allow_html=True)
col3.metric("⏱ 总耗时", format_ms(dur_ms))
col4.metric("📋 事件总数", len(events))

st.markdown("---")


# ─────────────────────────────────────────────
# 聚合指标
# ─────────────────────────────────────────────

render_run_summary_metrics(summary)

st.markdown("---")


# ─────────────────────────────────────────────
# 配置信息（折叠）
# ─────────────────────────────────────────────

with st.expander("⚙️ 运行配置", expanded=False):
    cfg_col1, cfg_col2 = st.columns(2)
    with cfg_col1:
        st.markdown(f"**agent_run_id：** `{agent_run_id}`")
        st.markdown(f"**run_id：** `{run_id}`")
    with cfg_col2:
        # 从 plan_start 事件提取 extra 字段
        extra = (plan_start or {}).get("extra") or {}
        model = extra.get("model", "—")
        plan  = extra.get("plan_name", extra.get("plan_path", "—"))
        st.markdown(f"**模型：** `{model}`")
        st.markdown(f"**Plan：** `{plan}`")

    if extra:
        st.markdown("**完整 extra 字段：**")
        st.json(extra)


# ─────────────────────────────────────────────
# Step 详情卡片
# ─────────────────────────────────────────────

st.markdown("### 🔧 Step 执行详情")

# 提取所有 step_end 事件（按 created_at 升序）
step_events = [e for e in events if e.get("event_type") == "step_end"]

if not step_events:
    st.caption("未找到 step_end 事件记录。")
else:
    for i, step in enumerate(step_events):
        render_step_card(step, expanded=(i == 0))


# ─────────────────────────────────────────────
# 耗时对比图
# ─────────────────────────────────────────────

if step_events:
    st.markdown("---")
    st.markdown("### 📊 各 Step 耗时")
    render_duration_chart(step_events)


# ─────────────────────────────────────────────
# 完整事件时间线（折叠）
# ─────────────────────────────────────────────

with st.expander("📜 完整事件时间线", expanded=False):
    st.caption("按 created_at 升序排列的全部 trace 事件")
    for ev in events:
        etype  = ev.get("event_type", "—")
        sid    = ev.get("step_id", "")
        estatus = ev.get("status", "")
        edur   = ev.get("duration_ms")
        ecreated = str(ev.get("created_at", ""))[:19]

        badge = render_status_badge(estatus) if estatus else ""
        dur_str = format_ms(edur) if edur else ""

        line_parts = [f"`{ecreated}`", f"**{etype}**"]
        if sid:
            line_parts.append(f"`{sid}`")
        if badge:
            line_parts.append(badge)
        if dur_str:
            line_parts.append(f"⏱ {dur_str}")

        st.markdown("　".join(line_parts), unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 侧边栏操作
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🛠 操作")

    if st.button("🔄 刷新数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    compare_list = st.session_state.get("compare_list", [])
    if run_id not in compare_list:
        if st.button("📦 加入对比列表", use_container_width=True):
            if len(compare_list) < 3:
                st.session_state["compare_list"] = compare_list + [run_id]
                st.success("已加入对比列表")
                st.rerun()
            else:
                st.warning("对比列表已满（最多3条）")
    else:
        if st.button("✅ 已在对比列表（点击移除）", use_container_width=True):
            st.session_state["compare_list"] = [r for r in compare_list if r != run_id]
            st.rerun()

    st.markdown("---")
    if st.button("← 返回运行历史", use_container_width=True):
        st.switch_page("pages/01_runs.py")
