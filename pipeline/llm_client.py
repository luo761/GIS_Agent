"""LLM 客户端封装：各阶段统一调用入口。

- 模型对象延迟创建，导入本模块时不会因为缺少 API Key 而报错；
- `chat_json` 对 markdown 代码块、前后多余文字做容错解析。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# 项目根目录的 .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
DEFAULT_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

_model = None
_usage: dict[str, int | float] = {}


def reset_usage_metrics() -> None:
    """重置本进程的模型调用计数；不保存提示词、回复或凭据。"""
    _usage.clear()
    _usage.update(llm_calls=0, failed_calls=0, input_tokens=0, output_tokens=0,
                  total_tokens=0, usage_reported_calls=0, elapsed_s=0.0)


def usage_metrics() -> dict[str, int | float]:
    """返回逻辑 invoke 次数和服务端报告的 token 用量快照。"""
    return {**_usage, "elapsed_s": round(float(_usage["elapsed_s"]), 6)}


def _invoke_with_metrics(model_factory, messages):
    started = time.perf_counter()
    _usage["llm_calls"] += 1
    try:
        response = model_factory().invoke(messages)
    except Exception:
        _usage["failed_calls"] += 1
        raise
    finally:
        _usage["elapsed_s"] += time.perf_counter() - started

    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, dict) or not usage:
        metadata = getattr(response, "response_metadata", None)
        usage = metadata.get("token_usage") if isinstance(metadata, dict) else None
    if isinstance(usage, dict) and usage:
        aliases = {"input_tokens": "prompt_tokens", "output_tokens": "completion_tokens"}
        counts = {}
        for key, alias in aliases.items():
            value = usage.get(key, usage.get(alias, 0))
            counts[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
        total = usage.get("total_tokens", sum(counts.values()))
        counts["total_tokens"] = total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else sum(counts.values())
        for key, value in counts.items():
            _usage[key] += value
        _usage["usage_reported_calls"] += 1
    return response


reset_usage_metrics()


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
        resp = _invoke_with_metrics(get_model, messages)
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
# 首次使用工具模型时通过 bind_tools 绑定，模型可直接发起函数调用，
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
        return _invoke_with_metrics(get_tool_model, messages)
    except Exception as e:  # pragma: no cover - 依赖外部服务
        raise RuntimeError(f"LLM 工具调用失败: {e}") from e
