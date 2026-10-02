from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Domain = Literal["燃气", "水务", "电务", "环卫", "自然资源"]
#定义用户的业务意图
Intent = Literal[
    "pipe_length_statistics",    #管线长度统计
    "hazards_near_pipes",        #管线周边隐患查询
    "buffer_analysis",           #缓冲区分析
    "overlay_analysis",          #图层叠加分析
    "facility_coverage",         #设施覆盖范围分析
    "line_conflict_detection",   #管线冲突检测
    "spatiotemporal_filter",     #时空条件筛选
    "unknown",                   #未识别
]
#定义底层可执行的空间算子
Operation = Literal[
    "select_layer",
    "filter",
    "clip_by_area",
    "buffer",
    "intersect",
    "distance_query",
    "length_sum",
    "area_sum",
    "count",
]


class SpatialFilter(BaseModel):
    field: str
    op: Literal["=", "!=", ">", ">=", "<", "<=", "in", "contains"] = "="
    value: str | int | float | list[str] | list[int] | list[float]


class TimeRange(BaseModel):
    start: str | None = Field(default=None, description="ISO date/time lower bound.")
    end: str | None = Field(default=None, description="ISO date/time upper bound.")


class GisTask(BaseModel):
    """Stable intermediate task parsed from a natural-language GIS question."""

    question: str
    domains: list[Domain] = Field(default_factory=list)
    intent: Intent = "unknown"
    area: str | None = None
    layers: list[str] = Field(default_factory=list)
    filters: list[SpatialFilter] = Field(default_factory=list)
    distance: float | None = Field(default=None, description="Distance threshold in meters.")
    time_range: TimeRange | None = None
    operations: list[Operation] = Field(default_factory=list)
    output_format: Literal["summary", "table", "geojson", "report"] = "summary"


class PlanStep(BaseModel):
    """Executable step derived from GisTask."""

    step_id: str
    operation: Operation
    inputs: dict[str, str | int | float | list[str]]
    depends_on: list[str] = Field(default_factory=list)
    output_key: str


class ExecutionPlan(BaseModel):
    task: GisTask
    steps: list[PlanStep]
