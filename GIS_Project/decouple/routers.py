# routers.py

from time import sleep
from typing import Literal

from loguru import logger

from states import OverAllState, PrecheckState


# [替换-文档版] 原 router_preference 改为预检查子图内路由。
def router_get_preference(state: PrecheckState) -> Literal["check_preferences_node", "domain_detect_node"]:
    """判断是否需要从长期记忆读取领域知识库。"""

    if not state.get("preferences"):
        logger.info("需要读取 Postgres 长期记忆获取领域知识库")
        sleep(0.01)
        return "check_preferences_node"

    logger.info("领域知识库已加载")
    return "domain_detect_node"


def router_after_llm(state: OverAllState) -> Literal["tool_node", "end_node"]:
    """判断是否调用 GIS 工具算子。"""

    messages = state["messages"]
    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tool_node"

    return "end_node"


# [新增-文档版] 预检查子图结束后的父图分支。
def router_after_precheck(state: OverAllState) -> Literal["llm_parse_node", "end_node"]:
    """
    子图执行完之后的分支：
    - 若 cancelled=True，直接走 end_node 结束主流程；
    - 否则进入 llm_parse_node。
    """

    if state.get("cancelled"):
        logger.info("预检查子图返回 cancelled=True，跳转到 end_node")
        return "end_node"
    return "llm_parse_node"
