"""
scripts/debugger/components/ui_helpers.py — Streamlit UI 工具函数库

位置：scripts/debugger/components/
依赖：streamlit（st.*）
职责：提供可复用的 UI 渲染函数，供各 Streamlit 页面共同使用。
      不含任何业务逻辑，只负责展示层。

导出函数：
  - render_status_badge(status)       → HTML 颜色徽章字符串
  - render_step_card(step_data)       → st.expander 包裹的 step 详情卡片
  - render_duration_chart(step_list)  → 各 step 耗时横向对比 bar_chart
  - render_diff_row(label, val_a, val_b) → 并排对比行（差异高亮）
  - format_ms(ms)                     → 毫秒格式化为人类可读字符串

使用方式（Streamlit 页面中）：
    from components.ui_helpers import (
        render_status_badge, render_step_card,
        render_duration_chart, render_diff_row, format_ms
    )
"""

from __future__ import annotations

import json
from typing import Any

import streamlit as st


# ─────────────────────────────────────────────
# 颜色 / 图标常量（全局统一）
# ─────────────────────────────────────────────

STATUS_COLORS: dict[str, str] = {
    "success":   "#00D4AA",   # teal — 成功
    "failed":    "#FF4B4B",   # red  — 失败
    "running":   "#FFA500",   # orange — 进行中
    "skipped":   "#888888",   # gray — 已跳过
    "partial":   "#FFD700",   # gold — 部分成功
    "unknown":   "#AAAAAA",   # light gray — 未知状态
    "replanned": "#A78BFA",   # purple — MODIFY_STEP replan（指令被 LLM 改写过）
}

STATUS_ICONS: dict[str, str] = {
    "success":   "✅",
    "failed":    "❌",
    "running":   "🔄",
    "skipped":   "⏭",
    "partial":   "⚠️",
    "unknown":   "❓",
    "replanned": "🔧",   # MODIFY_STEP replan
}


# ─────────────────────────────────────────────
# format_ms
# ─────────────────────────────────────────────

def format_ms(ms: float | None) -> str:
    """毫秒格式化为人类可读字符串。

    转换规则：
      < 1000ms  → "XXXms"（整数）
      ≥ 1000ms  → "X.Xs"（保留1位小数）
      None      → "—"

    Args:
        ms: 毫秒数值，可为 None。

    Returns:
        格式化后的字符串，如 "42ms"、"1.2s"、"—"。

    Examples:
        format_ms(42)     → "42ms"
        format_ms(1234)   → "1.2s"
        format_ms(None)   → "—"
        format_ms(60000)  → "60.0s"
    """
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{int(ms)}ms"
    return f"{ms / 1000:.1f}s"


# ─────────────────────────────────────────────
# render_status_badge
# ─────────────────────────────────────────────

def render_status_badge(status: str) -> str:
    """生成带颜色的 HTML 状态徽章字符串。

    返回一个 HTML <span> 字符串，调用方使用
    st.markdown(badge, unsafe_allow_html=True) 渲染。

    Args:
        status: 状态字符串（success / failed / running / skipped / partial / unknown）。

    Returns:
        HTML 字符串，含圆角、背景色、图标和状态文字。

    Example:
        st.markdown(render_status_badge("success"), unsafe_allow_html=True)
    """
    color = STATUS_COLORS.get(status, STATUS_COLORS["unknown"])
    icon  = STATUS_ICONS.get(status, STATUS_ICONS["unknown"])
    label = status.upper()
    return (
        f'<span style="'
        f'background-color:{color};'
        f'color:#000000;'
        f'padding:2px 10px;'
        f'border-radius:12px;'
        f'font-size:0.8em;'
        f'font-weight:bold;'
        f'letter-spacing:0.05em;'
        f'">{icon} {label}</span>'
    )


# ─────────────────────────────────────────────
# render_replan_card
# ─────────────────────────────────────────────

def render_replan_card(payload: dict) -> None:
    """渲染 MODIFY_STEP replan 事件卡片（两次 step 尝试之间的紫色分隔块）。

    在时间轴视图中作为独立元素插入，清晰分隔失败尝试与 replan 后的重试。
    展示：原始指令 vs 改写后指令（并排）、改写理由、触发时 retry_count、模型。
    """
    retry_at = payload.get("retry_count_at_replan", "?")
    orig     = payload.get("original_instruction") or "—"
    new_inst = payload.get("new_instruction") or "—"
    reason   = payload.get("replan_reason") or ""
    model    = payload.get("model_used") or ""

    # ── 紫色标题行
    model_str = f"  ·  模型：<code>{model}</code>" if model else ""
    st.markdown(
        f'<div style="border-left:4px solid #A78BFA; background:#1e1a2e; '
        f'padding:10px 14px; border-radius:6px; margin:10px 0 4px 0;">'
        f'<span style="color:#A78BFA; font-weight:bold; font-size:1.05em;">'
        f'🔧 MODIFY_STEP Replan 触发</span>'
        f'<span style="color:#888; font-size:0.85em; margin-left:12px;">'
        f'retry_count={retry_at}{model_str}</span></div>',
        unsafe_allow_html=True,
    )

    # ── 原始指令 vs 改写后指令（并排两列）
    col_orig, col_new = st.columns(2)
    with col_orig:
        st.markdown('<span style="color:#888; font-size:0.9em;">▶ 原始指令</span>',
                    unsafe_allow_html=True)
        st.markdown(
            f'<div style="background:#141420; padding:8px 10px; border-radius:4px; '
            f'font-size:0.82em; color:#aaa; white-space:pre-wrap; line-height:1.4;">'
            f'{orig[:200]}{"…" if len(orig) >= 200 else ""}</div>',
            unsafe_allow_html=True,
        )
    with col_new:
        st.markdown('<span style="color:#A78BFA; font-size:0.9em;">✨ 改写后指令</span>',
                    unsafe_allow_html=True)
        st.markdown(
            f'<div style="background:#1e1a2e; padding:8px 10px; border-radius:4px; '
            f'border:1px solid #A78BFA55; font-size:0.82em; color:#ddd; '
            f'white-space:pre-wrap; line-height:1.4;">'
            f'{new_inst[:200]}{"…" if len(new_inst) >= 200 else ""}</div>',
            unsafe_allow_html=True,
        )

    # ── 改写理由
    if reason:
        st.markdown(
            f'<div style="color:#A78BFA; font-size:0.85em; margin:6px 0 0 4px;">'
            f'💡 改写理由：{reason[:200]}</div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div style="border-bottom:1px solid #A78BFA44; margin:10px 0 6px 0;"></div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
# render_step_card
# ─────────────────────────────────────────────

def render_step_card(step_data: dict[str, Any], expanded: bool = True,
                     llm_events: list[dict[str, Any]] | None = None) -> None:
    """渲染单个 step 的详情卡片（st.expander 包裹）。

    TraceEvent.to_dict() 的实际结构：
      {
        "step_id": "step_01_basic",
        "status": "success" | "failed" | "running",
        "duration_ms": 21000.0,
        "event_type": "step_end",
        "payload": {
            "step_name": "基础成功步骤",
            "retry_count": 0,
            "error_message": None | "...",
            "output_keys": ["result", "value", ...],   # 只有 key，无 value
            "summary": {
                "what_was_done": "...",
                "what_was_produced": "...",
                "key_numbers": {...},
                "issues_encountered": "..."
            },
            # 以下来自 step_start payload（合并后才有）：
            "tools_required": ["mock_success"],
            "step_name": "...",
            "max_retries": 1,
        },
        # ⭐ MODIFY_STEP replan 信息（经历过 LLM 改写指令时由 _update_steps_state 注入）：
        "replan_history": [
            {
                "trigger": "modify_step",
                "original_instruction": "...(截断200字)",
                "new_instruction": "...(截断200字)",
                "replan_reason": "...",
                "retry_count_at_replan": 1,
                "model_used": "minimax/...",
            },
            ...  # 可能有多次 replan
        ]
      }

    Args:
        step_data: TraceEvent.to_dict() 输出（step_start + step_end 合并后的 dict）。
        expanded: expander 默认是否展开（默认 True）。
        llm_events: LLM/工具调用事件列表（_UITracer 捕获），用于渲染思考链。
    """
    step_id   = step_data.get("step_id", "unknown_step")
    status    = step_data.get("status", "unknown")
    duration  = step_data.get("duration_ms")

    # payload 是嵌套 dict，所有 step 级信息在此
    payload   = step_data.get("payload") or {}
    step_name = payload.get("step_name", step_id)
    retry_cnt = int(payload.get("retry_count") or 0)
    error_msg = payload.get("error_message")
    out_keys  = payload.get("output_keys") or []
    summary   = payload.get("summary") or {}
    tools     = payload.get("tools_required") or []
    tool_str  = ", ".join(tools) if tools else "—"

    icon    = STATUS_ICONS.get(status, STATUS_ICONS["unknown"])
    dur_str = format_ms(duration)
    title   = f"{icon} {step_id}  ·  {step_name}  ·  {dur_str}"

    with st.expander(title, expanded=expanded):

        # ── 顶部状态行
        col_badge, col_tool, col_dur = st.columns([2, 3, 2])
        with col_badge:
            st.markdown(render_status_badge(status), unsafe_allow_html=True)
        with col_tool:
            st.markdown(f"**🔧 工具：** `{tool_str}`")
        with col_dur:
            st.markdown(f"**⏱ 耗时：** {dur_str}")

        # ── 重试提示
        if retry_cnt > 0:
            st.warning(f"🔁 该 step 重试了 **{retry_cnt}** 次")

        # ⭐ MODIFY_STEP replan 详情（LLM 曾改写过指令时展示）
        replan_history = step_data.get("replan_history") or []
        if replan_history:
            with st.expander(
                f"🔧 MODIFY_STEP Replan（共改写 {len(replan_history)} 次）",
                expanded=True,
            ):
                for i, rp in enumerate(replan_history, 1):
                    if len(replan_history) > 1:
                        st.markdown(f"**第 {i} 次改写**")
                    retry_at = rp.get("retry_count_at_replan", "?")
                    model_used = rp.get("model_used", "")
                    st.caption(
                        f"触发时 retry_count={retry_at}"
                        + (f"  ·  模型：`{model_used}`" if model_used else "")
                    )
                    col_orig, col_new = st.columns(2)
                    orig = rp.get("original_instruction") or "—"
                    new  = rp.get("new_instruction") or "—"
                    with col_orig:
                        st.markdown("**原始指令**")
                        st.caption(orig + ("…" if len(orig) >= 200 else ""))
                    with col_new:
                        st.markdown("**改写后指令**")
                        st.caption(new + ("…" if len(new) >= 200 else ""))
                    reason = rp.get("replan_reason") or ""
                    if reason:
                        st.info(f"💡 改写理由：{reason}")

        st.divider()

        # ── 执行摘要（来自 summary.what_was_done / what_was_produced）
        col_done, col_produced = st.columns(2)

        with col_done:
            st.markdown("**🎯 执行了什么**")
            what_done = summary.get("what_was_done") or "—"
            st.caption(what_done)

        with col_produced:
            st.markdown("**📦 产出内容**")
            what_produced = summary.get("what_was_produced") or "—"
            st.caption(what_produced)
            if out_keys:
                st.caption(f"输出字段：`{'`, `'.join(out_keys)}`")

        # ── key_numbers（可量化数字摘要）
        key_nums = summary.get("key_numbers") or {}
        if key_nums:
            st.divider()
            st.markdown("**📊 关键数字**")
            kn_cols = st.columns(min(len(key_nums), 4))
            for col, (k, v) in zip(kn_cols, key_nums.items()):
                col.metric(k, v)

        # ── 错误信息
        issues = summary.get("issues_encountered") or error_msg
        if status == "failed" and issues:
            st.divider()
            st.error(f"❌ 错误：{issues}")

        # ── LLM 思考链（由 _UITracer 捕获的实时回调事件）
        if llm_events is not None:
            st.divider()
            with st.expander("🧠 LLM 思考链（ReAct 详情）", expanded=False):
                render_llm_trace(llm_events)


# ─────────────────────────────────────────────
# render_llm_trace
# ─────────────────────────────────────────────

def render_llm_trace(llm_events: list[dict[str, Any]]) -> None:
    """在 st.expander 内渲染 LLM / 工具调用的思考链。

    每次 step 执行时，create_react_agent 的完整 ReAct 循环：
      LLM call 1（决策 → 选择工具）→ tool_call → tool_result → LLM call 2（总结）

    事件格式（由 _UITracer 写入 progress_queue）：
      {"event_type": "llm_start",   "content": "...", "model": "..."}
      {"event_type": "llm_end",     "content": "..."}
      {"event_type": "tool_call",   "tool": "mock_success", "input": "..."}
      {"event_type": "tool_result", "output": "..."}
      {"event_type": "llm_error",   "error": "..."}

    Args:
        llm_events: 该 step 的 LLM/tool 事件列表（按时间顺序）。
    """
    if not llm_events:
        st.caption("暂无 LLM 调用记录（步骤运行结束后显示）")
        return

    call_num = 0  # LLM call 编号
    for ev in llm_events:
        etype = ev.get("event_type", "")

        if etype == "llm_start":
            call_num += 1
            model = ev.get("model", "")
            label = f"🤖 LLM Call #{call_num}" + (f" `{model}`" if model else "")
            with st.expander(label, expanded=False):
                content = ev.get("content", "")
                if content:
                    st.caption("**输入（用户/系统消息摘要）：**")
                    st.text(content)
                else:
                    st.caption("（无输入内容）")

        elif etype == "llm_end":
            content = ev.get("content", "")
            if content:
                # 判断是否是 tool_use 响应（含 tool call）还是最终回答
                is_final = call_num > 1  # 第2次及以后通常是最终回答
                icon = "💬 最终回答" if is_final else "💭 LLM 决策"
                with st.expander(icon, expanded=is_final):
                    st.text(content)

        elif etype == "tool_call":
            tool = ev.get("tool", "?")
            inp  = ev.get("input", "")
            with st.expander(f"🔧 调用工具：`{tool}`", expanded=True):
                st.caption("**入参：**")
                # 尝试以 JSON 格式渲染入参
                try:
                    import json as _json
                    parsed = _json.loads(inp) if isinstance(inp, str) else inp
                    st.code(_json.dumps(parsed, ensure_ascii=False, indent=2), language="json")
                except Exception:
                    st.text(str(inp))

        elif etype == "tool_result":
            output = ev.get("output", "")
            with st.expander("📥 工具返回", expanded=True):
                try:
                    import json as _json
                    parsed = _json.loads(output) if isinstance(output, str) else output
                    st.code(_json.dumps(parsed, ensure_ascii=False, indent=2), language="json")
                except Exception:
                    st.text(str(output))

        elif etype == "llm_error":
            st.error(f"❌ LLM 报错：{ev.get('error', '未知错误')}")


def _render_json_or_text(value: Any, max_chars: int = 500) -> None:
    """尝试将 value 渲染为 JSON（若为 dict/list），否则渲染为纯文本。

    超过 max_chars 时截断显示，并附提示。

    Args:
        value: 要渲染的数据（dict / list / str / 其他）。
        max_chars: 最大显示字符数。
    """
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
            if len(text) > max_chars:
                st.code(text[:max_chars] + "\n… (已截断)", language="json")
            else:
                st.code(text, language="json")
        except Exception:
            st.text(str(value)[:max_chars])
    else:
        text = str(value)
        if len(text) > max_chars:
            st.text(text[:max_chars] + "\n… (已截断)")
        else:
            st.text(text)


# ─────────────────────────────────────────────
# render_duration_chart
# ─────────────────────────────────────────────

def render_duration_chart(step_results: list[dict[str, Any]]) -> None:
    """渲染各 step 耗时横向对比 bar_chart。

    Args:
        step_results: list[dict]，每个 dict 至少含：
                      step_id (str) 和 duration_ms (float | None)。
                      按 step_id 排序显示。
    """
    if not step_results:
        st.caption("暂无 step 数据")
        return

    # 构建 {step_id: duration_ms} dict（None → 0）
    data: dict[str, float] = {}
    for s in step_results:
        sid = s.get("step_id", "unknown")
        dur = s.get("duration_ms")
        data[sid] = float(dur) if dur is not None else 0.0

    if not data:
        st.caption("暂无耗时数据")
        return

    # st.bar_chart 接受 dict 或 DataFrame（此处用 dict，列名=step_id）
    import pandas as pd
    df = pd.DataFrame.from_dict(
        {"duration_ms": data},
        orient="columns",
    )
    st.bar_chart(df, color="#00D4AA")


# ─────────────────────────────────────────────
# render_diff_row
# ─────────────────────────────────────────────

def render_diff_row(label: str, val_a: Any, val_b: Any) -> None:
    """对比模式：左右两列并排显示，差异时用颜色高亮。

    三列布局：[label | val_a | val_b]
    若 val_a != val_b，左侧标签加 ⚡ 标记，val_a 用红色，val_b 用绿色。

    Args:
        label: 对比字段的标签文字。
        val_a: 第一个 run 的值。
        val_b: 第二个 run 的值。
    """
    # 序列化为字符串便于比较和展示
    str_a = _to_display_str(val_a)
    str_b = _to_display_str(val_b)
    is_diff = str_a != str_b

    col_label, col_a, col_b = st.columns([2, 3, 3])

    with col_label:
        if is_diff:
            st.markdown(f"⚡ **{label}**")
        else:
            st.markdown(f"**{label}**")

    with col_a:
        if is_diff:
            st.markdown(
                f'<span style="color:#FF4B4B">{str_a}</span>',
                unsafe_allow_html=True,
            )
        else:
            st.text(str_a)

    with col_b:
        if is_diff:
            st.markdown(
                f'<span style="color:#00D4AA">{str_b}</span>',
                unsafe_allow_html=True,
            )
        else:
            st.text(str_b)


def _to_display_str(value: Any) -> str:
    """将任意值转换为人类可读的展示字符串。

    Args:
        value: 任意值。

    Returns:
        字符串表示（dict/list 用紧凑 JSON，其他用 str()）。
    """
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            pass
    return str(value)


# ─────────────────────────────────────────────
# render_run_summary_metrics
# ─────────────────────────────────────────────

def render_run_summary_metrics(summary: dict[str, Any]) -> None:
    """渲染 run 聚合指标（4 个 st.metric 卡片）。

    Args:
        summary: cached_get_run_summary() 的返回值，含：
                 total_events / event_type_counts / stage_duration_ms / status_counts
    """
    if not summary:
        st.caption("暂无聚合数据（TRACE_DB_URL 未配置或 run_id 不存在）")
        return

    total       = summary.get("total_events", "—")
    step_count  = (summary.get("event_type_counts") or {}).get("step_end", "—")
    status_cnts = summary.get("status_counts") or {}
    success_cnt = status_cnts.get("success", 0)
    failed_cnt  = status_cnts.get("failed", 0)

    # 总耗时：取 stage_duration_ms 中最大值（整个 plan 耗时）
    dur_map     = summary.get("stage_duration_ms") or {}
    total_dur   = max(dur_map.values()) if dur_map else None

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📋 总事件数", total)
    col2.metric("🔧 Step 数", step_count)
    col3.metric("✅ 成功", success_cnt)
    col4.metric("⏱ 总耗时", format_ms(total_dur))

    if failed_cnt > 0:
        st.warning(f"⚠️ 本次运行有 **{failed_cnt}** 个 step 失败")
