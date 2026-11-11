"""LLM 客户端封装：各阶段统一调用入口。

- 模型对象延迟创建，导入本模块时不会因为缺少 API Key 而报错；
- `chat_json` 对 markdown 代码块、前后多余文字做容错解析。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# 项目根目录的 .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
DEFAULT_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

_model = None


def get_model():
    """延迟创建 ChatDeepSeek（首次真正调用时才需要 API Key）。"""
    global _model
    if _model is None:
        from langchain_deepseek import ChatDeepSeek

        _model = ChatDeepSeek(
            model=DEFAULT_MODEL,
            temperature=DEFAULT_TEMPERATURE,
            extra_body={"thinking": {"type": "disabled"}},
        )
    return _model


def chat(prompt: str, system: str = "") -> str:
    """统一 LLM 调用。"""
    messages = []
    if system:
        messages.append(("system", system))
    messages.append(("human", prompt))
    try:
        resp = get_model().invoke(messages)
    except Exception as e:  # pragma: no cover - 依赖外部服务
        raise RuntimeError(f"LLM 调用失败: {e}") from e
    content = resp.content
    if isinstance(content, list):  # 多模态/分块返回
        content = "".join(str(part) for part in content)
    return str(content).strip()


def _extract_json(text: str) -> str:
    """从模型输出里截出最可能的 JSON 片段。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        return text
    end = max(text.rfind("}"), text.rfind("]"))
    return text[start:end + 1] if end > start else text[start:]


def chat_json(prompt: str, system: str = "") -> dict:
    """调用 LLM 并解析 JSON 输出。"""
    text = chat(prompt, system)
    try:
        return json.loads(_extract_json(text))
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM 返回内容不是合法 JSON: {e}\n原文前 500 字:\n{text[:500]}") from e


# ---------------------------------------------------------------- 工具绑定
# 算子在启动时通过 bind_tools 与模型绑定，模型可直接发起函数调用，
# 因此各阶段提示词里不需要再罗列算子名与参数。
_tool_model = None
_tool_names: tuple[str, ...] = ()


def get_tool_model():
    """返回绑定了全部算子的模型（算子集合变化时自动重建）。"""
    global _tool_model, _tool_names
    from tools import tool_registry

    schemas = tool_registry.tool_schemas()
    names = tuple(s["function"]["name"] for s in schemas)
    if _tool_model is None or names != _tool_names:
        _tool_model = get_model().bind_tools(schemas)
        _tool_names = names
    return _tool_model


def chat_with_tools(messages):
    """一次 ReAct 轮次：返回 AIMessage（可能带 tool_calls）。"""
    try:
        return get_tool_model().invoke(messages)
    except Exception as e:  # pragma: no cover - 依赖外部服务
        raise RuntimeError(f"LLM 工具调用失败: {e}") from e
