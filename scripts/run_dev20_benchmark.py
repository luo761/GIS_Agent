"""在本地 PostGIS 上跑 dev20 20 题，并生成评测报告。

用法（项目根目录）：
    python scripts/run_dev20_benchmark.py                # 全量 20 题
    python scripts/run_dev20_benchmark.py --case D09      # 只跑一题
    python scripts/run_dev20_benchmark.py --limit 3       # 只跑前 3 题

运行前请确保 Docker 中的 PostGIS 已导入 dev20 数据（见 README / reports 文档）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _prepare_state(reset: bool) -> None:
    """清空能力向量、经验池与智能体记忆，保证每次评测从同一起点开始。"""
    if not reset:
        return
    from config import settings
    from agents.capability_store import CapabilityStore, set_default_store

    store = CapabilityStore(settings.CAPABILITY_PATH)
    store.reset()
    set_default_store(store)
    if Path(settings.EXPERIENCE_PATH).exists():
        Path(settings.EXPERIENCE_PATH).unlink()
    memory_dir = settings.DATA_DIR / "memory"
    if memory_dir.exists():
        shutil.rmtree(memory_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="dev20 基准评测")
    parser.add_argument("--case", default=None, help="只跑指定题号，如 D09")
    parser.add_argument("--cases", default=None, help="只跑逗号分隔的题号，如 D04,D05,D09")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题")
    parser.add_argument("--model", default=None, help="覆盖 LLM_MODEL")
    parser.add_argument("--max-replans", type=int, default=0,
                        help="失败后重规划次数（默认 0，单次作答）")
    parser.add_argument("--no-reset", action="store_true", help="保留当前能力/经验状态")
    parser.add_argument("--out-dir", default=str(ROOT / "reports"), help="输出目录")
    args = parser.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    # 先清状态，再导入会读写状态的模块
    _prepare_state(reset=not args.no_reset)

    import pipeline.pipeline_graph as pipeline_graph
    import pipeline.stage5_evaluate as stage5
    from agents.capability_store import get_default_store
    from benchmark.dev20 import compare, extract_json, format_requirement, load_cases
    from benchmark.report import render_markdown, summarize
    from config import settings

    pipeline_graph.MAX_REPLANS = args.max_replans
    # 每道题视为一个可独立作答的分析任务，约束拆解为单子任务，便于逐题归因与计分
    settings.MAX_SUBTASKS = 1

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c.id == args.case]
    if args.cases:
        wanted = {item.strip().upper() for item in args.cases.split(",") if item.strip()}
        cases = [c for c in cases if c.id in wanted]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("没有匹配的题目")
        return 1

    store = get_default_store()
    results: list[dict] = []
    started_all = time.time()

    print(f"开始评测：{len(cases)} 题｜模型 {os.getenv('LLM_MODEL')}｜"
          f"数据库 {settings.DATABASE_URL.split('@')[-1]}")
    for index, case in enumerate(cases, 1):
        def verifier(state, _case=case):
            text = state.subtasks[0].result if state.subtasks else ""
            answer = extract_json(text)
            if answer is None:
                return False, "最终答复中未找到 JSON 结果"
            diffs = compare(answer, _case.expected)
            return (not diffs), "；".join(diffs[:8])

        stage5.set_verifier(verifier)
        started = time.time()
        error = ""
        try:
            state = pipeline_graph.ask(
                case.question,
                ground_truth=case.id,
                answer_format=format_requirement(case),
            )
        except Exception as exc:  # 单题异常不打断整批
            state = None
            error = f"{type(exc).__name__}: {exc}"

        elapsed = round(time.time() - started, 1)
        sub = state.subtasks[0] if state and state.subtasks else None
        answer = extract_json(sub.result) if sub else None
        diffs = compare(answer, case.expected) if answer is not None else ["无 JSON 结果"]
        correct = bool(answer is not None and not diffs)
        agent = sub.assigned_agent if sub else ""
        cap_after = store.capabilities(agent) if agent else {}

        record = {
            "id": case.id,
            "level": case.level,
            "question": case.question,
            "expected": case.expected,
            "answer": answer,
            "answer_raw": (sub.result if sub else ""),
            "diffs": diffs,
            "correct": correct,
            "evaluation": state.evaluation if state else "error",
            "error": error,
            "failure_feedback": state.failure_feedback if state else "",
            "agent": agent,
            "agent_name": sub.assigned_agent_name if sub else "",
            "routing": (sub.routing if sub else {}),
            "capabilities": cap_after,
            "tools": sub.tools_used if sub else [],
            "steps": [
                {"step": t.get("step"), "tool": t.get("tool"),
                 "ok": t.get("ok"), "args": t.get("args"),
                 "brief": t.get("brief") or t.get("error")}
                for t in (sub.trace if sub else [])
            ],
            "elapsed_s": elapsed,
            "capability_changes": state.capability_changes if state else [],
        }
        results.append(record)
        flag = "OK" if correct else "FAIL"
        print(f"[{index:02d}/{len(cases)}] {case.id} {case.level} {flag} "
              f"{elapsed:5.1f}s 智能体 {record['agent_name'] or '-'} "
              f"工具 {len(record['tools'])} 类 / {len(record['steps'])} 步", flush=True)

    total_elapsed = round(time.time() - started_all, 1)
    meta = {
        "suite": "postgis_dev20_v1",
        "model": os.getenv("LLM_MODEL"),
        "database": settings.DATABASE_URL.split("@")[-1],
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_elapsed_s": total_elapsed,
        "max_replans": args.max_replans,
        "case_count": len(results),
        "initial_capability": settings.CAPABILITY_INITIAL,
        "final_capabilities": store.table(),
    }
    summary = summarize(results)

    out_dir = Path(args.out_dir) / "dev20"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = out_dir / f"dev20_run_{stamp}.json"
    raw_path.write_text(json.dumps({"meta": meta, "summary": summary, "results": results},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    report = render_markdown(meta, summary, results)
    report_path = out_dir / "dev20_test_report.md"
    report_path.write_text(report, encoding="utf-8")
    (out_dir / "dev20_latest.json").write_text(
        raw_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"\n汇总：{summary['correct']}/{summary['total']} 正确，"
          f"总耗时 {total_elapsed}s")
    print(f"报告：{report_path}")
    print(f"原始结果：{raw_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
