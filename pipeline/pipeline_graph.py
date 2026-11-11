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

    `state.replans` 在阶段⑤失败时自增，是图状态的一部分，
    因此重试次数在 LangGraph 的多轮调用之间不会丢失。
    """
    if state.evaluation == "failed" and state.replans <= MAX_REPLANS:
        return "replan"
    return END


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("understand", _node(stage1_understand.run))
    g.add_node("decompose", _node(stage2_decompose.run))
    g.add_node("plan", _node(stage3_plan.run))
    g.add_node("execute", _node(stage4_execute.run))
    g.add_node("evaluate", _node(stage5_evaluate.run))

    g.set_entry_point("understand")
    g.add_edge("understand", "decompose")
    g.add_edge("decompose", "plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "evaluate")
    g.add_conditional_edges("evaluate", _after_evaluate, {"replan": "plan", END: END})
    return g.compile()


def ask(question: str, ground_truth=None, answer_format: str = "") -> PipelineState:
    """端到端入口。

    ground_truth 非空时进入"测试模式"，由阶段⑤判定对错并据此进化能力；
    answer_format 用于把题目要求的输出契约传入执行器（基准评测使用）。
    """
    graph = build_graph()
    init = PipelineState(
        raw_question=question,
        ground_truth=ground_truth,
        answer_format=answer_format,
    )
    final = graph.invoke(init)
    return _coerce_state(final)
