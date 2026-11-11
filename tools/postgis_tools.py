"""把 dev20 项目的 PostGIS 工具集接入本项目的工具注册表。

空间计算逻辑复用外部工具集 `app_development/tool.py`（白名单图层、参数模型、
完整要素集、PostGIS 空间 SQL），本项目负责：
  · 生成 function-calling schema 并绑定到模型；
  · 工具调用的统一入口；
  · 结果引用（$ref）、轨迹与能力进化的衔接。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

from config import settings
from tools import tool_registry


def _load_external():
    """按配置路径加载外部工具集模块（只读调用，不修改其源码）。"""
    root = Path(settings.POSTGIS_TOOLKIT_ROOT)
    tool_file = root / "app_development" / "tool.py"
    if not tool_file.exists():
        raise FileNotFoundError(f"找不到 PostGIS 工具集: {tool_file}")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("DATABASE_URL", settings.DATABASE_URL)
    os.environ.setdefault("APP_SCHEMA", settings.APP_SCHEMA)
    from app_development import tool as external_tool  # type: ignore

    return external_tool


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    """把 Pydantic 的 $defs/$ref 内联成扁平的 JSON Schema，兼容不认 $ref 的服务端。"""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = _inline_refs(defs.get(ref.split("/")[-1], {}), defs)
            extra = {k: v for k, v in node.items() if k != "$ref"}
            if isinstance(target, dict):
                return _inline_refs({**target, **extra}, defs)
            return _inline_refs(extra, defs)
        return {k: _inline_refs(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.pop("$defs", {}) or {}
    cleaned = _inline_refs(schema, defs)
    cleaned.pop("$defs", None)
    cleaned.pop("title", None)
    cleaned.setdefault("type", "object")
    cleaned.setdefault("properties", {})
    return cleaned


def _make_tool(spec, toolkit) -> Callable[..., Any]:
    """把一个 ToolSpec 包装成 registry 可调用的函数（参数仍是关键字）。"""

    def tool(**kwargs: Any) -> dict[str, Any]:
        request = spec.validate_arguments(kwargs)
        return getattr(toolkit, spec.method_name)(request)

    tool.__name__ = spec.name
    tool.__doc__ = spec.description
    tool.parameters = _clean_schema(spec.llm_definition()["function"]["parameters"])
    return tool


_EXTERNAL = _load_external()
_TOOLKIT = _EXTERNAL.create_toolkit(
    settings.POSTGIS_TOOLSET, database_url=settings.DATABASE_URL
)
_SPECS: dict[str, Any] = dict(_EXTERNAL.get_tool_registry(settings.POSTGIS_TOOLSET))

for _name, _spec in _SPECS.items():
    tool_registry.register(_name)(_make_tool(_spec, _TOOLKIT))


def get_toolkit():
    """返回共享的工具集实例（调试与基准脚本直接用）。"""
    return _TOOLKIT


def get_tool_spec(name: str):
    return _SPECS[name]


def tool_names() -> list[str]:
    return list(_SPECS)
