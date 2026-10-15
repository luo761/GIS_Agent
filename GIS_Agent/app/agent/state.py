from __future__ import annotations

from typing import Any

from typing_extensions import NotRequired, TypedDict

'''
name：调用的工具名，比如 spatial_filter、buffer_query
input：传给工具的参数
result：工具返回结果；失败时可能是 None
elapsed_ms：耗时，单位毫秒
error：错误信息；成功时是 None
'''



class ToolCallRecord(TypedDict, total=False):
    name: str
    input: dict[str, Any]
    result: dict[str, Any] | None
    elapsed_ms: float
    error: str | None


class AgentState(TypedDict):
    question: str
    plan: NotRequired[list[dict[str, Any]]]
    tool_calls: NotRequired[list[ToolCallRecord]]
    answer: NotRequired[str]
    error: NotRequired[str | None]
