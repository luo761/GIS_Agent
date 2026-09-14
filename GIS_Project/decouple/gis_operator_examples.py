"""
Beginner-friendly GIS operator examples for the GIS Agent project.

This module keeps business tasks such as pipe_length_in_area, but decomposes
them into small pure-Python GIS operators. The operators use in-memory mock
layers and simple geometry math, so they do not depend on geopandas/shapely.
"""

from __future__ import annotations

from math import hypot, pi
from typing_extensions import Any, TypedDict

try:
    from langchain.tools import tool
except ImportError:
    class _LocalTool:
        def __init__(self, fn):
            self.fn = fn
            self.name = fn.__name__
            self.description = fn.__doc__ or ""

        def __call__(self, *args, **kwargs):
            return self.fn(*args, **kwargs)

        def invoke(self, args):
            return self.fn(**args)

    def tool(fn):
        return _LocalTool(fn)


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
    pipe_type: str
    hazard_id: str
    facility_id: str
    domain: str
    level: str
    facility_type: str
    name: str


def _rect(minx: float, miny: float, maxx: float, maxy: float) -> Bounds:
    return (minx, miny, maxx, maxy)


#计算线长度
def _line_length(line: list[Point]) -> float:
    return sum(hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(line, line[1:]))


#判断两个Bounds是否有交集
def _bounds_intersect(a: Bounds, b: Bounds) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])

#计算两个Bounds的交集
def _bounds_intersection(a: Bounds, b: Bounds) -> Bounds | None:
    if not _bounds_intersect(a, b):
        return None
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))

#计算Bounds的面积
def _bounds_area(bounds: Bounds) -> float:
    return max(0.0, bounds[2] - bounds[0]) * max(0.0, bounds[3] - bounds[1])

#判断点是否在Bounds内
def _point_in_bounds(point: Point, bounds: Bounds) -> bool:
    x, y = point
    return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]

#计算线的外接矩形Bounds
def _line_bounds(line: list[Point]) -> Bounds:
    xs = [p[0] for p in line]
    ys = [p[1] for p in line]
    return (min(xs), min(ys), max(xs), max(ys))

#计算缓冲区的Bounds
def _buffer_bounds(feature: Feature, distance: float) -> Bounds:
    if feature["geometry_type"] == "point":
        x, y = feature["geometry"]
        return (x - distance, y - distance, x + distance, y + distance)
    if feature["geometry_type"] == "line":
        minx, miny, maxx, maxy = _line_bounds(feature["geometry"])
        return (minx - distance, miny - distance, maxx + distance, maxy + distance)
    if feature["geometry_type"] == "polygon":
        minx, miny, maxx, maxy = feature["bounds"]
        return (minx - distance, miny - distance, maxx + distance, maxy + distance)
    raise ValueError(f"Unsupported geometry type: {feature['geometry_type']}")

#计算点到线段的距离
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

#计算点到折线的最短距离
def _distance_point_to_line(point: Point, line: list[Point]) -> float:
    return min(_distance_point_to_segment(point, a, b) for a, b in zip(line, line[1:]))

#计算三个点的方向关系
def _orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

#判断线段是否相交
def _segments_intersect(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    o1 = _orientation(a1, a2, b1)
    o2 = _orientation(a1, a2, b2)
    o3 = _orientation(b1, b2, a1)
    o4 = _orientation(b1, b2, a2)
    return o1 * o2 <= 0 and o3 * o4 <= 0

#简化版判断线段是否相交
def _distance_segment_to_segment(a1: Point, a2: Point, b1: Point, b2: Point) -> float:
    if _segments_intersect(a1, a2, b1, b2):
        return 0.0
    return min(
        _distance_point_to_segment(a1, b1, b2),
        _distance_point_to_segment(a2, b1, b2),
        _distance_point_to_segment(b1, a1, a2),
        _distance_point_to_segment(b2, a1, a2),
    )

#计算线段到线段的距离
def _distance_line_to_line(line_a: list[Point], line_b: list[Point]) -> float:
    return min(
        _distance_segment_to_segment(a1, a2, b1, b2)
        for a1, a2 in zip(line_a, line_a[1:])
        for b1, b2 in zip(line_b, line_b[1:])
    )

#将一条线段裁剪到矩形内
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

    for pi_value, qi_value in zip(p, q):
        if pi_value == 0:
            if qi_value < 0:
                return None
            continue
        ratio = qi_value / pi_value
        if pi_value < 0:
            u1 = max(u1, ratio)
        else:
            u2 = min(u2, ratio)
        if u1 > u2:
            return None

    return ((x1 + u1 * dx, y1 + u1 * dy), (x1 + u2 * dx, y1 + u2 * dy))

#将一条折线的每一段裁剪到矩形里，然后计算裁剪后的总长度
def _clip_line_length_to_bounds(line: list[Point], bounds: Bounds) -> float:
    total = 0.0
    for start, end in zip(line, line[1:]):
        clipped = _clip_segment_to_bounds(start, end, bounds)
        if clipped:
            total += hypot(clipped[1][0] - clipped[0][0], clipped[1][1] - clipped[0][1])
    return total


def _mock_layers() -> dict[str, list[Feature]]:
    return {
        "areas": [
            {"name": "A区", "geometry_type": "polygon", "bounds": _rect(0, 0, 1000, 800)},
            {"name": "B区", "geometry_type": "polygon", "bounds": _rect(1000, 0, 2000, 800)},
        ],
        "gas_pipes": [
            {"pipe_id": "G001", "pressure": "high", "geometry_type": "line", "geometry": [(100, 100), (900, 100)]},
            {"pipe_id": "G002", "pressure": "middle", "geometry_type": "line", "geometry": [(200, 500), (1300, 500)]},
            {"pipe_id": "G003", "pressure": "low", "geometry_type": "line", "geometry": [(1200, 200), (1800, 700)]},
        ],
        "water_pipes": [
            {"pipe_id": "W001", "pipe_type": "supply", "geometry_type": "line", "geometry": [(500, -100), (500, 900)]},
            {"pipe_id": "W002", "pipe_type": "drainage", "geometry_type": "line", "geometry": [(1100, 100), (1700, 700)]},
        ],
        "hazards": [
            {"hazard_id": "H001", "domain": "燃气", "level": "high", "geometry_type": "point", "geometry": (520, 120)},
            {"hazard_id": "H002", "domain": "燃气", "level": "middle", "geometry_type": "point", "geometry": (300, 530)},
            {"hazard_id": "H003", "domain": "水务", "level": "high", "geometry_type": "point", "geometry": (1150, 530)},
            {"hazard_id": "H004", "domain": "水务", "level": "low", "geometry_type": "point", "geometry": (1600, 650)},
        ],
        "facilities": [
            {"facility_id": "F001", "domain": "燃气", "facility_type": "阀门", "geometry_type": "point", "geometry": (250, 250)},
            {"facility_id": "F002", "domain": "燃气", "facility_type": "调压站", "geometry_type": "point", "geometry": (800, 400)},
            {"facility_id": "F003", "domain": "水务", "facility_type": "泵站", "geometry_type": "point", "geometry": (1300, 300)},
        ],
    }


def select_layer(layer_name: str) -> list[Feature]:
    """Atomic operator: load one mock layer by name."""
    layers = _mock_layers()
    if layer_name not in layers:
        raise ValueError(f"Unknown layer: {layer_name}")
    return layers[layer_name]


def filter_features(layer: list[Feature], field: str, value: Any) -> list[Feature]:
    """Atomic operator: attribute filter."""
    return [feature for feature in layer if feature.get(field) == value]


#线图层按矩形面裁剪。对每条线算落在 polygon bounds 内的长度。如果长度大于 0，就复制原 feature，并添加length长度字段
def clip_lines_by_polygon(line_layer: list[Feature], polygon: Feature) -> list[Feature]:
    """Atomic operator: clip line features by a rectangular polygon."""
    bounds = polygon["bounds"]
    clipped = []
    for feature in line_layer:
        length = _clip_line_length_to_bounds(feature["geometry"], bounds)
        if length > 0:
            clipped_feature = dict(feature)
            clipped_feature["length"] = length
            clipped.append(clipped_feature)
    return clipped

#统计线图层数量和总长度。优先使用已经裁剪出的 length 字段；如果没有，就现场算整条线长度
def length_statistics(line_layer: list[Feature]) -> dict[str, float | int]:
    """Atomic operator: calculate total line length."""
    total = 0.0
    for feature in line_layer:
        total += feature.get("length", _line_length(feature["geometry"]))
    return {"count": len(line_layer), "total_length": total}

#查找距离任意线不超过阈值的点
def find_points_near_lines(point_layer: list[Feature], line_layer: list[Feature], distance: float) -> list[Feature]:
    """Atomic operator: find points whose distance to any line is within a threshold."""
    matched = []
    for point in point_layer:
        point_xy = point["geometry"]
        if any(_distance_point_to_line(point_xy, line["geometry"]) <= distance for line in line_layer):
            matched.append(point)
    return matched

#查找两组线之间的近距离冲突。双层循环比较每条 A 线和每条 B 线，如果距离小于阈值，就生成一个冲突要素。
def find_line_conflicts(line_layer_a: list[Feature], line_layer_b: list[Feature], distance: float) -> list[Feature]:
    """Atomic operator: find line pairs whose distance is within a threshold."""
    conflicts = []
    for line_a in line_layer_a:
        for line_b in line_layer_b:
            pair_distance = _distance_line_to_line(line_a["geometry"], line_b["geometry"])
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

#对点图层做服务半径缓冲
def buffer_points(point_layer: list[Feature], radius: float) -> list[Feature]:
    """Atomic operator: represent point buffers by bounding boxes and circle areas."""
    buffered = []
    for feature in point_layer:
        buffered_feature = dict(feature)
        buffered_feature["geometry_type"] = "buffer"
        buffered_feature["bounds"] = _buffer_bounds(feature, radius)
        buffered_feature["area"] = pi * radius * radius
        buffered.append(buffered_feature)
    return buffered

#把一组面状范围和目标区域求交。
def intersect_areas(layer: list[Feature], polygon: Feature) -> list[Feature]:
    """Atomic operator: intersect rectangular areas with one rectangular polygon."""
    intersected = []
    for feature in layer:
        intersection = _bounds_intersection(feature["bounds"], polygon["bounds"])
        if intersection:
            result = dict(feature)
            result["bounds"] = intersection
            result["area"] = min(feature.get("area", _bounds_area(intersection)), _bounds_area(intersection))
            intersected.append(result)
    return intersected

#统计面数量和总面积（可能有区域重叠）
def area_statistics(area_layer: list[Feature]) -> dict[str, float | int]:
    """Atomic operator: calculate total area without exact overlap removal."""
    total = sum(feature.get("area", _bounds_area(feature["bounds"])) for feature in area_layer)
    return {"count": len(area_layer), "total_area": total}


@tool
def pipe_length_in_area(area_name: str = "A区", domain: str = "燃气") -> str:
    """
    Business task: calculate total pipe length inside one administrative area.

    Plan: select area -> select pipe layer -> clip/intersect -> length statistics.
    """
    areas = select_layer("areas")
    target_areas = filter_features(areas, "name", area_name)
    if not target_areas:
        return f"没有找到区域：{area_name}"

    pipe_layer_name = "gas_pipes" if domain == "燃气" else "water_pipes"
    pipes = select_layer(pipe_layer_name)
    clipped = clip_lines_by_polygon(pipes, target_areas[0])
    stats = length_statistics(clipped)

    return (
        f"问题：统计{area_name}内{domain}管线总长度。\n"
        f"规划：选择区域 -> 选择管线图层 -> 空间裁剪/相交 -> 长度统计。\n"
        f"结果：命中管线{stats['count']}段，总长度约{stats['total_length']:.2f}米。"
    )


@tool
def hazards_near_pipes(domain: str = "燃气", buffer_distance: float = 100) -> str:
    """
    Business task: find hazards within a distance of pipes.

    Plan: select pipe layer -> select hazards -> filter hazards -> distance query.
    """
    pipe_layer_name = "gas_pipes" if domain == "燃气" else "water_pipes"
    pipes = select_layer(pipe_layer_name)
    hazards = filter_features(select_layer("hazards"), "domain", domain)
    matched = find_points_near_lines(hazards, pipes, buffer_distance)

    ids = ", ".join(item["hazard_id"] for item in matched) if matched else "无"
    return (
        f"问题：查询距离{domain}管线{buffer_distance}米内的隐患点。\n"
        f"规划：选择管线图层 -> 选择隐患点图层 -> 属性筛选 -> 距离阈值查询。\n"
        f"结果：发现隐患点{len(matched)}个，编号：{ids}。"
    )


@tool
def gas_water_cross_conflict(buffer_distance: float = 20) -> str:
    """
    Business task: detect possible conflict areas between gas and water pipes.

    Plan: select gas pipes -> select water pipes -> line distance conflict detection.
    """
    gas = select_layer("gas_pipes")
    water = select_layer("water_pipes")
    conflicts = find_line_conflicts(gas, water, buffer_distance * 2)
    total_area = sum(item["area"] for item in conflicts)
    pairs = ", ".join(f"{item['pipe_a']}-{item['pipe_b']}" for item in conflicts) if conflicts else "无"

    return (
        "问题：识别燃气管线与水务管线是否存在交叉或近距离冲突。\n"
        "规划：选择燃气管线 -> 选择水务管线 -> 线段距离/相交检测 -> 冲突统计。\n"
        f"结果：发现疑似冲突区域{len(conflicts)}处，涉及管线对：{pairs}，估算影响面积约{total_area:.2f}平方米。"
    )


@tool
def facility_coverage_in_area(
    facility_domain: str = "燃气",
    area_name: str = "A区",
    radius: float = 300,
) -> str:
    """
    Business task: calculate facility service coverage ratio in one area.

    Plan: select area -> select facilities -> filter facilities -> buffer -> intersect -> area ratio.
    """
    areas = select_layer("areas")
    target_areas = filter_features(areas, "name", area_name)
    if not target_areas:
        return f"没有找到区域：{area_name}"

    facilities = filter_features(select_layer("facilities"), "domain", facility_domain)
    service_areas = buffer_points(facilities, radius)
    covered_parts = intersect_areas(service_areas, target_areas[0])
    stats = area_statistics(covered_parts)
    area_total = _bounds_area(target_areas[0]["bounds"])
    ratio = stats["total_area"] / area_total * 100 if area_total else 0

    return (
        f"问题：统计{area_name}内{facility_domain}设施{radius}米服务覆盖范围。\n"
        f"规划：选择区域 -> 选择设施图层 -> 属性筛选 -> 服务半径缓冲 -> 区域相交 -> 面积占比统计。\n"
        f"结果：覆盖面积约{stats['total_area']:.2f}平方米，覆盖率约{ratio:.2f}%。"
    )


gis_operator_tools = [
    select_layer,
    filter_features,
    clip_lines_by_polygon,
    length_statistics,
    find_points_near_lines,
    find_line_conflicts,
    buffer_points,
    intersect_areas,
    area_statistics,
]

gis_business_tools = [
    pipe_length_in_area,
    hazards_near_pipes,
    gas_water_cross_conflict,
    facility_coverage_in_area,
]

gis_operator_example_tools = gis_business_tools

def main():
    """
    问题：统计A区内燃气管线总长度。
    规划：选择区域 -> 选择管线图层 -> 空间裁剪 / 相交 -> 长度统计。
    结果：命中管线2段，总长度约1600.00米。

    问题：查询距离燃气管线100米内的隐患点。
    规划：选择管线图层 -> 选择隐患点图层 -> 属性筛选 -> 距离阈值查询。
    结果：发现隐患点2个，编号：H001, H002。

    问题：识别燃气管线与水务管线是否存在交叉或近距离冲突。
    规划：选择燃气管线 -> 选择水务管线 -> 线段距离/相交检测 -> 冲突统计。
    结果：发现疑似冲突区域3处，涉及管线对：G001-W001, G002-W001, G003-W002，估算影响面积约15079.64平方米。

    问题：统计A区内燃气设施300米服务覆盖范围。
    规划：选择区域 -> 选择设施图层 -> 属性筛选 -> 服务半径缓冲 -> 区域相交 -> 面积占比统计。
    结果：覆盖面积约565486.68平方米，覆盖率约70.69%。
    """


    print("===== 1. 测试 pipe_length_in_area =====")
    result1 = pipe_length_in_area.invoke({
        "area_name": "A区",
        "domain": "燃气"
    })
    print(result1)

    print("\n===== 2. 测试 hazards_near_pipes =====")
    result2 = hazards_near_pipes.invoke({
        "domain": "燃气",
        "buffer_distance": 100
    })
    print(result2)

    print("\n===== 3. 测试 gas_water_cross_conflict =====")
    result3 = gas_water_cross_conflict.invoke({
        "buffer_distance": 20
    })
    print(result3)

    print("\n===== 4. 测试 facility_coverage_in_area =====")
    result4 = facility_coverage_in_area.invoke({
        "facility_domain": "燃气",
        "area_name": "A区",
        "radius": 300
    })
    print(result4)


if __name__ == "__main__":
    main()
