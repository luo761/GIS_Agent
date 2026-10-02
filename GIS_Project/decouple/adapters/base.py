from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


Point = tuple[float, float]
Bounds = tuple[float, float, float, float]


class Feature(TypedDict, total=False):
    geometry_type: str
    geometry: Any
    bounds: Bounds
    area: float
    length: float
    pipe_id: str
    pressure: str
    material: str
    pipe_type: str
    diameter: float
    hazard_id: str
    hazard_type: str
    facility_id: str
    domain: str
    level: str
    risk_level: str
    facility_type: str
    name: str


class GISAdapter(ABC):
    """Common interface for mock, PostGIS, and platform-specific GIS backends."""

    @abstractmethod
    def list_layers(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def get_layer_schema(self, layer_name: str) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def select_layer(self, layer_name: str) -> list[Feature]:
        raise NotImplementedError

    @abstractmethod
    def filter_features(self, layer: list[Feature], field: str, value: Any) -> list[Feature]:
        raise NotImplementedError

    @abstractmethod
    def clip_lines_by_polygon(self, line_layer: list[Feature], polygon: Feature) -> list[Feature]:
        raise NotImplementedError

    @abstractmethod
    def length_statistics(self, line_layer: list[Feature]) -> dict[str, float | int]:
        raise NotImplementedError

    @abstractmethod
    def find_points_near_lines(
        self,
        point_layer: list[Feature],
        line_layer: list[Feature],
        distance: float,
    ) -> list[Feature]:
        raise NotImplementedError

    @abstractmethod
    def find_line_conflicts(
        self,
        line_layer_a: list[Feature],
        line_layer_b: list[Feature],
        distance: float,
    ) -> list[Feature]:
        raise NotImplementedError

    @abstractmethod
    def buffer_points(self, point_layer: list[Feature], radius: float) -> list[Feature]:
        raise NotImplementedError

    @abstractmethod
    def intersect_areas(self, layer: list[Feature], polygon: Feature) -> list[Feature]:
        raise NotImplementedError

    @abstractmethod
    def area_statistics(self, area_layer: list[Feature]) -> dict[str, float | int]:
        raise NotImplementedError
