"""
scripts/debugger/app.py — BioForge Debugger Streamlit 多页面主入口

位置：scripts/debugger/
启动：cd scripts/debugger && streamlit run app.py
依赖：streamlit>=1.35.0，components/*

页面结构：
  01_runs.py   — 运行历史列表（筛选 / 排序 / 进入详情）
  02_detail.py — 单次运行详情（step 卡片 / 耗时图）
  03_compare.py — 对比实验（最多3个 run 并排）
  04_editor.py — 配置编辑 + 流式运行（核心页面）

session_state 全局键（各页面共同使用）：
  selected_run_id  : str | None  — 当前查看的 run_id（01 → 02 跳转）
  compare_list     : list[str]   — 待对比的 run_id 列表（最多3条）
  last_result      : dict | None — 最近一次 run_streaming 的结果
  last_run_id      : str | None  — 最近一次运行的 run_id
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── 路径设置（确保 backend / scripts 可被 import）────────────────────────────
_DEBUGGER_DIR = Path(__file__).parent        # scripts/debugger/
_SCRIPTS_DIR  = _DEBUGGER_DIR.parent         # scripts/
_ROOT         = _SCRIPTS_DIR.parent          # 项目根目录

for _p in [str(_ROOT), str(_SCRIPTS_DIR), str(_DEBUGGER_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st

# ─────────────────────────────────────────────
# 页面配置（必须在任何其他 st.* 之前调用）
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="BioForge Debugger",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get help": None,
        "Report a bug": None,
        "About": "BioForge 算子调优调试工具 — AgentTemplate Debugger v0.1",
    },
)


# ─────────────────────────────────────────────
# 全局 session_state 初始化
# ─────────────────────────────────────────────

def _init_session_state() -> None:
    """初始化全局 session_state 键（缺失时设为默认值）。

    使用 setdefault 模式，保证热重载 / 多次调用安全。
    """
    defaults = {
        "selected_run_id": None,   # 01_runs → 02_detail 的跳转目标
        "compare_list":    [],     # 待对比 run_id（最多3条）
        "last_result":     None,   # 04_editor 最近一次运行结果
        "last_run_id":     None,   # 04_editor 最近一次 run_id
        "editor_agent":    "test", # 04_editor 上次选择的 agent
        "editor_plan":     "plan_happy_path",  # 04_editor 上次选择的 plan
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


_init_session_state()


# ─────────────────────────────────────────────
# 侧边栏
# ─────────────────────────────────────────────

def _render_sidebar() -> None:
    """渲染主页侧边栏（导航说明 + 状态摘要 + 快捷入口）。"""
    with st.sidebar:
        st.markdown("## 🧬 BioForge Debugger")
        st.markdown("---")

        st.markdown("### 📄 页面导航")
        st.page_link("pages/01_runs.py",   label="📋 运行历史",   help="查看历史 agent 运行记录，支持按 stage/状态/时间筛选")
        st.page_link("pages/02_detail.py", label="🔍 运行详情",   help="单次运行的逐 step 详情，含 LLM 思考链")
        st.page_link("pages/03_compare.py",label="⚡ 对比实验",   help="并排对比最多3次运行，差异自动高亮")
        st.page_link("pages/04_editor.py", label="⚙️ 运行编辑器", help="配置编辑 + 流式运行，step 卡片实时出现")
        st.markdown("---")

        # ── 当前 session 状态摘要
        st.markdown("### 📊 Session 状态")

        selected = st.session_state.get("selected_run_id")
        if selected:
            st.success(f"📌 当前查看：`{selected[:20]}…`" if len(selected) > 20 else f"📌 当前查看：`{selected}`")
        else:
            st.caption("未选择 run_id")

        compare_list = st.session_state.get("compare_list", [])
        if compare_list:
            st.info(f"📦 对比列表：{len(compare_list)} 条")
            if st.button("🗑 清空对比列表", use_container_width=True):
                st.session_state["compare_list"] = []
                st.rerun()
        else:
            st.caption("对比列表为空")

        last_result = st.session_state.get("last_result")
        if last_result:
            last_run_id = st.session_state.get("last_run_id", "—")
            status = last_result.get("status", "unknown")
            icon = "✅" if status == "success" else "❌"
            st.markdown(f"**最近运行**：{icon} `{last_run_id}`")

        st.markdown("---")

        # ── 环境信息
        st.markdown("### 🌍 环境")
        import os
        trace_url = os.getenv("TRACE_DB_URL")
        if trace_url:
            st.success("🗄 Trace DB 已配置")
        else:
            st.warning("⚠️ TRACE_DB_URL 未配置\n（历史页面不可用）")

        default_model = os.getenv("DEFAULT_LLM_MODEL", "minimax/MiniMax-M2.7-highspeed")
        st.caption(f"默认模型：`{default_model}`")
        st.caption("v0.1 · Apache 2.0")


_render_sidebar()


# ─────────────────────────────────────────────
# 主页内容
# ─────────────────────────────────────────────

st.title("🧬 BioForge Debugger")
st.markdown("**AgentTemplate 算子调优工具** — 配置编辑、流式运行、trace 查看、实验对比。")

st.info(
    "👈 **使用侧边栏导航前往各功能页面**，或直接点击左侧页面列表。\n\n"
    "推荐从 **⚙️ 运行编辑器（04_editor）** 开始，配置并流式运行一个 agent，"
    "然后在 **🔍 运行详情（02_detail）** 查看每个 step 的输入输出。"
)

# ── 快速入口卡片
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("### 📋 运行历史")
    st.caption("查看全部历史 agent 运行记录。支持按 stage、状态、时间筛选。")
    st.page_link("pages/01_runs.py", label="前往运行历史 →", use_container_width=True)

with col2:
    st.markdown("### 🔍 运行详情")
    st.caption("查看单次运行的每个 step：工具调用、输入/输出、耗时、重试。")
    st.page_link("pages/02_detail.py", label="前往运行详情 →", use_container_width=True)

with col3:
    st.markdown("### ⚡ 对比实验")
    st.caption("并排对比最多 3 次运行，差异自动高亮，生成文字摘要。")
    st.page_link("pages/03_compare.py", label="前往对比实验 →", use_container_width=True)

with col4:
    st.markdown("### ⚙️ 运行编辑器")
    st.caption("内联编辑配置 + 流式运行。step 卡片逐个出现，实时查看进度。")
    st.page_link("pages/04_editor.py", label="前往运行编辑器 →", use_container_width=True)

st.markdown("---")

# ── 快捷运行区域（在主页也提供一键运行入口）
st.markdown("### ⚡ 快捷运行（test_agent）")
st.caption("无需前往编辑器页面，直接在此选择 plan 并运行。结果可在「运行详情」页查看。")

quick_col1, quick_col2, quick_col3 = st.columns([2, 2, 1])

PLAN_OPTIONS = {
    "plan_happy_path":      "😊 全成功路径",
    "plan_retry_scenario":  "🔁 失败→重试→成功",
    "plan_abort_scenario":  "💥 持续失败→中止",
    "plan_full_coverage":   "🧪 全分支覆盖",
    "plan_deep_analysis":   "🔬 深度分析（多轮轮询）",
}

with quick_col1:
    quick_plan = st.selectbox(
        "选择 Plan",
        options=list(PLAN_OPTIONS.keys()),
        format_func=lambda x: PLAN_OPTIONS[x],
        key="quick_plan",
    )
with quick_col2:
    import os
    quick_model = st.text_input(
        "模型（可选）",
        value=os.getenv("DEFAULT_LLM_MODEL", "minimax/MiniMax-M2.7-highspeed"),
        key="quick_model",
        help="留空使用默认模型",
    )
with quick_col3:
    st.markdown("<br>", unsafe_allow_html=True)
    quick_run = st.button("▶ 运行", use_container_width=True, type="primary")

if quick_run:
    import queue
    import time
    import uuid
    from components.agent_runner import AgentRunner

    run_id = f"debug_{uuid.uuid4().hex[:8]}"
    st.session_state["last_run_id"] = run_id

    progress_q: queue.Queue = queue.Queue(maxsize=200)
    runner = AgentRunner()

    overrides = {"plan_name": quick_plan}
    if quick_model:
        overrides["model"] = quick_model

    thread = runner.run_streaming("test", overrides, {}, progress_q, run_id=run_id)

    steps_state: dict[str, dict] = {}
    placeholder = st.empty()
    status_bar  = st.empty()

    status_bar.info(f"🔄 运行中... run_id=`{run_id}`")

    final_result = None

    while thread.is_alive() or not progress_q.empty():
        updated = False
        while not progress_q.empty():
            event = progress_q.get_nowait()
            etype = event.get("type") or event.get("event_type", "")

            if etype == "done":
                final_result = event.get("result")
                st.session_state["last_result"] = final_result
                break
            elif etype == "error":
                status_bar.error(f"❌ 运行出错：{event.get('error')}")
                break

            # step_start → running；step_end → success/failed；LLM trace → 追加到 step
            step_id = event.get("step_id")
            _LLM_ETYPES = {"llm_start", "llm_end", "tool_call", "tool_result", "llm_error"}

            if etype in _LLM_ETYPES and step_id and step_id in steps_state:
                # LLM/工具调用事件：追加到对应 step 的 llm_trace 列表
                steps_state[step_id].setdefault("llm_trace", []).append(event)
                updated = True
            elif step_id:
                if etype == "step_start":
                    steps_state[step_id] = {**event, "status": "running", "llm_trace": []}
                elif etype == "step_end":
                    existing = steps_state.get(step_id, {})
                    start_payload = existing.get("payload") or {}
                    end_payload = event.get("payload") or {}
                    steps_state[step_id] = {
                        **existing, **event,
                        "payload": {**start_payload, **end_payload},
                        "llm_trace": existing.get("llm_trace", []),
                    }
                updated = True

        if updated and steps_state:
            from components.ui_helpers import render_step_card, STATUS_ICONS
            with placeholder.container():
                for sid, sdata in sorted(steps_state.items()):
                    llm_evs = sdata.get("llm_trace") or None
                    render_step_card(sdata, expanded=False, llm_events=llm_evs)

        time.sleep(0.15)

    # 最终渲染
    if final_result:
        status = final_result.get("status", "unknown")
        if status == "success":
            status_bar.success(f"✅ 运行完成！run_id=`{run_id}`")
        else:
            status_bar.warning(f"⚠️ 运行结束，状态={status}，run_id=`{run_id}`")
