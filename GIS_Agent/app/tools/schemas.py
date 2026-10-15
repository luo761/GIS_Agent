from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SpatialRelation = Literal["ST_Intersects", "ST_Within", "ST_Contains"]
GeometryType = Literal["Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"]


class ListSpatialLayersInput(BaseModel):
    pass


class DescribeSpatialLayerInput(BaseModel):
    layer_name: str
    sample_limit: int = Field(default=5, ge=1, le=20)


class TargetGeometry(BaseModel):
    """分析目标，可以来自已有图层对象，也可以来自 GeoJSON 几何。"""

    layer_name: str | None = None
    feature_id: int | None = None
    feature_code: str | None = None
    geometry: dict[str, Any] | None = None
    srid: int = Field(default=3857, ge=1)

    @model_validator(mode="after")
    def validate_source(self) -> "TargetGeometry":
        has_layer = self.layer_name is not None and (
            self.feature_id is not None or self.feature_code is not None
        )
        has_geometry = self.geometry is not None
        if has_layer == has_geometry:
            raise ValueError("目标必须且只能使用图层对象或 GeoJSON 几何之一")
        return self


class SpatialFilterInput(BaseModel):
    layer_name: str
    target: TargetGeometry
    relation: SpatialRelation
    max_results: int = Field(default=20, ge=1, le=100)


class BufferQueryInput(BaseModel):
    target: TargetGeometry
    distance_m: float = Field(gt=0, le=10000)
    query_layer_name: str
    max_results: int = Field(default=20, ge=1, le=100)


class ClipAndMeasureInput(BaseModel):
    layer_name: str
    clip_target: TargetGeometry
    measure: Literal["auto", "length", "area"] = "auto"


class NearestFeaturesInput(BaseModel):
    query_layer_name: str
    x: float
    y: float
    srid: int = Field(default=3857, ge=1)
    limit: int = Field(default=5, ge=1, le=50)
    max_distance_m: float | None = Field(default=None, gt=0, le=100000)
