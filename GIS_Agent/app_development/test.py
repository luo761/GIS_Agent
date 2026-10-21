"""多步计划比较、开发题集验收和真实模型评测。

来源：app/agent/plan_compare.py、app/benchmarks/development.py、live.py，
以及 scripts/validate_devset.py、run_devset_llm.py。

不指定参数时只做静态验收；--postgis 只读验证；--live 显式启用模型评测。
原始资料继续从项目 data/、sql/ 读取，不复制或改写标准答案。
"""
from __future__ import annotations

import sys

from app_development.agent import (
    ExecutionPlan, ResultReference, PlanExecutor, iter_references,
    MultiStepLLMGISAgent, execution_plan_definition, JsonRunLogger, persist_run,
)
from app_development.tool import create_toolkit, get_tool_spec
from app_development.db import get_settings


# ===== 原文件：app/agent/plan_compare.py =====
"""比较完整执行记录，而非仅比较第一个工具。不是通用 SQL/几何等价证明器。"""

import hashlib
import json
import math
from collections import Counter
from copy import deepcopy
from typing import Any



def _execution(run: dict[str, Any]) -> dict[str, Any]:
    return run.get("execution") or run


def _succeeded(run: dict[str, Any]) -> bool:
    execution = _execution(run)
    return run.get("status") == "ok" and execution.get("status") == "ok" and not run.get("error") and not execution.get("error")


def _numeric_json(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("比较不接受 NaN 或无穷大")
        return int(value) if value.is_integer() else value
    if isinstance(value, dict):
        return {key: _numeric_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_numeric_json(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_numeric_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reference(reference: ResultReference, identities: dict[str, str]) -> dict[str, Any]:
    return {"source": identities[reference.step_id], "path": reference.ref.split(".")[1:]}


def _restore_references(original: Any, normalized: Any, identities: dict[str, str]) -> Any:
    if isinstance(original, dict):
        if "$ref" in original:
            return {"$ref": _reference(ResultReference.model_validate(original), identities)}
        if not isinstance(normalized, dict):
            raise ValueError("标准化参数与原参数结构不一致")
        result = deepcopy(normalized)
        for key, item in original.items():
            result[key] = _restore_references(item, normalized[key], identities)
        return result
    if isinstance(original, list):
        if not isinstance(normalized, list) or len(original) != len(normalized):
            raise ValueError("标准化列表与原参数结构不一致")
        return [_restore_references(a, b, identities) for a, b in zip(original, normalized)]
    return normalized


def normalized_plan(run: dict[str, Any]) -> dict[str, Any]:
    """用实际执行时校验后的参数补齐默认值，再恢复符号引用，比较整张依赖图。

    忽略步骤 ID 和独立步骤排列；求交左右参数按交换律排序。输出名称、引用路径、
    工具次数和额外依赖仍属于合同。仅接受完整成功的执行记录，失败不能算相同。
    """
    if not _succeeded(run):
        raise ValueError("运行未完整成功，不能进行完整计划标准化")
    execution = _execution(run)
    plan = ExecutionPlan.model_validate(run["plan"])
    if ExecutionPlan.model_validate(execution["plan"]).model_dump(by_alias=True) != plan.model_dump(by_alias=True):
        raise ValueError("计划与执行记录不一致")
    records = execution["steps"]
    by_id = {record["step_id"]: record for record in records}
    if len(by_id) != len(records) or set(by_id) != {step.id for step in plan.steps}:
        raise ValueError("步骤执行记录不完整或重复")
    if not isinstance(run.get("outputs"), dict) or set(run["outputs"]) != set(plan.outputs):
        raise ValueError("最终输出与计划声明不一致")
    identities: dict[str, str] = {}
    nodes = []
    for step in plan.ordered_steps():
        record = by_id[step.id]
        if record["status"] != "ok" or record["tool"] != step.tool:
            raise ValueError(f"步骤执行记录未成功或工具不匹配: {step.id}")
        spec = get_tool_spec(step.tool, toolset=execution.get("toolset", "composable"))
        normalized = spec.validate_arguments(record["normalized_arguments"]).model_dump()
        arguments = _restore_references(step.arguments, normalized, identities)
        if step.tool == "query_features":
            for condition in arguments["filters"]:
                if condition["operator"] in {"in", "not_in"} and isinstance(condition["value"], list):
                    condition["value"] = sorted(condition["value"], key=_json)
            arguments["filters"] = sorted(arguments["filters"], key=_json)
        if step.tool == "intersection_geometry" and _json(arguments["left"]) > _json(arguments["right"]):
            arguments["left"], arguments["right"] = arguments["right"], arguments["left"]
        node = {"tool": step.tool, "arguments": arguments,
                "dependencies": sorted(identities[dep] for dep in step.depends_on)}
        encoded = _json(node)
        identities[step.id] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        nodes.append(encoded)
    return {"nodes": sorted(nodes), "outputs": {
        name: _reference(reference, identities) for name, reference in plan.outputs.items()
    }}


def _equal_outputs(left: Any, right: Any, abs_tol: float, rel_tol: float) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, abs_tol=abs_tol, rel_tol=rel_tol)
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            (left[k] == right[k] if k in {"srid", "measure_srid"} else _equal_outputs(left[k], right[k], abs_tol, rel_tol))
            for k in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_equal_outputs(a, b, abs_tol, rel_tol) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def compare_plan_runs(
    reference: dict[str, Any], candidate: dict[str, Any], *, abs_tol: float = 1e-6, rel_tol: float = 0,
) -> dict[str, Any]:
    """分别报告工具集合、标准化完整计划和最终输出是否一致；两边失败不算通过。"""
    if not all(math.isfinite(tol) and tol >= 0 for tol in (abs_tol, rel_tol)):
        raise ValueError("比较容差必须是有限非负数")
    result: dict[str, Any] = {
        "reference_success": _succeeded(reference), "candidate_success": _succeeded(candidate),
        "same_tools": False, "same_plan": False, "same_outputs": False,
        "matched": False, "diagnostics": [], "abs_tol": abs_tol, "rel_tol": rel_tol,
    }
    try:
        a = ExecutionPlan.model_validate(reference["plan"])
        b = ExecutionPlan.model_validate(candidate["plan"])
        result["same_tools"] = Counter(s.tool for s in a.steps) == Counter(s.tool for s in b.steps)
        result["same_plan"] = normalized_plan(reference) == normalized_plan(candidate)
        result["same_outputs"] = _equal_outputs(reference["outputs"], candidate["outputs"], abs_tol, rel_tol)
    except (ValueError, TypeError, KeyError) as exc:
        result["diagnostics"].append(f"{type(exc).__name__}: {exc}")
    result["matched"] = all(result[key] for key in (
        "reference_success", "candidate_success", "same_tools", "same_plan", "same_outputs",
    ))
    return result


# ===== 原文件：app/benchmarks/development.py =====
"""20 道开发题的合同、只读 SQL 基准和人工计划验收。

标准答案来自独立 SQL，不从参考计划复制。结果比较不要求计划相同；
静态验收流程不发起模型请求，也不自动改写标准答案快照。
"""

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, model_validator



ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "data/benchmarks/dev20.json"
SNAPSHOT = "data/benchmarks/dev20_expected.json"
SEEDS = ("sql/001_extensions_and_schema.sql", "sql/002_seed_mock_data.sql")
LAYERS = ("construction_areas", "gas_pipelines", "gas_devices", "water_pipelines", "demo_roads")


class DevelopmentCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^D(?:0[1-9]|1[0-9]|20)$")
    level: Literal["L1", "L2", "L3"]
    question: str = Field(min_length=10)
    tags: list[str] = Field(min_length=1)
    semantics: str = Field(min_length=5)
    reference_plan: str
    gold_sql: str
    output_contract: dict[str, str] = Field(min_length=1)
    tolerances: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_tolerances(self):
        if any(not math.isfinite(value) or value < 0 for value in self.tolerances.values()):
            raise ValueError("容差必须为有限非负数")
        return self


class DevelopmentSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite_id: Literal["postgis_dev20_v1"]
    split: Literal["development"]
    description: str
    toolset: Literal["advanced"]
    measure_srid: Literal[3857]
    quad_segs: Literal[8]
    default_abs_tol: float = Field(ge=0, allow_inf_nan=False)
    rel_tol: Literal[0]
    cases: list[DevelopmentCase] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def check_cases(self):
        if {case.id for case in self.cases} != {f"D{i:02}" for i in range(1, 21)}:
            raise ValueError("题目 ID 必须为不重复的 D01～D20")
        return self


def artifact_path(relative: str, root: Path = ROOT) -> Path:
    """拒绝绝对路径和越出项目目录的路径；不执行用户任意位置的 SQL。"""
    path = Path(relative)
    resolved = (root / path).resolve()
    if path.is_absolute() or not resolved.is_relative_to(root.resolve()):
        raise ValueError("题集文件必须位于项目目录内")
    return resolved


def read_json(path: Path) -> Any:
    def reject_constant(value):
        raise ValueError(f"JSON 不接受非有限常量: {value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def file_hash(path: Path) -> str:
    # Windows CRLF / Unix LF 不应导致同一资料出现不同指纹。
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def load_suite(root: Path = ROOT) -> DevelopmentSuite:
    return DevelopmentSuite.model_validate(read_json(artifact_path(MANIFEST, root)))


def load_plan(case: DevelopmentCase, root: Path = ROOT) -> ExecutionPlan:
    plan = ExecutionPlan.model_validate(read_json(artifact_path(case.reference_plan, root)))
    if set(plan.outputs) != set(case.output_contract):
        raise ValueError(f"{case.id}: 计划输出与题目合同不一致")
    producers = {step.id: step.tool for step in plan.steps}
    for step in plan.steps:
        spec = get_tool_spec(step.tool, toolset="advanced")
        if not list(iter_references(step.arguments)):
            spec.validate_arguments(step.arguments)
        if "features" in spec.args_schema.model_fields:
            value = step.arguments.get("features")
            if not isinstance(value, dict) or set(value) != {"$ref"}:
                raise ValueError(f"{case.id}: 完整集合必须引用上游结果")
            source, *suffix = value["$ref"].split(".")
            if suffix != ["result", "feature_set"] or producers[source] not in {
                "query_features", "buffer_features", "clip_features", "measure_features",
            }:
                raise ValueError(f"{case.id}: 非法 feature_set 引用")
    return plan


def artifact_hashes(suite: DevelopmentSuite, root: Path = ROOT) -> dict[str, str]:
    paths = [MANIFEST, *SEEDS]
    paths += [name for case in suite.cases for name in (case.reference_plan, case.gold_sql)]
    return {name: file_hash(artifact_path(name, root)) for name in paths}


def validate_static(root: Path = ROOT) -> dict[str, Any]:
    suite = load_suite(root)
    snapshot = read_json(artifact_path(SNAPSHOT, root))
    if not isinstance(snapshot, dict) or set(snapshot) != {"suite_id", "artifacts", "dataset", "cases"}:
        raise ValueError("标准答案快照结构不完整")
    dataset = snapshot["dataset"]
    if (not isinstance(dataset, dict) or set(dataset) != {"sha256", "layer_counts"}
            or not isinstance(dataset["sha256"], str) or len(dataset["sha256"]) != 64
            or not isinstance(dataset["layer_counts"], dict) or set(dataset["layer_counts"]) != set(LAYERS)):
        raise ValueError("标准答案快照的数据库指纹不完整")
    if snapshot.get("suite_id") != suite.suite_id or snapshot.get("artifacts") != artifact_hashes(suite, root):
        raise ValueError("题目、种子 SQL、参考计划或基准 SQL 已变化，标准答案快照需要人工复核")
    if set(snapshot.get("cases", {})) != {case.id for case in suite.cases}:
        raise ValueError("标准答案快照题目不完整")
    for case in suite.cases:
        load_plan(case, root)
        sql = artifact_path(case.gold_sql, root).read_text(encoding="utf-8")
        body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--")).lstrip()
        if not body.upper().startswith(("SELECT ", "WITH ")):
            raise ValueError(f"{case.id}: 基准必须为查询 SQL")
        if set(snapshot["cases"][case.id]) != set(case.output_contract):
            raise ValueError(f"{case.id}: 标准答案输出与合同不一致")
    return {"status": "ok", "suite_id": suite.suite_id, "split": suite.split,
            "case_count": len(suite.cases), "levels": dict(Counter(c.level for c in suite.cases)),
            "model_called": False, "database_checked": False}


def compare_outputs(actual: Any, expected: Any, *, abs_tol: float = 1e-6,
                    tolerances: dict[str, float] | None = None) -> list[str]:
    """只比较业务结果，不比较工具或计划；列表顺序、字段、单位和 SRID 均保留。"""
    effective_tolerances: dict[str, float] = tolerances or {}
    if any(not math.isfinite(v) or v < 0 for v in [abs_tol, *effective_tolerances.values()]):
        raise ValueError("容差必须为有限非负数")
    differences: list[str] = []

    def walk(left, right, path="", count_values=False):
        label = path or "outputs"
        if isinstance(left, bool) or isinstance(right, bool):
            equal = type(left) is type(right) and left == right
        elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
            leaf = path.split(".")[-1]
            exact = (leaf in {"srid", "measure_srid", "count"} or leaf.endswith("_count")
                     or (leaf == "value" and count_values))
            tolerance = 0 if exact else effective_tolerances.get(path, abs_tol)
            equal = math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, abs_tol=tolerance, rel_tol=0)
        elif isinstance(left, dict) and isinstance(right, dict):
            if left.keys() != right.keys():
                differences.append(f"{label}: 字段不一致")
            for key in right.keys() & left.keys():
                # 分组计数 value 也必须精确；不能被长度/面积的浮点容差掩盖。
                counted = ((key == "groups" and right.get("unit") == "feature")
                           or (key.endswith("_groups") and right.get(key[:-7] + "_unit") == "feature"))
                walk(left[key], right[key], f"{path}.{key}" if path else key, count_values or counted)
            return
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                differences.append(f"{label}: 列表长度不一致")
            for index, (a, b) in enumerate(zip(left, right)):
                walk(a, b, f"{path}.{index}", count_values)
            return
        else:
            equal = type(left) is type(right) and left == right
        if not equal:
            differences.append(f"{label}: 值不一致")

    walk(actual, expected)
    return differences


def dataset_fingerprint(conn) -> dict[str, Any]:
    # 常量表名，不接收外部 SQL/标识符。记录属性、ID、几何及 SRID，而非只检查数量。
    queries = [f"SELECT '{name}' AS layer, t.code, to_jsonb(t)-'geom' AS properties, "
               f"encode(ST_AsEWKB(t.geom),'hex') AS geometry FROM gis_lab.{name} t" for name in LAYERS]
    rows = conn.execute("SELECT * FROM (" + " UNION ALL ".join(queries) + ") source ORDER BY layer, code").fetchall()
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {"sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "layer_counts": dict(Counter(row["layer"] for row in rows))}


def sql_answer(conn, case: DevelopmentCase, root: Path = ROOT) -> dict[str, Any]:
    rows = conn.execute(artifact_path(case.gold_sql, root).read_text(encoding="utf-8")).fetchall()
    if len(rows) != 1 or set(rows[0]) != {"answer"} or not isinstance(rows[0]["answer"], dict):
        raise ValueError(f"{case.id}: 基准 SQL 必须返回一行 answer JSON 对象")
    return rows[0]["answer"]


def validate_postgis(database_url: str, *, case_ids: list[str] | None = None, root: Path = ROOT) -> dict[str, Any]:
    """只读核对 SQL→快照、人工计划→SQL 两条链；不生成模型能力成绩。"""
    result = validate_static(root)
    suite = load_suite(root)
    snapshot = read_json(artifact_path(SNAPSHOT, root))
    known = {case.id for case in suite.cases}
    if case_ids is not None and (not case_ids or len(set(case_ids)) != len(case_ids) or not set(case_ids) <= known):
        raise ValueError("题目 ID 必须非空、不重复且属于 D01～D20")
    selected = [case for case in suite.cases if case_ids is None or case.id in case_ids]
    dsn = make_conninfo(database_url, connect_timeout=5,
                        options="-c default_transaction_read_only=on -c statement_timeout=10000")
    executor = PlanExecutor(create_toolkit("advanced", dsn), toolset="advanced")
    records = []
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        fingerprint = dataset_fingerprint(conn)
        if fingerprint != snapshot["dataset"]:
            raise ValueError("数据库属性、几何或要素数量与开发题集快照不一致；请先核对数据，不自动重建数据库")
        for case in selected:
            answer = sql_answer(conn, case, root)
            baseline_errors = compare_outputs(answer, snapshot["cases"][case.id],
                                             abs_tol=suite.default_abs_tol, tolerances=case.tolerances)
            run = executor.run(load_plan(case, root))
            plan_errors = compare_outputs(run["outputs"], answer,
                                         abs_tol=suite.default_abs_tol, tolerances=case.tolerances)
            records.append({"case_id": case.id, "reference_success": run["status"] == "ok",
                            "sql_matches_snapshot": not baseline_errors, "plan_matches_sql": not plan_errors,
                            "diagnostics": [*baseline_errors, *plan_errors, *([run["error"]] if run["error"] else [])]})
        if dataset_fingerprint(conn) != fingerprint:
            raise ValueError("验收过程中数据库发生变化，不能接受本次结果；请冻结数据后重试")
    passed = sum(r["reference_success"] and r["sql_matches_snapshot"] and r["plan_matches_sql"] for r in records)
    result.update(status="ok" if passed == len(records) else "error", database_checked=True,
                  validation_kind="manual_plan_vs_independent_sql", checked_count=len(records), passed=passed, cases=records)
    return result


# ===== 原文件：app/benchmarks/live.py =====
"""单次真实模型开发题集试跑：不泄露标准解、不重试、不自动调优。

每题一次请求，独立上下文；只读执行并与独立SQL比较。批次可恢复，但
已经记录为开始却没有结果的请求不会自动重发，避免中断后重复计费。
"""

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import statistics
from typing import Any, Callable
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row



DEFAULT_DIRECTORY = ROOT / "reports" / "runs" / "dev20"
# 指纹必须记录本组合版实际执行的四个文件，避免误记原 app 实现。
IMPLEMENTATION_FILES = (
    "app_development/agent.py", "app_development/tool.py",
    "app_development/db.py", "app_development/test.py",
)


class DevelopmentLLMAgent(MultiStepLLMGISAgent):
    """仅增加统一输出接口规则，不提供任何一题的参考步骤或答案。"""

    def system_prompt(self) -> str:
        return super().system_prompt() + """
开发题集的输出合同规则（优先于上述通用 area/length 命名及输出层级约定）：
用户消息包含题目和输出合同，outputs 的键必须恰好是合同要求的字段名。
所有输出仍必须是 $ref，禁止写常量或自行计算数值，禁止增加合同外字段。
计数可引用 query_features.result.feature_set.feature_count；小型标量计数允许输出。
合同要求完整集合量测 summary 时引用 measure_features.result.summary；
合同要求完整单几何量测时引用 measure_geometry.result；两种对象字段不同，不可混用。
分组列表引用 summarize_features.result.groups；单独的单位字段引用该工具 result.unit。
完整比值引用 calculate_ratio.result。数组排序必须按题目执行，不默认截断。
只依据本题和统一工具定义规划；不需要、也不会提供标准SQL、答案或参考计划。
"""


def case_prompt(case: DevelopmentCase) -> str:
    return json.dumps({"题目": case.question, "输出合同": case.output_contract}, ensure_ascii=False, indent=2)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def protocol(model_name: str, *, injected_model: bool) -> dict[str, Any]:
    suite = load_suite()
    agent = DevelopmentLLMAgent(model=object(), toolset="advanced")
    return {
        "suite_id": suite.suite_id, "split": "development", "requested_model": model_name,
        "model_source": "injected_test_double" if injected_model else "live_provider",
        "temperature": 0, "timeout_seconds": 60, "max_retries": 0, "thinking": "disabled",
        "attempts_per_case": 1, "toolset": "advanced", "scoring": "outputs_vs_independent_sql",
        "system_prompt_sha256": _hash(agent.system_prompt()), "plan_schema_sha256": _hash(execution_plan_definition()),
        "artifacts": artifact_hashes(suite), "answer_snapshot_sha256": file_hash(artifact_path(SNAPSHOT)),
        "implementation": {path: file_hash(ROOT / path) for path in IMPLEMENTATION_FILES},
        "packages": {name: version(name) for name in ("langchain-deepseek", "langchain-core", "psycopg", "pydantic")},
    }


def _exclusive_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _atomic_json(path: Path, data: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        _exclusive_json(temporary, data)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _batch_lock(directory: Path):
    lock = directory / "batch.lock"
    # 不删除别的进程创建的锁；崩溃残留锁需先人工确认没有运行进程。
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(datetime.now(timezone.utc).isoformat())
    try:
        yield
    finally:
        lock.unlink()


def _ready(database_url: str, case_ids: list[str]) -> None:
    result = validate_postgis(database_url, case_ids=case_ids)
    if result["status"] != "ok":
        raise ValueError("独立基准或人工计划预检失败，未调用模型")


def _gold(dsn: str, case: DevelopmentCase) -> dict[str, Any]:
    suite = load_suite()
    snapshot = read_json(artifact_path(SNAPSHOT))
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        if dataset_fingerprint(conn) != snapshot["dataset"]:
            raise ValueError("数据库指纹已变化，停止批次，不将其计为模型错误")
        answer = sql_answer(conn, case)
    if compare_outputs(answer, snapshot["cases"][case.id], abs_tol=suite.default_abs_tol, tolerances=case.tolerances):
        raise ValueError("独立SQL与快照不一致，停止批次")
    return answer


def _check_dataset(dsn: str) -> None:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        if dataset_fingerprint(conn) != read_json(artifact_path(SNAPSHOT))["dataset"]:
            raise ValueError("模型执行期间数据库发生变化，本题结果不可评分")


def assess(run: dict[str, Any], case: DevelopmentCase, answer: dict[str, Any]) -> dict[str, Any]:
    response_received = run.get("model_response") is not None
    valid_plan = run.get("plan") is not None
    execution = run.get("execution") or {}
    execution_success = execution.get("status") == "ok"
    differences = compare_outputs(run.get("outputs", {}), answer,
                                  abs_tol=load_suite().default_abs_tol, tolerances=case.tolerances)
    correct = run.get("status") == "ok" and execution_success and not differences
    if not response_received:
        outcome = "provider_error"
    elif not valid_plan:
        outcome = "planning_error"
    elif not execution_success:
        outcome = "execution_error"
    elif run.get("status") != "ok":
        outcome = "summary_error"
    else:
        outcome = "correct" if correct else "output_mismatch"
    return {"case_id": case.id, "level": case.level, "response_received": response_received,
            "valid_plan": valid_plan, "execution_success": execution_success, "baseline_valid": True,
            "result_correct": correct, "outcome": outcome, "differences": differences,
            "error_stage": run.get("error_stage"), "error": run.get("error"),
            "planning_elapsed_ms": run.get("planning_elapsed_ms", 0),
            "execution_elapsed_ms": execution.get("elapsed_ms", 0), "elapsed_ms": run.get("elapsed_ms", 0),
            "usage": (run.get("model_response") or {}).get("usage"),
            "actual_model": (run.get("model_response") or {}).get("metadata", {}).get("model_name")}


def aggregate(records: list[dict[str, Any]], planned_count: int) -> dict[str, Any]:
    attempted = len(records)
    responses = sum(r["response_received"] for r in records)
    valid = sum(r["valid_plan"] for r in records)
    executed = sum(r["execution_success"] for r in records)
    evaluated = sum(r["response_received"] and r["baseline_valid"] for r in records)
    correct = sum(r["result_correct"] is True for r in records)
    usages = [r["usage"] for r in records if isinstance(r.get("usage"), dict)]
    return {"planned": planned_count, "attempted": attempted, "responses_received": responses,
            "valid_plans": valid, "execution_successes": executed, "evaluated": evaluated, "correct": correct,
            "result_accuracy": correct / evaluated if evaluated else None,
            "end_to_end_accuracy": correct / attempted if attempted else None,
            "planning_valid_rate": valid / responses if responses else None,
            "execution_success_rate": executed / valid if valid else None,
            "outcomes": dict(Counter(r["outcome"] for r in records)),
            "mean_planning_ms": statistics.mean(r["planning_elapsed_ms"] for r in records) if records else None,
            "total_elapsed_ms": sum(r["elapsed_ms"] for r in records),
            "token_usage": {key: sum(usage.get(key, 0) or 0 for usage in usages)
                            for key in ("input_tokens", "output_tokens", "total_tokens")},
            "usage_recorded_cases": len(usages)}


def _redact(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    return value


def run_batch(database_url: str, model_name: str, *, live: bool = False, model: Any = None,
              directory: Path = DEFAULT_DIRECTORY, case_ids: list[str] | None = None,
              resume: str | None = None, limit: int = 20, secrets: tuple[str, ...] = (),
              progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    if model is None and not live:
        raise ValueError("真实模型试跑必须显式启用 live")
    if not 1 <= limit <= 20:
        raise ValueError("limit 必须为1～20")
    suite = load_suite()
    by_id = {case.id: case for case in suite.cases}
    if case_ids is not None and (not case_ids or len(set(case_ids)) != len(case_ids) or not set(case_ids) <= set(by_id)):
        raise ValueError("题目ID必须非空、不重复且属于D01～D20")
    if resume is not None and (not re.fullmatch(r"[a-f0-9]{32}", resume) or case_ids is not None):
        raise ValueError("resume必须是批次UUID，不能同时指定case_ids")
    current_protocol = protocol(model_name, injected_model=model is not None)
    directory = Path(directory).resolve()
    if resume:
        batch_id = resume
        batch_dir = directory / batch_id
        metadata = read_json(batch_dir / "batch.json")
        if metadata["protocol"] != current_protocol:
            raise ValueError("模型、提示词、资料、工具代码或SDK版本变化，禁止混入原批次")
        selected_ids = metadata["case_ids"]
    else:
        batch_id = uuid4().hex
        selected_ids = case_ids or list(by_id)
        batch_dir = directory / batch_id
        batch_dir.mkdir(parents=True, exist_ok=False)
        metadata = {"batch_id": batch_id, "created_at": datetime.now(timezone.utc).isoformat(),
                    "case_ids": selected_ids, "protocol": current_protocol}
        _exclusive_json(batch_dir / "batch.json", metadata)
    with _batch_lock(batch_dir):
        if progress:
            progress({"event": "preflight", "batch_id": batch_id, "case_count": len(selected_ids)})
        _ready(database_url, selected_ids)  # 任何付费请求之前核对全部基准。
        dsn = make_conninfo(database_url, connect_timeout=5,
                           options="-c default_transaction_read_only=on -c statement_timeout=10000")
        agent = DevelopmentLLMAgent(model=model, toolkit=create_toolkit("advanced", dsn), toolset="advanced")
        records = []
        pending = []
        for case_id in selected_ids:
            checkpoint = batch_dir / "cases" / f"{case_id}.json"
            if checkpoint.exists():
                record = read_json(checkpoint)
                run_path = batch_dir / "runs" / f"{record['run_id']}.json"
                if not run_path.exists() or file_hash(run_path) != record["run_sha256"]:
                    raise ValueError("逐题原始日志缺失或变化，停止恢复批次")
                records.append(record)
            elif (batch_dir / "attempts" / f"{case_id}.json").exists():
                raise ValueError(f"{case_id}已开始但未保存结果，不能自动重复付费请求；请人工核对")
            else:
                pending.append(case_id)
        stop_reason = None
        for case_id in pending[:limit]:
            case = by_id[case_id]
            answer = _gold(dsn, case)
            prompt = case_prompt(case)
            _exclusive_json(batch_dir / "attempts" / f"{case_id}.json", {
                "case_id": case_id, "started_at": datetime.now(timezone.utc).isoformat(), "prompt_sha256": _hash(prompt)})
            if progress:
                progress({"event": "case_started", "case_id": case_id, "batch_id": batch_id})
            run = agent.run(prompt)
            assessment = assess(run, case, answer)
            try:
                _check_dataset(dsn)
            except (ValueError, psycopg.Error):
                assessment.update(baseline_valid=False, result_correct=None, outcome="dataset_invalidated")
            run["benchmark"] = {"batch_id": batch_id, "assessment": assessment, "expected_outputs": answer,
                                "prompt_sha256": _hash(prompt)}
            run = _redact(run, (*secrets, database_url, dsn))
            persist_run(run, JsonRunLogger(batch_dir / "runs"))
            if run["logging_error"]:
                raise OSError("模型已经调用但原始日志保存失败，停止批次，禁止自动重发")
            record = {**_redact(assessment, (*secrets, database_url, dsn)), "run_id": run["run_id"],
                      "run_sha256": file_hash(Path(run["log_path"]))}
            _exclusive_json(batch_dir / "cases" / f"{case_id}.json", record)
            records.append(record)
            if progress:
                progress({"event": "case_finished", "case_id": case_id, "outcome": record["outcome"],
                          "elapsed_ms": record["elapsed_ms"], "batch_id": batch_id})
            if record["outcome"] in {"provider_error", "dataset_invalidated"}:
                stop_reason = record["outcome"]
            summary = _summary(metadata, records, by_id, stop_reason, batch_dir)
            _atomic_json(batch_dir / "summary.json", summary)
            if stop_reason:
                break
        summary = _summary(metadata, records, by_id, stop_reason, batch_dir)
        _atomic_json(batch_dir / "summary.json", summary)
        return summary


def _summary(metadata, records, by_id, stop_reason, batch_dir):
    selected_ids = metadata["case_ids"]
    ordered = sorted(records, key=lambda record: selected_ids.index(record["case_id"]))
    completed = len(ordered) == len(selected_ids)
    return {"batch_id": metadata["batch_id"], "suite_id": metadata["protocol"]["suite_id"],
            "status": "stopped" if stop_reason else ("complete" if completed else "partial"),
            "stop_reason": stop_reason, "model_source": metadata["protocol"]["model_source"],
            "requested_model": metadata["protocol"]["requested_model"],
            "actual_models": sorted({r["actual_model"] for r in ordered if r.get("actual_model")}),
            "metrics": aggregate(ordered, len(selected_ids)),
            "by_level": {level: aggregate([r for r in ordered if r["level"] == level],
                                          sum(by_id[c].level == level for c in selected_ids))
                         for level in ("L1", "L2", "L3")},
            "pending_case_ids": [case_id for case_id in selected_ids if case_id not in {r["case_id"] for r in ordered}],
            "cases": ordered, "summary_path": str(batch_dir / "summary.json"),
            "note": "开发集单次试跑，不是独立正式测试或稳定性结论；未自动调优或重试。"}


# ===== 原文件：scripts/validate_devset.py =====
"""检查开发题集资料；--postgis 只读验证人工计划，不调用真实模型。"""

import argparse
import json

import psycopg



def validate_main() -> int:
    parser = argparse.ArgumentParser(description="检查20道开发题及独立SQL，不调用LLM")
    parser.add_argument("--postgis", action="store_true", help="显式启用只读数据库及人工计划对照")
    parser.add_argument("--case", action="append", choices=[f"D{i:02}" for i in range(1, 21)], help="只验收指定题，可重复指定不同题；需 --postgis")
    args = parser.parse_args()
    if args.case and not args.postgis:
        parser.error("--case 需要 --postgis")
    try:
        result = (validate_postgis(get_settings().database_url, case_ids=args.case)
                  if args.postgis else validate_static())
    except psycopg.Error as exc:
        result = {"status": "error", "model_called": False, "error": type(exc).__name__,
                  "message": "数据库连接或查询失败，请检查连接、种子数据及只读权限。"}
    except (ValueError, OSError) as exc:
        result = {"status": "error", "model_called": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


# ===== 原文件：scripts/run_devset_llm.py =====
"""显式 --live 付费试跑开发题集，数据库只读，每题最多一次请求。"""

import argparse
import json
from pathlib import Path

import psycopg



def live_main() -> int:
    parser = argparse.ArgumentParser(description="真实模型开发题集试跑（会产生模型费用），不自动重试")
    parser.add_argument("--live", action="store_true", help="明确授权调用真实模型")
    parser.add_argument("--case", action="append", choices=[f"D{i:02}" for i in range(1, 21)], help="指定题目；重复该参数可控制批次题目顺序")
    parser.add_argument("--limit", type=int, default=20, help="本次最多新增请求数，1～20；恢复批次时不重跑已有记录")
    parser.add_argument("--resume", help="恢复相同协议的批次UUID，不重试已有结果或不明中断请求")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args()
    if not args.live:
        parser.error("请显式添加 --live 才会调用真实模型，调用可能产生费用")
    if args.resume and args.case:
        parser.error("--resume 不能与 --case 同时使用")
    if not 1 <= args.limit <= 20:
        parser.error("--limit 必须为1～20")
    settings = get_settings()
    if not settings.llm_api_key:
        parser.error("未配置 LLM_API_KEY 或 DEEPSEEK_API_KEY，不会调用模型")
    def progress(event):
        print(json.dumps(event, ensure_ascii=True), flush=True)
    try:
        result = run_batch(settings.database_url, settings.llm_model, live=True,
                           case_ids=args.case, limit=args.limit, resume=args.resume, directory=args.output_dir,
                           secrets=(settings.llm_api_key,), progress=progress)
    except psycopg.Error as exc:
        result = {"status": "error", "error": type(exc).__name__, "message": "数据库预检或基准查询失败；未对失败步骤自动重试。"}
    except (ValueError, OSError, KeyError) as exc:
        result = {"status": "error", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False), flush=True)
    return 0 if result["status"] in {"partial", "complete"} else 1


def main() -> int:
    """合并两个既有命令入口；不带 --live 时绝不启动真实模型试跑。"""
    return live_main() if "--live" in sys.argv[1:] else validate_main()


if __name__ == "__main__":
    raise SystemExit(main())
