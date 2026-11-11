"""dev20 基准题集的加载、答案解析与判分。

题集与标准答案来自 dev20 项目（只读）：
  data/benchmarks/dev20.json         题目、等级、输出契约
  data/benchmarks/dev20_expected.json 标准答案快照
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import settings


@dataclass
class Case:
    id: str
    level: str
    question: str
    tags: list[str] = field(default_factory=list)
    semantics: str = ""
    output_contract: dict[str, str] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)


def load_suite(bench_dir: str | Path | None = None) -> dict[str, Any]:
    base = Path(bench_dir or settings.BENCHMARK_DIR)
    suite = json.loads((base / "dev20.json").read_text(encoding="utf-8"))
    expected = json.loads((base / "dev20_expected.json").read_text(encoding="utf-8"))
    return {"suite": suite, "expected": expected}


def load_cases(bench_dir: str | Path | None = None) -> list[Case]:
    data = load_suite(bench_dir)
    suite, expected = data["suite"], data["expected"]["cases"]
    cases: list[Case] = []
    for item in suite["cases"]:
        cases.append(Case(
            id=item["id"],
            level=item["level"],
            question=item["question"],
            tags=list(item.get("tags") or []),
            semantics=item.get("semantics", ""),
            output_contract=dict(item.get("output_contract") or {}),
            expected=expected.get(item["id"], {}),
        ))
    return cases


def format_requirement(case: Case) -> str:
    """把题目的输出契约转成给执行器的最终答复要求（只给结构，不给数值）。"""
    lines = ["最终只输出一个 JSON 对象（不要 markdown 代码块，不要解释文字）。",
             "JSON 的键与含义如下："]
    for key, desc in case.output_contract.items():
        lines.append(f"- {key}: {desc}")
    if case.id in {"D06", "D07", "D12", "D14", "D17", "D20"}:
        lines.append("其中 summary/长度对象需包含 value、unit、measure、measure_srid、feature_count 字段。")
    skeleton = json_skeleton(case.expected)
    lines.append("")
    lines.append("输出结构（仅示意层级与字段名，数值请用真实计算结果替换，数组需输出全部元素）：")
    lines.append(json.dumps(skeleton, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def json_skeleton(value: Any) -> Any:
    """从标准答案里提取“结构骨架”：保留层级与字段名，数值/字符串置空。"""
    if isinstance(value, dict):
        return {k: json_skeleton(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_skeleton(value[0])] if value else []
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0.0
    return ""


def extract_json(text: Any) -> Any:
    """从模型最终答复中提取第一个 JSON 对象。"""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def compare(actual: Any, expected: Any, *, abs_tol: float | None = None,
            rel_tol: float = 0.0) -> list[str]:
    """递归比较业务输出；返回差异列表（空列表表示一致）。

    只校验标准答案里出现的键，允许多余字段；列表按下标严格比较（题集要求顺序）。
    """
    abs_tol = settings.BENCHMARK_ABS_TOL if abs_tol is None else abs_tol
    diffs: list[str] = []

    def walk(exp: Any, act: Any, path: str) -> None:
        if isinstance(exp, dict):
            if not isinstance(act, dict):
                diffs.append(f"{path}: 期望对象，实际 {type(act).__name__}")
                return
            for key, value in exp.items():
                if key not in act:
                    diffs.append(f"{path}.{key}: 缺失")
                    continue
                walk(value, act[key], f"{path}.{key}")
            return
        if isinstance(exp, list):
            if not isinstance(act, list):
                diffs.append(f"{path}: 期望数组，实际 {type(act).__name__}")
                return
            if len(exp) != len(act):
                diffs.append(f"{path}: 长度 {len(act)}，期望 {len(exp)}")
                return
            for i, (e, a) in enumerate(zip(exp, act)):
                walk(e, a, f"{path}[{i}]")
            return
        if isinstance(exp, bool):
            if not isinstance(act, bool) or exp != act:
                diffs.append(f"{path}: {act!r}，期望 {exp!r}")
            return
        if isinstance(exp, (int, float)):
            e = float(exp)
            a = _num(act)
            if a is None:
                diffs.append(f"{path}: {act!r}，期望数值 {exp!r}")
            elif not math.isclose(e, a, rel_tol=rel_tol, abs_tol=abs_tol):
                diffs.append(f"{path}: {a:.6g}，期望 {e:.6g}")
            return
        if exp != act:
            diffs.append(f"{path}: {act!r}，期望 {exp!r}")

    walk(expected, actual, "$")
    return diffs
