"""工具池：算子注册表 + 统一调用入口 + 工具 schema。

算子在进程启动时就通过 `tool_schemas()` 生成 OpenAI function-calling 描述，
并由 `pipeline/llm_client.py` 的 `bind_tools` 绑定到模型上——之后模型可以直接发起工具调用，
提示词里不需要再罗列算子名和参数。
"""
from __future__ import annotations

import importlib
import inspect
from typing import Any, Callable, get_type_hints

_REGISTRY: dict[str, Callable] = {}

_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def register(name: str):
    """装饰器：把函数注册为工具池算子。"""
    def deco(fn):
        _REGISTRY[name] = fn
        fn.tool_name = name
        return fn
    return deco


def call(name: str, **params):
    """按名称调用算子；异常统一上抛，由执行器捕获后反馈模型。"""
    if name not in _REGISTRY:
        raise KeyError(f"工具池中不存在算子: {name}，可用: {list(_REGISTRY)}")
    return _REGISTRY[name](**params)


def list_tools() -> list[str]:
    return list(_REGISTRY)


def describe_tools() -> list[str]:
    """算子名 + 一句话说明（日志/调试用；不再注入提示词）。"""
    out = []
    for name, fn in _REGISTRY.items():
        doc = (fn.__doc__ or "").strip().splitlines()
        out.append(f"{name}: {doc[0]}" if doc else name)
    return out


def _parameter_schema(fn: Callable) -> dict:
    """根据函数签名生成 JSON Schema 参数定义。"""
    try:  # operators.py 用了延迟注解，需要解析成真实类型
        hints = get_type_hints(fn)
    except Exception:  # pragma: no cover - 无法解析时退回原始注解
        hints = {}
    props: dict[str, dict] = {}
    required: list[str] = []
    for pname, p in inspect.signature(fn).parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        annotation = hints.get(pname, p.annotation)
        api_type = _JSON_TYPES.get(annotation)
        schema: dict[str, Any] = {}
        if api_type:
            schema["type"] = api_type
        props[pname] = schema
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def get_openai_tool_schema(name: str) -> dict:
    """导出单个算子的 OpenAI function-calling 描述。

    若注册时提供了显式 `parameters`（外部工具集通常自带完整 JSON Schema），优先使用它。
    """
    fn = _REGISTRY[name]
    parameters = getattr(fn, "parameters", None) or _parameter_schema(fn)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (fn.__doc__ or name).strip(),
            "parameters": parameters,
        },
    }


def tool_schemas() -> list[dict]:
    """全部算子的 OpenAI function-calling 描述（供 bind_tools 使用）。"""
    return [get_openai_tool_schema(name) for name in _REGISTRY]


# 导入 PostGIS 工具集以触发注册（空间算子实现位于外部 dev20 项目，只读调用）
importlib.import_module("tools.postgis_tools")
