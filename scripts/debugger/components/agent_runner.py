"""
scripts/debugger/components/agent_runner.py — AgentTemplate 运行封装

位置：scripts/debugger/components/
依赖：backend/src/agents/（各 agent 工厂函数）
      backend/src/db_access/trace/postgres_backend.py（PostgresBackend, get_trace_engine）
      components/streamlit_backend.py（CompositeBackend, StreamlitProgressBackend）
      threading / queue（标准库）
职责：封装 AgentTemplate 的同步和流式两种运行模式，供 CLI 和 Streamlit 页面共同使用。

运行模式说明：
  1. run_sync()    — 同步阻塞运行，直接返回结果。CLI (debug_agent.py) 使用。
  2. run_streaming() — 后台线程运行，TraceEvent 实时写入 progress_queue：
       - 每个 step_start/step_end 事件放入 queue（供 Streamlit 实时渲染 step 卡片）
       - 运行结束后放入 {"type": "done", "result": ...}
       - 出错时放入 {"type": "error", "error": "..."}
       - 调用方（04_editor.py）轮询 queue 直到收到 done/error 消息

关键规则：
  - 每次 run 开始前自动调用 reset_flaky_counters()，防止跨 run 计数污染
  - 若 TRACE_DB_URL 存在则同时写 DB + Queue（CompositeBackend）；
    否则只写 Queue（StreamlitProgressBackend 单独）
  - screen/extract agent 尚未实现，调用时 raise NotImplementedError

使用方式（Streamlit 04_editor.py）：
    import queue
    from components.agent_runner import AgentRunner

    runner = AgentRunner()
    progress_q = queue.Queue(maxsize=100)
    thread = runner.run_streaming("test", {"plan_name": "plan_retry_scenario"},
                                  {}, progress_q, run_id="debug_xxx")
    while thread.is_alive() or not progress_q.empty():
        while not progress_q.empty():
            event = progress_q.get_nowait()
            if event.get("type") == "done":
                result = event["result"]
        time.sleep(0.15)
"""

from __future__ import annotations

import importlib
import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Any

# ── 路径设置（确保 backend 可被 import）──────────────────────────────────────
import sys

_DEBUGGER_DIR = Path(__file__).parent.parent          # scripts/debugger/
_SCRIPTS_DIR = _DEBUGGER_DIR.parent                   # scripts/
_ROOT = _SCRIPTS_DIR.parent                           # 项目根目录

for p in [str(_ROOT), str(_SCRIPTS_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ─────────────────────────────────────────────
# Agent 工厂函数路径表
# ─────────────────────────────────────────────

# 已实现 agent 的工厂函数完整路径（module.path:function_name 格式）
# None 表示尚未实现，调用时 raise NotImplementedError
_AGENT_FACTORIES: dict[str, str | None] = {
    "search":  "backend.src.agents.search_agent.agent:create_search_agent",
    "screen":  None,   # TODO(编排负责人): screen_agent 完成后填入 "backend...agent:create_screen_agent"
    "extract": None,   # TODO(编排负责人): extract_agent 完成后填入 "backend...agent:create_extract_agent"
    "test":    "backend.src.agents.test_agent.agent:create_test_agent",
}


def _load_factory(agent_name: str):
    """动态加载 agent 工厂函数。

    Args:
        agent_name: agent 标识符（search / screen / extract / test）。

    Returns:
        工厂函数（callable）。

    Raises:
        NotImplementedError: screen / extract 尚未实现时。
        KeyError: agent_name 不在已知列表时。
    """
    factory_path = _AGENT_FACTORIES.get(agent_name)

    if agent_name not in _AGENT_FACTORIES:
        raise KeyError(f"未知 agent: '{agent_name}'。可选：{list(_AGENT_FACTORIES.keys())}")

    if factory_path is None:
        raise NotImplementedError(
            f"agent '{agent_name}' 的工厂函数尚未实现，"
            f"请等待对应负责人完成 create_{agent_name}_agent() 后再使用。"
        )

    module_path, func_name = factory_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


# ─────────────────────────────────────────────
# AgentRunner
# ─────────────────────────────────────────────

class AgentRunner:
    """AgentTemplate 运行封装，支持同步和流式两种模式。

    线程安全说明：
      run_streaming() 在后台线程中运行 agent，通过 queue.Queue 传递事件。
      Streamlit 主线程消费 queue，无需额外同步原语。
    """

    def _create_agent(self, agent_name: str, overrides: dict[str, Any] | None = None):
        """根据 agent_name 和 overrides 创建 AgentTemplate 实例。

        Args:
            agent_name: agent 标识符。
            overrides: 覆盖参数 dict（model / plan_name / plan_path / temperature 等）。

        Returns:
            AgentTemplate 实例（plan 和 identity 已加载）。

        Raises:
            NotImplementedError: agent 尚未实现时。
        """
        overrides = dict(overrides or {})
        factory_fn = _load_factory(agent_name)

        if agent_name == "test":
            # test_agent 用 plan_name 参数（不含 .yaml 后缀）
            plan_name = overrides.pop("plan_name", "plan_happy_path")
            # model 单独取出，其余作为 overrides 传入
            model = overrides.pop("model", None)
            return factory_fn(plan_name=plan_name, model=model, overrides=overrides)
        else:
            # 其他 agent 只接受 model 参数（未来可扩展）
            model = overrides.get(
                "model",
                os.getenv("DEFAULT_LLM_MODEL", "minimax/MiniMax-M2.7-highspeed"),
            )
            return factory_fn(model=model)

    def _attach_backend(self, agent, progress_queue: queue.Queue | None = None) -> bool:
        """为 agent 配置合适的 trace backend。

        若 TRACE_DB_URL 存在：CompositeBackend（Postgres + 可选 Queue）
        否则：只用 StreamlitProgressBackend（若有 queue）或 NullBackend

        Args:
            agent: AgentTemplate 实例。
            progress_queue: Streamlit 进度队列（None 表示同步模式，不需要流式）。

        Returns:
            bool，True 表示已接入 Postgres DB，False 表示只有 print/Queue。
        """
        from components.streamlit_backend import CompositeBackend, StreamlitProgressBackend

        trace_db_url = os.getenv("TRACE_DB_URL")
        backends = []

        # 优先接入 Postgres（若配置了 TRACE_DB_URL）
        if trace_db_url:
            try:
                from backend.src.db_access.trace.postgres_backend import PostgresBackend
                backends.append(PostgresBackend())
                has_db = True
            except Exception as e:
                print(f"[AgentRunner] ⚠️ PostgresBackend 初始化失败：{e}")
                has_db = False
        else:
            has_db = False

        # 若有 progress_queue，加入流式 backend
        if progress_queue is not None:
            backends.append(StreamlitProgressBackend(progress_queue))

        if backends:
            agent.hook.backend = CompositeBackend(*backends)

        return has_db

    def run_sync(
        self,
        agent_name: str,
        overrides: dict[str, Any] | None = None,
        input_data: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """同步运行 agent，返回 PipelineState patch dict。

        每次运行前自动重置 mock_flaky 计数器，防止跨 run 污染。

        Args:
            agent_name: agent 标识符。
            overrides: 覆盖参数 dict。
            input_data: 传入 pipeline_state 的初始数据（暂未使用，留接口）。
            run_id: pipeline 级别 run_id。None 时自动生成 "debug_<8hex>"。

        Returns:
            dict，agent.run() 返回的 PipelineState patch。
        """
        # 每次 run 前重置 flaky 计数器，防止跨 run 计数污染
        try:
            from backend.src.tools.test_agent.mock_flaky import reset_flaky_counters
            reset_flaky_counters()
        except ImportError:
            pass  # test_agent tools 不可用时忽略

        resolved_run_id = run_id or f"debug_{uuid.uuid4().hex[:8]}"
        agent = self._create_agent(agent_name, overrides)
        self._attach_backend(agent)  # 同步模式不需要 progress_queue

        return agent.run(run_id=resolved_run_id, pipeline_state=input_data or {})

    def run_streaming(
        self,
        agent_name: str,
        overrides: dict[str, Any] | None = None,
        input_data: dict[str, Any] | None = None,
        progress_queue: queue.Queue | None = None,
        run_id: str | None = None,
    ) -> threading.Thread:
        """在后台线程运行 agent，TraceEvent 实时写入 progress_queue。

        运行结束后自动 put {"type": "done", "result": ...} 进 queue。
        出错时 put {"type": "error", "error": "..."} 进 queue。

        调用方（04_editor.py）应：
        1. 轮询 progress_queue 直到 thread.is_alive() == False 且 queue 为空
        2. 处理 "done" 消息拿到最终结果
        3. 处理 "error" 消息展示错误信息

        Args:
            agent_name: agent 标识符。
            overrides: 覆盖参数 dict。
            input_data: 传入 pipeline_state 的初始数据。
            progress_queue: 进度队列（None 时使用内部 Queue，不推荐）。
            run_id: pipeline 级别 run_id。None 时自动生成。

        Returns:
            threading.Thread（daemon=True，主线程退出时自动清理）。
        """
        if progress_queue is None:
            progress_queue = queue.Queue(maxsize=100)

        resolved_run_id = run_id or f"debug_{uuid.uuid4().hex[:8]}"

        def _run_in_thread():
            """后台线程执行体。"""
            # 每次 run 前重置 flaky 计数器
            try:
                from backend.src.tools.test_agent.mock_flaky import reset_flaky_counters
                reset_flaky_counters()
            except ImportError:
                pass

            try:
                agent = self._create_agent(agent_name, overrides)
                self._attach_backend(agent, progress_queue)

                # 运行 agent（阻塞，直到 plan 完成）
                result = agent.run(
                    run_id=resolved_run_id,
                    pipeline_state=input_data or {},
                )

                # 运行完成，发 done 消息给 Streamlit 主线程
                progress_queue.put({
                    "type": "done",
                    "result": result,
                    "run_id": resolved_run_id,
                })

            except NotImplementedError as e:
                progress_queue.put({"type": "error", "error": f"agent 未实现：{e}"})
            except Exception as e:
                import traceback
                progress_queue.put({
                    "type": "error",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })

        # 启动后台守护线程（daemon=True：主线程退出时自动清理）
        thread = threading.Thread(target=_run_in_thread, daemon=True)
        thread.start()
        return thread
