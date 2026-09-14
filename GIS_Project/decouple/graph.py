# graph.py

from langgraph.graph import END, START, StateGraph
from langgraph.types import CachePolicy, RetryPolicy
from requests.exceptions import HTTPError

from nodes import audit_node, call_precheck_subgraph, end_node, llm_parse_node, tool_node_wrapper
from persistence import DB_URL, PostgresSaver, PostgresStore
from routers import router_after_llm, router_after_precheck
from states import InputState, OutputState, OverAllState, UserContext


builder = StateGraph(
    OverAllState,
    input_schema=InputState,
    output_schema=OutputState,
    context_schema=UserContext
)

# [替换-文档版] 原主图直接 check_preferences_node；现在先进入预检查子图。
builder.add_node("call_precheck_subgraph", call_precheck_subgraph)
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

# [替换-文档版] 新流程：START -> 预检查子图 -> LLM -> 可选工具 -> LLM -> 结束。
builder.add_edge(START, "audit_node")
builder.add_edge("audit_node", END)
builder.add_edge(START, "call_precheck_subgraph")
builder.add_conditional_edges("call_precheck_subgraph", router_after_precheck)
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


if __name__ == "__main__":
    graph = get_graph()
    print(graph.get_graph().draw_mermaid())
