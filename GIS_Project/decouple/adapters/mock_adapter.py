from __future__ import annotations

from math import hypot, pi
from typing import Any

from .base import Bounds, Feature, GISAdapter, Point


def _rect(minx: float, miny: float, maxx: float, maxy: float) -> Bounds:
    return (minx, miny, maxx, maxy)


class MockGISAdapter(GISAdapter):
    """In-memory municipal GIS sandbox used when real customer data is unavailable."""

    def __init__(self) -> None:
        self._layers = self._build_layers()

    def list_layers(self) -> list[str]:
        return list(self._layers.keys())

    def get_layer_schema(self, layer_name: str) -> dict[str, str]:
        layer = self.select_layer(layer_name)
        schema: dict[str, str] = {}
        for feature in layer:
            for key, value in feature.items():
                schema.setdefault(key, type(value).__name__)
        return schema

    def select_layer(self, layer_name: str) -> list[Feature]:
        if layer_name not in self._layers:
            raise ValueError(f"未知图层：{layer_name}")
        return [dict(feature) for feature in self._layers[layer_name]]

    def filter_features(self, layer: list[Feature], field: str, value: Any) -> list[Feature]:
        return [feature for feature in layer if feature.get(field) == value]

    def clip_lines_by_polygon(self, line_layer: list[Feature], polygon: Feature) -> list[Feature]:
        bounds = polygon["bounds"]
        clipped = []
        for feature in line_layer:
            length = self._clip_line_length_to_bounds(feature["geometry"], bounds)
            if length > 0:
                clipped_feature = dict(feature)
                clipped_feature["length"] = length
                clipped.append(clipped_feature)
        return clipped

    def length_statistics(self, line_layer: list[Feature]) -> dict[str, float | int]:
        total = 0.0
        for feature in line_layer:
            total += feature.get("length", self._line_length(feature["geometry"]))
        return {"count": len(line_layer), "total_length": total}

    def find_points_near_lines(
        self,
        point_layer: list[Feature],
        line_layer: list[Feature],
        distance: float,
    ) -> list[Feature]:
        matched = []
        for point in point_layer:
            point_xy = point["geometry"]
            if any(self._distance_point_to_line(point_xy, line["geometry"]) <= distance for line in line_layer):
                matched.append(point)
        return matched

    def find_line_conflicts(
        self,
        line_layer_a: list[Feature],
        line_layer_b: list[Feature],
        distance: float,
    ) -> list[Feature]:
        conflicts = []
        for line_a in line_layer_a:
            for line_b in line_layer_b:
                pair_distance = self._distance_line_to_line(line_a["geometry"], line_b["geometry"])
                if pair_distance <= distance:
                    conflicts.append(
                        {
                            "geometry_type": "conflict",
                            "pipe_a": line_a.get("pipe_id", ""),
                            "pipe_b": line_b.get("pipe_id", ""),
                            "distance": pair_distance,
                            "area": pi * distance * distance,
                        }
                    )
        return conflicts

    def buffer_points(self, point_layer: list[Feature], radius: float) -> list[Feature]:
        buffered = []
        for feature in point_layer:
            buffered_feature = dict(feature)
            buffered_feature["geometry_type"] = "buffer"
            buffered_feature["bounds"] = self._buffer_bounds(feature, radius)
            buffered_feature["area"] = pi * radius * radius
            buffered.append(buffered_feature)
        return buffered

    def intersect_areas(self, layer: list[Feature], polygon: Feature) -> list[Feature]:
        intersected = []
        for feature in layer:
            intersection = self._bounds_intersection(feature["bounds"], polygon["bounds"])
            if intersection:
                result = dict(feature)
                result["bounds"] = intersection
                result["area"] = min(feature.get("area", self._bounds_area(intersection)), self._bounds_area(intersection))
                intersected.append(result)
        return intersected

    def area_statistics(self, area_layer: list[Feature]) -> dict[str, float | int]:
        total = sum(feature.get("area", self._bounds_area(feature["bounds"])) for feature in area_layer)
        return {"count": len(area_layer), "total_area": total}

    def _build_layers(self) -> dict[str, list[Feature]]:
        return {
            "areas": [
                {"name": "A区", "geometry_type": "polygon", "bounds": _rect(0, 0, 1000, 800)},
                {"name": "B区", "geometry_type": "polygon", "bounds": _rect(1000, 0, 2000, 800)},
                {"name": "C区", "geometry_type": "polygon", "bounds": _rect(0, 800, 1000, 1600)},
            ],
            "gas_pipes": [
                {
                    "pipe_id": "G001",
                    "pressure": "高压",
                    "material": "钢管",
                    "risk_level": "高",
                    "geometry_type": "line",
                    "geometry": [(100, 100), (900, 100)],
                },
                {
                    "pipe_id": "G002",
                    "pressure": "中压",
                    "material": "PE",
                    "risk_level": "中",
                    "geometry_type": "line",
                    "geometry": [(200, 500), (1300, 500)],
                },
                {
                    "pipe_id": "G003",
                    "pressure": "低压",
                    "material": "钢管",
                    "risk_level": "低",
                    "geometry_type": "line",
                    "geometry": [(1200, 200), (1800, 700)],
                },
            ],
            "water_pipes": [
                {
                    "pipe_id": "W001",
                    "pipe_type": "供水",
                    "diameter": 600,
                    "risk_level": "中",
                    "geometry_type": "line",
                    "geometry": [(500, -100), (500, 900)],
                },
                {
                    "pipe_id": "W002",
                    "pipe_type": "排水",
                    "diameter": 800,
                    "risk_level": "高",
                    "geometry_type": "line",
                    "geometry": [(1100, 100), (1700, 700)],
                },
            ],
            "hazards": [
                {
                    "hazard_id": "H001",
                    "domain": "燃气",
                    "hazard_type": "泄漏",
                    "level": "高",
                    "geometry_type": "point",
                    "geometry": (520, 120),
                },
                {
                    "hazard_id": "H002",
                    "domain": "燃气",
                    "hazard_type": "腐蚀",
                    "level": "中",
                    "geometry_type": "point",
                    "geometry": (300, 530),
                },
                {
                    "hazard_id": "H003",
                    "domain": "水务",
                    "hazard_type": "破损",
                    "level": "高",
                    "geometry_type": "point",
                    "geometry": (1150, 530),
                },
                {
                    "hazard_id": "H004",
                    "domain": "水务",
                    "hazard_type": "淤积",
                    "level": "低",
                    "geometry_type": "point",
                    "geometry": (1600, 650),
                },
            ],
            "facilities": [
                {"facility_id": "F001", "domain": "燃气", "facility_type": "阀门", "geometry_type": "point", "geometry": (250, 250)},
                {"facility_id": "F002", "domain": "燃气", "facility_type": "调压站", "geometry_type": "point", "geometry": (800, 400)},
                {"facility_id": "F003", "domain": "水务", "facility_type": "泵站", "geometry_type": "point", "geometry": (1300, 300)},
            ],
        }

    @staticmethod
    def _line_length(line: list[Point]) -> float:
        return sum(hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(line, line[1:]))

    @staticmethod
    def _line_bounds(line: list[Point]) -> Bounds:
        xs = [p[0] for p in line]
        ys = [p[1] for p in line]
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _bounds_intersect(a: Bounds, b: Bounds) -> bool:
        return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])

    def _bounds_intersection(self, a: Bounds, b: Bounds) -> Bounds | None:
        if not self._bounds_intersect(a, b):
            return None
        return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))

    @staticmethod
    def _bounds_area(bounds: Bounds) -> float:
        return max(0.0, bounds[2] - bounds[0]) * max(0.0, bounds[3] - bounds[1])

    def _buffer_bounds(self, feature: Feature, distance: float) -> Bounds:
        if feature["geometry_type"] == "point":
            x, y = feature["geometry"]
            return (x - distance, y - distance, x + distance, y + distance)
        if feature["geometry_type"] == "line":
            minx, miny, maxx, maxy = self._line_bounds(feature["geometry"])
            return (minx - distance, miny - distance, maxx + distance, maxy + distance)
        if feature["geometry_type"] == "polygon":
            minx, miny, maxx, maxy = feature["bounds"]
            return (minx - distance, miny - distance, maxx + distance, maxy + distance)
        raise ValueError(f"不支持的几何类型：{feature['geometry_type']}")

    @staticmethod
    def _clip_segment_to_bounds(start: Point, end: Point, bounds: Bounds) -> tuple[Point, Point] | None:
        x1, y1 = start
        x2, y2 = end
        minx, miny, maxx, maxy = bounds
        dx = x2 - x1
        dy = y2 - y1
        p = [-dx, dx, -dy, dy]
        q = [x1 - minx, maxx - x1, y1 - miny, maxy - y1]
        u1 = 0.0
        u2 = 1.0

        for p_value, q_value in zip(p, q):
            if p_value == 0:
                if q_value < 0:
                    return None
                continue
            ratio = q_value / p_value
            if p_value < 0:
                u1 = max(u1, ratio)
            else:
                u2 = min(u2, ratio)
            if u1 > u2:
                return None

        return ((x1 + u1 * dx, y1 + u1 * dy), (x1 + u2 * dx, y1 + u2 * dy))

    def _clip_line_length_to_bounds(self, line: list[Point], bounds: Bounds) -> float:
        total = 0.0
        for start, end in zip(line, line[1:]):
            clipped = self._clip_segment_to_bounds(start, end, bounds)
            if clipped:
                total += hypot(clipped[1][0] - clipped[0][0], clipped[1][1] - clipped[0][1])
        return total

    @staticmethod
    def _distance_point_to_segment(point: Point, start: Point, end: Point) -> float:
        px, py = point
        x1, y1 = start
        x2, y2 = end
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return hypot(px - x1, py - y1)
        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        nearest = (x1 + t * dx, y1 + t * dy)
        return hypot(px - nearest[0], py - nearest[1])

    def _distance_point_to_line(self, point: Point, line: list[Point]) -> float:
        return min(self._distance_point_to_segment(point, a, b) for a, b in zip(line, line[1:]))

    @staticmethod
    def _orientation(a: Point, b: Point, c: Point) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def _segments_intersect(self, a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
        o1 = self._orientation(a1, a2, b1)
        o2 = self._orientation(a1, a2, b2)
        o3 = self._orientation(b1, b2, a1)
        o4 = self._orientation(b1, b2, a2)
        return o1 * o2 <= 0 and o3 * o4 <= 0

    def _distance_segment_to_segment(self, a1: Point, a2: Point, b1: Point, b2: Point) -> float:
        if self._segments_intersect(a1, a2, b1, b2):
            return 0.0
        return min(
            self._distance_point_to_segment(a1, b1, b2),
            self._distance_point_to_segment(a2, b1, b2),
            self._distance_point_to_segment(b1, a1, a2),
            self._distance_point_to_segment(b2, a1, a2),
        )

    def _distance_line_to_line(self, line_a: list[Point], line_b: list[Point]) -> float:
        return min(
            self._distance_segment_to_segment(a1, a2, b1, b2)
            for a1, a2 in zip(line_a, line_a[1:])
            for b1, b2 in zip(line_b, line_b[1:])
        )
