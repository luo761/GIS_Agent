"""50题题集、历史答案恢复及独立SQL生成的离线回归测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark import dev50
from benchmark.dev20 import compare
from scripts import build_dev50_suite


ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT / "data" / "benchmarks"
HISTORY = ROOT / "reports" / "dev20" / "dev20_latest.json"


def _fixture(tmp_path):
    for name in ("dev50.json", "dev50_expected.json"):
        (tmp_path / name).write_text((BENCH_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_preview_contains_exactly_fifty_cases_and_retains_original_twenty():
    cases = dev50.load_cases(BENCH_DIR, require_complete=False)
    history = json.loads(HISTORY.read_text(encoding="utf-8"))["results"]
    assert [case.id for case in cases] == list(dev50.CASE_IDS)
    for actual, reference in zip(cases[:20], history):
        assert (actual.id, actual.level, actual.question) == (
            reference["id"], reference["level"], reference["question"])
        # 不同 PostGIS/GEOS 版本重算允许既定 1e-6 容差内的浮点舍入差异。
        assert compare(actual.expected, reference["expected"]) == []
    assert all(case.output_contract and case.semantics for case in cases)
    assert {case.level for case in cases[20:]} == {"L1", "L2", "L3"}
    assert len({case.question for case in cases}) == 50
    assert all(not hasattr(case, "reference_sql") for case in cases)


def test_pending_answers_cannot_be_used_as_a_completed_benchmark(tmp_path):
    base = _fixture(tmp_path)
    data = json.loads((base / "dev50_expected.json").read_text(encoding="utf-8"))
    data.update(status="pending", pending_case_ids=list(dev50.CASE_IDS[20:]))
    data["cases"] = {key: value for key, value in data["cases"].items() if key in dev50.CASE_IDS[:20]}
    _save(base / "dev50_expected.json", data)
    with pytest.raises(ValueError, match="D21.*D50"):
        dev50.load_cases(base)
    assert all(case.expected == {} for case in dev50.load_cases(base, require_complete=False)[20:])


def test_complete_answers_load_but_empty_or_duplicate_case_data_is_rejected(tmp_path):
    base = _fixture(tmp_path)
    data = json.loads((base / "dev50_expected.json").read_text(encoding="utf-8"))
    # 仅作加载器测试的临时夹具，不会写入真实标准答案。
    data.update(status="complete", pending_case_ids=[], cases={case_id: {"count": 1} for case_id in dev50.CASE_IDS})
    _save(base / "dev50_expected.json", data)
    assert len(dev50.load_cases(base)) == 50
    data["cases"]["D50"] = {}
    _save(base / "dev50_expected.json", data)
    with pytest.raises(ValueError, match="D50"):
        dev50.load_cases(base)
    suite = json.loads((base / "dev50.json").read_text(encoding="utf-8"))
    suite["cases"][-1]["id"] = "D49"
    _save(base / "dev50.json", suite)
    with pytest.raises(ValueError, match="D01-D50"):
        dev50.load_cases(base, require_complete=False)


def test_bootstrap_uses_historical_expected_not_historical_model_answer(tmp_path):
    run = json.loads(HISTORY.read_text(encoding="utf-8"))
    expected = run["results"][0]["expected"]
    run["results"][0]["answer"] = {"count": -999999}
    history = tmp_path / "history.json"
    _save(history, run)
    output = tmp_path / "benchmarks"
    build_dev50_suite.build_suite(output, history)
    assert json.loads((output / "dev50_expected.json").read_text(encoding="utf-8"))["cases"]["D01"] == expected
    assert json.loads((output / "dev20_expected.json").read_text(encoding="utf-8"))["cases"]["D01"] == expected
    suite = json.loads((output / "dev50.json").read_text(encoding="utf-8"))
    assert len(suite["cases"]) == 50
    assert all(case["reference_sql"] and isinstance(case["reference_params"], list) for case in suite["cases"])


def test_changed_original_dataset_cannot_be_mixed_with_old_answer_snapshot(tmp_path, monkeypatch):
    def changed_answers():
        answers = {item["id"]: item["expected"] for item in json.loads(HISTORY.read_text(encoding="utf-8"))["results"]}
        answers["D01"] = {"count": -1}
        return answers

    monkeypatch.setattr(build_dev50_suite, "compute_expected", changed_answers)
    with pytest.raises(ValueError, match="D01"):
        build_dev50_suite.build_suite(tmp_path, HISTORY, calculate=True)
    pending = json.loads((tmp_path / "dev50_expected.json").read_text(encoding="utf-8"))
    assert pending["status"] == "pending" and pending["cases"]["D01"] != {"count": -1}


@pytest.mark.parametrize("case_id", dev50.CASE_IDS)
def test_each_oracle_binds_values_and_uses_the_selected_schema(case_id):
    sql, params = dev50.oracle_query(case_id, "tenant_gis")
    assert sql.startswith("WITH ") and " AS answer" in sql
    assert sql.count("%s") == len(params)
    assert '"tenant_gis".construction_areas' in sql
    assert "gis_lab." not in sql
    assert all(word not in sql.upper().split() for word in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE"))


def test_unknown_oracle_and_unsafe_schema_are_rejected():
    with pytest.raises(ValueError, match="未知"):
        dev50.oracle_query("D99", "gis_lab")
    with pytest.raises(ValueError, match="标识符"):
        dev50.oracle_query("D21", "gis_lab;DROP TABLE test")


def test_answer_generation_uses_one_read_only_snapshot_and_refuses_partial_results(monkeypatch):
    from tools import db

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0]

        def fetchall(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.sql = []
            self.answers = 0
            self.fail_after = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            self.sql.append(sql)
            if sql.startswith("SET "):
                return Rows([])
            if sql.startswith("SELECT COUNT(*)"):
                return Rows([(1, 0)])
            if sql.startswith("SELECT code"):
                return Rows([(code, 1) for code in params[0]])
            self.answers += 1
            if self.answers == self.fail_after:
                raise RuntimeError("oracle execution failed")
            return Rows([({"value": self.answers},)])

    connection = Connection()
    monkeypatch.setattr(db, "get_connection", lambda dsn: connection)
    answers = dev50.compute_expected("postgresql://localhost/offline", "tenant_gis")
    assert list(answers) == list(dev50.CASE_IDS)
    assert connection.sql[:2] == ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
                                  "SET LOCAL statement_timeout = '30s'"]
    assert connection.answers == 50
    broken = Connection()
    broken.fail_after = 3
    monkeypatch.setattr(db, "get_connection", lambda dsn: broken)
    with pytest.raises(RuntimeError, match="oracle execution failed"):
        dev50.compute_expected("postgresql://localhost/offline", "tenant_gis")
    assert broken.answers == 3
