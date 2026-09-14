# routers.py

from typing import Literal
from langgraph.graph import END
from loguru import logger
from states import OverAllState


def router_preference(state: OverAllState) -> Literal["check_preferences_node", "llm_parse_node"]:
    """判断是否需要从长期记忆读取领域知识库"""
    if not state.get("preferences"):
        logger.info("需要读取Postgres长期记忆获取领域知识库")
        return "check_preferences_node"
    logger.info("领域知识库已加载，直接进入语义解析")
    return "llm_parse_node"


def router_after_llm(state: OverAllState) -> Literal["tool_node", END]:
    """判断是否调用GIS工具算子"""
    messages = state["messages"]
    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tool_node"
    return END
