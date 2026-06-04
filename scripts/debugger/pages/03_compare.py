"""
scripts/debugger/pages/03_compare.py — 对比实验页（最多3个 run 并排）

位置：scripts/debugger/pages/
依赖：components/trace_reader.py（cached_get_run_events, cached_get_run_summary,
                                   list_recent_runs）
      components/ui_helpers.py（render_diff_row, render_status_badge, format_ms）
职责：
  - 从 session_state["compare_list"] 或手动输入获取最多3个 run_id
  - 左侧选择面板 + 右侧并排展示
  - 配置差异对比（model / plan / stage）
  - Step 对比表：行=step_id，列=各 run 的状态/耗时/输出
  - 差异行自动高亮（颜色）
  - 底部生成文字摘要（"B 比 A 快 Xs，多 N 步，无重试"）

使用方式：
  - 在 01_runs.py 选中多条记录加入对比列表，然后导航到此页面
  - 或在此页面直接输入 run_id
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
from typing import Any

import streamlit as st

from components.ui_helpers import format_ms, render_diff_row, render_status_badge

# ─────────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="对比实验 — BioForge Debugger",
    page_icon="⚡",
    layout="wide",
)

st.title("⚡ 对比实验")
st.caption("并排对比最多 3 次运行，差异自动高亮。")


# ─────────────────────────────────────────────
# 检查 TRACE_DB_URL
# ─────────────────────────────────────────────

if not os.getenv("TRACE_DB_URL"):
    st.warning("⚠️ **TRACE_DB_URL 未配置**，无法查询历史运行记录进行对比。")
    st.stop()


# ─────────────────────────────────────────────
# Run ID 选择
# ─────────────────────────────────────────────

from components.trace_reader import (
    cached_get_run_events,
    cached_get_run_summary,
    list_recent_runs,
)

# 获取候选 run_id 列表（最近50条，用于 selectbox）
@st.cache_data(ttl=60, show_spinner=False)
def _get_recent_run_ids() -> list[str]:
    runs = list_recent_runs(limit=50)
    return [r["run_id"] for r in runs if r.get("run_id")]

recent_ids = _get_recent_run_ids()

# 初始化（从 session_state 的 compare_list 填充）
compare_list = st.session_state.get("compare_list", [])

with st.sidebar:
    st.markdown("### 📦 选择对比 Run")
    st.caption("从下拉框选择，或直接输入 run_id")

    selected_ids: list[str | None] = []
    for i in range(3):
        label = f"Run {chr(65 + i)}"  # A / B / C
        # 优先填充 compare_list 中的值
        default_id = compare_list[i] if i < len(compare_list) else None

        options = [None] + recent_ids
        option_labels = ["（不选）"] + [rid[:24] + "…" if len(rid) > 24 else rid for rid in recent_ids]

        if default_id and default_id not in recent_ids:
            # 手动输入的 run_id 不在最近列表中，用文本输入
            val = st.text_input(f"{label} run_id", value=default_id or "", key=f"cmp_input_{i}")
            selected_ids.append(val.strip() if val.strip() else None)
        else:
            idx = (recent_ids.index(default_id) + 1) if default_id in recent_ids else 0
            sel = st.selectbox(
                label,
                options=options,
                format_func=lambda x, opts=option_labels, ids=[None]+recent_ids: (
                    opts[ids.index(x)] if x in ids else str(x)
                ),
                index=idx,
                key=f"cmp_sel_{i}",
            )
            # 允许在 selectbox 下方额外手动输入
            manual = st.text_input(f"或手动输入 {label}", value="", key=f"cmp_manual_{i}", placeholder="run_id")
            selected_ids.append((manual.strip() or sel))

    st.markdown("---")
    if st.button("🔄 刷新数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# 过滤空值
active_ids = [rid for rid in selected_ids if rid]

if len(active_ids) < 2:
    st.info(
        "📭 请至少选择 **2 个** run_id 进行对比。\n\n"
        "可以从 **📋 运行历史** 页面点击「+」按钮加入对比列表，或在左侧直接输入 run_id。"
    )
    st.stop()


# ─────────────────────────────────────────────
# 查询数据
# ─────────────────────────────────────────────

run_data: dict[str, dict[str, Any]] = {}

for rid in active_ids:
    with st.spinner(f"查询 {rid[:16]}..."):
        events  = cached_get_run_events(rid)
        summary = cached_get_run_summary(rid)
        plan_end   = next((e for e in events if e.get("event_type") == "plan_end"), {})
        plan_start = next((e for e in events if e.get("event_type") == "plan_start"), {})
        step_events = [e for e in events if e.get("event_type") == "step_end"]

        extra = (plan_start or {}).get("extra") or {}
        run_data[rid] = {
            "events":      events,
            "summary":     summary,
            "plan_end":    plan_end,
            "plan_start":  plan_start,
            "step_events": step_events,
            "stage":       (plan_end or {}).get("stage", "—"),
            "status":      (plan_end or {}).get("status", "—"),
            "duration_ms": (plan_end or {}).get("duration_ms"),
            "model":       extra.get("model", "—"),
            "plan":        extra.get("plan_name", extra.get("plan_path", "—")),
            "total_events": len(events),
            "step_count":  len(step_events),
        }


# ─────────────────────────────────────────────
# 顶部：各 run 状态概览
# ─────────────────────────────────────────────

st.markdown("### 📊 运行概览")

cols = st.columns(len(active_ids))
label_names = [chr(65 + i) for i in range(len(active_ids))]

for col, rid, label in zip(cols, active_ids, label_names):
    data = run_data[rid]
    with col:
        st.markdown(f"#### Run {label}")
        st.code(rid[:24] + "…" if len(rid) > 24 else rid, language=None)
        st.markdown(render_status_badge(data["status"]), unsafe_allow_html=True)
        st.metric("⏱ 总耗时", format_ms(data["duration_ms"]))
        st.metric("🔧 Steps", data["step_count"])
        st.metric("📋 事件数", data["total_events"])


# ─────────────────────────────────────────────
# 配置差异对比
# ─────────────────────────────────────────────

st.markdown("---")
st.markdown("### ⚙️ 配置对比")
st.caption("差异字段用 ⚡ 标记并高亮显示")

# 对比字段：stage / status / model / plan / duration
for field, label in [
    ("stage",    "Stage"),
    ("status",   "状态"),
    ("model",    "模型"),
    ("plan",     "Plan"),
]:
    vals = [run_data[rid][field] for rid in active_ids]
    if len(active_ids) == 2:
        render_diff_row(label, vals[0], vals[1])
    else:
        # 3列对比
        col_label, *data_cols = st.columns([2] + [3] * len(active_ids))
        all_same = len(set(str(v) for v in vals)) == 1
        with col_label:
            prefix = "" if all_same else "⚡ "
            st.markdown(f"**{prefix}{label}**")
        for dc, v in zip(data_cols, vals):
            with dc:
                if not all_same:
                    st.markdown(
                        f'<span style="color:#00D4AA">{v}</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.text(str(v))


# ─────────────────────────────────────────────
# Step 对比表
# ─────────────────────────────────────────────

st.markdown("---")
st.markdown("### 🔧 Step 对比")
st.caption("行=step_id，列=各 run 的状态/耗时/重试次数")

# 收集所有 step_id（并集）
all_step_ids: list[str] = []
seen_ids: set[str] = set()
for rid in active_ids:
    for step in run_data[rid]["step_events"]:
        sid = step.get("step_id", "")
        if sid and sid not in seen_ids:
            all_step_ids.append(sid)
            seen_ids.add(sid)

if not all_step_ids:
    st.caption("未找到任何 step 事件记录。")
else:
    # 表头
    header_cols = st.columns([3] + [3] * len(active_ids))
    with header_cols[0]:
        st.markdown("**Step ID**")
    for i, (rid, label) in enumerate(zip(active_ids, label_names)):
        with header_cols[i + 1]:
            short_id = rid[:12] + "…" if len(rid) > 12 else rid
            st.markdown(f"**Run {label}** `{short_id}`")

    st.markdown("---")

    for sid in all_step_ids:
        row_cols = st.columns([3] + [3] * len(active_ids))

        # 查找各 run 对应该 step 的数据
        step_row_data: list[dict | None] = []
        for rid in active_ids:
            match = next(
                (s for s in run_data[rid]["step_events"] if s.get("step_id") == sid),
                None,
            )
            step_row_data.append(match)

        # 检查状态是否一致
        statuses = [s.get("status", "—") if s else "—" for s in step_row_data]
        all_same_status = len(set(statuses)) == 1

        with row_cols[0]:
            prefix = "⚡ " if not all_same_status else ""
            st.markdown(f"**{prefix}`{sid}`**")

        for col, step_ev in zip(row_cols[1:], step_row_data):
            with col:
                if step_ev is None:
                    st.caption("（无记录）")
                else:
                    s   = step_ev.get("status", "—")
                    dur = step_ev.get("duration_ms")
                    rc  = step_ev.get("retry_count", 0) or 0
                    tool = step_ev.get("tool", "—")

                    badge = render_status_badge(s)
                    st.markdown(badge, unsafe_allow_html=True)
                    st.caption(f"⏱ {format_ms(dur)}  🔧 {tool}" + (f"  🔁×{rc}" if rc > 0 else ""))


# ─────────────────────────────────────────────
# 自动文字摘要
# ─────────────────────────────────────────────

if len(active_ids) == 2:
    st.markdown("---")
    st.markdown("### 💡 自动摘要")

    rid_a, rid_b = active_ids[0], active_ids[1]
    da, db = run_data[rid_a], run_data[rid_b]

    summary_lines: list[str] = []

    # 耗时对比
    dur_a = da["duration_ms"]
    dur_b = db["duration_ms"]
    if dur_a and dur_b:
        diff = abs(dur_a - dur_b)
        faster = "B" if dur_b < dur_a else "A"
        summary_lines.append(f"- Run **{faster}** 更快，相差 **{format_ms(diff)}**（A={format_ms(dur_a)}，B={format_ms(dur_b)}）")

    # Step 数对比
    sc_a, sc_b = da["step_count"], db["step_count"]
    if sc_a != sc_b:
        more  = "B" if sc_b > sc_a else "A"
        extra = abs(sc_b - sc_a)
        summary_lines.append(f"- Run **{more}** 多执行了 **{extra}** 个 step")
    else:
        summary_lines.append(f"- 两次运行均执行了 **{sc_a}** 个 step")

    # 重试次数
    retry_a = sum((s.get("retry_count") or 0) for s in da["step_events"])
    retry_b = sum((s.get("retry_count") or 0) for s in db["step_events"])
    if retry_a == 0 and retry_b == 0:
        summary_lines.append("- 两次运行均**无重试**")
    elif retry_a == 0 and retry_b > 0:
        summary_lines.append(f"- Run A 无重试，Run B 有 **{retry_b}** 次重试")
    elif retry_a > 0 and retry_b == 0:
        summary_lines.append(f"- Run A 有 **{retry_a}** 次重试，Run B 无重试")
    else:
        summary_lines.append(f"- Run A 重试 **{retry_a}** 次，Run B 重试 **{retry_b}** 次")

    # 状态
    if da["status"] == db["status"]:
        summary_lines.append(f"- 两次运行状态相同：**{da['status']}**")
    else:
        summary_lines.append(f"- 状态不同：A={da['status']}，B={db['status']}")

    st.info("\n".join(summary_lines))
