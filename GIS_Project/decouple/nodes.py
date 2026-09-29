# nodes.py

import json
import os
from time import sleep

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from loguru import logger

from models import DomainDetectResult, domain_router, model
from persistence import FIELDS_NS, PREFERENCES_KEY
from routers import router_get_preference
from states import OverAllState, PrecheckState, UserContext
from tools import gis_tool_profile, gis_tools


# [保留-现有工具] 不替换 tools.py，仅把现有 gis_tools 绑定给模型与 ToolNode。
model_with_gis_tools = model.bind_tools(gis_tools)
builtin_tool_node = ToolNode(gis_tools)
tool_by_name = {tool.name: tool for tool in gis_tools}
tool_execution_mode = os.getenv("GIS_TOOL_EXECUTION_MODE", "sequential").lower()


# [新增-文档版] 领域识别节点：支持自动识别燃气/水务/电务，多领域返回列表。
def domain_detect_node(state: PrecheckState) -> PrecheckState:
    """
    领域识别节点：调用结构化输出大模型，从问句识别业务领域。
    如果 state 已经携带 fieldnames 列表，则跳过 LLM 识别，直接复用已有值。
    """

    existing_fields = state.get("fieldnames")
    legacy_field = state.get("fieldname")

    if existing_fields:
        return {}

    # [兼容-保留] 旧代码入口传入 fieldname 时转换成文档版 fieldnames。
    if legacy_field:
        return {
            "fieldnames": [legacy_field],
            "detect_fieldnames_reason": "由旧字段 fieldname 转换得到"
        }

    prompt_sys = SystemMessage(content="""
你是 GIS 业务领域识别助手。
只允许输出领域：燃气、水务、电务。
- 用户问题涉及多个业务就输出多个；
- 完全不相关输出空列表；
同时给出简短推理理由。
""")
    prompt_human = HumanMessage(content=f"用户问题：{state['input']}")

    res: DomainDetectResult = domain_router.invoke([prompt_sys, prompt_human])

    return {
        "fieldnames": res.domains,
        "detect_fieldnames_reason": res.reason,
        "info": [f"{len(state.get('info', [])) + 1}. 领域识别完成，识别到领域：{res.domains}，理由：{res.reason}"]
    }


# [替换-文档版] 原 check_preferences_node 只读取单个 fieldname；现在支持 fieldnames 列表，未指定时加载全部领域。
def check_preferences_node(state: PrecheckState, runtime: Runtime) -> PrecheckState:
    """读取 PostgresStore 长期记忆 store，领域的时空语义知识库。"""

    confirm = interrupt("准备读取PostgresStore长期记忆知识库，是否继续？(yes/no)")
    if confirm not in (True, "yes"):
        return Command(
            goto=END,
            update={
                "cancelled": True,
                "info": [f"{len(state.get('info', [])) + 1}. 用户取消读取知识库，流程终止。"]
            }
        )

    merged_description = []
    merged_terms = []
    merged_skills = []
    fieldnames = state.get("fieldnames")

    if not fieldnames and state.get("fieldname"):
        fieldnames = [state["fieldname"]]

    if not fieldnames:
        logger.warning("目前暂未指定业务领域 fieldnames")
        domains = ["燃气", "水务", "电务"]
    else:
        logger.info("正在根据 fieldnames 收集对应专业知识")
        domains = fieldnames

    store = runtime.store
    for domain in domains:
        namespace = (*FIELDS_NS, domain)
        item = store.get(namespace, PREFERENCES_KEY)
        if not item:
            logger.warning(f"长期记忆没有关于 {domain} 的知识库")
            continue

        logger.info(f"已读取 {domain} 的领域知识库")
        val = item.value
        merged_description.append(f"【{domain}】\n{val.get('description', '')}")
        merged_terms.append(f"【{domain}】\n{val.get('term', '')}")
        merged_skills.append(f"【{domain}】\n{val.get('skill', '')}")

    merged_preferences = {
        "description": "\n".join(merged_description),
        "term": "；".join(merged_terms),
        "skill": "；".join(merged_skills)
    }

    sleep(0.05)

    return {
        "preferences": merged_preferences,
        "info": [f"{len(state.get('info', [])) + 1}. 读取 PostgresStore 知识库完成，已加载领域知识"]
    }


# [新增-文档版] 构建预检查子图。
precheck_builder = StateGraph(state_schema=PrecheckState)
precheck_builder.add_node("domain_detect_node", domain_detect_node)
precheck_builder.add_node("check_preferences_node", check_preferences_node)
precheck_builder.add_conditional_edges(START, router_get_preference)
precheck_builder.add_edge("check_preferences_node", "domain_detect_node")
precheck_builder.add_edge("domain_detect_node", END)
call_precheck_subgraph = precheck_builder.compile()


# [替换-文档版] LLM 解析节点增加人工中断确认、运行时用户上下文和知识库提示。
def llm_parse_node(state: OverAllState, runtime: Runtime[UserContext]) -> OverAllState:
    """时空语义解析节点：自然语言问句 -> 识别 GIS 任务，可调用 GIS 工具算子。"""

    confirm = interrupt("准备调用大语言模型，是否继续？(yes/no)")
    if confirm not in (True, "yes"):
        return Command(goto=END, update={"info": ["用户取消调用大语言模型，流程终止。"]})

    runtime_context = runtime.context
    preferences = state.get("preferences", {})
    user_input = state["input"]
    history_messages = state.get("messages", [])

    knowledge_text = f"""【领域知识库】
描述:{preferences.get('description', '')}
业务术语:{preferences.get('term', '')}
支持分析能力:{preferences.get('skill', '')}

你是 GIS 智能体，接收市政业务人员自然语言提问，识别 GIS 空间分析意图，按需调用提供的 GIS 工具算子。
不要编造不存在工具，参数严格按照工具描述填写。
"""

    if runtime_context:
        username = runtime_context.username
        level = runtime_context.membership_level

        if level == "VIP":
            system_prompt = f"你是高级客服助理。当前 VIP 用户是 {username}，请使用尊称'您'，语气热情周到，回复末尾加上'VIP专属服务'。"
        else:
            system_prompt = f"你是普通客服助理。当前用户是 {username}，请友好简洁地回复。"
    else:
        logger.warning("运行时上下文为空，使用默认风格")
        system_prompt = "你是客服助理，请友好简洁地回复。"

    if gis_tool_profile == "operator":
        system_prompt += (
            "\n当前处于 GIS operator 模式。你只能调用已提供的底层 GIS 算子解决问题。"
            "先在心中拆解任务步骤；每一轮最多调用一个算子，必须等待该算子的返回结果后，"
            "再决定下一步算子及参数。不要调用业务封装工具，不要并行调用多个算子。"
        )

    sys_msg = SystemMessage(content=knowledge_text + system_prompt)
    if history_messages:
        messages = [sys_msg] + history_messages
    else:
        messages = [sys_msg, HumanMessage(content=user_input)]
    resp = model_with_gis_tools.invoke(messages)

    sleep(0.1)
    return {
        "messages": [resp],
        "output": resp.content,
        "info": [f"{len(state.get('info', [])) + 1}. LLM 解析完成，生成了回复（可能包含工具调用）"]
    }


# [替换-文档版] 删除旧 tool_node 中手写遍历 tool_calls 的逻辑，改用 LangGraph 内置 ToolNode。
def tool_node_wrapper(state: OverAllState) -> OverAllState:
    """
    包装内置 ToolNode，在调用前后记录日志，并保留 state["info"] 累积功能。
    内置 ToolNode 默认并行执行所有工具调用。
    """

    last_ai = state["messages"][-1]
    tool_calls = getattr(last_ai, "tool_calls", [])
    tool_names = [tc["name"] for tc in tool_calls]
    logger.info(f"即将并行调用工具: {tool_names}")

    result_state = builtin_tool_node.invoke(state)

    info_msg = "当前工具正在并行执行:"
    for tool_name in tool_names:
        info_msg = info_msg + f"['{tool_name}'] "
    result_state["info"] = [f"{len(state.get('info', [])) + 1}. {info_msg}"]

    sleep(0.1)

    return result_state


# [新增-文档版] 显式结束节点。
def end_node(state: OverAllState) -> OverAllState:
    """结算节点，记录结束信息。"""

    logger.info("进入结算节点")
    return {
        "info": [f"{len(state.get('info', [])) + 1}. 当前任务执行完毕"]
    }


def tool_node_wrapper(state: OverAllState) -> OverAllState:
    """
    Execute tool calls in the order emitted by the model by default.
    Set GIS_TOOL_EXECUTION_MODE=parallel to use LangGraph's built-in ToolNode.
    """

    last_ai = state["messages"][-1]
    tool_calls = getattr(last_ai, "tool_calls", [])
    tool_names = [tc["name"] for tc in tool_calls]
    use_parallel = tool_execution_mode == "parallel"

    if use_parallel:
        logger.info(f"Tools will run in parallel: {tool_names}")
        result_state = builtin_tool_node.invoke(state)
        result_state["info"] = [f"{len(state.get('info', [])) + 1}. Tools executed in parallel: {tool_names}"]
        sleep(0.1)
        return result_state

    logger.info(f"Tools will run sequentially: {tool_names}")
    tool_messages = []
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call.get("args", {})
        tool_obj = tool_by_name.get(tool_name)

        if tool_obj is None:
            content = f"Unknown tool: {tool_name}"
        else:
            tool_result = tool_obj.invoke(tool_args)
            content = tool_result if isinstance(tool_result, str) else json.dumps(tool_result, ensure_ascii=False)

        tool_messages.append(
            ToolMessage(
                content=content,
                name=tool_name,
                tool_call_id=tool_call["id"],
            )
        )

    sleep(0.1)
    return {
        "messages": tool_messages,
        "info": [f"{len(state.get('info', [])) + 1}. Tools executed sequentially: {tool_names}"],
    }


def audit_node(state: OverAllState) -> OverAllState:
    """延迟审计节点，业务日志埋点。"""

    logger.info("[审计]会话执行完成")
    return {
        "info": [f"{len(state.get('info', [])) + 1}. 当前任务的审计日志已记录"]
    }
