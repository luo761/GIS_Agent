"""阶段④ 执行器：计划/DAG → 模型直接发起算子调用（ReAct）。

算子已通过 bind_tools 绑定在模型上（`tools/postgis_tools.py`），模型的每一轮要么
返回 tool_calls（执行算子），要么返回最终答复。

中间结果通过**结果仓库 + `$ref` 引用**传递：完整几何/要素集不回灌给模型，
只回填压缩视图；下游工具需要上游结果时写 `{"$ref": "t1.result.feature_set"}`，
由执行器在调用前解析。这样既避免上下文爆炸，也避免模型手抄几何。
"""
from __future__ import annotations

import copy
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from pipeline.pipeline_state import PipelineState, SubTask
from pipeline import llm_client as llm
from tools import tool_registry
from pipeline.stage3_plan import _agent_memory

MAX_TOOL_ROUNDS = 20  # 单个子任务最大工具调用轮数（防死循环）

SYSTEM_PROMPT = (
    "你是 GIS 空间分析执行器。工具已绑定在模型上，请直接调用工具完成任务，"
    "参数名与含义以工具 schema 为准。\n"
    "工具返回的完整结果已保存在结果仓库中，回填给你的是压缩视图；"
    "下游工具需要上游结果时，用引用对象代替整段数据，例如：\n"
    '  {"$ref": "t1.result.feature_set"}\n'
    '  {"$ref": "t1.result.geometry"}\n'
    '  {"$ref": "t2.result.summary"}\n'
    "其中 t1/t2 是工具结果中的 step_id。不要把几何坐标抄进参数。\n"
    "语义约定：ST_Within 严格位于内部（不含边界），ST_Intersects 相交（含边界）；"
    "长度/面积用 measure_features 或 measure_geometry；分组汇总用 summarize_features。\n"
    "图层与编号：施工区 construction_areas（A001…）、燃气管线 gas_pipelines（G001…）、"
    "燃气设备 gas_devices（D001…）、水管 water_pipelines（W001…）；"
    "层内用 code 引用，跨层用空间关系，不要把 A001 当成设备编号。\n"
    "工具报错时根据错误信息调整参数重试。全部步骤完成后直接给出最终结果，不要再调用工具。\n"
    "执行约束：\n"
    "1) measure_geometry 只量测单个几何，target 用 {\"$ref\": \"tN.result.geometry\"}；"
    "要素集请用 measure_features，不要把它塞进 measure_geometry。\n"
    "2) clip_features 默认就会保留边界接触（非空、长度可能为 0）并丢弃空几何；"
    "不要设置 keep_empty=True，除非题目明确要求保留“完全为空”的要素。\n"
    "3) 裁剪前先用 query_features + relation 筛出确实相交的候选要素，再裁剪；"
    "不要对整表裁剪后再靠空几何凑结果。\n"
    "4) 题目同时给出两个范围条件（例如“在影响范围内且在 A001 内”）时，要依次裁剪到两个范围，"
    "不能只裁剪一个。\n"
    "5) 输出时区分“区域总面积/分母”与“覆盖面积/分子”，不要把 A001 面积当成覆盖面积。\n"
    "6) $ref 只能指向已成功的 step_id；引用失败步骤会直接报错。"
)


def _as_text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(str(part) for part in content)
    return "" if content is None else str(content)


# ---------------------------------------------------------------- 结果引用
def _resolve_refs(value: Any, results: dict[str, dict]) -> Any:
    """递归解析 {"$ref": "t1.result.feature_set"} 形式的引用。"""
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            return _lookup(str(value["$ref"]), results)
        return {k: _resolve_refs(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(v, results) for v in value]
    return value


def _lookup(path: str, results: dict[str, dict]) -> Any:
    parts = [p for p in str(path).split(".") if p]
    if not parts or parts[0] not in results:
        raise KeyError(f"引用失败：步骤 {parts[0] if parts else ''} 没有成功结果")
    node: Any = results[parts[0]]
    for part in parts[1:]:
        if isinstance(node, dict):
            if part not in node:
                raise KeyError(f"引用失败：路径 {path} 在 {part} 处不存在")
            node = node[part]
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"引用失败：路径 {path} 的下标无效") from exc
        else:
            raise KeyError(f"引用失败：路径 {path} 无法继续下钻")
    return copy.deepcopy(node)


# ---------------------------------------------------------------- 结果压缩
def _compact(value: Any, depth: int = 0) -> Any:
    """压缩工具结果：去掉几何坐标与完整要素列表，保留可判读的摘要。"""
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "geometry" and isinstance(item, dict):
                out[key] = {"type": item.get("type"), "note": "几何已保存，可用 $ref 引用"}
            elif key == "features" and isinstance(item, list):
                out[key] = [
                    {k: v for k, v in f.items() if k != "geometry"}
                    for f in item[:3] if isinstance(f, dict)
                ]
                if len(item) > 3:
                    out[key + "_note"] = f"共 {len(item)} 条，仅显示前 3 条；完整集合用 $ref"
            else:
                out[key] = _compact(item, depth + 1)
        return out
    if isinstance(value, list):
        return [_compact(v, depth + 1) for v in value[:20]]
    if isinstance(value, str) and len(value) > 400:
        return value[:400] + "…"
    return value


def _payload(step_id: str, tool: str, ok: bool, result: Any = None,
             error: str | None = None) -> str:
    body: dict[str, Any] = {"step_id": step_id, "tool": tool, "ok": ok}
    if ok:
        body["result"] = _compact(result)
        body["ref_hint"] = f'需要完整结果时用 {{"$ref": "{step_id}.result..."}}'
    else:
        body["error"] = error
    text = json.dumps(body, ensure_ascii=False, default=str)
    if len(text) > 12000:  # 二次兜底，避免超长结果挤爆上下文
        body.pop("result", None)
        body["result"] = "结果过大，已省略；可用 $ref 引用"
        text = json.dumps(body, ensure_ascii=False, default=str)
    return text


# ---------------------------------------------------------------- 工具执行
def _run_tool_calls(tool_calls: list[dict], trace: list[dict], tools_used: list[str],
                    results: dict[str, dict]) -> list[ToolMessage]:
    """执行模型发起的工具调用，返回要回填给模型的 ToolMessage 列表。"""
    messages: list[ToolMessage] = []
    for tc in tool_calls:
        name = tc.get("name") or ""
        raw_args = tc.get("args") or {}
        step_id = f"t{len(trace) + 1}"
        try:
            args = _resolve_refs(raw_args, results)
            result = tool_registry.call(name, **args)
            if not isinstance(result, dict) or result.get("status") != "ok":
                raise ValueError(str(result.get("error") or "工具未返回成功结果"))
            results[step_id] = result
            trace.append({
                "step": step_id,
                "tool": name,
                "args": raw_args,
                "ok": True,
                "brief": _brief(result),
            })
            if name and name not in tools_used:
                tools_used.append(name)
            content = _payload(step_id, name, True, result.get("result"))
        except Exception as e:  # 工具报错回填给模型，让它自行纠正
            error = f"{type(e).__name__}: {e}"
            trace.append({"step": step_id, "tool": name, "args": raw_args,
                          "ok": False, "error": error})
            content = _payload(step_id, name, False, error=error)
        messages.append(ToolMessage(content=content, tool_call_id=str(tc.get("id") or name)))
    return messages


def _brief(result: dict) -> dict:
    """轨迹里保存的简短结果摘要（报告用）。"""
    inner = result.get("result") or {}
    brief: dict[str, Any] = {}
    if isinstance(inner, dict):
        fs = inner.get("feature_set")
        if isinstance(fs, dict):
            brief["feature_count"] = fs.get("feature_count")
        if "summary" in inner:
            brief["summary"] = inner["summary"]
        if "groups" in inner:
            brief["groups"] = len(inner["groups"] or [])
        if "value" in inner:
            brief["value"] = inner["value"]
        if "geometry" in inner:
            brief["geometry_type"] = (inner["geometry"] or {}).get("type")
    return brief


def run_subtask(state: PipelineState, sub: SubTask) -> SubTask:
    """执行器：模型按计划反复调用算子，直至给出最终结果。"""
    plan_json = json.dumps(sub.plan, ensure_ascii=False)
    trace: list[dict] = []
    tools_used: list[str] = []
    results: dict[str, dict] = {}

    prompt = (
        f"执行者：智能体 {sub.assigned_agent_name}（编号）\n"
        f"子问题：{sub.question}\n"
        f"所需能力维度：{sub.required_capabilities}\n"
        f"{state.injected_context}\n"
        f"执行计划(DAG)：{plan_json}\n"
    )
    if state.answer_format:
        prompt += f"\n输出要求（最终答复必须满足）：\n{state.answer_format}\n"
    prompt += "\n请开始执行；全部步骤完成后直接给出最终结果。"

    messages = [SystemMessage(SYSTEM_PROMPT), HumanMessage(prompt)]

    for round_index in range(MAX_TOOL_ROUNDS):
        if round_index == MAX_TOOL_ROUNDS - 3:
            messages.append(HumanMessage(
                "提示：剩余工具调用轮次不多，请基于已有结果尽快给出最终 JSON 结果，不要再无谓重试。"
            ))
        try:
            ai = llm.chat_with_tools(messages)
        except Exception as e:
            sub.error = f"执行器调用失败: {e}"
            sub.trace = trace
            sub.tools_used = tools_used
            sub.status = "failed"
            _agent_memory(sub.assigned_agent).push_cache(
                {"question": sub.question, "outcome": "failed", "note": sub.error}
            )
            return sub

        messages.append(ai)
        tool_calls = list(getattr(ai, "tool_calls", None) or [])

        if not tool_calls:
            sub.result = _as_text(getattr(ai, "content", ""))
            sub.trace = trace
            sub.tools_used = tools_used
            sub.status = "success"
            mem = _agent_memory(sub.assigned_agent)
            mem.record_task(sub.question, sub.plan, str(sub.result)[:200], "success")
            mem.push_cache({"question": sub.question, "outcome": "success", "note": "executed"})
            return sub

        messages.extend(_run_tool_calls(tool_calls, trace, tools_used, results))

    sub.error = f"超过最大工具调用轮数 {MAX_TOOL_ROUNDS}"
    sub.trace = trace
    sub.tools_used = tools_used
    sub.status = "failed"
    _agent_memory(sub.assigned_agent).push_cache(
        {"question": sub.question, "outcome": "failed", "note": sub.error}
    )
    return sub


def run(state: PipelineState) -> PipelineState:
    """逐个子任务执行（子任务间可并行；DAG 内部串行）。
    实际部署时可用 asyncio / LangGraph Send 并行分发。"""
    for sub in state.subtasks:
        run_subtask(state, sub)
    return state
