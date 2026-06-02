"""
config.py — AgentTemplate 配置模型

位置：依赖 schemas.py（SummaryMode）、stopping.py（StoppingConfig）。
职责：定义 AgentTemplateConfig，各 agent 通过此对象向 template 注入所有个性化配置。

设计原则：
  - 组合注入而非继承：各 agent 只需提供自己的 config 实例，不改 template 代码。
  - 模型字符串 provider-agnostic：填写任意 LiteLLM 兼容格式（如 "openai/gpt-4o"、
    "minimax/MiniMax-M2.7-highspeed"、"anthropic/claude-3-5-sonnet-20241022"）。
    API key 等鉴权信息由用户在 .env 中配置，template 层完全不感知供应商细节。
  - 路径用 Path 类型，planner/context_builder 直接操作文件系统。

扩展点：
  - 需要 per-agent stopping 配置时，在此增加 stopping: StoppingConfig = StoppingConfig() 字段。
  - 需要 per-agent 额外 LiteLLM 参数（如 max_tokens、extra_headers），
    增加 litellm_kwargs: dict = {} 字段并在 executor.py 解包传入 ChatLiteLLM。
"""

from pathlib import Path

from pydantic import BaseModel, Field

from .schemas import SummaryMode
from .stopping import StoppingConfig


class AgentTemplateConfig(BaseModel):
    """AgentTemplate 的完整配置，由各 agent 的 agent.py 实例化后传入 AgentTemplate。"""

    # ── 基本信息 ──────────────────────────────
    agent_name: str
    """agent 标识名，需与 identity.yaml 的 agent_name 一致，用于 trace 记录。"""

    # ── 文件路径 ──────────────────────────────
    plan_path: Path
    """plan.yaml 的绝对路径或相对于 cwd 的路径。"""

    identity_path: Path
    """identity.yaml 的绝对路径或相对于 cwd 的路径。"""

    skills_dir: Path
    """skills/ 目录路径，下面的所有 .md 文件都会被加载注入 system prompt。"""

    # ── 模型（LiteLLM provider-agnostic） ────
    model: str
    """LiteLLM 兼容的模型字符串，格式 '<provider>/<model_id>'。
    示例：
      "openai/gpt-4o"
      "minimax/MiniMax-M2.7-highspeed"
      "anthropic/claude-3-5-sonnet-20241022"
    API key 由 .env 中对应的环境变量提供（LiteLLM 自动读取），template 层无需感知。
    """

    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    """LLM 采样温度，0.0 表示确定性输出（推荐用于结构化抽取场景）。"""

    # ── 工具 ──────────────────────────────────
    tools: list[str] = Field(default_factory=list)
    """本 agent 可用的 tool 名称列表，executor 通过 tools.registry.get_tools() 按名加载。
    各 step 再从此列表中按 PlanStep.tools_required 进一步过滤。
    """

    # ── 运行配置 ──────────────────────────────
    max_step_retries: int = Field(default=2, ge=0)
    """单个 step 最大重试次数（覆盖 PlanStep.max_retries 的上限，取两者较小值）。"""

    max_plan_retries: int = Field(default=1, ge=0)
    """validate_plan 失败后最多重跑整个 plan 的次数（v0.1 暂未实现，保留字段）。"""

    summary_mode: SummaryMode = SummaryMode.TEMPLATE
    """output_adapter 生成摘要的模式：TEMPLATE（纯函数）或 LLM（调模型）。"""

    stopping: StoppingConfig = Field(default_factory=StoppingConfig)
    """ReAct 循环的停止配置，各 agent 可按需覆盖默认值。"""

    # ── 功能开关 ──────────────────────────────
    enable_trace: bool = True
    """是否启用 TraceHook。False 时 hooks 仍被构造但 _write() 立即返回（NullBackend 行为）。
    未来：False 时可完全跳过 hook 构造以节省开销。
    """

    enable_memory: bool = False
    """内存功能开关（v0.1 固定为 False，不接线 db_access/memory/）。
    未来：True 时 context_builder 从 PostgresStore 读取 memory_refs 注入上下文。
    """

    model_config = {"arbitrary_types_allowed": True}
