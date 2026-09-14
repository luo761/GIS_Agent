# graph.py

from dataclasses import dataclass
from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy, CachePolicy
from requests.exceptions import HTTPError
from langgraph.prebuilt import ToolNode
from states import UserContext
from GIS_Project.decouple.tools import gis_tools
from persistence import DB_URL, PostgresSaver, PostgresStore
from states import OverAllState, InputState, OutputState
from nodes import check_preferences_node, llm_parse_node, tool_node, audit_node
from routers import router_preference, router_after_llm
from pydantic import BaseModel



# 构建图
builder = StateGraph(
    OverAllState,
    input_schema=InputState,
    output_schema=OutputState,
    context_schema=UserContext
)

# 添加节点
builder.add_node("check_preferences_node", check_preferences_node)
builder.add_node("llm_parse_node", llm_parse_node)
builder.add_node(
    "tool_node",
    ToolNode(tools=gis_tools),
    retry_policy=RetryPolicy(
        max_attempts=3,
        jitter=False,
        retry_on=(HTTPError, ConnectionError)
    ),
    cache_policy=CachePolicy(ttl=60)
)
builder.add_node("audit_node", audit_node, defer=True)

# 流程拓扑：START → 判断是否加载知识库 → LLM语义解析 → 可选调用GIS工具 → END → 延迟审计
builder.add_conditional_edges(START, router_preference)
builder.add_edge(START, "audit_node")
builder.add_edge("check_preferences_node", "llm_parse_node")
builder.add_conditional_edges("llm_parse_node", router_after_llm)
builder.add_edge("tool_node", "llm_parse_node")
builder.add_edge("audit_node", END)


# 编译图：传入postgres checkpointer与store
def get_graph():
    checkpointer = PostgresSaver.from_conn_string(DB_URL)
    store = PostgresStore.from_conn_string(DB_URL)
    checkpointer.setup()
    store.setup()
    graph = builder.compile(checkpointer=checkpointer, store=store)
    return graph, checkpointer, store


if __name__ == "__main__":
    graph, cp, st = get_graph()
    # mermaid 打印图
    print(graph.get_graph().draw_mermaid())





