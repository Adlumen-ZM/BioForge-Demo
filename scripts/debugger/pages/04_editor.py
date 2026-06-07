"""
scripts/debugger/pages/04_editor.py — 配置编辑器 + 流式运行（核心页面）

位置：scripts/debugger/pages/
依赖：components/agent_runner.py（AgentRunner）
      components/ui_helpers.py（render_step_card, render_status_badge, format_ms）
      queue / threading / uuid（标准库）
职责：
  - 左栏：Agent 下拉 / Plan 下拉 / 模型 / Identity YAML 内联编辑 / user_query
  - 右栏：流式运行结果（step 卡片逐个出现）
  - [▶ 运行] 按钮：后台线程运行，150ms 轮询 queue，实时重绘 step 卡片
  - [💾 保存为实验] 按钮：将配置写入 experiments/{filename}.yaml

注意：
  - Identity / Skills 编辑只修改内存中的 overrides dict，不写回原文件
  - 流式显示依赖 run_streaming() 的 queue.Queue 机制
  - 保存实验前会弹出文件名输入框（默认时间戳命名）

使用方式：cd scripts/debugger && streamlit run app.py，然后点击左侧「04_editor」
"""

from __future__ import annotations

import os
import queue
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# ── 路径设置 ──────────────────────────────────────────────────────────────────
_DEBUGGER_DIR = Path(__file__).parent.parent
_SCRIPTS_DIR  = _DEBUGGER_DIR.parent
_ROOT         = _SCRIPTS_DIR.parent

for _p in [str(_ROOT), str(_SCRIPTS_DIR), str(_DEBUGGER_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st

from components.agent_runner import AgentRunner
from components.ui_helpers import STATUS_ICONS, format_ms, render_status_badge, render_step_card

# ─────────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="运行编辑器 — BioForge Debugger",
    page_icon="⚙️",
    layout="wide",
)

# ─────────────────────────────────────────────
# session_state 初始化（此页面专属）
# ─────────────────────────────────────────────

def _init() -> None:
    defaults: dict[str, Any] = {
        "is_running":       False,
        "steps_state":      {},   # step_id → 最新事件数据
        "run_error":        None,
        "run_done":         False,
        "current_run_id":   None,
        "last_result":      None,
        "last_run_id":      None,
        "save_filename":    None,  # 待确认保存的文件名
        # 编辑器持久化配置
        "editor_agent":     "test",
        "editor_plan":      "plan_happy_path",
        "editor_model":     os.getenv("DEFAULT_LLM_MODEL", "minimax/MiniMax-M2.7-highspeed"),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init()


# ─────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────

PLAN_OPTIONS: dict[str, str] = {
    "plan_happy_path":      "😊 全成功路径（3步 mock_success）",
    "plan_retry_scenario":  "🔁 失败→重试→成功（mock_flaky）",
    "plan_abort_scenario":  "💥 持续失败→中止（mock_fail）",
    "plan_full_coverage":   "🧪 全分支覆盖（4步串联）",
    "plan_deep_analysis":   "🔬 深度分析（多轮轮询 + validate_plan 失败）",
    "plan_modify_step":     "🔧 MODIFY_STEP Replan（LLM 改写指令）",  # ⭐ 新增
}

AGENT_OPTIONS: dict[str, str] = {
    "test":    "🧪 test_agent（框架测试）",
    "search":  "🔍 search_agent（搜索）",
    "screen":  "🖥 screen_agent（筛选，未实现）",
    "extract": "📝 extract_agent（提取，未实现）",
}

EXPERIMENTS_DIR = _DEBUGGER_DIR / "experiments"
EXPERIMENTS_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────
# 辅助：更新 steps_state
# ─────────────────────────────────────────────

_LLM_TRACE_ETYPES = {"llm_start", "llm_end", "tool_call", "tool_result", "llm_error"}


def _update_steps_state(steps_state: dict[str, Any], event: dict[str, Any]) -> None:
    """根据 TraceEvent / LLM Trace 事件 dict 更新 steps_state。

    step_start    → status=running（占位），初始化 llm_trace=[]
                    保留跨次执行的 replan_history（MODIFY_STEP 重试时 step_start 会再次到来）
    step_end      → 完整事件数据（含 status / output / duration 等）
                    保留 replan_history 和 llm_trace
    step_replanned → 将 replan payload 追加到 replan_history 列表，不影响其他字段
    llm_start / llm_end / tool_call / tool_result / llm_error
                  → 追加到对应 step 的 llm_trace 列表
    其他事件（plan_start/plan_end）→ 忽略

    Args:
        steps_state: step_id → 事件状态 dict，就地修改。
                     每条记录额外含：
                       "llm_trace":     list[dict]  — LLM/工具调用事件
                       "replan_history": list[dict]  — MODIFY_STEP replan 事件 payload 列表
        event: 从 progress_queue 取出的事件 dict。
    """
    etype   = event.get("event_type", event.get("type", ""))
    step_id = event.get("step_id")

    # ── LLM Trace 事件：追加到对应 step 的 llm_trace 列表 ─────────────────
    if etype in _LLM_TRACE_ETYPES:
        if step_id and step_id in steps_state:
            steps_state[step_id].setdefault("llm_trace", []).append(event)
        return  # LLM trace 事件不修改 step 的其他字段

    # ── 普通 step 事件 ────────────────────────────────────────────────────
    if not step_id:
        return

    if etype == "step_start":
        existing = steps_state.get(step_id, {})
        steps_state[step_id] = {
            **event,
            "status": "running",
            "llm_trace": [],  # 重置本次执行的 LLM 事件列表
            # ⭐ 保留跨次执行的 replan 历史（MODIFY_STEP 重试时 step_start 会再次到来）
            "replan_history": existing.get("replan_history", []),
        }
    elif etype == "step_end":
        # 合并 step_start 的 payload（含 tools_required）到 step_end 数据
        existing = steps_state.get(step_id, {})
        start_payload = existing.get("payload") or {}
        end_payload = event.get("payload") or {}
        # step_end payload 优先，但保留 step_start 独有的字段（如 tools_required）
        merged_payload = {**start_payload, **end_payload}
        steps_state[step_id] = {
            **existing,
            **event,
            "payload": merged_payload,
            "llm_trace": existing.get("llm_trace", []),       # 保留已积累的 LLM 事件
            "replan_history": existing.get("replan_history", []),  # 保留 replan 历史
        }
    elif etype == "step_replanned":
        # ⭐ MODIFY_STEP replan 事件：将 replan payload 追加到历史列表
        # 此事件在 step_end(failed) 之后、下一次 step_start 之前到来
        # 不修改 step 的 status，只追加 replan 记录供 UI 展示
        existing = steps_state.get(step_id, {})
        replan_history = list(existing.get("replan_history", []))
        replan_history.append(event.get("payload", {}))
        steps_state[step_id] = {
            **existing,
            "replan_history": replan_history,
        }


def _render_streaming_view(steps_state: dict[str, Any]) -> None:
    """在 placeholder.container() 中渲染当前所有 step 的卡片。

    running 状态的 step：显示蓝色进度提示 + 已捕获的实时 LLM 事件；
    已完成的 step：渲染完整 step 卡片（含 LLM 思考链折叠区）。

    Args:
        steps_state: step_id → 事件状态 dict。
    """
    for sid, sdata in sorted(steps_state.items()):
        status     = sdata.get("status", "unknown")
        llm_events = sdata.get("llm_trace", [])

        if status == "running":
            # 实时进度：显示已捕获到的 LLM/工具事件数量
            llm_cnt  = sum(1 for e in llm_events if e.get("event_type") == "llm_end")
            tool_cnt = sum(1 for e in llm_events if e.get("event_type") == "tool_call")
            detail = []
            if llm_cnt:
                detail.append(f"LLM×{llm_cnt}")
            if tool_cnt:
                detail.append(f"工具×{tool_cnt}")
            hint = ("  |  " + ", ".join(detail)) if detail else ""
            # ⭐ replan 中：已被 MODIFY_STEP 改写指令，正在用新指令重试
            if sdata.get("replan_history"):
                replan_cnt = len(sdata["replan_history"])
                st.markdown(
                    f'<div style="background:#3d1f6e;border-left:4px solid #A78BFA;'
                    f'padding:8px 12px;border-radius:4px;margin:4px 0;">'
                    f'🔧 <b>{sid}</b> — 已 MODIFY_STEP（第{replan_cnt}次改写），正在用新指令重试...{hint}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.info(f"🔄 **{sid}** — 执行中...{hint}")
        else:
            render_step_card(sdata, expanded=(status == "failed"),
                             llm_events=llm_events or None)


# ─────────────────────────────────────────────
# 主页面布局：左栏配置 + 右栏结果
# ─────────────────────────────────────────────

st.title("⚙️ 运行编辑器")

left_col, right_col = st.columns([1, 1], gap="large")


# ══════════════════════════════════════════════
# 左栏：配置面板
# ══════════════════════════════════════════════

with left_col:
    st.markdown("### 🛠 配置")

    # ── Agent 选择
    agent_name = st.selectbox(
        "Agent",
        options=list(AGENT_OPTIONS.keys()),
        format_func=lambda x: AGENT_OPTIONS[x],
        index=list(AGENT_OPTIONS.keys()).index(st.session_state.get("editor_agent", "test")),
        key="sel_agent",
    )
    st.session_state["editor_agent"] = agent_name

    # screen / extract 提示
    if agent_name in ("screen", "extract"):
        st.warning(f"⚠️ {agent_name}_agent 尚未实现，运行时将报错。")

    # ── Plan 选择（test_agent 专属）
    overrides: dict[str, Any] = {}
    if agent_name == "test":
        plan_name = st.selectbox(
            "Plan",
            options=list(PLAN_OPTIONS.keys()),
            format_func=lambda x: PLAN_OPTIONS[x],
            index=list(PLAN_OPTIONS.keys()).index(
                st.session_state.get("editor_plan", "plan_happy_path")
            ),
            key="sel_plan",
        )
        st.session_state["editor_plan"] = plan_name
        overrides["plan_name"] = plan_name

    # ── 模型
    model_input = st.text_input(
        "模型（LiteLLM 格式）",
        value=st.session_state.get("editor_model", os.getenv("DEFAULT_LLM_MODEL", "")),
        placeholder="minimax/MiniMax-M2.7-highspeed",
        key="inp_model",
        help="接受任意 LiteLLM 兼容字符串，如 openai/gpt-4o、anthropic/claude-3-5-sonnet",
    )
    if model_input.strip():
        overrides["model"] = model_input.strip()
        st.session_state["editor_model"] = model_input.strip()

    # ── Identity YAML 内联编辑（只在内存 overrides，不写回文件）
    with st.expander("📄 Identity YAML（内联编辑）", expanded=False):
        st.caption("⚠️ 仅在内存中生效，不写回原文件。留空则使用 agent 默认 identity。")
        identity_text = st.text_area(
            "identity.yaml 内容",
            value="",
            height=200,
            placeholder="留空使用默认 identity，或粘贴 YAML 内容覆盖",
            key="ta_identity",
        )
        if identity_text.strip():
            overrides["identity_yaml"] = identity_text.strip()

    # ── Skills 内联编辑
    with st.expander("📚 Skills（内联编辑）", expanded=False):
        st.caption("⚠️ 仅在内存中生效，不写回文件。格式：skill_name = Markdown 内容。")
        skill_name_input = st.text_input(
            "Skill 名称（无需扩展名）",
            value="",
            placeholder="如：test_protocol",
            key="inp_skill_name",
        )
        skill_content_input = st.text_area(
            "Skill 内容（Markdown）",
            value="",
            height=150,
            placeholder="在此粘贴 Markdown 内容",
            key="ta_skill_content",
        )
        if skill_name_input.strip() and skill_content_input.strip():
            overrides[f"skill_{skill_name_input.strip()}"] = skill_content_input.strip()

    # ── user_query（search_agent 等用）
    if agent_name != "test":
        user_query = st.text_area(
            "user_query",
            value="",
            height=100,
            placeholder="输入要传给 agent 的用户指令",
            key="ta_query",
        )
        if user_query.strip():
            overrides["user_query"] = user_query.strip()

    # ── Run ID（可选指定）
    run_id_input = st.text_input(
        "Run ID（可选）",
        value="",
        placeholder="留空自动生成 debug_xxxxxxxx",
        key="inp_run_id",
        help="用于 trace 落库和历史查询。建议保持默认。",
    )

    st.markdown("---")

    # ── 操作按钮
    btn_col1, btn_col2 = st.columns(2)

    with btn_col1:
        run_btn = st.button(
            "▶ 运行",
            use_container_width=True,
            type="primary",
            disabled=st.session_state.get("is_running", False),
        )

    with btn_col2:
        save_btn = st.button(
            "💾 保存为实验",
            use_container_width=True,
            disabled=not st.session_state.get("last_result"),
            help="将最近一次运行的配置保存为 experiments/*.yaml",
        )

    # ── 保存实验逻辑
    if save_btn:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{agent_name}_{ts}"
        st.session_state["save_filename"] = default_name

    if st.session_state.get("save_filename") is not None:
        with st.form("save_experiment_form"):
            filename = st.text_input(
                "实验文件名（不含 .yaml）",
                value=st.session_state["save_filename"],
                key="save_fname_input",
            )
            save_confirm = st.form_submit_button("✅ 确认保存")
            save_cancel  = st.form_submit_button("❌ 取消")

        if save_confirm and filename.strip():
            import yaml as _yaml  # 可选依赖
            experiment = {
                "agent_name":  agent_name,
                "overrides":   overrides,
                "run_id":      st.session_state.get("last_run_id"),
                "created_at":  datetime.now().isoformat(),
                "result_status": (st.session_state.get("last_result") or {}).get("status"),
            }
            target = EXPERIMENTS_DIR / f"{filename.strip()}.yaml"
            try:
                target.write_text(
                    _yaml.dump(experiment, allow_unicode=True, default_flow_style=False),
                    encoding="utf-8",
                )
                st.success(f"✅ 已保存到 `experiments/{filename.strip()}.yaml`")
            except ImportError:
                import json
                target_json = EXPERIMENTS_DIR / f"{filename.strip()}.json"
                target_json.write_text(
                    json.dumps(experiment, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                st.success(f"✅ 已保存到 `experiments/{filename.strip()}.json`（yaml 未安装，改用 JSON）")
            except Exception as e:
                st.error(f"❌ 保存失败：{e}")
            finally:
                st.session_state["save_filename"] = None

        if save_cancel:
            st.session_state["save_filename"] = None
            st.rerun()


# ══════════════════════════════════════════════
# 右栏：实时运行结果
# ══════════════════════════════════════════════

with right_col:
    st.markdown("### 📡 运行结果")

    status_placeholder = st.empty()
    result_placeholder = st.empty()

    # ── 启动运行
    if run_btn and not st.session_state.get("is_running"):
        # 重置状态
        st.session_state["is_running"]     = True
        st.session_state["steps_state"]    = {}
        st.session_state["run_error"]      = None
        st.session_state["run_done"]       = False
        st.session_state["last_result"]    = None

        resolved_run_id = run_id_input.strip() or f"debug_{uuid.uuid4().hex[:8]}"
        st.session_state["current_run_id"] = resolved_run_id
        st.session_state["last_run_id"]    = resolved_run_id

        # 启动后台线程
        progress_q: queue.Queue = queue.Queue(maxsize=200)
        runner = AgentRunner()
        thread = runner.run_streaming(
            agent_name,
            overrides,
            {},
            progress_q,
            run_id=resolved_run_id,
        )

        status_placeholder.info(f"🔄 运行中... `{resolved_run_id}`")

        # ── 轮询 queue，实时重绘
        steps_state: dict[str, Any] = {}
        while thread.is_alive() or not progress_q.empty():
            updated = False
            done_or_error = False

            while not progress_q.empty():
                try:
                    event = progress_q.get_nowait()
                except queue.Empty:
                    break

                etype = event.get("type") or event.get("event_type", "")

                if etype == "done":
                    result = event.get("result", {})
                    st.session_state["last_result"] = result
                    st.session_state["run_done"]    = True
                    done_or_error = True
                    break
                elif etype == "error":
                    err = event.get("error", "未知错误")
                    tb  = event.get("traceback", "")
                    st.session_state["run_error"] = err
                    done_or_error = True
                    with result_placeholder.container():
                        st.error(f"❌ 运行出错：{err}")
                        if tb:
                            with st.expander("📋 详细 traceback", expanded=False):
                                st.code(tb, language="python")
                    break
                else:
                    _update_steps_state(steps_state, event)
                    updated = True

            if updated:
                with result_placeholder.container():
                    _render_streaming_view(steps_state)

            if done_or_error:
                break

            time.sleep(0.15)

        # ── 最终渲染
        st.session_state["is_running"]  = False
        st.session_state["steps_state"] = steps_state

        final_result = st.session_state.get("last_result")
        run_error    = st.session_state.get("run_error")

        if run_error:
            status_placeholder.error(f"❌ 运行出错：{run_error}")
        elif final_result:
            final_status = final_result.get("status", "unknown")
            if final_status == "success":
                status_placeholder.success(
                    f"✅ 运行完成！`{resolved_run_id}`  ·  "
                    f"⏱ {format_ms(final_result.get('total_duration_ms'))}"
                )
            else:
                status_placeholder.warning(
                    f"⚠️ 运行结束，状态=**{final_status}**  ·  `{resolved_run_id}`"
                )

            # 最终完整渲染
            with result_placeholder.container():
                _render_streaming_view(steps_state)

                # 最终结果摘要
                st.markdown("---")
                st.markdown("#### 📦 最终结果")
                st.json(final_result)
        else:
            status_placeholder.warning("⚠️ 运行结束，但未收到 done 消息。请检查日志。")

    else:
        # 非运行状态：展示上次结果（如果有）
        last_result = st.session_state.get("last_result")
        last_run_id = st.session_state.get("last_run_id")

        if last_result:
            last_status = last_result.get("status", "unknown")
            icon = STATUS_ICONS.get(last_status, "❓")
            status_placeholder.markdown(
                f"{icon} **上次运行** `{last_run_id}` · 状态={last_status}"
            )

            last_steps = st.session_state.get("steps_state", {})
            if last_steps:
                with result_placeholder.container():
                    _render_streaming_view(last_steps)

                    st.markdown("---")
                    st.markdown("#### 📦 最终结果")
                    st.json(last_result)
            else:
                with result_placeholder.container():
                    st.json(last_result)
        else:
            with result_placeholder.container():
                st.info(
                    "👈 在左侧选择 Agent 和配置，然后点击 **▶ 运行** 开始流式运行。\n\n"
                    "step 卡片将逐个出现，实时展示每步的工具调用、输入、输出和耗时。"
                )
