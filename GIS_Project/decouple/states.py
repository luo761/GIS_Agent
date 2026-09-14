# states.py

from dataclasses import dataclass
from operator import add
from typing_extensions import Annotated, Optional, TypedDict, List

from langgraph.graph.message import MessagesState
from langgraph.managed import RemainingSteps


@dataclass
class UserContext:
    username: str
    membership_level: str  # "普通用户" / "VIP"


class OverAllState(MessagesState):
    remaining_steps: RemainingSteps
    input: str
    info: Annotated[list[str], add]
    output: str

    # [替换-文档版] 原字段 fieldname: Optional[str] 改为 fieldnames: Optional[list[str]]，支持多领域交叉。
    fieldnames: Optional[list[str]]
    detect_fieldnames_reason: str

    preferences: dict
    is_llm_approved: bool
    cancelled: bool

    # [删除-文档版] 原 GisTask / gis_task 标准化任务字段未在文档版流程中继续使用。


class InputState(TypedDict, total=False):
    input: str
    fieldnames: Optional[list[str]]

    # [兼容-保留] 旧入口如果仍传 fieldname，可在节点中转换为 fieldnames。
    fieldname: Optional[str]


class OutputState(TypedDict, total=False):
    info: list[str]
    detect_fieldnames_reason: str
    output: str


# [新增-文档版] 子图状态：预检查（领域识别 + 知识库读取）。
class PrecheckState(TypedDict, total=False):
    input: str
    fieldnames: Optional[List[str]]
    fieldname: Optional[str]
    detect_fieldnames_reason: str
    preferences: dict
    info: Annotated[list[str], add]
    cancelled: bool
