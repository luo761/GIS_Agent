"""
GIS Agent 工具集。

这个文件分为三层：
1. 模拟 GIS 数据：暂时不用连接真实燃气/水务平台，先用少量假数据学习流程。
2. 底层 GIS 算子：选择图层、属性筛选、空间裁剪、距离查询、冲突检测、缓冲区、面积统计。
3. Agent 业务工具：给 LangGraph / LangChain 调用的 @tool 函数。

新手理解方式：
- “算子”就是一个很小的 GIS 能力，例如“算长度”“查距离”“做缓冲区”。
- “业务工具”就是把多个算子串起来，解决一个完整业务问题。
"""

from __future__ import annotations

import os
from math import hypot, pi
from typing_extensions import Any, TypedDict

from langchain.tools import tool


Point = tuple[float, float]
Bounds = tuple[float, float, float, float]


class Feature(TypedDict, total=False):
    """简化版 GIS 要素结构。

    真实 GIS 数据通常来自 Shapefile、GeoJSON、PostGIS、ArcGIS 服务等。
    为了便于学习，这里用 Python 字典模拟点、线、面要素。
    """

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


# =========================
# 1. 模拟 GIS 数据
# =========================


def _rect(minx: float, miny: float, maxx: float, maxy: float) -> Bounds:
    """创建矩形范围，格式为 (最小X, 最小Y, 最大X, 最大Y)。"""
    return (minx, miny, maxx, maxy)


def _mock_layers() -> dict[str, list[Feature]]:
    """构造一批模拟图层。

    坐标单位按“米”理解。后续接真实 GIS 平台时，可以把这个函数替换成数据库
    或接口读取逻辑。
    """

    return {
        "areas": [
            {"name": "A区", "geometry_type": "polygon", "bounds": _rect(0, 0, 1000, 800)},
            {"name": "B区", "geometry_type": "polygon", "bounds": _rect(1000, 0, 2000, 800)},
        ],
        "gas_pipes": [
            {
                "pipe_id": "G001",
                "pressure": "高压",
                "geometry_type": "line",
                "geometry": [(100, 100), (900, 100)],
            },
            {
                "pipe_id": "G002",
                "pressure": "中压",
                "geometry_type": "line",
                "geometry": [(200, 500), (1300, 500)],
            },
            {
                "pipe_id": "G003",
                "pressure": "低压",
                "geometry_type": "line",
                "geometry": [(1200, 200), (1800, 700)],
            },
        ],
        "water_pipes": [
            {
                "pipe_id": "W001",
                "pipe_type": "供水",
                "geometry_type": "line",
                "geometry": [(500, -100), (500, 900)],
            },
            {
                "pipe_id": "W002",
                "pipe_type": "排水",
                "geometry_type": "line",
                "geometry": [(1100, 100), (1700, 700)],
            },
        ],
        "hazards": [
            {"hazard_id": "H001", "domain": "燃气", "level": "高", "geometry_type": "point", "geometry": (520, 120)},
            {"hazard_id": "H002", "domain": "燃气", "level": "中", "geometry_type": "point", "geometry": (300, 530)},
            {"hazard_id": "H003", "domain": "水务", "level": "高", "geometry_type": "point", "geometry": (1150, 530)},
            {"hazard_id": "H004", "domain": "水务", "level": "低", "geometry_type": "point", "geometry": (1600, 650)},
        ],
        "facilities": [
            {"facility_id": "F001", "domain": "燃气", "facility_type": "阀门", "geometry_type": "point", "geometry": (250, 250)},
            {"facility_id": "F002", "domain": "燃气", "facility_type": "调压站", "geometry_type": "point", "geometry": (800, 400)},
            {"facility_id": "F003", "domain": "水务", "facility_type": "泵站", "geometry_type": "point", "geometry": (1300, 300)},
        ],
    }


# =========================
# 2. 底层 GIS 算子
# =========================


def select_layer(layer_name: str) -> list[Feature]:
    """图层选择算子。

    作用：
    根据图层名称读取对应 GIS 图层。

    参数：
    - layer_name: 图层名称，例如 areas、gas_pipes、water_pipes、hazards、facilities。

    返回：
    - 一个要素列表，每个要素是一个字典。
    """

    layers = _mock_layers()
    if layer_name not in layers:
        raise ValueError(f"未知图层：{layer_name}")
    return layers[layer_name]


def filter_features(layer: list[Feature], field: str, value: Any) -> list[Feature]:
    """属性筛选算子。

    作用：
    按字段值筛选图层要素。例如只筛选 domain="燃气" 的隐患点。
    """

    return [feature for feature in layer if feature.get(field) == value]


def _line_length(line: list[Point]) -> float:
    """计算折线长度。"""

    return sum(hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(line, line[1:]))


def _line_bounds(line: list[Point]) -> Bounds:
    """计算线要素的外接矩形。"""

    xs = [p[0] for p in line]
    ys = [p[1] for p in line]
    return (min(xs), min(ys), max(xs), max(ys))


def _bounds_intersect(a: Bounds, b: Bounds) -> bool:
    """判断两个矩形范围是否相交。"""

    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _bounds_intersection(a: Bounds, b: Bounds) -> Bounds | None:
    """计算两个矩形范围的相交部分。"""

    if not _bounds_intersect(a, b):
        return None
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _bounds_area(bounds: Bounds) -> float:
    """计算矩形范围面积。"""

    return max(0.0, bounds[2] - bounds[0]) * max(0.0, bounds[3] - bounds[1])


def _buffer_bounds(feature: Feature, distance: float) -> Bounds:
    """生成简化缓冲区范围。

    说明：
    真实 GIS 中，缓冲区通常是圆形或沿线扩展的面。
    这里为了降低学习难度，用外接矩形近似表达缓冲区。
    """

    if feature["geometry_type"] == "point":
        x, y = feature["geometry"]
        return (x - distance, y - distance, x + distance, y + distance)
    if feature["geometry_type"] == "line":
        minx, miny, maxx, maxy = _line_bounds(feature["geometry"])
        return (minx - distance, miny - distance, maxx + distance, maxy + distance)
    if feature["geometry_type"] == "polygon":
        minx, miny, maxx, maxy = feature["bounds"]
        return (minx - distance, miny - distance, maxx + distance, maxy + distance)
    raise ValueError(f"不支持的几何类型：{feature['geometry_type']}")


def _clip_segment_to_bounds(start: Point, end: Point, bounds: Bounds) -> tuple[Point, Point] | None:
    """把一条线段裁剪到矩形范围内。

    这是一个简化版线段裁剪算法。新手只需要知道：
    - 线段穿过区域，就保留区域里面的部分；
    - 线段完全在区域外，就返回 None。
    """

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


def _clip_line_length_to_bounds(line: list[Point], bounds: Bounds) -> float:
    """把折线裁剪到矩形范围内，并计算裁剪后的长度。"""

    total = 0.0
    for start, end in zip(line, line[1:]):
        clipped = _clip_segment_to_bounds(start, end, bounds)
        if clipped:
            total += hypot(clipped[1][0] - clipped[0][0], clipped[1][1] - clipped[0][1])
    return total


def clip_lines_by_polygon(line_layer: list[Feature], polygon: Feature) -> list[Feature]:
    """空间裁剪/相交算子。

    作用：
    用一个区域面裁剪线图层，得到落在区域内的线段长度。

    典型场景：
    统计 A区 内燃气管线、水务管线长度。
    """

    bounds = polygon["bounds"]
    clipped = []
    for feature in line_layer:
        length = _clip_line_length_to_bounds(feature["geometry"], bounds)
        if length > 0:
            clipped_feature = dict(feature)
            clipped_feature["length"] = length
            clipped.append(clipped_feature)
    return clipped


def length_statistics(line_layer: list[Feature]) -> dict[str, float | int]:
    """长度统计算子。

    作用：
    统计线图层的数量和总长度。
    """

    total = 0.0
    for feature in line_layer:
        total += feature.get("length", _line_length(feature["geometry"]))
    return {"count": len(line_layer), "total_length": total}


def _distance_point_to_segment(point: Point, start: Point, end: Point) -> float:
    """计算点到线段的最短距离。"""

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


def _distance_point_to_line(point: Point, line: list[Point]) -> float:
    """计算点到折线的最短距离。"""

    return min(_distance_point_to_segment(point, a, b) for a, b in zip(line, line[1:]))


def find_points_near_lines(point_layer: list[Feature], line_layer: list[Feature], distance: float) -> list[Feature]:
    """邻近查询算子。

    作用：
    查找距离任意线要素不超过指定距离的点要素。

    典型场景：
    查询燃气管线 100 米范围内有哪些隐患点。
    """

    matched = []
    for point in point_layer:
        point_xy = point["geometry"]
        if any(_distance_point_to_line(point_xy, line["geometry"]) <= distance for line in line_layer):
            matched.append(point)
    return matched


def _orientation(a: Point, b: Point, c: Point) -> float:
    """计算三个点的方向关系。"""

    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    """判断两条线段是否相交。"""

    o1 = _orientation(a1, a2, b1)
    o2 = _orientation(a1, a2, b2)
    o3 = _orientation(b1, b2, a1)
    o4 = _orientation(b1, b2, a2)
    return o1 * o2 <= 0 and o3 * o4 <= 0


def _distance_segment_to_segment(a1: Point, a2: Point, b1: Point, b2: Point) -> float:
    """计算两条线段之间的最短距离。"""

    if _segments_intersect(a1, a2, b1, b2):
        return 0.0
    return min(
        _distance_point_to_segment(a1, b1, b2),
        _distance_point_to_segment(a2, b1, b2),
        _distance_point_to_segment(b1, a1, a2),
        _distance_point_to_segment(b2, a1, a2),
    )


def _distance_line_to_line(line_a: list[Point], line_b: list[Point]) -> float:
    """计算两条折线之间的最短距离。"""

    return min(
        _distance_segment_to_segment(a1, a2, b1, b2)
        for a1, a2 in zip(line_a, line_a[1:])
        for b1, b2 in zip(line_b, line_b[1:])
    )


def find_line_conflicts(line_layer_a: list[Feature], line_layer_b: list[Feature], distance: float) -> list[Feature]:
    """管线冲突检测算子。

    作用：
    查找两组线要素之间距离小于阈值的管线对。

    典型场景：
    燃气管线和水务管线距离过近，可能存在施工或运维冲突。
    """

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


def buffer_points(point_layer: list[Feature], radius: float) -> list[Feature]:
    """点缓冲区算子。

    作用：
    给点要素生成服务半径范围。

    典型场景：
    统计阀门、调压站、泵站等设施的服务覆盖范围。
    """

    buffered = []
    for feature in point_layer:
        buffered_feature = dict(feature)
        buffered_feature["geometry_type"] = "buffer"
        buffered_feature["bounds"] = _buffer_bounds(feature, radius)
        buffered_feature["area"] = pi * radius * radius
        buffered.append(buffered_feature)
    return buffered


def intersect_areas(layer: list[Feature], polygon: Feature) -> list[Feature]:
    """面叠加/相交算子。

    作用：
    计算一组面范围与目标区域的相交部分。
    """

    intersected = []
    for feature in layer:
        intersection = _bounds_intersection(feature["bounds"], polygon["bounds"])
        if intersection:
            result = dict(feature)
            result["bounds"] = intersection
            result["area"] = min(feature.get("area", _bounds_area(intersection)), _bounds_area(intersection))
            intersected.append(result)
    return intersected


def area_statistics(area_layer: list[Feature]) -> dict[str, float | int]:
    """面积统计算子。

    作用：
    统计面要素数量和总面积。

    注意：
    这是新手版简化实现，没有精确消除多个缓冲区之间的重叠面积。
    """

    total = sum(feature.get("area", _bounds_area(feature["bounds"])) for feature in area_layer)
    return {"count": len(area_layer), "total_area": total}


# =========================
# 3. 给 Agent 调用的业务工具
# =========================


@tool
def buffer_analysis(domain: str, layer: str, buffer_distance: float) -> str:
    """
    GIS 缓冲区分析工具。

    适用问题：
    - “给燃气管线做 100 米缓冲区”
    - “查询水务隐患点周边 200 米影响范围”

    参数：
    - domain: 业务领域，例如“燃气”“水务”。
    - layer: 图层名称，例如“燃气管线”“水务隐患点”。
    - buffer_distance: 缓冲距离，单位米。

    返回：
    - 模拟的缓冲区分析结果。
    """

    return (
        "【缓冲区分析结果】\n"
        f"业务领域：{domain}\n"
        f"分析图层：{layer}\n"
        f"缓冲距离：{buffer_distance}米\n"
        "计算步骤：选择目标图层 -> 坐标统一 -> 生成缓冲区面 -> 输出影响范围。\n"
        "模拟结果：生成缓冲区面要素 2 个，缓冲区总面积约 0.36 平方公里。"
    )


@tool
def pipe_length_stat(domain: str, filter_condition: str = "") -> str:
    """
    管线长度统计工具。

    适用问题：
    - “统计燃气管线总长度”
    - “统计水务高风险管线长度”

    参数：
    - domain: 业务领域，例如“燃气”“水务”。
    - filter_condition: 筛选条件，例如“高压管线”“老旧管线”，可以为空。

    返回：
    - 模拟的管线长度统计结果。
    """

    if domain == "燃气":
        total = 128.72
    elif domain == "水务":
        total = 246.15
    else:
        total = 88.20

    return (
        "【管线长度统计结果】\n"
        f"业务领域：{domain}\n"
        f"筛选条件：{filter_condition or '无'}\n"
        "计算步骤：选择管线图层 -> 按条件筛选 -> 计算每段长度 -> 汇总总长度。\n"
        f"模拟结果：管线总长度约 {total:.2f} 公里。"
    )


@tool
def hazard_query(domain: str, hazard_type: str = "全部") -> str:
    """
    隐患查询工具。

    适用问题：
    - “查询燃气隐患分布”
    - “筛选水务破损隐患点”

    参数：
    - domain: 业务领域，例如“燃气”“水务”。
    - hazard_type: 隐患类型，例如“泄漏”“腐蚀”“破损”“全部”。

    返回：
    - 模拟的隐患点查询结果。
    """

    mock_data = {
        "燃气": ["阀门腐蚀隐患 3 处", "管线泄漏风险点 2 处"],
        "水务": ["管网破损点 5 处", "排水淤积隐患 4 处"],
    }
    items = mock_data.get(domain, ["暂无匹配隐患"])

    return (
        "【隐患查询结果】\n"
        f"业务领域：{domain}\n"
        f"隐患类型：{hazard_type}\n"
        "计算步骤：选择隐患点图层 -> 按业务领域和隐患类型筛选 -> 输出空间分布。\n"
        f"模拟结果：{items}"
    )


@tool
def overlay_analysis(domain: str, layer_a: str, layer_b: str) -> str:
    """
    图层叠加分析工具。

    适用问题：
    - “分析燃气管线和道路施工范围是否重叠”
    - “检查两个图层是否存在空间冲突”

    参数：
    - domain: 业务领域。
    - layer_a: 图层 A 名称。
    - layer_b: 图层 B 名称。

    返回：
    - 模拟的图层叠加分析结果。
    """

    return (
        "【叠加分析结果】\n"
        f"业务领域：{domain}\n"
        f"图层A：{layer_a}\n"
        f"图层B：{layer_b}\n"
        "计算步骤：读取两个图层 -> 坐标统一 -> 空间相交/叠加 -> 输出重叠区域。\n"
        "模拟结果：检测到图层交叉冲突位置 3 处。"
    )


@tool
def pipe_length_in_area(area_name: str = "A区", domain: str = "燃气") -> str:
    """
    区域内管线长度统计工具。

    适用问题：
    - “统计 A区 内燃气管线总长度”
    - “计算 B区 内水务管线长度”

    用到的 GIS 算子：
    - 图层选择 select_layer
    - 属性筛选 filter_features
    - 空间裁剪/相交 clip_lines_by_polygon
    - 长度统计 length_statistics

    参数：
    - area_name: 区域名称，例如“A区”“B区”。
    - domain: 业务领域，目前支持“燃气”“水务”。

    返回：
    - 命中的管线段数和区域内管线总长度。
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
        f"问题：统计 {area_name} 内 {domain} 管线总长度。\n"
        "计算步骤：选择区域 -> 选择管线图层 -> 空间裁剪/相交 -> 长度统计。\n"
        f"结果：命中管线 {stats['count']} 段，总长度约 {stats['total_length']:.2f} 米。"
    )


@tool
def hazards_near_pipes(domain: str = "燃气", buffer_distance: float = 100) -> str:
    """
    管线周边隐患查询工具。

    适用问题：
    - “查询燃气管线 100 米内有哪些隐患点”
    - “找出水务管线 200 米范围内的高风险点”

    用到的 GIS 算子：
    - 图层选择 select_layer
    - 属性筛选 filter_features
    - 邻近查询 find_points_near_lines

    参数：
    - domain: 业务领域，目前支持“燃气”“水务”。
    - buffer_distance: 距离阈值，单位米。

    返回：
    - 管线指定距离范围内的隐患点数量和编号。
    """

    pipe_layer_name = "gas_pipes" if domain == "燃气" else "water_pipes"
    pipes = select_layer(pipe_layer_name)
    hazards = filter_features(select_layer("hazards"), "domain", domain)
    matched = find_points_near_lines(hazards, pipes, buffer_distance)

    ids = ", ".join(item["hazard_id"] for item in matched) if matched else "无"
    return (
        f"问题：查询距离 {domain} 管线 {buffer_distance} 米内的隐患点。\n"
        "计算步骤：选择管线图层 -> 选择隐患点图层 -> 按领域筛选 -> 距离阈值查询。\n"
        f"结果：发现隐患点 {len(matched)} 个，编号：{ids}。"
    )


@tool
def gas_water_cross_conflict(buffer_distance: float = 20) -> str:
    """
    燃气与水务管线交叉冲突检测工具。

    适用问题：
    - “检查燃气管线和水务管线是否存在交叉冲突”
    - “识别燃气和水务管线距离过近的位置”

    用到的 GIS 算子：
    - 图层选择 select_layer
    - 管线冲突检测 find_line_conflicts

    参数：
    - buffer_distance: 安全距离，单位米。小于该距离认为可能存在冲突。

    返回：
    - 疑似冲突数量、涉及管线对、估算影响面积。
    """

    gas = select_layer("gas_pipes")
    water = select_layer("water_pipes")
    conflicts = find_line_conflicts(gas, water, buffer_distance)
    total_area = sum(item["area"] for item in conflicts)
    pairs = ", ".join(f"{item['pipe_a']}-{item['pipe_b']}" for item in conflicts) if conflicts else "无"

    return (
        "问题：识别燃气管线与水务管线是否存在交叉或近距离冲突。\n"
        "计算步骤：选择燃气管线 -> 选择水务管线 -> 线段距离/相交检测 -> 冲突统计。\n"
        f"结果：发现疑似冲突 {len(conflicts)} 处，涉及管线对：{pairs}，"
        f"估算影响面积约 {total_area:.2f} 平方米。"
    )


@tool
def facility_coverage_in_area(
    facility_domain: str = "燃气",
    area_name: str = "A区",
    radius: float = 300,
) -> str:
    """
    区域内设施服务覆盖率统计工具。

    适用问题：
    - “统计 A区 燃气设施 300 米服务覆盖率”
    - “计算 B区 水务泵站服务覆盖范围”

    用到的 GIS 算子：
    - 图层选择 select_layer
    - 属性筛选 filter_features
    - 点缓冲区 buffer_points
    - 面叠加/相交 intersect_areas
    - 面积统计 area_statistics

    参数：
    - facility_domain: 设施业务领域，例如“燃气”“水务”。
    - area_name: 区域名称，例如“A区”“B区”。
    - radius: 服务半径，单位米。

    返回：
    - 覆盖面积和覆盖率。
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
        f"问题：统计 {area_name} 内 {facility_domain} 设施 {radius} 米服务覆盖范围。\n"
        "计算步骤：选择区域 -> 选择设施图层 -> 属性筛选 -> 服务半径缓冲 -> 区域相交 -> 面积占比统计。\n"
        f"结果：覆盖面积约 {stats['total_area']:.2f} 平方米，覆盖率约 {ratio:.2f}%。"
    )


# Raw operator functions for direct Python composition.
gis_operator_functions = [
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


# Agent-callable GIS operators. Use GIS_TOOL_PROFILE=operator to expose only
# these atomic tools to the LLM.
gis_operator_tools = [tool(operator_func) for operator_func in gis_operator_functions]


# Agent-callable business tools. These wrap multiple operators into one task.
gis_business_tools = [
    buffer_analysis,
    pipe_length_stat,
    hazard_query,
    overlay_analysis,
    pipe_length_in_area,
    hazards_near_pipes,
    gas_water_cross_conflict,
    facility_coverage_in_area,
]


# Select which tool surface the agent sees.
# - business: existing behavior with high-level GIS task tools.
# - operator: the LLM must plan and compose the atomic GIS operators.
gis_tool_profile = os.getenv("GIS_TOOL_PROFILE", "business").lower()
gis_tools = gis_operator_tools if gis_tool_profile == "operator" else gis_business_tools


model_with_gis_tools = None
