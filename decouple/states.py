# states.py —— 用户上下文与图状态定义

from dataclasses import dataclass, field
from typing import TypedDict, Annotated, Optional, List
from operator import add

from langgraph.graph.message import MessagesState
from langgraph.managed import RemainingSteps

@dataclass
class UserContext:
    username: str
    membership_level: str = "普通用户"

class AgentNetState(MessagesState):
    remaining_steps: RemainingSteps
    input: str                                    # 用户原始问题
    info: Annotated[list[str], add]               # 过程日志
    output: str                                   # 最终输出
    detected_domain: Optional[str]                # 识别出的领域
    task_type: Optional[str]                      # 识别出的任务类型（工具名）
    selected_agent: Optional[str]                 # 当前选中的智能体
    subtasks: List[str] = field(default_factory=list)   # 待处理子任务
    subtask_results: Annotated[list[str], add]    # 子任务结果汇总
    cooperation: Optional[bool]                   # 是否需要多智能体协作
    trajectory: Annotated[list[str], add]         # 任务执行轨迹（用于提炼 skill）
    task_success: Optional[bool]                  # 任务是否成功
    preferences: dict                             # 领域知识库

class InputState(MessagesState):
    input: str

class OutputState(MessagesState):
    info: list[str]
    output: str
