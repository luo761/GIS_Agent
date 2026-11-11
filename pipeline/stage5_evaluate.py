"""阶段⑤ 评估与沉淀：结果对比 → 能力进化 → 汇总输出 / 错误经验写入经验库

评估是能力进化的唯一入口：
  · 子任务执行成功、且结果被判为正确 → 该智能体在所需能力维度上"成功经验 +1"；
  · 执行报错，或结果与正确答案不符 → 对应智能体在所需能力维度上"失败经验 +1"。
能力值的变化立即落盘并重绘动态能力向量图。
"""
from __future__ import annotations

from pipeline.pipeline_state import PipelineState
from pipeline import llm_client as llm
from experience.experience_pool import ExperiencePool
from agents.capability_store import get_default_store

_store = ExperiencePool()

# 可选的确定性判分器：fn(state) -> (correct: bool, reason: str)
# 基准评测用它替代 LLM 判卷，保证分数可复现。
_VERIFIER = None


def set_verifier(fn) -> None:
    """设置判分器（传 None 恢复为 LLM 判卷）。"""
    global _VERIFIER
    _VERIFIER = fn


def _verifier_verdict(state: PipelineState):
    try:
        correct, reason = _VERIFIER(state)
        return bool(correct), str(reason or "")
    except Exception as exc:  # 判分器异常不阻断主流程
        return False, f"判分器异常: {exc}"


# ---------------------------------------------------------------- 工具函数
def _task_signature(state: PipelineState) -> str:
    """任务签名：领域+任务类型，用于同类任务判定。"""
    return f"{state.domain}/{state.task_type}"


def _traces_text(state: PipelineState) -> str:
    chunks: list[str] = []
    for s in state.subtasks:
        chunks.append(f"[{s.subtask_id}｜智能体 {s.assigned_agent_name}] {s.question}")
        for t in s.trace:
            chunks.append(f"  {t.get('tool')}({t.get('params')}) -> {t.get('result')}")
        if s.error:
            chunks.append(f"  错误：{s.error}")
    return "\n".join(chunks)


def _compress_experience(state: PipelineState, outcome: str) -> dict:
    """把问题特征、计划与执行轨迹压缩为一条经验（筛选摘要，不是全量）。"""
    summary = llm.chat(
        "请把以下执行轨迹压缩为不超过200字的经验摘要，保留关键算子调用顺序与结果形式：\n"
        + _traces_text(state)
    )
    return {
        "task_signature": _task_signature(state),
        "question_feat": state.refined_question or state.raw_question,
        "plan": {s.subtask_id: s.plan for s in state.subtasks},
        "trace": summary,
        "outcome": outcome,
        "error_lesson": state.failure_feedback if outcome == "error" else "",
    }


def _evolve(state: PipelineState, faulty_ids: set[str]) -> list[dict]:
    """按每个子任务的成败更新其智能体的能力向量。"""
    store = get_default_store()
    events: list[dict] = []
    for sub in state.subtasks:
        if not sub.assigned_agent:
            continue
        if sub.status != "success":
            outcome = "failure"
        elif state.evaluation == "failed" and sub.subtask_id in faulty_ids:
            outcome = "failure"
        else:
            outcome = "success"
        sub.outcome = outcome

        event = store.apply(
            sub.assigned_agent,
            sub.required_capabilities,
            outcome,
            question=sub.question,
            task_signature=_task_signature(state),
            tools=sub.tools_used,
            note=(sub.error or (state.failure_feedback[:120] if outcome == "failure" else "")),
        )
        sub.capability_update = {
            "ts": event["ts"],
            "agent_id": event["agent_id"],
            "agent_name": event["agent_name"],
            "dims": event["dims"],
            "outcome": event["outcome"],
            "before": event["before"],
            "after": event["after"],
            "delta": event["delta"],
        }
        state.capability_changes.append({**sub.capability_update,
                                         "subtask_id": sub.subtask_id})
        events.append(event)
    return events


# ---------------------------------------------------------------- 主流程
def run(state: PipelineState) -> PipelineState:
    ground_truth = state.ground_truth
    faulty_ids: set[str] = set()

    # 1) 执行层面：跑通 / 报错
    state.evaluation = "success"
    state.failure_feedback = ""
    failed_runs = [s for s in state.subtasks if s.status != "success"]
    if failed_runs:
        state.evaluation = "failed"
        state.failure_feedback = llm.chat(
            "子任务执行报错：\n"
            + "\n".join(f"[{s.subtask_id}] {s.error}" for s in failed_runs)
            + f"\n对应计划：{[s.plan for s in failed_runs]}\n"
            + "请总结错误原因与下次规划时的避免措施。"
        )
        faulty_ids = {s.subtask_id for s in failed_runs}

    # 2) 结果层面：与正确答案对比（测试模式）
    elif ground_truth is not None:
        if _VERIFIER is not None:
            correct, reason = _verifier_verdict(state)
        else:
            verdict = llm.chat_json(
                f"各子任务结果：{[(s.subtask_id, s.result) for s in state.subtasks]}\n"
                f"正确答案：{ground_truth}\n"
                f'对比并输出 {{"correct": true/false, "reason": "...", '
                f'"faulty_subtasks": ["出错的子任务id"]}}',
                system="你是结果评估器，只输出JSON。",
            )
            correct = bool(verdict.get("correct", False))
            reason = str(verdict.get("reason") or "结果与正确答案不符")
            valid = {s.subtask_id for s in state.subtasks}
            faulty_ids = {str(x) for x in (verdict.get("faulty_subtasks") or [])} & valid
        if not correct:
            state.evaluation = "failed"
            state.failure_feedback = reason or "结果与正确答案不符"
            if not faulty_ids and state.subtasks:
                faulty_ids = {s.subtask_id for s in state.subtasks}  # 无法定位时共同承担

    # 3) 能力进化：成功/失败经验 → 能力向量（同时重绘能力向量图）
    _evolve(state, faulty_ids)
    chart = get_default_store().refresh_chart()
    state.capability_chart = chart.get("html") or ""

    # 4) 汇总输出 / 经验入库
    if state.evaluation == "success":
        if len(state.subtasks) == 1:
            state.final_answer = str(state.subtasks[0].result)
        elif state.subtasks:
            state.final_answer = llm.chat(
                f"原始问题：{state.raw_question}\n"
                f"各子任务结果：{[{'q': s.question, 'r': s.result} for s in state.subtasks]}\n"
                f"请汇总为一份完整答案。"
            )
        state.aggregated_result = [s.result for s in state.subtasks]
        _store.write(_compress_experience(state, "success"))
    else:
        _store.write(_compress_experience(state, "error"))
        state.replans += 1

    return state
