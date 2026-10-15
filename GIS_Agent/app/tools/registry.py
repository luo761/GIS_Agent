from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.tools.layers import ALLOWED_LAYERS
from app.tools.schemas import (
    BufferQueryInput,
    ClipAndMeasureInput,
    DescribeSpatialLayerInput,
    ListSpatialLayersInput,
    NearestFeaturesInput,
    SpatialFilterInput,
)


ToolInvocation = Literal["none", "kwargs", "request"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    method_name: str
    args_schema: type[BaseModel]
    description: str
    invocation: ToolInvocation

    def validate_arguments(self, arguments: dict[str, Any] | None) -> BaseModel:
        return self.args_schema(**(arguments or {}))

    def llm_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _tool_parameters_schema(self.args_schema),
            },
        }


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "list_spatial_layers": ToolSpec(
        name="list_spatial_layers",
        method_name="list_spatial_layers",
        args_schema=ListSpatialLayersInput,
        description="List whitelisted spatial layers available in the PostGIS database.",
        invocation="none",
    ),
    "describe_spatial_layer": ToolSpec(
        name="describe_spatial_layer",
        method_name="describe_spatial_layer",
        args_schema=DescribeSpatialLayerInput,
        description="Describe columns, spatial reference, and sample features for one layer.",
        invocation="kwargs",
    ),
    "spatial_filter": ToolSpec(
        name="spatial_filter",
        method_name="spatial_filter",
        args_schema=SpatialFilterInput,
        description="Find features in one layer by spatial relation to a target geometry.",
        invocation="request",
    ),
    "buffer_query": ToolSpec(
        name="buffer_query",
        method_name="buffer_query",
        args_schema=BufferQueryInput,
        description="Create a meter-based buffer around a target and find intersecting features.",
        invocation="request",
    ),
    "clip_and_measure": ToolSpec(
        name="clip_and_measure",
        method_name="clip_and_measure",
        args_schema=ClipAndMeasureInput,
        description="Clip line or polygon features by a target area and measure length or area.",
        invocation="request",
    ),
    "nearest_features": ToolSpec(
        name="nearest_features",
        method_name="nearest_features",
        args_schema=NearestFeaturesInput,
        description="Find nearest features in a layer from an input point.",
        invocation="request",
    ),
}


def get_tool_spec(name: str) -> ToolSpec:
    try:
        return TOOL_REGISTRY[name]
    except KeyError as exc:
        allowed = ", ".join(sorted(TOOL_REGISTRY))
        raise ValueError(f"Unsupported PostGIS tool: {name}. Allowed tools: {allowed}") from exc


def postgis_tool_definitions() -> list[dict[str, Any]]:
    return [spec.llm_definition() for spec in TOOL_REGISTRY.values()]


def postgis_tool_names() -> set[str]:
    return set(TOOL_REGISTRY)


def _tool_parameters_schema(args_schema: type[BaseModel]) -> dict[str, Any]:
    schema = args_schema.model_json_schema()
    schema.pop("title", None)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    _add_layer_enums(schema)
    return schema


def _add_layer_enums(schema: Any) -> None:
    if isinstance(schema, dict):
        if schema.get("title") in {
            "Layer Name",
            "Query Layer Name",
        } or schema.get("description", "").lower().endswith("layer."):
            schema.setdefault("enum", sorted(ALLOWED_LAYERS))
        for value in schema.values():
            _add_layer_enums(value)
    elif isinstance(schema, list):
        for item in schema:
            _add_layer_enums(item)
