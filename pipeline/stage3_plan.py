"""阶段③ 规划：检索共享经验池 + 智能体专属记忆 → 生成计划表 / DAG

规划者是编号智能体（如 agent_03），提示词里给出它**当前**的能力向量与
工具偏好——这些不是启动时配置出来的，而是它此前执行经验沉淀的结果。
"""
from __future__ import annotations

from pipeline.pipeline_state import PipelineState, SubTask
from pipeline import llm_client as llm
from experience import experience_retriever
from memory.agent_memory import AgentMemory
from agents import agent_registry
from agents.capability_store import get_default_store


def _agent_memory(agent_id: str) -> AgentMemory:
    return AgentMemory(
        agent_id,
        root_dir=agent_registry.memory_dir(agent_id),
        cache_max=agent_registry.cache_max(agent_id),
    )


def _capability_line(agent_id: str) -> str:
    store = get_default_store()
    caps = store.capabilities(agent_id)
    labels = agent_registry.dimension_labels()
    vec = "、".join(f"{labels.get(d, d)}{caps[d]:.2f}" for d in store.dimensions)
    tools = store.preferred_tools(agent_id)
    tool_text = "、".join(tools) if tools else "暂无（尚无成功经验）"
    return (f"你是智能体 {store.name(agent_id)}（编号 {store.name(agent_id)}）。\n"
            f"你当前的能力向量（由历史成功/失败经验进化而来）：{vec}\n"
            f"你积累的工具偏好：{tool_text}")


def run_subtask(state: PipelineState, sub: SubTask) -> SubTask:
    # 1a. 检索共享经验池中最相关的经验（跨智能体共享）
    exps = experience_retriever.retrieve_experiences(sub.question, state.domain)
    exp_text = experience_retriever.render_experiences(exps)

    # 1b. 加载该智能体的专属记忆（自己完成的任务 + 短期缓存）
    mem = _agent_memory(sub.assigned_agent)
    own_memory = mem.render_memory(sub.question)

    # 2. 生成计划表 / DAG（JSON：nodes + edges，边表示依赖）
    sys = "你是GIS任务规划器，只输出JSON格式计划。"
    res = llm.chat_json(
        f"{_capability_line(sub.assigned_agent)}\n\n"
        f"子问题：{sub.question}\n"
        f"该子问题所需能力维度：{sub.required_capabilities}\n"
        f"{own_memory}\n"
        f"{exp_text}\n"
        f"{state.injected_context}\n"
        f"{state.loaded_knowledge}\n\n"
        f"请参考你的专属记忆与共享经验，生成执行计划。输出格式：\n"
        f'{{"plan": {{"nodes": [{{"id": "s1", "action": "工具池算子名或子步骤", '
        f'"params": {{}}, "depends_on": []}}], '
        f'"edges": [["s1", "s2"]]}}}}\n'
        f"edges 表示节点依赖关系，构成有向无环图 DAG。",
        system=sys,
    )
    sub.plan = res.get("plan") or {"nodes": [], "edges": []}

    # 把本次规划上下文写入该智能体的短期缓存
    mem.push_cache({"question": sub.question, "plan": sub.plan, "note": "planned"})
    return sub


def run(state: PipelineState) -> PipelineState:
    for sub in state.subtasks:
        run_subtask(state, sub)
    return state
