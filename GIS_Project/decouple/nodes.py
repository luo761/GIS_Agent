# nodes.py

from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from langgraph.runtime import Runtime
from langgraph.types import RetryPolicy
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import interrupt, Command
from persistence import FIELDS_NS, PREFERENCES_KEY
from states import OverAllState
from models import model
from tools import gis_tools, model_with_gis_tools
from typing import TypedDict, Literal
from states import UserContext

# 绑定工具只执行一次
if model_with_gis_tools is None:
    model_with_gis_tools = model.bind_tools(gis_tools)


def check_preferences_node(state: OverAllState, runtime: Runtime) -> OverAllState:
    """读取PostgresStore长期记忆，支持加载**多个**领域的时空语义知识库，合并"""
    field_list = state.get("fieldname", [])
    if not field_list:
        logger.warning("没有识别到任何业务领域fieldname列表")
        return {}
    store = runtime.store
    namespace_base = FIELDS_NS

    merged_description = []
    merged_terms = []
    merged_skills = []

    for domain in field_list:
        namespace = (*namespace_base, domain)
        item = store.get(namespace, PREFERENCES_KEY)
        if not item:
            logger.warning(f"长期记忆没有 {domain} 的知识库，跳过该领域")
            continue
        val = item.value
        logger.info(f"读取领域[{domain}]知识库:{val}")
        merged_description.append(f"【{domain}】{val.get('description','')}")
        merged_terms.append(val.get("term",""))
        merged_skills.append(val.get("skill",""))

    merged_preference = {
        "description": "\n".join(merged_description),
        "term": "；".join(merged_terms),
        "skill": "；".join(merged_skills),
        "domains": field_list  # 记录原始领域列表
    }
    return {"preferences": merged_preference}

def approve_node(state:OverAllState) -> Command[Literal["llm_parse_node","default_node"]]:
    is_approved = interrupt("是否同意调用模型?")
    goto = "llm_parse_node" if is_approved else "default_node"
    return Command(
        goto=goto,
        update={"is_llm_approved":is_approved}
    )

def default_node(state:OverAllState) -> OverAllState:
    return {
        "output":"模型调用请求被拒绝"
    }

def llm_parse_node(state: OverAllState, runtime: Runtime[UserContext]) -> OverAllState:
    """时空语义解析节点：自然语言问句→识别GIS任务，可调用GIS模拟算子"""
    runtime_context = runtime.context
    preferences = state.get("preferences", {})
    user_input = state["input"]
    history_messages = state.get("messages", [])

    # 把知识库dict转为字符串给SystemMessage
    knowledge_text = f"""【领域知识库】
    描述:{preferences.get('description','')}
    业务术语:{preferences.get('term','')}
    支持分析能力:{preferences.get('skill','')}
    
    你是GIS智能体，接收市政业务人员自然语言提问，识别GIS空间分析意图，按需调用提供的GIS工具算子。
    支持工具：缓冲区分析、管线长度统计、隐患查询、叠加分析。
    不要编造不存在工具，参数严格按照工具描述填写。
    """

    if runtime_context:
        username = runtime_context.username
        level = runtime_context.membership_level
        logger.info(f"当前用户: {username}, 会员等级: {level}")

        if level == "VIP":
            system_prompt = f"你是高级客服助理。当前VIP用户是{username}，请使用尊称'您'，语气热情周到，回复末尾加上'🎖️VIP专属服务'。"
        else:
            system_prompt = f"你是普通客服助理。当前用户是{username}，请友好简洁地回复。"
    else:
        logger.warning("运行时上下文为空，使用默认风格")
        system_prompt = "你是客服助理，请友好简洁地回复。"

    sys_msg = SystemMessage(content=knowledge_text + system_prompt)
    messages = [sys_msg] + history_messages + [HumanMessage(content=user_input)]
    resp = model_with_gis_tools.invoke(messages)
    return {
        "messages": [resp],
        "output": resp.content
    }


def tool_node(state: OverAllState) -> OverAllState:
    """GIS工具执行节点，执行模拟GIS算子，模拟少量失败重试"""
    messages = state["messages"]
    last_ai_msg: AIMessage = messages[-1]
    tool_calls = last_ai_msg.tool_calls
    new_messages = []
    for call in tool_calls:
        tool_name = call["name"]
        tool_args = call["args"]
        found = next((t for t in gis_tools if t.name == tool_name), None)
        if found:
            tool_result = found.invoke(tool_args)
            new_messages.append(ToolMessage(content=tool_result, tool_call_id=call["id"]))
        else:
            new_messages.append(ToolMessage(content=f"不存在工具:{tool_name}", tool_call_id=call["id"]))
    return {"messages": messages + new_messages}


def audit_node(state: OverAllState) -> OverAllState:
    """延迟审计节点，业务日志埋点"""
    logger.info(f"[审计]会话执行完成，输出：{state.get('output')}")
    return {}
