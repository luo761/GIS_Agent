from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def simple_rule_parse(question: str) -> dict:
    """Deterministic baseline parser for measuring the eval harness itself."""

    domains = []
    if "燃气" in question:
        domains.append("燃气")
    if "水务" in question or "供水" in question or "排水" in question:
        domains.append("水务")
    if not domains and "隐患" in question:
        domains.extend(["燃气", "水务"])

    area = next((name for name in ["A区", "B区", "C区"] if name in question), None)
    distance = None
    for token in ["20", "50", "100", "200", "300", "500"]:
        if f"{token}米" in question:
            distance = float(token)
            break

    if "冲突" in question or "交叉" in question:
        intent = "line_conflict_detection"
    elif "覆盖" in question:
        intent = "facility_coverage"
    elif "范围内" in question and "隐患" in question:
        intent = "hazards_near_pipes"
    elif "长度" in question:
        intent = "pipe_length_statistics"
    elif "缓冲" in question:
        intent = "buffer_analysis"
    elif "重叠" in question:
        intent = "overlay_analysis"
    else:
        intent = "spatiotemporal_filter"

    return {"domains": domains, "intent": intent, "area": area, "distance": distance}


def score_case(predicted: dict, expected: dict) -> dict[str, bool]:
    return {
        "domain_ok": set(predicted.get("domains", [])) == set(expected.get("domains", [])),
        "intent_ok": predicted.get("intent") == expected.get("intent"),
        "area_ok": predicted.get("area") == expected.get("area"),
        "distance_ok": predicted.get("distance") == expected.get("distance"),
    }


def main() -> None:
    cases_path = Path(__file__).with_name("eval_cases.json")
    cases = load_cases(cases_path)
    started = perf_counter()
    scores = []

    for case in cases:
        predicted = simple_rule_parse(case["question"])
        scores.append(score_case(predicted, case["expected"]))

    elapsed = perf_counter() - started
    metrics = {
        key: sum(1 for score in scores if score[key]) / len(scores)
        for key in ["domain_ok", "intent_ok", "area_ok", "distance_ok"]
    }
    metrics["case_count"] = len(cases)
    metrics["elapsed_seconds"] = elapsed
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
