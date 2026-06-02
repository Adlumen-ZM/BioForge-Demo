"""
errors.py — AgentTemplate 异常类型定义

位置：最底层，无任何内部依赖。
职责：定义模板层所有自定义异常，便于上层精确捕获和分类处理。

使用原则：
  - 各模块在边界处抛出对应的具体异常类型（而非裸 Exception）。
  - plan_runner 捕获 StepExecutionError 触发 replanner；
    捕获 AgentTemplateError 的其他子类决定是否终止整个 run。
  - TraceError 由 hooks._write() 内部捕获，绝不向上传播（trace 失败不拖垮主流程）。
"""


class AgentTemplateError(Exception):
    """AgentTemplate 所有自定义异常的基类。"""


class PlanLoadError(AgentTemplateError):
    """plan.yaml 或 identity.yaml 加载/解析失败时抛出。

    常见原因：文件不存在、YAML 格式错误、Pydantic 校验失败。
    """


class ContextBuildError(AgentTemplateError):
    """context_builder 组装 executor 输入时发生错误。

    常见原因：skills 目录不存在、identity.yaml 格式错误。
    """


class StepExecutionError(AgentTemplateError):
    """executor 执行单个 step 时发生不可恢复错误。

    plan_runner 捕获此异常后交给 replanner 决策（retry / abort）。
    携带 step_id 便于 trace 记录。
    """

    def __init__(self, step_id: str, message: str, cause: Exception | None = None):
        super().__init__(f"[step={step_id}] {message}")
        self.step_id = step_id
        self.cause = cause


class ValidationError(AgentTemplateError):
    """validator 校验失败时抛出（区别于 Pydantic 自身的 ValidationError）。

    validate_step 返回 (False, msg) 而非抛出；
    此异常保留给 validate_plan 的 LLM 调用本身失败的情形。
    """


class ReplanError(AgentTemplateError):
    """replanner 自身逻辑出错时抛出（而非它返回的 abort 决策）。

    正常的 abort 决策由 ReplanDecision(action=ABORT) 表达，不用此异常。
    """


class TraceError(AgentTemplateError):
    """TraceHook 写入失败时内部使用，由 _write() try/except 捕获后 print。

    此异常绝不向 plan_runner 传播，确保 trace 失败不影响主流程。
    """


class OutputAdapterError(AgentTemplateError):
    """output_adapter 生成 PipelineState patch 失败时抛出。"""
