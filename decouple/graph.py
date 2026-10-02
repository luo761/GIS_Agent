# graph.py —— StateGraph 组装与编译

from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy
from requests.exceptions import HTTPError

from states import AgentNetState, InputState, OutputState, UserContext
from persistence import DB_URL
from nodes import (detect_node, route_node, execute_node, tool_node_wrapper,
                   final_answer_node, learn_node, end_node)
from routers import router_after_execute

builder = StateGraph(
    AgentNetState,
    input_schema=InputState,
    output_schema=OutputState,
    context_schema=UserContext,
)

builder.add_node("detect_node", detect_node)
builder.add_node("route_node", route_node)
builder.add_node("execute_node", execute_node)
builder.add_node("tool_node", tool_node_wrapper,
                 retry_policy=RetryPolicy(max_attempts=3, jitter=False,
                                          retry_on=(HTTPError, ConnectionError)))
builder.add_node("final_answer_node", final_answer_node)
builder.add_node("learn_node", learn_node)
builder.add_node("end_node", end_node)

# 拓扑
builder.add_edge(START, "detect_node")
builder.add_edge("detect_node", "route_node")
builder.add_edge("route_node", "execute_node")
builder.add_conditional_edges("execute_node", router_after_execute)
builder.add_edge("tool_node", "final_answer_node")  # 工具完成后先整合最终答复
builder.add_edge("final_answer_node", "learn_node")  # 再进入学习沉淀
builder.add_edge("learn_node", "end_node")
builder.add_edge("end_node", END)

def get_graph():
    """在 with 内部编译图；注意连接生命周期归调用方管理（harness 自持连接）"""
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
            PostgresStore.from_conn_string(DB_URL) as store:
        checkpointer.setup()
        store.setup()
        return builder.compile(checkpointer=checkpointer, store=store)
