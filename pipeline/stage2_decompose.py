"""阶段② 初步拆解：问题专业化精炼 → 拆分/不拆 → 按能力向量路由。

注意：路由**不由 LLM 决定**。LLM 只负责精炼问题、拆分问题、
并标注每个子问题所需的能力维度；选哪个智能体由 `agents/capability_router.py`
按能力向量计算，能力均等时随机抽取。
"""
from __future__ import annotations

from pipeline.pipeline_state import PipelineState, SubTask
from pipeline import llm_client as llm
from agents import agent_registry, capability_router
from agents.capability_store import get_default_store
from config import settings


def run(state: PipelineState) -> PipelineState:
    store = get_default_store()
    labels = agent_registry.dimension_labels()
    dims_desc = "\n".join(f"- {d}: {labels.get(d, d)}（{v}）"
                          for d, v in agent_registry.load_agents_config()["capability_glossary"].items())

    sys = "你是公用事业GIS任务拆解模块，只输出JSON。"
    res = llm.chat_json(
        f"用户口语化问题：{state.raw_question}\n"
        f"领域：{state.domain}，任务类型：{state.task_type}\n"
        f"注入的表结构：\n{state.injected_context}\n"
        f"领域知识：\n{state.loaded_knowledge}\n\n"
        f"请依次完成三件事并输出JSON：\n"
        f"1) formalize：把口语化问题专业形式精炼（引用真实表名字段名）。\n"
        f"2) decompose：判断问题规模——若较复杂，拆分为多个可并行的子问题"
        f"（每个子问题内部串行可解），最多 {settings.MAX_SUBTASKS} 个；"
        f"若不复杂，subtasks 只含一条（即精炼后的问题本身，不再拆分）。\n"
        f"3) capabilities：为每个子问题标注所需的能力维度（可多选），"
        f"只能从下列维度中选取：\n{dims_desc}\n\n"
        f"说明：执行任务的智能体只有编号（如 01、02），没有预设专长，"
        f"具体派谁由系统按能力向量决定，因此**不要**指定智能体、不要猜测谁更擅长。\n"
        f'输出格式：{{"formalized_question": "...", "subtasks": ['
        f'{{"subtask_id": "t1", "question": "...", "required_capabilities": ["..."]}}]}}',
        system=sys,
    )
    state.refined_question = res.get("formalized_question", state.raw_question)

    subtasks: list[SubTask] = []
    for i, s in enumerate(res.get("subtasks") or []):
        question = s.get("question") or state.refined_question
        dims = capability_router.normalize_dimensions(s.get("required_capabilities"), state.task_type)
        decision = capability_router.route(store, dims, task_type=state.task_type)
        subtasks.append(
            SubTask(
                subtask_id=str(s.get("subtask_id") or f"t{i + 1}"),
                question=question,
                required_capabilities=decision.required,
                assigned_agent=decision.agent_id,
                assigned_agent_name=decision.agent_name,
                routing=decision.to_dict(),
            )
        )
    state.subtasks = subtasks[: settings.MAX_SUBTASKS]
    if not state.subtasks:  # 兜底：拆解失败时至少保留一个子任务
        dims = capability_router.normalize_dimensions(None, state.task_type)
        decision = capability_router.route(store, dims, task_type=state.task_type)
        state.subtasks = [
            SubTask(
                subtask_id="t1",
                question=state.refined_question,
                required_capabilities=decision.required,
                assigned_agent=decision.agent_id,
                assigned_agent_name=decision.agent_name,
                routing=decision.to_dict(),
            )
        ]
    return state
