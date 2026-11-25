"""LangGraph 主图：五阶段编排。

支持失败回溯：阶段⑤判定失败后回到阶段③重新规划，最多重试 MAX_REPLANS 次。
每次尝试都会在阶段⑤留下一次能力进化（成功或失败经验）。

说明：节点函数返回「字段更新字典」，而不是直接返回状态对象——
LangGraph 只按返回值做状态写入，这样 `evaluation`、`final_answer` 等
标量字段才能可靠地从阶段⑤传回最终状态。
"""
from __future__ import annotations

from dataclasses import fields
from typing import Callable

from langgraph.graph import StateGraph, END

from pipeline.pipeline_state import PipelineState, SubTask
from pipeline import stage1_understand, stage2_decompose, stage3_plan, stage4_execute, stage5_evaluate

MAX_REPLANS = 2


def _as_updates(state: PipelineState) -> dict:
    """把状态对象转成 LangGraph 的字段更新字典。"""
    return {f.name: getattr(state, f.name) for f in fields(PipelineState)}


def _node(fn: Callable[[PipelineState], PipelineState]) -> Callable[[PipelineState], dict]:
    """包装阶段函数：内部仍是"接收状态、原地加工、返回状态"，对外输出更新字典。"""

    def wrapped(state: PipelineState) -> dict:
        return _as_updates(fn(state))

    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


def _coerce_state(value) -> PipelineState:
    """LangGraph 以 dict 形式返回状态时，还原成 PipelineState 数据类。"""
    if isinstance(value, PipelineState):
        return value
    if not isinstance(value, dict):
        raise TypeError(f"无法识别的状态类型: {type(value)!r}")

    field_names = PipelineState.__dataclass_fields__
    data = {k: v for k, v in value.items() if k in field_names}
    subs = []
    sub_fields = SubTask.__dataclass_fields__
    for item in data.get("subtasks") or []:
        if isinstance(item, SubTask):
            subs.append(item)
        elif isinstance(item, dict):
            subs.append(SubTask(**{k: v for k, v in item.items() if k in sub_fields}))
    data["subtasks"] = subs
    return PipelineState(**data)


def _after_evaluate(state: PipelineState) -> str:
    """路由：失败且还有重试次数 → 回到规划；否则结束。

    这里只选择分支；实际重规划计数由单独节点更新，以确保写回图状态。
    """
    limit = MAX_REPLANS if state.max_replans is None else state.max_replans
    if state.evaluation == "failed" and state.replans < limit:
        return "replan"
    return END


def _begin_replan(state: PipelineState) -> PipelineState:
    """计入一次真实重规划，并清除上轮子任务的执行状态。

    上轮计划、结果、轨迹已由阶段⑤深拷贝到 attempt_history；失败反馈保留给阶段③。
    """
    state.replans += 1
    for sub in state.subtasks:
        sub.plan = None
        sub.result = None
        sub.trace = []
        sub.tools_used = []
        sub.status = "pending"
        sub.outcome = ""
        sub.error = ""
        sub.capability_update = {}
    return state


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("understand", _node(stage1_understand.run))
    g.add_node("decompose", _node(stage2_decompose.run))
    g.add_node("plan", _node(stage3_plan.run))
    g.add_node("execute", _node(stage4_execute.run))
    g.add_node("evaluate", _node(stage5_evaluate.run))
    g.add_node("replan", _node(_begin_replan))

    g.set_entry_point("understand")
    g.add_edge("understand", "decompose")
    g.add_edge("decompose", "plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "evaluate")
    g.add_conditional_edges("evaluate", _after_evaluate, {"replan": "replan", END: END})
    g.add_edge("replan", "plan")
    return g.compile()


def ask(question: str, ground_truth=None, answer_format: str = "", *,
        max_replans: int | None = None) -> PipelineState:
    """端到端入口。

    ground_truth 非空时进入"测试模式"，由阶段⑤判定对错并据此进化能力；
    answer_format 用于把题目要求的输出契约传入执行器（基准评测使用）。
    max_replans=0 为单次作答；N 表示失败后最多重新规划 N 次，共最多 N+1 轮。
    """
    limit = MAX_REPLANS if max_replans is None else max_replans
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("max_replans 必须是非负整数")
    graph = build_graph()
    init = PipelineState(
        raw_question=question,
        ground_truth=ground_truth,
        answer_format=answer_format,
        max_replans=limit,
    )
    # 初次作答经过 5 个节点；每轮重规划增加 replan/plan/execute/evaluate 4 个节点。
    final = graph.invoke(init, config={"recursion_limit": max(25, 8 + 4 * limit)})
    return _coerce_state(final)
