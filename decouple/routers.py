# routers.py —— 图拓扑决策路由

from typing import Literal

# 领域关键词兜底表（领域识别失败时扫描）
DOMAIN_KEYWORDS = {
    "燃气": ["燃气", "阀门", "泄漏", "管材", "铸铁", "PE管"],
    "水务": ["水务", "供水", "排水", "隐患点", "洪涝", "淤积", "水质"],
    "电务": ["电力", "电务", "缆线", "杆塔", "电压"],
}

def router_after_execute(state) -> Literal["tool_node", "learn_node"]:
    """执行后：有工具调用则进工具节点，否则直接进入学习沉淀"""
    messages = state["messages"]
    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tool_node"
    return "learn_node"
