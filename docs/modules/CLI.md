# CLI 模块 README

## 定位

CLI 是当前 Demo UI，负责系统检查、Banner、Guide interrupt 对话、pipeline 进度面板和错误展示。

## 文件

```text
backend/src/cli/__main__.py
backend/src/cli/app.py
backend/src/cli/system_check.py
backend/src/cli/session.py
backend/src/cli/conversation.py
backend/src/cli/pipeline_view.py
```

## 命令

```bash
python -m backend.src.cli --check-only
python -m backend.src.cli
```

## 主流程

`system_check → banner → CLISession → TraceManager → build_graph(MemorySaver) → run_guide_conversation → run_pipeline_view`。

## 检查项

LLM、TraceDB、BizDB、Mode、Checkpoint。

## 未来

支持 `/help`、`/history`、run 恢复、Guide 输出编辑和 Trace viewer。
