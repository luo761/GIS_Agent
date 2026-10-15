from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek

from app.agent.deterministic import DeterministicGISAgent, PlannedToolCall
from app.config.settings import get_settings
from app.tools.layers import ALLOWED_LAYERS
from app.tools.registry import postgis_tool_definitions, postgis_tool_names


class LLMGISAgent(DeterministicGISAgent):
    """Real LLM planner with registered PostGIS tool schemas.

    The LLM only selects one registered tool and produces JSON arguments.
    Local PostGISToolkit methods still execute the actual database work.
    """

    def __init__(self, model: ChatDeepSeek | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        settings = get_settings()
        if settings.llm_api_key:
            os.environ.setdefault("DEEPSEEK_API_KEY", settings.llm_api_key)
        self.model = model or ChatDeepSeek(
            model=settings.llm_model,
            temperature=0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        self.planner = self.model.bind_tools(postgis_tool_definitions(), tool_choice="auto")

    def plan(self, question: str) -> list[PlannedToolCall]:
        response = self.planner.invoke(
            [
                SystemMessage(content=self._system_prompt()),
                HumanMessage(content=question),
            ]
        )
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            tool_calls = _raw_tool_calls(response)
        if not tool_calls:
            raise ValueError("LLM did not choose a registered PostGIS tool.")

        first_call = tool_calls[0]
        name = first_call.get("name")
        arguments = first_call.get("args") or {}
        if name not in postgis_tool_names():
            raise ValueError(f"LLM chose unsupported tool: {name}")
        if not isinstance(arguments, dict):
            raise ValueError(f"LLM returned invalid arguments for tool {name}: {arguments!r}")
        return [PlannedToolCall(name=name, arguments=arguments)]

    @staticmethod
    def _system_prompt() -> str:
        allowed_layers = ", ".join(sorted(ALLOWED_LAYERS))
        return f"""
你是一个 GIS Agent 的规划器。你的任务不是直接回答问题，而是调用一个已注册的 PostGIS Tool。

必须遵守：
- 每次只选择一个已注册工具。
- 不要编造图层名、字段名或 SQL。
- 不要直接返回 SQL。
- 坐标默认 SRID 为 3857。
- 允许图层：{allowed_layers}
- 常用区域编码：施工一区/A区=A001，施工二区/B区=A002，施工三区/C区=A003。
- 常用目标对象：D011 是 520,520 附近的燃气监测点。
"""

def _raw_tool_calls(response: Any) -> list[dict[str, Any]]:
    raw_calls = getattr(response, "additional_kwargs", {}).get("tool_calls", [])
    normalized = []
    for raw_call in raw_calls:
        function = raw_call.get("function", {})
        raw_args = function.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON tool arguments: {raw_args}") from exc
        normalized.append({"name": function.get("name"), "args": args})
    return normalized
