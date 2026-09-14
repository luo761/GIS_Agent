"""
GIS LangGraph 一体化单文件脚本
整合 graph.py / main.py / models.py / nodes.py / persistence.py / routers.py / states.py / tools.py
"""
from dataclasses import dataclass
from time import sleep
from typing import TypedDict, Annotated, Literal, Optional, Final, Tuple, List
from operator import add

from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy, CachePolicy, interrupt, Command
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langgraph.graph.message import MessagesState
from langgraph.managed import RemainingSteps
from langgraph.runtime import Runtime
from langgraph.prebuilt import ToolNode, ToolRuntime

from langchain_core.messages import (
    SystemMessage, HumanMessage, ToolMessage, AIMessage
)
from langchain_core.runnables.config import RunnableConfig
from langchain.tools import tool
from langgraph.types import interrupt, Command

from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv
from loguru import logger
from requests.exceptions import HTTPError
from pydantic import BaseModel, Field

# ===================== models.py =====================
load_dotenv(override=True)

model = ChatDeepSeek(
    model="deepseek-v4-flash",
    extra_body={
        "thinking": {
            "type": "disabled"
        }
    },
    temperature=0.1
)

# ===================== 结构化输出Schema：领域识别结果 =====================
class DomainDetectResult(BaseModel):
    """LLM结构化输出：识别用户问题涉及哪些GIS业务领域"""
    domains: List[Literal["燃气", "水务", "电务"]] = Field(
        description="从【燃气、水务、电务】中选出问题相关领域，根据匹配可返回含多个领域的列表，无匹配返回空列表"
    )
    reason: str = Field(
        description="简短推理说明，为什么选出这些或这个领域"
    )
# 给模型绑定结构化输出能力，专门用于领域检测
domain_router = model.with_structured_output(DomainDetectResult)

# ===================== states.py =====================
@dataclass
class UserContext:
    username: str
    membership_level: str  # "普通用户" / "VIP"


class OverAllState(MessagesState):
    remaining_steps: RemainingSteps
    input: str  # 用户原始输入问句
    info: Annotated[list[str], add]  # 记录中间过程日志
    output: str  # 最终输出文本
    is_llm_approved: bool  # 是否同意调用大语言模型
    fieldnames: Optional[list[str]] # 当前业务领域 "燃气"/"水务"，支持多领域交叉
    detect_fieldnames_reason: str  # LLM推理理由
    preferences: dict  # 从postgres store读取的领域知识库


class InputState(MessagesState):
    input: str
    fieldnames: Optional[list[str]]


class OutputState(MessagesState):
    info: list[str]
    detect_fieldnames_reason: str
    output: str

# ===================== persistence.py =====================
DB_URL = "postgresql://langgraph_user:123456@localhost:5432/langgraph_db?sslmode=disable"

FIELDS_NS: Final[Tuple[str]] = ("fields",)
PREFERENCES_KEY: Final[str] = "preferences"


def init_knowledge_base():
    """初始化记忆库，写入燃气、水务、电务领域知识库，只需要运行一次"""
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
            PostgresStore.from_conn_string(DB_URL) as store:
        checkpointer.setup()
        store.setup()

        namespace1 = (*FIELDS_NS, "水务")
        value1 = {
            "description": "水务信息系统，包含供水管线、排水管网、水务设施、水务隐患",
            "term": "管线长度、管网覆盖、排水隐患、供水范围、缓冲区、管线叠加、设施统计",
            "skill": "管线统计、隐患筛查、缓冲区分析、叠加分析、邻近分析"
        }

        namespace2 = (*FIELDS_NS, "电务")
        value2 = {
            "description": "电务信息系统，电力管线、电力设施",
            "term": "电缆长度、电力隐患、电力保护区缓冲区",
            "skill": "管线统计、隐患筛查"
        }

        namespace3 = (*FIELDS_NS, "燃气")
        value3 = {
            "description": "燃气信息系统，燃气管线、阀门、调压站、燃气泄漏隐患",
            "term": "燃气管线长度、泄漏隐患、燃气保护区缓冲区、管线交叉冲突",
            "skill": "管线长度统计、隐患筛查、缓冲区分析、管线叠加冲突检测"
        }
        store.put(namespace1, PREFERENCES_KEY, value1)
        store.put(namespace2, PREFERENCES_KEY, value2)
        store.put(namespace3, PREFERENCES_KEY, value3)
    logger.info("领域知识库初始化完成")


# ===================== tools.py =====================
@tool(parse_docstring=True)
def buffer_analysis(domain: str, layer: str, buffer_distance: float) -> str:
    """
    GIS缓冲区分析算子，对应课题关键技术，生成要素周边缓冲区范围

    Args:
        domain: 业务领域，燃气/水务
        layer: 图层名称，例如燃气管线、水务隐患点
        buffer_distance: 缓冲距离，单位米
    """
    return f"""【模拟缓冲区分析结果】
    领域:{domain},图层:{layer},缓冲距离:{buffer_distance}米
    生成缓冲区面要素共12个，缓冲区总面积2.36平方公里，已完成图层预处理坐标归一化。"""

@tool(parse_docstring=True)
def pipe_length_stat(domain: str, filter_condition: str = "") -> str:
    """
    管线长度统计算子，统计指定领域管线总长度

    Args:
        domain: 业务领域，燃气/水务
        filter_condition: 筛选条件，如"高压管线"、"隐患管线"
    """
    if domain == "燃气":
        total = 128.72
    elif domain == "水务":
        total = 246.15
    else:
        total = 88.2
    return f"""【模拟管线统计结果】
    领域:{domain},筛选条件:{filter_condition}
    管线总长度：{total} KM"""

@tool(parse_docstring=True)
def hazard_query(domain: str, hazard_type: str = "all") -> str:
    """
    隐患筛查查询算子，查询领域内空间隐患分布

    Args:
        domain: 业务领域：燃气/水务
        hazard_type: 隐患类型，all全部，泄漏、腐蚀、破损
    """
    mock_data = {
        "燃气": ["阀门腐蚀隐患 3处", "管线泄漏风险点 2处"],
        "水务": ["管网破损点 5处", "排水淤积隐患4处"]
    }
    items = mock_data.get(domain, [])
    return f"""【模拟隐患查询结果】
    领域:{domain},隐患类型:{hazard_type}
    隐患列表：{items}
    隐患空间分布范围已完成图层加载。"""

@tool(parse_docstring=True)
def overlay_analysis(domain: str, layer_a: str, layer_b: str) -> str:
    """
    GIS叠加分析算子，图层叠加，用于管线交叉冲突检测

    Args:
        domain:业务领域
        layer_a:图层A
        layer_b:图层B
    """
    return f"""【模拟叠加分析结果】
    领域:{domain},图层A:{layer_a},图层B:{layer_b}
    检测到图层交叉冲突位置共4处，已输出冲突空间坐标。"""


gis_tools = [buffer_analysis, pipe_length_stat, hazard_query, overlay_analysis]
model_with_gis_tools = None

# 定义后创建内置工具节点实例
builtin_tool_node = ToolNode(gis_tools)

# 绑定工具只执行一次
if model_with_gis_tools is None:
    model_with_gis_tools = model.bind_tools(gis_tools)


# ===================== routers.py =====================
def router_get_preference(state: OverAllState) -> Literal["check_preferences_node", "domain_detect_node"]:
    """判断是否需要从长期记忆读取领域知识库"""
    if not state.get("preferences"):
        logger.info("需要读取Postgres长期记忆获取领域知识库")
        sleep(0.01)
        return "check_preferences_node"
    
    logger.info("领域知识库已加载")
    return "domain_detect_node"


def router_after_llm(state: OverAllState) -> Literal["tool_node", "end_node"]:
    """判断是否调用GIS工具算子"""
    messages = state["messages"]
    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tool_node"
    
    return "end_node"


# ===================== nodes.py =====================
# ===================== 节点定义 =====================
def domain_detect_node(state: OverAllState) -> OverAllState:
    """
    领域识别节点：调用结构化输出大模型，从问句识别业务领域
    如果state已经携带fieldnames列表，则跳过LLM识别，直接复用已有值
    """
    # 如果已经外部传入领域，直接复用，不调用LLM
    existing_fields = state.get("fieldnames", [])
    if existing_fields is not None and len(existing_fields) > 0:
        return {}

    prompt_sys = SystemMessage(content="""
    你是GIS业务领域识别助手。
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
        "info": [f"{len(state.get("info", []))+1}. 领域识别完成，识别到领域：{res.domains}，理由：{res.reason}"]
    }

# def no_domain_node(state: OverAllState) -> OverAllState:
#     """识别不到有效领域的兜底节点"""
#     return {
#         "output": "未能识别到【燃气/水务/电务】相关业务领域，无法执行GIS分析。",
#         "info": [f"{len(state.get("info", []))+1}. 未识别到有效领域，流程终止"]
#     }

def check_preferences_node(state: OverAllState, runtime: Runtime) -> OverAllState:
    """读取PostgresStore长期记忆store，领域的时空语义知识库"""

    # ---------- 中断确认 ----------
    confirm = interrupt("准备读取PostgresStore长期记忆知识库，是否继续？(yes/no)")
    if confirm not in (True, "yes"):
        return Command(goto=END, update={"info": "用户取消读取知识库，流程终止。"})


    merged_description = []
    merged_terms = []
    merged_skills = []
    # 读取fieldnames字段
    fieldnames = state.get("fieldnames", [])
    if not fieldnames:
        logger.warning("目前暂未未指定业务领域fieldnames")
        store = runtime.store
        # 加载全部专业知识库知识
        domains = list(["燃气", "水务", "电务"])

        for domain in domains:
            namespace = (*FIELDS_NS, domain)
            item = store.get(namespace, PREFERENCES_KEY)
            if not item:
                logger.warning(f"长期记忆没有关于{domain}的知识库")
                continue
            logger.info(f"已读取{domain}的领域知识库")
            val = item.value
            merged_description.append(f"【{domain}】\n{val.get("description", "")}")
            merged_terms.append(f"【{domain}】\n{val.get("term", "")}")
            merged_skills.append(f"【{domain}】\n{val.get("skill", "")}")
        # 加载全部专业知识库知识---

    else:
        logger.info("正在根据fieldnames收集对应专业知识")
        store = runtime.store
        # 加载对应专业知识库知识
        for domain in fieldnames:
            namespace = (*FIELDS_NS, domain)
            item = store.get(namespace, PREFERENCES_KEY)
            if not item:
                logger.warning(f"长期记忆没有关于{domain}的知识库")
                continue
            logger.info(f"已读取{domain}的领域知识库")
            val = item.value
            merged_description.append(f"【{domain}】\n{val.get("description", "")}")
            merged_terms.append(f"【{domain}】\n{val.get("term", "")}")
            merged_skills.append(f"【{domain}】\n{val.get("skill", "")}")
        # 加载对应专业知识库知识---

    merged_preferences = {
        "description": "\n".join(merged_description),
        "term": "；".join(merged_terms),
        "skill": "；".join(merged_skills)
    }

    sleep(0.05)

    return {
        "preferences": merged_preferences,
        "info": [f"{len(state.get("info", []))+1}. 读取PostgresStore知识库完成，已加载领域知识"]
    }

# def approve_node(state: OverAllState) -> Command[Literal["llm_parse_node", "default_node"]]:
#     is_approved = interrupt("是否同意调用模型?")
#     goto = "llm_parse_node" if is_approved else "default_node"
#     return Command(
#         goto=goto,
#         update={"is_llm_approved": is_approved}
#     )


# def default_node(state: OverAllState) -> OverAllState:
#     return {
#         "output": "模型调用请求被拒绝"
#     }


def llm_parse_node(state: OverAllState, runtime: Runtime[UserContext]) -> OverAllState:
    """时空语义解析节点：自然语言问句→识别GIS任务，可调用GIS模拟算子"""
    # ---------- 中断确认 ----------
    confirm = interrupt("准备调用大语言模型，是否继续？(yes/no)")
    if confirm not in (True, "yes"):
        return Command(goto=END, update={"info": "用户取消调用大语言模型，流程终止。"})

    runtime_context = runtime.context
    preferences = state.get("preferences", {})
    user_input = state["input"]
    history_messages = state.get("messages", [])

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
        # logger.info(f"当前用户: {username}, 会员等级: {level}")

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

    sleep(0.1)
    return {
        "messages": [resp],
        "output": resp.content,
        "info": [f"{len(state.get("info", []))+1}. LLM解析完成，生成了回复（可能包含工具调用）"]
    }


def tool_node_wrapper(state: OverAllState) -> OverAllState:
    """
    包装内置 ToolNode，在调用前后记录日志，并保留 state["info"] 累积功能。
    内置 ToolNode 默认并行执行所有工具调用。
    """
    # ---------- 前置日志：记录即将调用的工具 ----------
    last_ai = state["messages"][-1]
    tool_calls = getattr(last_ai, "tool_calls", [])
    tool_names = [tc["name"] for tc in tool_calls]
    logger.info(f"即将并行调用工具: {tool_names}")

    # ---------- 调用内置 ToolNode（自动并行） ----------
    # 内置 ToolNode 的 invoke 返回更新后的 state（包含新的 ToolMessage）
    result_state = builtin_tool_node.invoke(state)

    # 追加 info 日志
    info_msg = f"当前工具正在并行执行:"
    for tool_name in tool_names:
        info_msg = info_msg + f"['{tool_name}'] "
    result_state["info"] = [f"{len(state.get("info", [])) + 1}. {info_msg}"]

    sleep(0.1)

    return result_state

def end_node(state: OverAllState) -> OverAllState:
    """结算节点，结算信息"""
    logger.info(f"进入结算节点")
    return {
        "info": [f"{len(state.get("info", []))+1}. 当前任务执行完毕"]
    }

def audit_node(state: OverAllState) -> OverAllState:
    """延迟审计节点，业务日志埋点"""
    logger.info(f"[审计]会话执行完成")
    return {
        "info": [f"{len(state.get("info", []))+1}. 当前任务的审计日志已记录"]
    }


# ===================== graph.py 图构建 =====================
builder = StateGraph(
    OverAllState,
    input_schema=InputState,
    output_schema=OutputState,
    context_schema=UserContext
)

# 添加节点
builder.add_node("domain_detect_node", domain_detect_node)
builder.add_node("check_preferences_node", check_preferences_node)
builder.add_node("llm_parse_node", llm_parse_node)
builder.add_node(
    "tool_node",
    tool_node_wrapper,
    retry_policy=RetryPolicy(
        max_attempts=3,
        jitter=False,
        retry_on=(HTTPError, ConnectionError)
    ),
    cache_policy=CachePolicy(ttl=60)
)
builder.add_node("audit_node", audit_node, defer=True)
builder.add_node("end_node", end_node)

# 流程拓扑
builder.add_edge(START, "audit_node")
builder.add_edge("audit_node", END)
builder.add_conditional_edges(START, router_get_preference)
builder.add_edge("check_preferences_node", "domain_detect_node")
builder.add_edge("domain_detect_node", "llm_parse_node")
builder.add_conditional_edges("llm_parse_node", router_after_llm)
builder.add_edge("tool_node", "llm_parse_node")
builder.add_edge("end_node", END)

def get_graph():
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
         PostgresStore.from_conn_string(DB_URL) as store:
        checkpointer.setup()
        store.setup()
        graph = builder.compile(checkpointer=checkpointer, store=store)
        return graph


# ===================== main.py 入口逻辑 =====================
def run_demo():
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
         PostgresStore.from_conn_string(DB_URL) as store:
        graph = builder.compile(checkpointer=checkpointer, store=store)

        config = {
            "configurable": {"thread_id": "GIS_Test"},
            "recursion_limit": 10
        }
        initial_state = {
            "input": "帮我统计燃气管线总长度",
            "fieldnames": ["燃气"]
        }
        context = UserContext(username="GIS测试用户", membership_level="普通用户")

        inputs = initial_state
        final_state = None
        while True:
            try:
                for event in graph.stream(
                    inputs,
                    config=config,
                    context=context,
                    stream_mode=["updates", "values"],
                    # 切换不同版本的流式执行输出
                    version="v2"
                ):
                    print(event)
                    if "__interrupt__" in event:
                        interrupts = event["__interrupt__"]
                        for inter in interrupts:
                            print(f"⏸️ 中断：{inter.value}")
                            user_input = input("是否继续？(yes/no): ").strip().lower()
                            if user_input == "yes":
                                inputs = Command(resume=True)
                                # 跳出 for，重新进入 while，继续流
                                break
                            else:
                                print("用户取消，流程终止。")
                                return
                        else:
                            # 没有中断，继续处理事件
                            continue
                        break  # 如果有中断并恢复，跳出 for 重新开始 while
                    else:
                        # 正常事件，保留最新状态
                        if "output" in event:
                            final_state = event
                        # 可以打印中间状态用于调试
                        # print("当前状态:", event)
                else:
                    # for 循环正常结束（没有中断），流已结束
                    break
            except StopIteration:
                break

        if final_state:
            # 打印info列表
            if "info" in final_state and final_state["info"]:
                print("\n====================执行过程记录====================")
                for i, info_msg in enumerate(final_state["info"], 1):
                    print(f"{info_msg}")
                print("\n")

            for msg in final_state.get("messages", []):
                msg.pretty_print()

            if "output" in final_state:
                print("\n====================最终输出====================")
                print(final_state["output"])
                print("\n")
            # 打印所有消息（可选）
            # 如果有 messages，也可以遍历打印

        # # 示例2：水务缓冲区分析提问，复用同一个thread会话
        # res2 = graph.invoke(
        #     {
        #         "input": "给水隐患点做100米缓冲区分析",
        #         "fieldnames": "水务"
        #     },
        #     config=config,
        #     context=UserContext(username="老王", membership_level="普通用户")
        # )
        # print("\n=====提问2结果=====")
        # print(res2["output"])


if __name__ == "__main__":
    # 第一次运行打开下面这行初始化知识库，之后可以注释
    # init_knowledge_base()

    # 打印mermaid图
    graph = get_graph()
    print(graph.get_graph().draw_mermaid())

    # 执行demo
    run_demo()
