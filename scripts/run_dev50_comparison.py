"""50 题真实配对实验；每题每模式独立进程，逐题落盘，可安全续跑。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker() -> int:
    from benchmark.comparison import atomic_json, execute_case
    request = json.loads(sys.stdin.read())
    try:
        record = execute_case(request)
    except Exception as exc:
        record = {"id": request["case_id"], "mode": request["mode"], "status": "blocked",
                  "error": "worker 执行前置条件或服务异常", "exception_type": type(exc).__name__}
    record["signature"] = request["signature"]
    atomic_json(Path(request["record_path"]), record)
    return 0 if record["status"] == "completed" else 2


def api_probe() -> int:
    try:
        from pipeline.llm_client import chat
        chat("请只回复 OK。", system="这是连接可用性检查。")
        return 0
    except Exception:
        # SDK 异常详情可能包含认证配置，不写入实验日志。
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="dev50：关闭/开启重规划的隔离配对实验")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--probe-api", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--bench-dir", default=None, help="含 dev50.json/dev50_expected.json 的目录")
    parser.add_argument("--out-dir", default=str(ROOT / "reports" / "dev50_comparison"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--max-replans", type=int, default=2, help="开启模式最多额外重规划次数，默认2")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cases", default=None, help="逗号分隔题号，如 D01,D21")
    parser.add_argument("--resume", action="store_true", help="仅复用完全相同实验签名的逐题结果")
    parser.add_argument("--timeout", type=int, default=1200, help="每题每模式最多秒数")
    parser.add_argument("--workers", type=int, default=1, help="同时执行的题目数；每题两模式仍顺序执行，默认1")
    parser.add_argument("--validate-only", action="store_true", help="只验证题目和答案完整性，不访问服务")
    parser.add_argument("--preflight-only", action="store_true", help="只检查题集、答案、数据库和模型服务")
    args = parser.parse_args()
    if args.worker:
        return worker()
    if args.probe_api:
        return api_probe()
    if args.max_replans < 1 or args.timeout < 1 or args.workers < 1 or (args.limit is not None and args.limit < 1):
        parser.error("--max-replans、--timeout、--workers 和 --limit 必须为正整数")
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    from benchmark.comparison import (MODES, atomic_json, checked_cached_record, digest,
                                      experiment_settings, preflight, save_report, schedule_pairs)
    from benchmark.dev50 import load_cases
    from pipeline.llm_client import DEFAULT_MODEL, DEFAULT_TEMPERATURE

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        cases = load_cases(args.bench_dir, require_complete=False)
    except (OSError, ValueError, KeyError) as exc:
        blockers = [{"kind": "suite", "message": "题集文件缺失或结构无效", "exception_type": type(exc).__name__}]
        atomic_json(out_dir / "preflight.json", {"status": "blocked", "blockers": blockers})
        save_report(out_dir, [], [], {}, blockers)
        print("实验被阻塞：题集不可用；请查看 preflight.json。", flush=True)
        return 2
    if args.cases:
        wanted = {item.strip().upper() for item in args.cases.split(",") if item.strip()}
        missing = wanted - {case.id for case in cases}
        if missing:
            parser.error("未知题号：" + ", ".join(sorted(missing)))
        cases = [case for case in cases if case.id in wanted]
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        parser.error("没有可运行题目")

    check = preflight(cases, validate_only=args.validate_only)
    # 配置有密钥时做一次小请求，错误不暴露 SDK 凭据或连接串。
    if not args.validate_only and not any(item["kind"] == "api_credentials" for item in check["blockers"]):
        try:
            probe = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--probe-api"],
                                   cwd=ROOT, capture_output=True, timeout=45)
            probe_ok = probe.returncode == 0
        except subprocess.TimeoutExpired:
            probe_ok = False
        if not probe_ok:
            check["blockers"].append({"kind": "api_service", "message": "模型认证、网络或服务可用性检查未通过"})
            check["status"] = "blocked"
    atomic_json(out_dir / "preflight.json", check)
    metadata = {"model": DEFAULT_MODEL, "temperature": DEFAULT_TEMPERATURE,
                "seed": args.seed, "max_replans": args.max_replans, "workers": args.workers}
    if check["status"] == "blocked":
        save_report(out_dir, cases, [], metadata, check["blockers"])
        print(f"实验被阻塞：{len(check['blockers'])} 项条件未满足；未运行题目不计为答错。", flush=True)
        print(out_dir / "comparison_report.md", flush=True)
        return 2
    if args.validate_only or args.preflight_only:
        print(f"检查通过：{len(cases)} 题；尚未执行两组实验。", flush=True)
        return 0

    metadata = experiment_settings(cases, check["database"], seed=args.seed, max_replans=args.max_replans)
    metadata["worker_timeout_s"] = args.timeout
    metadata["workers"] = args.workers
    signature = digest(metadata)
    manifest = out_dir / "manifest.json"
    if manifest.exists():
        existing = json.loads(manifest.read_text(encoding="utf-8"))
        if not args.resume:
            parser.error("输出目录已有实验，请选择新 --out-dir 或使用 --resume")
        if existing.get("signature") != signature:
            parser.error("实验配置、代码、题集/答案或数据库已变化，不能复用断点；请选择新输出目录")
    elif args.resume and (out_dir / "records").exists():
        parser.error("已有逐题结果但缺失 manifest，无法安全续跑")
    atomic_json(manifest, {"signature": signature, "meta": metadata, "database": check["database"]})
    if args.resume:
        # 提交任何新任务前校验全部已有断点，避免发现错配时已发出其他模型请求。
        for case in cases:
            for mode in MODES:
                try:
                    checked_cached_record(out_dir / "records" / f"{mode}_{case.id}.json", signature, case.id, mode)
                except (ValueError, OSError) as exc:
                    parser.error(f"断点不可用（{type(exc).__name__}），请使用新输出目录")
    records, blockers = [], []
    started = time.monotonic()

    def run_pair(job):
        index, case = job
        pair_records, pair_blockers = [], []
        # 两组先后顺序按题交替，减少持续时间带来的服务状态偏差。
        modes = MODES if index % 2 == 0 else tuple(reversed(MODES))
        for mode in modes:
            record_path = out_dir / "records" / f"{mode}_{case.id}.json"
            cached = checked_cached_record(record_path, signature, case.id, mode) if args.resume else None
            if cached is not None:
                pair_records.append({**cached, "resumed": True})
                continue
            request = {
                "case_id": case.id, "mode": mode, "seed": args.seed,
                "max_replans": 0 if mode == "no_replan" else args.max_replans,
                "bench_dir": str(Path(args.bench_dir).resolve()) if args.bench_dir else None,
                "signature": signature, "database_fingerprint": check["database"]["fingerprint"],
                "output_root": str(out_dir), "record_path": str(record_path),
                "state_dir": str(out_dir / "state" / mode / case.id / uuid.uuid4().hex),
            }
            try:
                subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker"], cwd=ROOT,
                               input=json.dumps(request), text=True, encoding="utf-8", capture_output=True,
                               timeout=args.timeout)
                record = checked_cached_record(record_path, signature, case.id, mode)
                if record is None:
                    raise RuntimeError("worker 被服务或运行条件阻塞")
            except (subprocess.TimeoutExpired, RuntimeError, ValueError, OSError) as exc:
                record = {"id": case.id, "mode": mode, "signature": signature, "status": "blocked",
                          "error": type(exc).__name__}
                atomic_json(record_path, record)
                pair_blockers.append({"kind": "runtime", "message": f"{case.id} / {mode} 未完成（超时或服务/运行条件异常），可恢复后 --resume"})
                pair_records.append(record)
                break
            pair_records.append(record)
        return {"index": index, "records": pair_records, "blockers": pair_blockers}

    print(f"开始配对实验：{len(cases)}题，两模式，题目并发数 {args.workers}；模型 {metadata['model']}", flush=True)
    for pair in schedule_pairs(enumerate(cases), run_pair, workers=args.workers):
        blockers.extend(pair["blockers"])
        for record in pair["records"]:
            records.append(record)
            if record["status"] == "completed":
                resumed = "（断点复用）" if record.get("resumed") else ""
                print(f"[{pair['index'] + 1:02d}/{len(cases)}] {record['id']} {record['mode']} "
                      f"{'OK' if record['correct'] else 'FAIL'}{resumed}；{record['attempt_count']} 轮，"
                      f"{record['tool_call_count']} 次工具调用，{record['elapsed_s']:.1f}s", flush=True)
            else:
                print(f"{record['id']} {record['mode']} blocked；停止调度新题，收集已在途结果", flush=True)
            # 仅主线程更新汇总；worker 只写自己独占的逐题文件。
            save_report(out_dir, cases, records, metadata, blockers)
    metadata["this_invocation_elapsed_s"] = round(time.monotonic() - started, 3)
    report = save_report(out_dir, cases, records, metadata, blockers)
    print(f"状态 {report['status']}；完成配对 {report['paired_case_count']}/{len(cases)}", flush=True)
    print(out_dir / "comparison_report.md", flush=True)
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
