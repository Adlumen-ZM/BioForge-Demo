# -*- coding: utf-8 -*-
"""
run_demo_pipeline.py — BioForge 非交互式 Demo Pipeline 入口

与 app.py 的区别：自动确认 Guide 的所有 interrupt，无需键盘输入。
验收命令：
  python -m backend.src.cli.run_demo_pipeline --profile hap_peptide_v1 --mode demo
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BioForge Demo Pipeline — 非交互式端到端运行",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--profile",        default="hap_peptide_v1",
                        help="提取配置名（template_id），决定 DB schema 和字段映射")
    parser.add_argument("--mode",           default="demo",
                        choices=["mock", "demo", "real"],
                        help="Agent 运行模式（mock=无 LLM；demo=完整 LLM；real=生产）")
    parser.add_argument("--topic",          default="hydroxyapatite-binding peptides for enamel remineralization",
                        help="初始研究主题，替代 Guide 阶段的用户输入")
    parser.add_argument("--max-candidates", type=int, default=100,
                        help="Search Agent 最大候选文献数")
    parser.add_argument("--max-downloads",  type=int, default=1,
                        help="Screen Agent 最大下载 PDF 数")
    parser.add_argument("--trace-level",    default="normal",
                        choices=["quiet", "normal", "debug"],
                        help="CLI trace 输出级别")
    args = parser.parse_args()

    # 必须在导入 graph 模块前设置：guide_node 在模块级读取 GRAPH_AGENT_MODE
    os.environ.setdefault("GRAPH_AGENT_MODE", args.mode)
    os.environ.setdefault("TRACE_CLI_LEVEL", args.trace_level)
    os.environ.setdefault("EXTRACTION_PROFILE", args.profile)

    from dotenv import load_dotenv
    load_dotenv()

    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    from backend.src.graph.pipeline import build_graph

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"run-{ts}-{uuid4().hex[:6]}"

    data_root = os.getenv("DATA_ROOT", "data")
    trace_dir    = f"{data_root}/runs/{run_id}/trace"
    artifacts_dir = f"{data_root}/runs/{run_id}/artifacts"
    Path(trace_dir).mkdir(parents=True, exist_ok=True)
    Path(artifacts_dir).mkdir(parents=True, exist_ok=True)

    print(f"[RUN] run_id={run_id}  profile={args.profile}  mode={args.mode}")

    checkpointer = MemorySaver()
    graph = build_graph(mode=args.mode, checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": run_id}}

    initial_state = {
        "run_id":             run_id,
        "agent_mode":         args.mode,
        "user_input":         args.topic,
        "user_query":         args.topic,
        "query":              args.topic,
        "template_id":        args.profile,
        "extraction_profile": args.profile,
        "trace_dir":          trace_dir,
        "artifacts_dir":      artifacts_dir,
        "errors":             [],
    }

    # 首次流式运行；pipeline_hook / console_backend 负责 trace 输出
    for _chunk in graph.stream(initial_state, cfg, stream_mode="values"):
        pass

    # 循环自动确认 Guide 的所有 interrupt（最多 6 次，覆盖 4 个确认点）
    MAX_INTERRUPTS = 6
    for _ in range(MAX_INTERRUPTS):
        snap = graph.get_state(cfg)
        if not snap.next:
            break
        for _chunk in graph.stream(Command(resume=0), cfg, stream_mode="values"):
            pass

    final = graph.get_state(cfg).values
    status = final.get("status", "unknown")

    print(f"\n[DONE] status={status}")
    if final.get("summary_path"):
        print(f"[DONE] summary  : {final['summary_path']}")
    if final.get("timeline_path"):
        print(f"[DONE] timeline : {final['timeline_path']}")

    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
