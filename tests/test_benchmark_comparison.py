"""dev50 实验完整性、指标和隔离性的离线测试；不调用真实模型或数据库。"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import threading

import pytest

from benchmark import comparison
from benchmark.dev20 import Case
from config import settings


def _record(case_id, mode, *, correct=False, first=False, calls=3, attempts=1, seconds=2):
    return {"id": case_id, "mode": mode, "level": "L1", "status": "completed",
            "correct": correct, "first_correct": first, "tool_call_count": calls,
            "attempt_count": attempts, "elapsed_s": seconds, "replans": attempts - 1,
            "llm_usage": {"llm_calls": 4, "total_tokens": 120, "usage_reported_calls": 4}}


def test_feedback_preserves_diagnostic_paths_without_answer_values():
    expected = {"private_name": "SECRET_EXPECTED_LABEL", "groups": [{"value": 987654321}]}
    answer = {"private_name": "wrong", "groups": [{"value": 0}]}
    correct, feedback = comparison.safe_feedback(answer, expected)
    assert not correct
    assert "$.private_name" in feedback and "$.groups[0].value" in feedback
    assert "SECRET_EXPECTED_LABEL" not in feedback and "987654321" not in feedback
    assert "wrong" not in feedback
    assert comparison.safe_feedback(expected, expected) == (True, "")
    assert comparison.safe_feedback(None, expected)[0] is False


def test_empty_run_never_reports_zero_accuracy_or_fabricated_pairs():
    cases = [Case("D01", "L1", "q", expected={"value": 1})]
    result = comparison.summarize_comparison(cases, [], {}, blockers=[{"kind": "database", "message": "数据库不可用"}])
    assert result["status"] == "blocked"
    assert result["paired_case_count"] == 0
    assert result["paired_accuracy_delta_pp"] is None
    assert all(summary["accuracy"] is None for summary in result["summaries"].values())
    markdown = comparison.render_comparison(result)
    assert "未运行" in markdown and "0.0%" not in markdown


def test_paired_gain_and_regression_are_distinct_from_within_run_rescue():
    cases = [Case("D01", "L1", "q1"), Case("D02", "L1", "q2")]
    records = [
        _record("D01", "no_replan", calls=2),
        _record("D01", "with_replan", correct=True, first=False, attempts=3, calls=8),
        _record("D02", "no_replan", correct=True, first=True),
        _record("D02", "with_replan", correct=False, first=False, attempts=3),
    ]
    result = comparison.summarize_comparison(cases, records, {})
    assert result["status"] == "completed"
    assert result["paired_accuracy_delta_pp"] == 0
    assert result["rescued_case_ids"] == ["D01"]
    assert result["regressed_case_ids"] == ["D02"]
    replanned = result["summaries"]["with_replan"]
    assert replanned["accuracy"] == 0.5 and replanned["first_accuracy"] == 0
    assert replanned["rescued_after_first_failure"] == 1
    assert replanned["attempts"] == 6 and replanned["replans"] == 4
    assert replanned["tool_calls"] == 11 and replanned["llm_usage"]["total_tokens"] == 240


def test_partial_pairs_use_only_matched_cases_and_exclude_service_failures():
    cases = [Case("D01", "L1", "q1"), Case("D02", "L2", "q2")]
    records = [_record("D01", "no_replan", correct=True),
               _record("D02", "with_replan", correct=True),
               {"id": "D01", "mode": "with_replan", "status": "blocked"}]
    result = comparison.summarize_comparison(cases, records, {})
    assert result["status"] == "partial" and result["paired_case_count"] == 0
    assert result["paired_accuracy_delta_pp"] is None
    assert result["summaries"]["with_replan"]["completed"] == 1


def test_atomic_records_and_resume_reject_wrong_configuration(tmp_path):
    path = tmp_path / "record.json"
    record = {**_record("D01", "no_replan"), "signature": "original"}
    comparison.atomic_json(path, record)
    assert comparison.checked_cached_record(path, "original", "D01", "no_replan") == record
    assert not path.with_suffix(".json.tmp").exists()
    for signature, case_id, mode in [("changed", "D01", "no_replan"),
                                     ("original", "D02", "no_replan"),
                                     ("original", "D01", "with_replan")]:
        with pytest.raises(ValueError):
            comparison.checked_cached_record(path, signature, case_id, mode)
    record["status"] = "blocked"
    comparison.atomic_json(path, record)
    assert comparison.checked_cached_record(path, "original", "D01", "no_replan") is None


def test_preflight_collects_missing_answers_key_and_database_without_secrets(monkeypatch):
    monkeypatch.setattr(settings, "POSTGIS_TOOLSET", "advanced")
    monkeypatch.setattr(settings, "SCHEMA_SOURCE", "postgis")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    def unavailable():
        raise RuntimeError("postgresql://user:SECRET_PASSWORD@localhost/db")
    monkeypatch.setattr(comparison, "database_snapshot", unavailable)
    result = comparison.preflight([Case("D21", "L2", "q")])
    assert result["status"] == "blocked"
    assert {item["kind"] for item in result["blockers"]} == {"expected_answers", "api_credentials", "database"}
    assert "SECRET_PASSWORD" not in json.dumps(result)


def test_validate_only_never_contacts_database_or_model(monkeypatch):
    monkeypatch.setattr(settings, "POSTGIS_TOOLSET", "advanced")
    monkeypatch.setattr(settings, "SCHEMA_SOURCE", "postgis")
    monkeypatch.setattr(comparison, "database_snapshot", lambda: pytest.fail("unexpected database call"))
    result = comparison.preflight([Case("D01", "L1", "q", expected={"count": 1})], validate_only=True)
    assert result["status"] == "validated"
    assert result["blockers"] == []


def test_preflight_rejects_stale_answers_after_database_change(monkeypatch):
    monkeypatch.setattr(settings, "POSTGIS_TOOLSET", "advanced")
    monkeypatch.setattr(settings, "SCHEMA_SOURCE", "postgis")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setattr(comparison, "database_snapshot", lambda: {"fingerprint": "current-db"})
    monkeypatch.setattr(comparison, "verify_expected_answers", lambda cases: ["D01"])
    result = comparison.preflight([Case("D01", "L1", "q", expected={"count": 1})])
    assert result["status"] == "blocked"
    assert result["blockers"] == [{"kind": "expected_database_mismatch",
                                    "message": "标准答案与当前数据库独立 SQL 计算结果不一致，请重新生成答案",
                                    "case_ids": ["D01"]}]


def test_isolated_state_redirects_all_memory_and_store_paths(tmp_path, monkeypatch):
    from agents import agent_registry, capability_router
    isolated_config = copy.deepcopy(agent_registry.load_agents_config())
    monkeypatch.setattr(agent_registry, "_CONFIG", isolated_config)
    monkeypatch.setattr(capability_router, "_RNG", capability_router._RNG)
    path_settings = ("DATA_DIR", "AGENT_MEMORY_BASE", "CAPABILITY_PATH", "EXPERIENCE_PATH",
                     "CAPABILITY_CHART_HTML", "CAPABILITY_CHART_PNG", "CAPABILITY_CHART_ENABLED", "MAX_SUBTASKS")
    for key in path_settings:
        monkeypatch.setattr(settings, key, getattr(settings, key))
    original_base = settings.BASE_DIR
    path = tmp_path / "fresh_state"
    comparison.configure_isolated_state(path, 42)
    assert settings.BASE_DIR == original_base
    assert settings.MAX_SUBTASKS == 1 and settings.CAPABILITY_CHART_ENABLED is False
    for key in path_settings[:6]:
        assert Path(getattr(settings, key)).resolve().is_relative_to(path.resolve())
    assert all(Path(agent_registry.memory_dir(agent_id)).is_relative_to(path)
               for agent_id in agent_registry.agent_ids())
    assert all(value == settings.CAPABILITY_INITIAL
               for vector in agent_registry.initial_vectors().values() for value in vector.values())
    with pytest.raises(FileExistsError):
        comparison.configure_isolated_state(path, 42)


def test_experiment_signature_changes_with_answer_model_or_source(monkeypatch):
    from pipeline import llm_client
    monkeypatch.setattr(comparison, "source_fingerprint", lambda: "source-v1")
    cases = [Case("D01", "L1", "q", expected={"value": 1})]
    original = comparison.experiment_settings(cases, {"fingerprint": "db"}, seed=42, max_replans=2)
    cases[0].expected["value"] = 2
    changed_answer = comparison.experiment_settings(cases, {"fingerprint": "db"}, seed=42, max_replans=2)
    assert comparison.digest(original) != comparison.digest(changed_answer)
    monkeypatch.setattr(llm_client, "DEFAULT_MODEL", "different-model")
    changed_model = comparison.experiment_settings(cases, {"fingerprint": "db"}, seed=42, max_replans=2)
    assert comparison.digest(changed_answer) != comparison.digest(changed_model)


def test_saved_report_is_self_contained_and_has_both_modes(tmp_path):
    cases = [Case("D01", "L1", "q")]
    records = [_record("D01", "no_replan", correct=False),
               _record("D01", "with_replan", correct=True, attempts=2)]
    report = comparison.save_report(tmp_path, cases, records, {"model": "stub", "max_replans": 2})
    assert report["status"] == "completed"
    assert json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))["pairs"][0]["accuracy_delta"] == 1
    text = (tmp_path / "comparison_report.md").read_text(encoding="utf-8")
    assert "no_replan" in text and "with_replan" in text
    assert "+100.0 个百分点" in text


def test_pair_scheduler_caps_concurrency_and_collects_each_job_once():
    lock = threading.Lock()
    first_batch = threading.Barrier(3)
    active, peak = 0, 0

    def run_pair(job):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        if job < 3:
            first_batch.wait(timeout=3)
        with lock:
            active -= 1
        return {"index": job, "records": [job], "blockers": []}

    results = list(comparison.schedule_pairs(range(10), run_pair, workers=3))
    assert sorted(result["index"] for result in results) == list(range(10))
    assert peak == 3 and active == 0


def test_pair_scheduler_stops_new_jobs_but_drains_inflight_after_blocker():
    second_started = threading.Event()
    release_second = threading.Event()
    started = []

    def run_pair(job):
        started.append(job)
        if job == 0:
            assert second_started.wait(timeout=3)
            return {"index": job, "records": [job], "blockers": [{"kind": "service"}]}
        second_started.set()
        assert release_second.wait(timeout=3)
        return {"index": job, "records": [job], "blockers": []}

    iterator = comparison.schedule_pairs(range(10), run_pair, workers=2)
    try:
        first = next(iterator)
        assert first["index"] == 0 and first["blockers"]
    finally:
        release_second.set()
    remainder = list(iterator)
    assert [item["index"] for item in remainder] == [1]
    assert set(started) == {0, 1}
