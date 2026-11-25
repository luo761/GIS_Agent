"""dev50 配对实验：隔离状态、预检、逐轮指标、断点签名和比较报告。"""
from __future__ import annotations

import hashlib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from importlib.metadata import PackageNotFoundError, version
import json
import os
import platform
from pathlib import Path
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODES = ("no_replan", "with_replan")


def schedule_pairs(jobs, run_pair, *, workers: int = 1):
    """限制在途题目数量；收到 blocked 后不再发新题，收完已在途题目。"""
    if workers < 1:
        raise ValueError("workers 必须为正整数")
    pending_jobs = iter(jobs)
    stopped = False
    with ThreadPoolExecutor(max_workers=workers) as executor:
        active = set()
        for _ in range(workers):
            job = next(pending_jobs, None)
            if job is None:
                break
            active.add(executor.submit(run_pair, job))
        while active:
            finished, _ = wait(active, return_when=FIRST_COMPLETED)
            batch = [future.result() for future in finished]
            active.difference_update(finished)
            if any(result.get("blockers") for result in batch):
                stopped = True
            for result in batch:
                yield result
            if not stopped:
                for _ in range(workers - len(active)):
                    job = next(pending_jobs, None)
                    if job is None:
                        break
                    active.add(executor.submit(run_pair, job))


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def safe_feedback(answer: Any, expected: Any) -> tuple[bool, str]:
    """评估反馈只返回出错字段，不把标准答案中的数值或文字喂给重规划。"""
    from benchmark.dev20 import compare

    if answer is None:
        return False, "最终答复中未找到 JSON 对象，请按输出契约作答。"
    differences = compare(answer, expected)
    if not differences:
        return True, ""
    fields = list(dict.fromkeys(item.partition(":")[0] for item in differences))
    return False, "结果校验未通过；以下字段存在类型、数量或取值问题，请重新计算：" + "、".join(fields[:8])


def database_snapshot() -> dict[str, Any]:
    """对实际白名单表的所有行做只读指纹，避免在不同数据上比较或续跑。"""
    import psycopg
    from psycopg.conninfo import make_conninfo
    from config import settings
    from tools.gis_toolkit import ALLOWED_LAYERS
    from tools.db import quote_identifier

    dsn = make_conninfo(settings.DATABASE_URL, connect_timeout=3,
                        options="-c default_transaction_read_only=on -c statement_timeout=10000")
    tables = {}
    with psycopg.connect(dsn) as connection:
        version = connection.execute("SELECT PostGIS_Full_Version()").fetchone()[0]
        for name, layer in sorted(ALLOWED_LAYERS.items()):
            table = f"{quote_identifier(layer.schema_name)}.{quote_identifier(layer.table_name)}"
            pk = quote_identifier(layer.id_column)
            count, checksum = connection.execute(
                f"SELECT count(*), md5(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY {pk})::text, '[]')) "
                f"FROM {table} AS t"
            ).fetchone()
            tables[name] = {"row_count": count, "checksum": checksum}
    snapshot = {"schema": settings.APP_SCHEMA, "postgis_version": version, "tables": tables}
    return {**snapshot, "fingerprint": digest(snapshot)}


def source_fingerprint() -> str:
    """实现、配置、提示词改变后不能混用先前结果。"""
    files = []
    for folder in ("pipeline", "tools", "agents", "knowledge", "retrieval", "experience", "memory", "config", "benchmark"):
        files.extend(sorted((ROOT / folder).glob("*.py")))
    files.extend(sorted((ROOT / "config").glob("*.yaml")))
    files.append(ROOT / "scripts" / "run_dev50_comparison.py")
    return digest({str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in files if path.exists()})


def verify_expected_answers(cases: list) -> list[str]:
    """运行独立 SQL oracle，确认快照答案确实属于当前数据库。"""
    import psycopg
    from psycopg.conninfo import make_conninfo
    from benchmark.dev50 import oracle_query
    from benchmark.dev20 import compare
    from config import settings

    dsn = make_conninfo(settings.DATABASE_URL, connect_timeout=3,
                        options="-c default_transaction_read_only=on -c statement_timeout=15000")
    mismatches = []
    with psycopg.connect(dsn) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for case in cases:
            if not case.expected:
                continue
            sql, params = oracle_query(case.id, settings.APP_SCHEMA)
            actual = connection.execute(sql, params).fetchone()[0]
            if isinstance(actual, str):
                actual = json.loads(actual)
            if compare(actual, case.expected):
                mismatches.append(case.id)
    return mismatches


def experiment_settings(cases: list, database: dict, *, seed: int, max_replans: int) -> dict:
    from config import settings
    from pipeline.llm_client import DEFAULT_MODEL, DEFAULT_TEMPERATURE

    dependencies = {}
    for package in ("langgraph", "langchain-core", "langchain-deepseek", "pydantic", "psycopg"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = "missing"
    return {
        "suite": "postgis_dev50_v1", "model": DEFAULT_MODEL, "temperature": DEFAULT_TEMPERATURE,
        "seed": seed, "max_replans": max_replans, "toolset": settings.POSTGIS_TOOLSET,
        "schema_source": settings.SCHEMA_SOURCE, "database_fingerprint": database.get("fingerprint"),
        "source_fingerprint": source_fingerprint(), "absolute_tolerance": settings.BENCHMARK_ABS_TOL,
        "cases_hash": digest([vars(case) for case in cases]), "case_ids": [case.id for case in cases],
        "isolation": "fresh_process_and_empty_state_per_case_and_mode",
        "feedback": "field_paths_only_no_expected_values",
        "python_version": platform.python_version(), "dependencies": dependencies,
    }


def preflight(cases: list, *, validate_only: bool = False) -> dict:
    """收集独立阻塞条件，不把没有运行条件的题目计为错误。"""
    from config import settings

    blockers = []
    pending = [case.id for case in cases if not case.expected]
    if pending:
        blockers.append({"kind": "expected_answers", "message": "以下题目尚缺独立 SQL 标准答案", "case_ids": pending})
    if settings.POSTGIS_TOOLSET != "advanced":
        blockers.append({"kind": "toolset", "message": "dev50 完整实验需要 POSTGIS_TOOLSET=advanced"})
    if settings.SCHEMA_SOURCE != "postgis":
        blockers.append({"kind": "schema_source", "message": "真实空间实验需要 SCHEMA_SOURCE=postgis"})
    database = {}
    if not validate_only:
        if not os.getenv("DEEPSEEK_API_KEY", "").strip():
            blockers.append({"kind": "api_credentials", "message": "尚未配置 DEEPSEEK_API_KEY"})
        try:
            database = database_snapshot()
            mismatches = verify_expected_answers(cases)
            if mismatches:
                blockers.append({"kind": "expected_database_mismatch", "message": "标准答案与当前数据库独立 SQL 计算结果不一致，请重新生成答案",
                                 "case_ids": mismatches})
            if database_snapshot()["fingerprint"] != database["fingerprint"]:
                blockers.append({"kind": "database_changed", "message": "预检期间数据库发生变化，请在数据稳定后重试"})
        except Exception as exc:
            # 不输出连接串或异常详情，防止驱动/SDK 的错误信息带出配置凭据。
            blockers.append({"kind": "database", "message": "PostGIS 连接、扩展或白名单图层不可用",
                             "exception_type": type(exc).__name__})
    return {"status": "blocked" if blockers else ("validated" if validate_only else "ready"),
            "case_count": len(cases), "expected_ready": len(cases) - len(pending),
            "pending_case_ids": pending, "database": database, "blockers": blockers,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def configure_isolated_state(state_dir: Path, seed: int) -> None:
    """在导入流水线前重定向全部运行期状态，配置文件仍从项目读取。"""
    from config import settings
    from agents import agent_registry

    state_dir = state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=False)
    settings.DATA_DIR = state_dir
    settings.AGENT_MEMORY_BASE = state_dir / "memory"
    settings.CAPABILITY_PATH = state_dir / "agent_capabilities.json"
    settings.EXPERIENCE_PATH = state_dir / "experience.json"
    settings.CAPABILITY_CHART_HTML = state_dir / "capability_vector_chart.html"
    settings.CAPABILITY_CHART_PNG = state_dir / "capability_vector_chart.png"
    settings.CAPABILITY_CHART_ENABLED = False
    settings.MAX_SUBTASKS = 1
    config = agent_registry.load_agents_config()
    for agent_id, agent in config["agents"].items():
        agent["memory_dir"] = str(settings.AGENT_MEMORY_BASE / agent_id)
        agent["capabilities"] = {dimension: settings.CAPABILITY_INITIAL for dimension in agent_registry.dimensions()}
    config["initial_capability"] = settings.CAPABILITY_INITIAL
    from agents import capability_router
    capability_router.set_random_seed(seed)


def _infrastructure_exception(exc: Exception) -> bool:
    current = exc
    while current is not None:
        name = type(current).__name__.lower()
        module = type(current).__module__
        if module.startswith(("httpx", "httpcore", "openai")):
            return True
        if module.startswith("psycopg") and any(word in name for word in ("connect", "timeout", "operational", "interface")):
            return True
        current = current.__cause__
    return False


def execute_case(request: dict) -> dict:
    """一个 worker 只执行一道题的一种模式；父进程负责限时和逐题落盘。"""
    from benchmark.dev50 import load_cases
    from benchmark.dev20 import compare, extract_json, format_requirement

    case = next(case for case in load_cases(request.get("bench_dir"), require_complete=False)
                if case.id == request["case_id"])
    if not case.expected:
        raise ValueError("当前题目尚缺独立标准答案")
    mode = request["mode"]
    state_dir = Path(request["state_dir"])
    output_root = Path(request["output_root"]).resolve()
    if not state_dir.resolve().is_relative_to(output_root / "state"):
        raise ValueError("实验状态目录必须位于输出目录的 state 下")
    configure_isolated_state(state_dir, request["seed"])
    from config import settings
    from psycopg.conninfo import make_conninfo

    settings.DATABASE_URL = make_conninfo(settings.DATABASE_URL, connect_timeout=5,
                                         options="-c default_transaction_read_only=on -c statement_timeout=60000")
    if database_snapshot()["fingerprint"] != request["database_fingerprint"]:
        return {"id": case.id, "mode": mode, "status": "blocked", "error": "实验过程中数据库指纹发生变化"}

    from pipeline import pipeline_graph, stage5_evaluate, llm_client
    from agents.capability_store import get_default_store
    from experience import experience_retriever

    # 评估写入的题内失败经验应立即可被下一轮规划检索。
    stage5_evaluate._store = experience_retriever._store

    def verifier(state):
        answer = extract_json(state.subtasks[0].result) if state.subtasks else None
        return safe_feedback(answer, case.expected)

    stage5_evaluate.set_verifier(verifier)
    llm_client.reset_usage_metrics()
    started = time.monotonic()
    state, exception = None, None
    try:
        state = pipeline_graph.ask(case.question, ground_truth=case.id,
                                   answer_format=format_requirement(case), max_replans=request["max_replans"])
    except Exception as exc:
        exception = exc
    elapsed = round(time.monotonic() - started, 3)
    sub = state.subtasks[0] if state and state.subtasks else None
    answer = extract_json(sub.result) if sub else None
    history = state.attempt_history if state else []
    service_error = bool(exception and _infrastructure_exception(exception))
    if sub and ("LLM 工具调用失败" in sub.error or "LLM 调用失败" in sub.error):
        service_error = True
    if any("LLM 工具调用失败" in str(item.get("error", "")) or "LLM 调用失败" in str(item.get("error", ""))
           for attempt in history for item in attempt.get("subtasks", [])):
        service_error = True
    if any("OperationalError:" in str(step.get("error", ""))
           for attempt in history for item in attempt.get("subtasks", []) for step in item.get("trace", [])):
        service_error = True
    database_changed = database_snapshot()["fingerprint"] != request["database_fingerprint"]
    if database_changed:
        service_error = True
    return {
        "id": case.id, "level": case.level, "question": case.question, "mode": mode,
        "status": "blocked" if service_error else "completed", "correct": bool(answer is not None and not compare(answer, case.expected)),
        "first_correct": bool(history and history[0]["correct"]),
        "answer": answer, "expected": case.expected,
        "diffs": compare(answer, case.expected) if answer is not None else ["无 JSON 结果"],
        "evaluation": state.evaluation if state else "error", "error": type(exception).__name__ if exception else "",
        "database_changed_during_case": database_changed,
        "attempt_history": history, "attempt_count": len(history), "replans": state.replans if state else 0,
        "failed_attempts": state.failed_attempts if state else 0,
        "tool_call_count": sum(attempt["tool_call_count"] for attempt in history),
        "elapsed_s": elapsed, "llm_usage": llm_client.usage_metrics(),
        "capability_changes": state.capability_changes if state else [],
        "final_capabilities": get_default_store().table(),
    }


def mode_summary(records: list[dict]) -> dict:
    completed = [item for item in records if item.get("status") == "completed"]
    count = len(completed)
    correct = sum(item["correct"] for item in completed)
    first = sum(item.get("first_correct", False) for item in completed)
    elapsed = sum(item.get("elapsed_s", 0) for item in completed)
    calls = sum(item.get("tool_call_count", 0) for item in completed)
    attempts = sum(item.get("attempt_count", 0) for item in completed)
    usage_keys = ("llm_calls", "input_tokens", "output_tokens", "total_tokens", "usage_reported_calls")
    usage = {key: sum(item.get("llm_usage", {}).get(key, 0) for item in completed) for key in usage_keys}
    return {
        "completed": count, "correct": correct, "accuracy": correct / count if count else None,
        "first_correct": first, "first_accuracy": first / count if count else None,
        "rescued_after_first_failure": sum(item["correct"] and not item.get("first_correct", False) for item in completed),
        "tool_calls": calls, "mean_tool_calls": calls / count if count else None,
        "attempts": attempts, "mean_attempts": attempts / count if count else None,
        "total_elapsed_s": round(elapsed, 3), "mean_elapsed_s": elapsed / count if count else None,
        "replans": sum(item.get("replans", 0) for item in completed), "llm_usage": usage,
    }


def summarize_comparison(cases: list, records: list[dict], metadata: dict, *, blockers: list | None = None) -> dict:
    indexed = {(item["mode"], item["id"]): item for item in records if item.get("status") == "completed"}
    pairs = []
    for case in cases:
        baseline = indexed.get(("no_replan", case.id))
        replanning = indexed.get(("with_replan", case.id))
        if baseline is None or replanning is None:
            continue
        pairs.append({"id": case.id, "level": case.level, "question": case.question,
                      "no_replan_correct": baseline["correct"], "with_replan_correct": replanning["correct"],
                      "with_replan_first_correct": replanning.get("first_correct", False),
                      "accuracy_delta": int(replanning["correct"]) - int(baseline["correct"]),
                      "tool_calls_delta": replanning.get("tool_call_count", 0) - baseline.get("tool_call_count", 0),
                      "elapsed_delta_s": round(replanning.get("elapsed_s", 0) - baseline.get("elapsed_s", 0), 3)})
    full = len(pairs) == len(cases) and bool(cases)
    summaries = {mode: mode_summary([item for item in records if item["mode"] == mode]) for mode in MODES}
    level_summaries = {
        level: {mode: mode_summary([item for item in records if item["mode"] == mode and item.get("level") == level]) for mode in MODES}
        for level in sorted({case.level for case in cases})
    }
    return {
        "status": "blocked" if blockers else ("completed" if full else "partial"), "meta": metadata,
        "planned_case_count": len(cases), "paired_case_count": len(pairs), "summaries": summaries,
        "by_level": level_summaries, "pairs": pairs, "blockers": blockers or [],
        "paired_accuracy_delta_pp": (100 * sum(pair["accuracy_delta"] for pair in pairs) / len(pairs)) if pairs else None,
        "rescued_case_ids": [pair["id"] for pair in pairs if pair["accuracy_delta"] > 0],
        "regressed_case_ids": [pair["id"] for pair in pairs if pair["accuracy_delta"] < 0],
    }


def render_comparison(report: dict) -> str:
    def percent(value):
        return "未运行" if value is None else f"{value:.1%}"

    def number(value):
        return "未运行" if value is None else f"{value:.2f}"

    meta = report.get("meta", {})
    lines = ["# dev50：重规划开启 / 关闭配对实验", "",
             f"- 状态：`{report['status']}`；计划 {report['planned_case_count']} 题，完成配对 {report['paired_case_count']} 题。",
             f"- 模型：`{meta.get('model', '待检查')}`；路由种子：`{meta.get('seed', '待检查')}`；题目并发数：{meta.get('workers', 1)}。",
             f"- 重规划预算：关闭为 0；开启为 {meta.get('max_replans', 2)}（首次执行之外的最大次数）。", "",
             "每道题、每种模式使用新的进程和空能力/经验/记忆目录；题目之间不学习，题内重规划保留反馈和经验。"
             "两模式使用相同题集、数据库、模型参数和路由种子。固定路由种子不保证模型输出完全确定。", "",
             "评估器只反馈出错字段路径，不向重规划提示词提供标准答案值。结果为单次配对的描述性比较，不代表统计显著性。", ""]
    if report.get("blockers"):
        lines.extend(["## 尚未满足的运行条件", ""])
        for item in report["blockers"]:
            suffix = "（" + ", ".join(item["case_ids"]) + "）" if item.get("case_ids") else ""
            lines.append(f"- {item.get('message', item.get('kind', '运行条件不足'))}{suffix}")
        lines.extend(["", "未运行项目不计为答错；在补齐条件前不生成虚构的正确率或重规划收益。", ""])
    lines.extend(["## 整体指标（仅已完成题目）", "",
                  "| 模式 | 已完成 | 最终正确率 | 首次正确率 | 题内挽回 | 总工具调用 | 平均轮数 | 平均耗时 / 秒 | 总耗时 / 秒 | LLM调用 | 总tokens |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for mode in MODES:
        summary = report["summaries"][mode]
        usage = summary["llm_usage"]
        tokens = str(usage["total_tokens"]) if usage["usage_reported_calls"] else "未报告"
        lines.append(f"| {mode} | {summary['completed']} | {percent(summary['accuracy'])} | {percent(summary['first_accuracy'])} | "
                     f"{summary['rescued_after_first_failure']} | {summary['tool_calls']} | {number(summary['mean_attempts'])} | "
                     f"{number(summary['mean_elapsed_s'])} | {summary['total_elapsed_s']:.2f} | {usage['llm_calls']} | {tokens} |")
    delta = report["paired_accuracy_delta_pp"]
    lines.extend(["", f"完成配对题目的正确率差：{'未运行' if delta is None else f'{delta:+.1f} 个百分点'}。",
                  f"表中总耗时为逐题作答耗时之和；本次调度墙钟耗时：{number(meta.get('this_invocation_elapsed_s'))} 秒。",
                  "开启模式正确、关闭模式错误：" + ("、".join(report["rescued_case_ids"]) or "暂无"),
                  "开启模式错误、关闭模式正确：" + ("、".join(report["regressed_case_ids"]) or "暂无"), "",
                  "“题内挽回”指开启模式自身首轮错误、后续轮正确；与两个独立模式最终结果的配对差异分别统计。", "",
                  "## 分难度正确率", "", "| 等级 | 关闭：正确/完成 | 开启：正确/完成 |", "| --- | --- | --- |"])
    for level, modes in report["by_level"].items():
        left, right = modes["no_replan"], modes["with_replan"]
        lines.append(f"| {level} | {left['correct']}/{left['completed']} ({percent(left['accuracy'])}) | "
                     f"{right['correct']}/{right['completed']} ({percent(right['accuracy'])}) |")
    lines.extend(["", "## 逐题配对", "", "| 题号 | 等级 | 关闭正确 | 开启正确 | 工具调用增量 | 耗时增量 / 秒 |",
                  "| --- | --- | --- | --- | ---: | ---: |"])
    for pair in report["pairs"]:
        lines.append(f"| {pair['id']} | {pair['level']} | {pair['no_replan_correct']} | {pair['with_replan_correct']} | "
                     f"{pair['tool_calls_delta']:+d} | {pair['elapsed_delta_s']:+.2f} |")
    return "\n".join(lines) + "\n"


def save_report(out_dir: Path, cases: list, records: list, metadata: dict, blockers: list | None = None) -> dict:
    report = summarize_comparison(cases, records, metadata, blockers=blockers)
    atomic_json(out_dir / "comparison.json", report)
    (out_dir / "comparison_report.md").write_text(render_comparison(report), encoding="utf-8")
    return report


def checked_cached_record(path: Path, signature: str, case_id: str, mode: str) -> dict | None:
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("signature") != signature or record.get("id") != case_id or record.get("mode") != mode:
        raise ValueError(f"断点结果与当前配置不一致：{path.name}")
    return record if record.get("status") == "completed" else None
