# states.py

from typing import TypedDict, Annotated, Literal, Optional
from operator import add
from langgraph.graph.message import MessagesState
from langgraph.managed import RemainingSteps
from dataclasses import dataclass

# 运行时上下文
@dataclass
class UserContext:
    username: str
    membership_level: str  # "普通用户" / "VIP"

class GisTask(TypedDict):
    """解析之后标准化GIS空间任务，对应课题：自然语言转标准化空间任务指令"""
    intent: str  # 业务意图：管线统计 / 缓冲区分析 / 隐患查询 /叠加分析
    domain: str  # 领域：燃气 / 水务
    layer_name: Optional[str]  # 操作图层
    params: dict  # 分析参数，例如缓冲距离、筛选条件


class OverAllState(MessagesState):
    remaining_steps: RemainingSteps
    input: str  # 用户原始输入问句
    info: Annotated[list[str], add]  # 记录中间过程日志
    output: str  # 最终输出文本
    is_llm_approved: bool # 是否同意调用大语言模型
    fieldname: Optional[str]  # 当前业务领域 "燃气"/"水务"，不是list
    preferences: dict  # 从postgres store读取的领域知识库
    gis_task: Optional[GisTask]  # LLM语义解析输出的标准化GIS任务


class InputState(MessagesState):
    input: str
    fieldname: Optional[str]


class OutputState(MessagesState):
    output: str
    info: list[str]
