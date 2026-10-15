from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.deterministic import DeterministicGISAgent
from app.agent.llm_agent import LLMGISAgent

from app.tools.registry import get_tool_spec


DEFAULT_COMPARISON_QUESTIONS = [
    "查看当前数据库有哪些空间图层",
    "查询施工一区内的燃气设备",
    "统计施工一区内燃气管线总长度",
    "查询与施工一区相交的燃气管线",
    "查询 520,520 附近最近 3 个燃气设备",
]


@dataclass(frozen=True)
class ComparisonCase:
    question: str
    deterministic: dict[str, Any]
    llm: dict[str, Any]
    same_tool: bool
    same_arguments: bool
    same_key_result: bool


def compare_agents(questions: list[str] | None = None) -> list[ComparisonCase]:
    deterministic_agent = DeterministicGISAgent()
    llm_agent = LLMGISAgent()
    results: list[ComparisonCase] = []

    for question in questions or DEFAULT_COMPARISON_QUESTIONS:
        deterministic = deterministic_agent.run(question)
        llm = llm_agent.run(question)
        results.append(
            ComparisonCase(
                question=question,
                deterministic=deterministic,
                llm=llm,
                same_tool=_first_tool_name(deterministic) == _first_tool_name(llm),
                same_arguments=_normalized_tool_args(deterministic) == _normalized_tool_args(llm),
                same_key_result=_key_result(deterministic) == _key_result(llm),
            )
        )
    return results

def _normalized_tool_args(run: dict[str, Any]) -> dict[str, Any] | None:
    plan = run.get("plan") or []
    if not plan:
        return None

    call = plan[0]
    spec = get_tool_spec(call["name"])
    return spec.validate_arguments(call.get("arguments")).model_dump()


def _first_tool_name(run: dict[str, Any]) -> str | None:
    plan = run.get("plan") or []
    return plan[0].get("name") if plan else None


def _first_tool_args(run: dict[str, Any]) -> dict[str, Any] | None:
    plan = run.get("plan") or []
    return plan[0].get("arguments") if plan else None


def _key_result(run: dict[str, Any]) -> Any:
    calls = run.get("tool_calls") or []
    if not calls or not calls[0].get("result"):
        return None
    tool_name = calls[0]["name"]
    payload = calls[0]["result"].get("result", {})

    if tool_name == "list_spatial_layers":
        return sorted(item["table_name"] for item in payload.get("layers", []))
    if tool_name == "describe_spatial_layer":
        spatial_ref = payload.get("spatial_ref") or {}
        return payload.get("layer"), spatial_ref.get("srid")
    if tool_name == "spatial_filter":
        return payload.get("relation"), sorted(item.get("code") for item in payload.get("features", []))
    if tool_name == "buffer_query":
        return payload.get("distance_m"), sorted(item.get("code") for item in payload.get("features", []))
    if tool_name == "clip_and_measure":
        return round(float(payload.get("total_measure", 0)), 3)
    if tool_name == "nearest_features":
        return [item.get("code") for item in payload.get("features", [])]
    return payload
