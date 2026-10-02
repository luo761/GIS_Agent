# nodes.py —— 图节点：领域识别 → 路由分工 → 执行 → 学习沉淀

from time import sleep

from loguru import logger
from langgraph.graph import END
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from langgraph.runtime import Runtime
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from requests.exceptions import HTTPError

from states import AgentNetState, UserContext
from models import model, detect_router, route_router
from agents import registry
from persistence import ExperiencePool, SkillManager, SKILLS_NS
from tools import gis_tools, model_with_gis_tools, SKILL_USAGE_DOCS
from routers import DOMAIN_KEYWORDS

def detect_node(state: AgentNetState) -> AgentNetState:
    """识别问题领域与任务类型；识别不出时不终止，降级为综合模式由智能体按Skill库求解"""
    res = detect_router.invoke(
        [SystemMessage(content="识别GIS问题的领域(燃气/水务/电务)与任务类型。"),
         HumanMessage(content=state["input"])]
    )
    domain = res.domain
    if domain == "无":
        # 兜底1：关键词扫描
        for d, kws in DOMAIN_KEYWORDS.items():
            if any(kw in state["input"] for kw in kws):
                domain = d
                break
    if domain == "无":
        # 兜底2：进入综合模式，交给智能体依据 Skill 库算子说明自行求解
        return {"detected_domain": "综合",
                "task_type": res.task_type or "综合分析",
                "task_success": True,
                "info": [f"{len(state.get('info', []))+1}. 领域未明确，进入综合模式（依托Skill库求解）"]}
    return {"detected_domain": domain,
            "task_type": res.task_type,
            "task_success": True,
            "info": [f"{len(state.get('info', []))+1}. 领域识别：{res.domain}，任务：{res.task_type}"]}

def route_node(state: AgentNetState, runtime: Runtime) -> AgentNetState:
    """协调路由：按能力匹配智能体，决定执行 or 拆分协作（AgentNet Forward/Split/Execute）"""
    # ---------- 中断确认：读取共享知识库/经验池前征得用户同意 ----------
    confirm = interrupt("准备读取共享经验池与智能体网络，进行任务分工，是否继续？(yes/no)")
    if confirm not in (True, "yes"):
        return Command(goto=END, update={"info": "用户取消读取共享知识库，流程终止。",
                                        "task_success": False})

    available = registry.all()
    agent_names = ", ".join(a.name for a in available)
    res = route_router.invoke(
        [SystemMessage(content=(
            f"你是去中心化协调器。从这些已注册智能体中选择最合适的处理当前GIS任务：{agent_names}。"
            f"如任务跨多个领域需要协作，设置cooperation=True并拆分子任务。")),
         HumanMessage(content=f"领域={state['detected_domain']}，任务={state['task_type']}，问题={state['input']}")]
    )

    # 校验智能体是否存在于注册表（动态注册体系下的兜底；综合模式匹配能力最强的智能体）
    agent = registry.get(res.agent) or registry.match(state.get("detected_domain", ""))
    if not agent:
        return {"output": "未找到合适智能体，流程终止。", "task_success": False}

    updates = {
        "selected_agent": agent.name,
        "cooperation": res.cooperation,
        "subtasks": res.subtasks,
        "info": [f"{len(state.get('info', []))+1}. 路由到 {agent.name}，"
                 f"协作={res.cooperation}，子任务={res.subtasks or '无'}（执行自身）"],
    }

    # 汇总各智能体独立记忆（每个智能体 namespace 独立，此处在共享决策时按需读取）
    store = runtime.store
    private_mem = store.get(agent.memory_namespace(), "last_task")
    if private_mem:
        updates["info"].append(f"{len(state.get('info', []))+2}. 读取{agent.name}私有记忆：{private_mem.value.get('summary','')}")
    return updates

def execute_node(state: AgentNetState, runtime: Runtime) -> AgentNetState:
    """执行节点：让选中的智能体调用 GIS 工具完成当前任务"""
    # ---------- 中断确认：调用大语言模型前征得用户同意 ----------
    confirm = interrupt(f"准备调用大语言模型，由 {state.get('selected_agent','智能体')} 执行任务，是否继续？(yes/no)")
    if confirm not in (True, "yes"):
        return Command(goto=END, update={"info": "用户取消调用大语言模型，流程终止。",
                                        "task_success": False})

    agent = registry.get(state["selected_agent"])
    domain = state["detected_domain"]

    # 组装当前智能体的专属系统提示 + 领域知识
    sys_msg = SystemMessage(content=(
        f"你是【{agent.name}】，专长领域：{domain}。\n"
        f"你的职责：{agent.description}\n"
        f"你的能力向量：{agent.capabilities}\n"
        "你是GIS智能体，按需调用GIS工具完成用户的空间分析请求，不要编造工具。"
    ))

    # 1) 先检索技能库：读取本领域已沉淀的通用方法论（LLM 提炼），用于定任务框架
    #    综合模式下检索不到领域技能时，回退到 Skill 库各域算子使用说明，
    #    让智能体依据算子知识自行拆解求解，而非直接失败。
    store = runtime.store
    try:
        skill_items = store.search((*SKILLS_NS, domain))
    except Exception:
        skill_items = []
    skill_refs = [it.value.get("skill", str(it.value)) for it in skill_items][:2]
    if not skill_refs and SKILL_USAGE_DOCS:
        skill_refs = list(SKILL_USAGE_DOCS.values())[:2]
    method_text = "\n".join(skill_refs) if skill_refs else "（暂无沉淀技能，可参考经验池）"

    # 2) 再从共享经验池检索历史成功轨迹做 few-shot（RAG）
    experiences = ExperiencePool.retrieve(store, state["input"], k=2)
    if experiences:
        # trajectory 可能是 list（逐条轨迹）也可能是字符串，统一转文本
        exp_lines = []
        for e in experiences:
            traj = e.get("trajectory", [])
            if isinstance(traj, list):
                exp_lines.append("\n".join(str(t) for t in traj))
            else:
                exp_lines.append(str(traj))
        exp_text = "\n".join(exp_lines)
    else:
        exp_text = "（无历史经验）"

    messages = [sys_msg,
                SystemMessage(content=f"【技能库·通用方法论】\n{method_text}"),
                SystemMessage(content=f"【共享经验池·历史成功轨迹】\n{exp_text}"),
                HumanMessage(content=state["input"])]
    resp = model_with_gis_tools.invoke(messages)

    updates: dict = {
        "messages": [resp],
        "output": resp.content,
        "trajectory": [f"{agent.name} 调用LLM解析，输出含工具调用",
                       f"{agent.name} 依据领域知识库与共享经验决策"],
        "info": [f"{len(state.get('info', []))+1}. {agent.name} 执行完成"],
    }

    # 记录到该智能体的独立记忆（记忆独立）
    store.put(agent.memory_namespace(), "last_task",
              {"task": state["input"], "summary": resp.content[:200]})
    logger.info(f"[记忆] 已写入 {agent.name} 独立记忆")
    sleep(0.05)
    return updates

def tool_node_wrapper(state: AgentNetState) -> AgentNetState:
    """包装 ToolNode：执行 GIS 工具，并记录轨迹"""
    last_ai = state["messages"][-1]
    tool_calls = getattr(last_ai, "tool_calls", [])
    tool_names = [tc["name"] for tc in tool_calls]
    logger.info(f"即将并行调用工具: {tool_names}")

    builtin_tool_node = ToolNode(gis_tools)
    result_state = builtin_tool_node.invoke(state)

    # 把工具调用追加进轨迹（用于后续提炼 skill）
    if isinstance(result_state, dict):
        traj = [f"{state['selected_agent']} 调用工具 {n}" for n in tool_names]
        result_state.setdefault("trajectory", []).extend(traj)
        result_state["info"] = [f"{len(state.get('info', []))+1}. 工具并行执行：{tool_names}"]
    sleep(0.1)
    return result_state

def learn_node(state: AgentNetState, runtime: Runtime) -> AgentNetState:
    """
    学习沉淀节点（AgentNet 自适应演化）：
      1) 把成功任务写入共享经验池
      2) 用 LLM 提炼成功思路 → skill，写入数据库
    """
    if not state.get("task_success"):
        return {"info": [f"{len(state.get('info', []))+1}. 任务未成功，跳过经验沉淀"]}

    store = runtime.store
    trajectory = state.get("trajectory", [])
    result = state.get("output", "")

    # 1) 共享经验池记录
    ExperiencePool.record(store, state["input"], state["selected_agent"],
                          trajectory, result)

    # 2) 提炼 skill 写库（AgentNet 经验→技能）
    skill_text = SkillManager.build_skill_from_trajectory(
        trajectory, result, state["detected_domain"])
    skill_id = f"skill_{abs(hash(state['input'] + state['detected_domain']))}"
    SkillManager.store_skill(store, skill_id, skill_text, state["detected_domain"])

    return {"info": [
        f"{len(state.get('info', []))+1}. 经验池已记录，技能已沉淀（{skill_id}）",
        f"{len(state.get('info', []))+2}. 沉淀技能：{skill_text[:80]}..."
    ]}

def final_answer_node(state: AgentNetState) -> AgentNetState:
    """整合节点：工具执行后，让模型基于工具结果生成最终答复（替代开场白）"""
    msgs = state.get("messages", [])
    tool_msgs = [m.content for m in msgs if isinstance(m, ToolMessage)]
    if not tool_msgs:
        return {"output": state.get("output", ""),
                "info": [f"{len(state.get('info', []))+1}. 无工具结果，直接结束"]}

    sys_msg = SystemMessage(content=(
        "你是GIS智能体，请基于下面已执行的工具返回结果，整合成一份简洁、结构化的最终答复"
        "给业务人员，包含关键数据与结论。不要编造未出现的数字。"
    ))
    human = HumanMessage(content=(
        f"原始问题：{state.get('input','')}\n"
        f"工具执行结果：\n" + "\n".join(f"- {t}" for t in tool_msgs)
    ))
    resp = model.invoke([sys_msg, human])
    return {"output": resp.content,
            "trajectory": ["智能体整合工具结果，生成最终答复"],
            "info": [f"{len(state.get('info', []))+1}. 整合生成最终答复"]}

def end_node(state: AgentNetState) -> AgentNetState:
    return {"info": [f"{len(state.get('info', []))+1}. 任务执行完毕"]}
