"""
================================================================================
gis_skill_library.py —— GIS 原子算子 Skill 库
================================================================================
定位：
  1. 提供一组【原子级】GIS 算子（每个算子只做一件事，可直接操作）。
  2. 所有算子返回【原始数据格式】（SQL 查询结果行 / GeoJSON / 距离表等），
     不做结论性精炼总结 —— 结论由上层智能体自行整合。
  3. 底层数据为内置模拟图层（与真实 PostGIS 表结构一致），保证接口可迁移。
  4. 每个算子附带使用说明（SKILL_USAGE_DOCS），可注入智能体 Skill 库，
     告诉模型"这个算子是干什么的、怎么用"。

图层清单（mock，但字段结构贴近真实业务库）：
  gas_pipelines   燃气管线    gas_valves    燃气阀门
  water_pipes     供水管线    water_hazards 水务隐患点
  power_cables    电力缆线    power_towers  电力杆塔
  buildings       建筑物      communities   居民小区
  roads           道路        parcels       地块
  dem_points      高程采样点
================================================================================
"""
from typing import List
from langchain.tools import tool

# =====================================================================
# 0. 模拟数据（模拟 PostGIS 数据表的查询结果，字段与真实库对齐）
# =====================================================================
GAS_PIPELINES = [
    {"gid": 1, "name": "燃气高压线A1", "type": "高压", "material": "钢管", "diameter_mm": 500,
     "length_km": 12.4, "lay_year": 2008, "pressure_mpa": 2.5, "geom": "LINESTRING(116.30 39.85, 116.36 39.88)"},
    {"gid": 2, "name": "燃气高压线A2", "type": "高压", "material": "钢管", "diameter_mm": 400,
     "length_km": 8.7, "lay_year": 2011, "pressure_mpa": 2.5, "geom": "LINESTRING(116.36 39.88, 116.42 39.86)"},
    {"gid": 3, "name": "燃气中压线B1", "type": "中压", "material": "PE管", "diameter_mm": 200,
     "length_km": 5.2, "lay_year": 2015, "pressure_mpa": 0.4, "geom": "LINESTRING(116.31 39.84, 116.33 39.86)"},
    {"gid": 4, "name": "燃气中压线B2", "type": "中压", "material": "钢管", "diameter_mm": 300,
     "length_km": 6.9, "lay_year": 2013, "pressure_mpa": 0.4, "geom": "LINESTRING(116.33 39.86, 116.35 39.84)"},
    {"gid": 5, "name": "燃气低压线C1", "type": "低压", "material": "PE管", "diameter_mm": 110,
     "length_km": 3.1, "lay_year": 2018, "pressure_mpa": 0.01, "geom": "LINESTRING(116.32 39.83, 116.34 39.835)"},
    {"gid": 6, "name": "燃气低压线C2", "type": "低压", "material": "铸铁管", "diameter_mm": 150,
     "length_km": 2.6, "lay_year": 1999, "pressure_mpa": 0.01, "geom": "LINESTRING(116.35 39.87, 116.37 39.87)"},
]

GAS_VALVES = [
    {"gid": 101, "code": "V-001", "type": "球阀", "status": "正常", "geom": "POINT(116.305 39.852)"},
    {"gid": 102, "code": "V-002", "type": "闸阀", "status": "正常", "geom": "POINT(116.358 39.878)"},
    {"gid": 103, "code": "V-003", "type": "球阀", "status": "轻微腐蚀", "geom": "POINT(116.332 39.861)"},
    {"gid": 104, "code": "V-004", "type": "蝶阀", "status": "正常", "geom": "POINT(116.318 39.838)"},
    {"gid": 105, "code": "V-005", "type": "球阀", "status": "正常", "geom": "POINT(116.372 39.865)"},
]

WATER_PIPES = [
    {"gid": 201, "name": "供水主管W1", "type": "输水", "material": "球墨铸铁", "diameter_mm": 800,
     "length_km": 9.8, "lay_year": 2010, "geom": "LINESTRING(116.29 39.86, 116.35 39.89)"},
    {"gid": 202, "name": "供水支管W2", "type": "配水", "material": "PE管", "diameter_mm": 300,
     "length_km": 4.4, "lay_year": 2016, "geom": "LINESTRING(116.31 39.87, 116.34 39.855)"},
    {"gid": 203, "name": "排水管D1", "type": "排水", "material": "混凝土", "diameter_mm": 600,
     "length_km": 7.3, "lay_year": 2005, "geom": "LINESTRING(116.32 39.84, 116.38 39.87)"},
    {"gid": 204, "name": "排水管D2", "type": "排水", "material": "混凝土", "diameter_mm": 400,
     "length_km": 5.1, "lay_year": 2007, "geom": "LINESTRING(116.33 39.88, 116.39 39.855)"},
]

WATER_HAZARDS = [
    {"gid": 301, "type": "管网破损", "level": "严重", "report_date": "2026-08-12", "geom": "POINT(116.315 39.868)"},
    {"gid": 302, "type": "管网破损", "level": "一般", "report_date": "2026-09-01", "geom": "POINT(116.345 39.852)"},
    {"gid": 303, "type": "排水淤积", "level": "一般", "report_date": "2026-09-15", "geom": "POINT(116.362 39.871)"},
    {"gid": 304, "type": "排水淤积", "level": "严重", "report_date": "2026-09-20", "geom": "POINT(116.372 39.858)"},
    {"gid": 305, "type": "水质异常", "level": "一般", "report_date": "2026-09-25", "geom": "POINT(116.322 39.842)"},
]

POWER_CABLES = [
    {"gid": 401, "name": "10kV线路P1", "voltage_kv": 10, "length_km": 6.2, "lay_year": 2014,
     "geom": "LINESTRING(116.34 39.83, 116.40 39.85)"},
    {"gid": 402, "name": "110kV线路P2", "voltage_kv": 110, "length_km": 11.5, "lay_year": 2009,
     "geom": "LINESTRING(116.35 39.89, 116.43 39.87)"},
    {"gid": 403, "name": "10kV线路P3", "voltage_kv": 10, "length_km": 3.8, "lay_year": 2019,
     "geom": "LINESTRING(116.36 39.84, 116.39 39.86)"},
]

POWER_TOWERS = [
    {"gid": 501, "code": "T-A01", "height_m": 18, "type": "直线塔", "geom": "POINT(116.348 39.838)"},
    {"gid": 502, "code": "T-A02", "height_m": 22, "type": "耐张塔", "geom": "POINT(116.398 39.849)"},
    {"gid": 503, "code": "T-B01", "height_m": 25, "type": "直线塔", "geom": "POINT(116.358 39.891)"},
]

BUILDINGS = [
    {"gid": 601, "name": "阳光花园3号楼", "floors": 18, "area_m2": 4200, "type": "住宅", "geom": "POINT(116.318 39.856)"},
    {"gid": 602, "name": "市第一中学实验楼", "floors": 5, "area_m2": 3100, "type": "教育", "geom": "POINT(116.338 39.849)"},
    {"gid": 603, "name": "万达广场", "floors": 8, "area_m2": 26000, "type": "商业", "geom": "POINT(116.352 39.868)"},
    {"gid": 604, "name": "幸福里6号楼", "floors": 11, "area_m2": 2800, "type": "住宅", "geom": "POINT(116.368 39.846)"},
    {"gid": 605, "name": "化学试剂厂主车间", "floors": 2, "area_m2": 5600, "type": "工业", "geom": "POINT(116.375 39.838)"},
    {"gid": 606, "name": "康和医院住院部", "floors": 12, "area_m2": 9800, "type": "医疗", "geom": "POINT(116.392 39.862)"},
]

COMMUNITIES = [
    {"gid": 701, "name": "阳光花园社区", "households": 1860, "population": 5230, "geom": "POINT(116.319 39.857)"},
    {"gid": 702, "name": "幸福里社区", "households": 1240, "population": 3610, "geom": "POINT(116.367 39.847)"},
    {"gid": 703, "name": "学府雅苑", "households": 980, "population": 2740, "geom": "POINT(116.341 39.852)"},
    {"gid": 704, "name": "滨江社区", "households": 1520, "population": 4180, "geom": "POINT(116.388 39.866)"},
]

ROADS = [
    {"gid": 801, "name": "建设大道", "class": "主干路", "length_km": 5.6, "geom": "LINESTRING(116.30 39.86, 116.40 39.86)"},
    {"gid": 802, "name": "文化路", "class": "次干路", "length_km": 3.2, "geom": "LINESTRING(116.34 39.83, 116.34 39.89)"},
    {"gid": 803, "name": "滨河路", "class": "支路", "length_km": 2.1, "geom": "LINESTRING(116.36 39.87, 116.42 39.85)"},
]

PARCELS = [
    {"gid": 901, "name": "A-03地块", "use": "居住用地", "area_km2": 0.42,
     "geom": "POLYGON((116.31 39.85, 116.33 39.85, 116.33 39.865, 116.31 39.865, 116.31 39.85))"},
    {"gid": 902, "name": "B-07地块", "use": "工业用地", "area_km2": 1.15,
     "geom": "POLYGON((116.36 39.83, 116.39 39.83, 116.39 39.85, 116.36 39.85, 116.36 39.83))"},
    {"gid": 903, "name": "C-02地块", "use": "公共设施用地", "area_km2": 0.36,
     "geom": "POLYGON((116.38 39.86, 116.40 39.86, 116.40 39.875, 116.38 39.875, 116.38 39.86))"},
]

DEM_POINTS = [
    {"gid": 1001, "elev_m": 43.2, "geom": "POINT(116.30 39.85)"},
    {"gid": 1002, "elev_m": 45.8, "geom": "POINT(116.32 39.855)"},
    {"gid": 1003, "elev_m": 44.1, "geom": "POINT(116.34 39.86)"},
    {"gid": 1004, "elev_m": 41.7, "geom": "POINT(116.36 39.865)"},
    {"gid": 1005, "elev_m": 39.9, "geom": "POINT(116.38 39.87)"},
    {"gid": 1006, "elev_m": 38.2, "geom": "POINT(116.40 39.875)"},
]

LAYERS = {
    "gas_pipelines": GAS_PIPELINES,
    "gas_valves": GAS_VALVES,
    "water_pipes": WATER_PIPES,
    "water_hazards": WATER_HAZARDS,
    "power_cables": POWER_CABLES,
    "power_towers": POWER_TOWERS,
    "buildings": BUILDINGS,
    "communities": COMMUNITIES,
    "roads": ROADS,
    "parcels": PARCELS,
    "dem_points": DEM_POINTS,
}

# 事件/工程点（用于最近设施、缓冲、路径分析的目标点）
POIS = {
    "泄漏点": "POINT(116.331 39.860)",
    "拟建化工厂": "POINT(116.375 39.840)",
    "抢修出发点": "POINT(116.305 39.850)",
    "事故点": "POINT(116.373 39.866)",
}


def _resolve_poi(name: str):
    """POI解析器：优先取预置POI表，否则在全部图层中按名称/编号模糊匹配点要素。
    使任意点要素（小区、建筑物、阀门、杆塔等）都可作为分析中心，而非仅限预置4个POI。"""
    if name in POIS:
        return POIS[name]
    for rows in LAYERS.values():
        for r in rows:
            if str(r.get("geom", "")).startswith("POINT") and \
               name in (r.get("name"), r.get("code"), str(r.get("name", "")).replace("社区", "")):
                return r["geom"]
    return None


def _fmt_rows(rows: List[dict], layer: str, sql_hint: str) -> str:
    """把模拟表查询结果格式化为『数据库查询结果』风格文本（含行数与SQL提示）"""
    lines = [f"[SQL查询结果] 图层:{layer}  共{len(rows)}行  (等价SQL: {sql_hint})"]
    if rows:
        header = " | ".join(rows[0].keys())
        lines.append(header)
        lines.append("-" * len(header))
        for r in rows:
            lines.append(" | ".join(str(v) for v in r.values()))
    else:
        lines.append("(空结果集)")
    return "\n".join(lines)


# =====================================================================
# 1. 原子算子（每个只做一件事，返回原始查询结果格式）
# =====================================================================

@tool(parse_docstring=True)
def spatial_query(layer: str, where: str = "") -> str:
    """
    属性条件查询算子：在指定图层上按SQL条件筛选要素，返回原始记录行（模拟SELECT * FROM layer WHERE ...）。

    Args:
        layer: 图层名，可选：gas_pipelines/gas_valves/water_pipes/water_hazards/power_cables/power_towers/buildings/communities/roads/parcels/dem_points
        where: SQL风格条件表达式，如 "type = '高压'"、"floors >= 10"、"status = '正常'"；空字符串表示全表查询
    """
    rows = LAYERS.get(layer, [])
    if where:
        # 极简条件解析：仅支持 "字段 = '值'"、">=数值"、">数值"、"<数值" 单条件
        matched = []
        for r in rows:
            ok = False
            if "=" in where and "!=" not in where:
                f, v = [s.strip() for s in where.split("=", 1)]
                ok = str(r.get(f, "")) == v.strip("'\"")
            elif ">=" in where:
                f, v = [s.strip() for s in where.split(">=")]
                ok = isinstance(r.get(f), (int, float)) and r[f] >= float(v)
            elif ">" in where:
                f, v = [s.strip() for s in where.split(">")]
                ok = isinstance(r.get(f), (int, float)) and r[f] > float(v)
            elif "<" in where:
                f, v = [s.strip() for s in where.split("<")]
                ok = isinstance(r.get(f), (int, float)) and r[f] < float(v)
            if ok:
                matched.append(r)
        rows = matched
    sql = f"SELECT * FROM {layer}" + (f" WHERE {where}" if where else "")
    return _fmt_rows(rows, layer, sql)


@tool(parse_docstring=True)
def attribute_agg(layer: str, agg_func: str, agg_field: str, group_by: str = "") -> str:
    """
    属性聚合统计算子：对图层字段做 count/sum/avg/min/max 聚合（可分组），返回GROUP BY查询结果行。

    Args:
        layer: 图层名（见spatial_query说明）
        agg_func: 聚合函数：count/sum/avg/min/max
        agg_field: 被聚合字段名（count时可用 * 或 gid）
        group_by: 分组字段名，可为空
    """
    rows = LAYERS.get(layer, [])
    if not group_by:
        if agg_func == "count":
            val = len(rows)
        else:
            vals = [r.get(agg_field) for r in rows if isinstance(r.get(agg_field), (int, float))]
            val = round(sum(vals), 2) if agg_func == "sum" else \
                  round(sum(vals) / len(vals), 2) if agg_func == "avg" and vals else \
                  min(vals) if agg_func == "min" and vals else max(vals) if vals else 0
        sql = f"SELECT {agg_func}({agg_field}) FROM {layer}"
        return f"[SQL查询结果] {sql}  共1行\n{agg_func}_{agg_field}\n{val}"
    groups: dict = {}
    for r in rows:
        groups.setdefault(r.get(group_by, "NULL"), []).append(r)
    lines = [f"[SQL查询结果] SELECT {group_by}, {agg_func}({agg_field}) FROM {layer} GROUP BY {group_by}  共{len(groups)}行",
             f"{group_by} | {agg_func}_{agg_field}"]
    for g, grs in groups.items():
        if agg_func == "count":
            v = len(grs)
        else:
            vals = [x.get(agg_field) for x in grs if isinstance(x.get(agg_field), (int, float))]
            v = round(sum(vals), 2) if agg_func == "sum" else \
                round(sum(vals) / len(vals), 2) if agg_func == "avg" and vals else \
                min(vals) if agg_func == "min" and vals else max(vals) if vals else 0
        lines.append(f"{g} | {v}")
    return "\n".join(lines)


@tool(parse_docstring=True)
def buffer_analysis(poi_name: str, buffer_distance: float) -> str:
    """
    缓冲区生成算子：以指定兴趣点（POI）为圆心生成缓冲区面，返回缓冲区的原始几何信息（WKT）与统计。

    Args:
        poi_name: 兴趣点名称，可选：泄漏点/拟建化工厂/抢修出发点/事故点
        buffer_distance: 缓冲半径，单位米
    """
    center = _resolve_poi(poi_name)
    if center is None:
        return f"[错误] 未找到POI: {poi_name}，可传入预置POI（{list(POIS.keys())}）或任意点要素名称/编号"
    area = 3.14159 * (buffer_distance / 1000) ** 2
    return (f"[缓冲区生成结果] center_poi={poi_name}, center_geom={center}, "
            f"radius_m={buffer_distance}, "
            f"buffer_geom=POLYGON((... 以{poi_name}为圆心 半径{buffer_distance}米 的圆面 ...)), "
            f"area_km2={round(area, 4)}, srid=4326")


@tool(parse_docstring=True)
def features_within_distance(layer: str, poi_name: str, distance_m: float) -> str:
    """
    邻近筛选算子：查询指定POI一定距离范围内的图层要素（模拟 ST_DWithin 查询），返回命中要素原始记录与距离。

    Args:
        layer: 图层名（见spatial_query说明）
        poi_name: 兴趣点名称，可选：泄漏点/拟建化工厂/抢修出发点/事故点
        distance_m: 距离阈值，单位米
    """
    center = _resolve_poi(poi_name)
    if center is None:
        return f"[错误] 未找到POI: {poi_name}，可传入预置POI（{list(POIS.keys())}）或任意点要素名称/编号"
    rows = LAYERS.get(layer, [])
    cx, cy = [float(x) for x in center.replace("POINT(", "").replace(")", "").split()]
    deg_per_m = 1.0 / 111000.0
    hits = []
    for r in rows:
        g = r.get("geom", "")
        if g.startswith("POINT"):
            x, y = [float(v) for v in g.replace("POINT(", "").replace(")", "").split()]
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / deg_per_m
        else:  # 线/面：取首个坐标近似
            coords = g.split("(")[-1].strip(")").split(",")[0]
            x, y = [float(v) for v in coords.split()]
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / deg_per_m
        if d <= distance_m:
            hits.append({**r, "distance_m": round(d, 1)})
    hits.sort(key=lambda h: h["distance_m"])
    sql = f"SELECT a.*, ST_Distance(a.geom, '{center}') FROM {layer} a WHERE ST_DWithin(a.geom, '{center}', {distance_m})"
    return _fmt_rows(hits, layer, sql)


@tool(parse_docstring=True)
def nearest_features(layer: str, poi_name: str, top_k: int = 3) -> str:
    """
    最近要素查询算子（KNN）：查询距离指定POI最近的K个要素（模拟 ORDER BY geom <-> poi LIMIT k），返回排序距离表。

    Args:
        layer: 图层名（见spatial_query说明）
        poi_name: 兴趣点名称，可选：泄漏点/拟建化工厂/抢修出发点/事故点
        top_k: 返回最近要素个数，默认3
    """
    center = _resolve_poi(poi_name)
    if center is None:
        return f"[错误] 未找到POI: {poi_name}，可传入预置POI（{list(POIS.keys())}）或任意点要素名称/编号"
    rows = LAYERS.get(layer, [])
    cx, cy = [float(x) for x in center.replace("POINT(", "").replace(")", "").split()]
    deg_per_m = 1.0 / 111000.0
    scored = []
    for r in rows:
        g = r.get("geom", "")
        coords = g.split("(")[-1].strip(")").split(",")[0]
        x, y = [float(v) for v in coords.split()]
        d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / deg_per_m
        scored.append({**r, "distance_m": round(d, 1)})
    scored.sort(key=lambda h: h["distance_m"])
    return _fmt_rows(scored[:top_k], layer,
                     f"SELECT * FROM {layer} ORDER BY geom <-> '{center}' LIMIT {top_k}")


@tool(parse_docstring=True)
def overlay_intersect(layer_a: str, layer_b: str) -> str:
    """
    叠加相交分析算子：检测两个图层要素的空间相交/交叉对（模拟 ST_Intersects 连接查询），返回相交要素对记录。

    Args:
        layer_a: 图层A名称（见spatial_query说明）
        layer_b: 图层B名称（见spatial_query说明）
    """
    rows_a, rows_b = LAYERS.get(layer_a, []), LAYERS.get(layer_b, [])
    pairs = []
    for a in rows_a:
        ga = a.get("geom", "")
        ax, ay = [float(v) for v in ga.split("(")[-1].strip(")").split(",")[0].split()]
        for b in rows_b:
            gb = b.get("geom", "")
            bx, by = [float(v) for v in gb.split("(")[-1].strip(")").split(",")[0].split()]
            if abs(ax - bx) < 0.045 and abs(ay - by) < 0.022:
                pairs.append({
                    "a_layer": layer_a, "a_gid": a.get("gid"), "a_name": a.get("name", a.get("code", "")),
                    "b_layer": layer_b, "b_gid": b.get("gid"), "b_name": b.get("name", b.get("code", "")),
                    "intersect_point": f"POINT({round((ax+bx)/2,4)} {round((ay+by)/2,4)})",
                })
    sql = f"SELECT a.*, b.* FROM {layer_a} a JOIN {layer_b} b ON ST_Intersects(a.geom, b.geom)"
    return _fmt_rows(pairs, f"{layer_a} × {layer_b}", sql)


@tool(parse_docstring=True)
def spatial_join(points_layer: str, polygons_layer: str) -> str:
    """
    空间关联算子：统计点要素落入面要素的归属关系（模拟 ST_Within 空间连接），返回"点-所在面"原始记录。

    Args:
        points_layer: 点图层名，如 gas_valves/water_hazards/buildings/communities/power_towers
        polygons_layer: 面图层名，如 parcels
    """
    pts, polys = LAYERS.get(points_layer, []), LAYERS.get(polygons_layer, [])
    out = []
    for p in pts:
        g = p.get("geom", "")
        if not g.startswith("POINT"):
            continue
        x, y = [float(v) for v in g.replace("POINT(", "").replace(")", "").split()]
        hit = "NULL(未落入任何面要素)"
        for pl in polys:
            coords_txt = pl["geom"].split("((")[-1].strip("))")
            ring = [tuple(float(v) for v in c.split()) for c in coords_txt.split(",")]
            xs = [c[0] for c in ring]; ys = [c[1] for c in ring]
            if min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys):
                hit = f"{polygons_layer}#{pl.get('gid')}({pl.get('name')},{pl.get('use')})"
                break
        out.append({"point_gid": p.get("gid"), "point_name": p.get("name", p.get("code", "")),
                    "within_polygon": hit})
    sql = f"SELECT p.*, z.name FROM {points_layer} p LEFT JOIN {polygons_layer} z ON ST_Within(p.geom, z.geom)"
    return _fmt_rows(out, f"{points_layer} ⊂ {polygons_layer}", sql)


@tool(parse_docstring=True)
def length_measure(layer: str, where: str = "") -> str:
    """
    长度量算算子：对线图层逐要素量算长度并返回逐条记录（模拟 ST_Length），不做总计汇总。

    Args:
        layer: 线图层名，如 gas_pipelines/water_pipes/power_cables/roads
        where: SQL风格筛选条件，可为空
    """
    res = spatial_query.invoke({"layer": layer, "where": where})
    if res.startswith("[错误]"):
        return res
    lines = res.split("\n")
    out = ["[长度量算结果] ST_Length 逐要素记录:", "gid | name | length_km"]
    for ln in lines[2:]:
        cells = ln.split(" | ")
        gid = cells[0]
        name = cells[1] if len(cells) > 1 else ""
        lk = cells[5] if len(cells) > 5 else cells[-2] if len(cells) > 2 else "0"
        try:
            out.append(f"{gid} | {name} | {float(lk)}")
        except ValueError:
            out.append(f"{gid} | {name} | (无长度字段)")
    return "\n".join(out)


@tool(parse_docstring=True)
def area_measure(layer: str, where: str = "") -> str:
    """
    面积量算算子：对面图层逐要素量算面积并返回逐条记录（模拟 ST_Area）。

    Args:
        layer: 面图层名，如 parcels
        where: SQL风格筛选条件，可为空
    """
    res = spatial_query.invoke({"layer": layer, "where": where})
    if res.startswith("[错误]"):
        return res
    lines = res.split("\n")
    out = ["[面积量算结果] ST_Area 逐要素记录:", "gid | name | area_km2"]
    for ln in lines[2:]:
        cells = ln.split(" | ")
        if len(cells) >= 6:
            out.append(f"{cells[0]} | {cells[1]} | {cells[5]}")
    return "\n".join(out)


@tool(parse_docstring=True)
def clip_analysis(clip_layer: str, input_layer: str, clip_where: str = "") -> str:
    """
    裁剪分析算子：用面图层裁剪输入图层（模拟 ST_Intersection），返回被裁剪保留的要素记录。

    Args:
        clip_layer: 裁剪面图层名，如 parcels
        input_layer: 被裁剪图层名，如 gas_pipelines/water_pipes/buildings
        clip_where: 裁剪面筛选条件，可为空
    """
    res = spatial_join(input_layer, clip_layer) if False else None
    pts = LAYERS.get(input_layer, [])
    polys = LAYERS.get(clip_layer, [])
    if clip_where:
        f, v = [s.strip() for s in clip_where.split("=", 1)]
        polys = [p for p in polys if str(p.get(f, "")) == v.strip("'\"")]
    out = []
    for p in pts:
        g = p.get("geom", "")
        coords = g.split("(")[-1].strip(")").split(",")[0]
        x, y = [float(v) for v in coords.split()]
        for pl in polys:
            coords_txt = pl["geom"].split("((")[-1].strip("))")
            ring = [tuple(float(v) for v in c.split()) for c in coords_txt.split(",")]
            xs = [c[0] for c in ring]; ys = [c[1] for c in ring]
            if min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys):
                out.append({**p, "clipped_by": f"{clip_layer}#{pl.get('gid')}"})
                break
    sql = f"SELECT ST_Intersection(i.geom, c.geom), i.* FROM {input_layer} i, {clip_layer} c WHERE ST_Intersects(i.geom, c.geom)"
    return _fmt_rows(out, f"{input_layer} clipped by {clip_layer}", sql)


@tool(parse_docstring=True)
def shortest_path(start_poi: str, end_poi: str, network_layer: str = "roads") -> str:
    """
    网络最短路径算子：在道路/管线网络上计算两点间最短路径（模拟 pgRouting），返回途经路段序列与分段长度。

    Args:
        start_poi: 起点POI名，可选：泄漏点/拟建化工厂/抢修出发点/事故点
        end_poi: 终点POI名，可选值同上
        network_layer: 网络图层名，默认 roads
    """
    if _resolve_poi(start_poi) is None or _resolve_poi(end_poi) is None:
        return f"[错误] POI不存在: {start_poi}/{end_poi}，可传入预置POI（{list(POIS.keys())}）或任意点要素名称/编号"
    segs = [
        {"seq": 1, "edge_id": 801, "road_name": "建设大道", "from_node": 1, "to_node": 2, "cost_km": 1.8},
        {"seq": 2, "edge_id": 802, "road_name": "文化路", "from_node": 2, "to_node": 3, "cost_km": 2.4},
        {"seq": 3, "edge_id": 803, "road_name": "滨河路", "from_node": 3, "to_node": 4, "cost_km": 1.5},
    ]
    total = round(sum(s["cost_km"] for s in segs), 2)
    lines = [f"[最短路径结果] pgRouting pgr_dijkstra: {start_poi} -> {end_poi}, network={network_layer}, 总代价={total}km, 共{len(segs)}条路段",
             "seq | edge_id | road_name | from_node | to_node | cost_km"]
    lines += [f"{s['seq']} | {s['edge_id']} | {s['road_name']} | {s['from_node']} | {s['to_node']} | {s['cost_km']}" for s in segs]
    return "\n".join(lines)


@tool(parse_docstring=True)
def service_area(facility_poi: str, max_distance_m: float) -> str:
    """
    服务区分析算子：计算设施点沿网络可达的服务范围（模拟 pgDrivingDistance），返回服务区覆盖的路段与到达代价记录。

    Args:
        facility_poi: 设施POI名，可选：泄漏点/拟建化工厂/抢修出发点/事故点
        max_distance_m: 服务半径，单位米
    """
    if _resolve_poi(facility_poi) is None:
        return f"[错误] 未找到POI: {facility_poi}，可传入预置POI（{list(POIS.keys())}）或任意点要素名称/编号"
    max_km = round(max_distance_m / 1000, 2)
    covered = [
        {"edge_id": 801, "road_name": "建设大道", "reach_cost_km": 1.2, "covered": True},
        {"edge_id": 802, "road_name": "文化路", "reach_cost_km": 1.9, "covered": True},
        {"edge_id": 803, "road_name": "滨河路", "reach_cost_km": max_km, "covered": "边界(部分覆盖)"},
    ]
    lines = [f"[服务区分析结果] pgr_drivingDistance: facility={facility_poi}, max_cost={max_km}km",
             "edge_id | road_name | reach_cost_km | covered"]
    lines += [f"{c['edge_id']} | {c['road_name']} | {c['reach_cost_km']} | {c['covered']}" for c in covered]
    return "\n".join(lines)


@tool(parse_docstring=True)
def terrain_profile(route_wkt: str, sample_interval_m: int = 500) -> str:
    """
    地形剖面采样算子：沿给定线路按间距采样高程（模拟 ST_LineInterpolatePoint + DEM查询），返回采样点高程序列。

    Args:
        route_wkt: 线路WKT坐标，如 "LINESTRING(116.30 39.85, 116.40 39.875)"；也可传POI名"泄漏点"使用其坐标
        sample_interval_m: 采样间距，单位米，默认500
    """
    if route_wkt in POIS:
        route_wkt = f"LINESTRING({POIS[route_wkt].replace('(', '').replace(')', '')}, 116.40 39.875)"
    xs = [43.2, 44.9, 44.1, 42.0, 39.4, 38.2]
    n = max(2, int(10000 / max(sample_interval_m, 1)))
    idx = [round(i * (len(xs) - 1) / (n - 1)) for i in range(n)]
    samples = [{"seq": i + 1, "offset_m": round(i * 10000 / (n - 1)), "elev_m": xs[j]} for i, j in enumerate(idx)]
    lines = [f"[地形剖面结果] route={route_wkt}, interval={sample_interval_m}m, 采样点数={len(samples)}",
             "seq | offset_m | elev_m"]
    lines += [f"{s['seq']} | {s['offset_m']} | {s['elev_m']}" for s in samples]
    return "\n".join(lines)


@tool(parse_docstring=True)
def density_heatmap(layer: str, cell_size_m: int = 500) -> str:
    """
    核密度/格网统计算子：将点要素落入格网并统计每格数量（模拟 ST_SnapToGrid 聚合），返回格网单元计数记录。

    Args:
        layer: 点图层名，如 water_hazards/gas_valves/buildings/communities
        cell_size_m: 格网边长，单位米，默认500
    """
    rows = [r for r in LAYERS.get(layer, []) if str(r.get("geom", "")).startswith("POINT")]
    grid: dict = {}
    for r in rows:
        x, y = [float(v) for v in r["geom"].replace("POINT(", "").replace(")", "").split()]
        gx, gy = round(x, 3), round(y, 3)
        grid.setdefault((gx, gy), []).append(r.get("gid"))
    cell_km = round(cell_size_m / 1000, 2)
    out = [{"cell_id": i + 1, "cell_origin": f"POINT({k[0]} {k[1]})", "point_count": len(v), "point_gids": v}
           for i, (k, v) in enumerate(sorted(grid.items()))]
    lines = [f"[格网密度结果] layer={layer}, cell_size={cell_km}km, 非空格网数={len(out)}",
             "cell_id | cell_origin | point_count | point_gids"]
    lines += [f"{o['cell_id']} | {o['cell_origin']} | {o['point_count']} | {o['point_gids']}" for o in out]
    return "\n".join(lines)


@tool(parse_docstring=True)
def topology_check(layer: str) -> str:
    """
    拓扑检查算子：检查线图层拓扑错误（悬垂节点、重复线、自相交，模拟 ST_IsSimple/节点度检查），返回错误要素记录。

    Args:
        layer: 线图层名，如 gas_pipelines/water_pipes/power_cables/roads
    """
    rows = LAYERS.get(layer, [])
    errs = []
    if rows:
        errs.append({"gid": rows[0]["gid"], "name": rows[0].get("name", ""), "error_type": "dangling_node",
                     "detail": f"端点 {rows[0]['geom'].split(',')[-1]} 未与其他线段连接"})
        if len(rows) > 3:
            errs.append({"gid": rows[3]["gid"], "name": rows[3].get("name", ""), "error_type": "overshoot",
                         "detail": "线段超出节点0.8米"})
    lines = [f"[拓扑检查结果] layer={layer}, 检查项=dangling_node/overshoot/self_intersect/duplicate, 错误数={len(errs)}",
             "gid | name | error_type | detail"]
    lines += [f"{e['gid']} | {e['name']} | {e['error_type']} | {e['detail']}" for e in errs]
    return "\n".join(lines)


ATOMIC_TOOLS = [
    spatial_query, attribute_agg, buffer_analysis, features_within_distance,
    nearest_features, overlay_intersect, spatial_join, length_measure,
    area_measure, clip_analysis, shortest_path, service_area,
    terrain_profile, density_heatmap, topology_check,
]

# =====================================================================
# 2. Skill 库使用说明（注入智能体 Skill 库：告诉模型算子是干什么的、怎么用）
# =====================================================================

SKILL_USAGE_DOCS = {
    "燃气": """【GIS原子算子Skill库·使用说明】
可用数据图层：gas_pipelines(燃气管线,字段:gid,name,type[高压/中压/低压],material,diameter_mm,length_km,lay_year,pressure_mpa,geom)、gas_valves(燃气阀门,字段:gid,code,type,status,geom)、buildings(建筑物)、communities(小区)、roads(道路)、parcels(地块)、water_pipes、water_hazards、power_cables、power_towers、dem_points。
可用POI：泄漏点/拟建化工厂/抢修出发点/事故点。

1. spatial_query(layer, where)：按SQL条件查图层原始记录。查"有哪些高压管线"用它，条件如 "type = '高压'"。
2. attribute_agg(layer, agg_func, agg_field, group_by)：count/sum/avg聚合。查"总长度/各类型数量"用它，如 attribute_agg("gas_pipelines","sum","length_km","type")。
3. buffer_analysis(poi_name, buffer_distance_m)：生成POI缓冲区。查"某点半径范围内分析"第一步先用它。
4. features_within_distance(layer, poi, distance_m)：查POI范围内要素及距离。查"500米内有哪些管线/建筑物"用它。
5. nearest_features(layer, poi, top_k)：KNN最近要素。查"离泄漏点最近的3个阀门"用它。
6. overlay_intersect(layer_a, layer_b)：两图层交叉检测。查"燃气管线与排水管交叉冲突"用它。
7. spatial_join(points_layer, polygons_layer)：点落入面归属。查"各阀门属于哪个地块"用它。
8. length_measure(layer, where)：逐要素量算长度（返回逐条记录，不做总计；总计请用attribute_agg）。
9. area_measure(layer, where)：面要素逐条面积。
10. clip_analysis(clip_layer, input_layer, clip_where)：面裁剪。
11. shortest_path(start_poi, end_poi)：网络最短路径。查"抢修最短路线"用它。
12. service_area(facility_poi, max_distance_m)：服务区分析。查"2公里服务范围覆盖哪些小区"先用它再对小区做邻近筛选。
13. terrain_profile(route_wkt, sample_interval_m)：沿线路高程剖面。查"管线沿线地势"用它。
14. density_heatmap(layer, cell_size_m)：点要素格网密度。查"隐患点密集区域"用它。
15. topology_check(layer)：线图层拓扑检查。查"管线数据质量/断头管"用它。

使用原则：一次只调用一个原子算子；复杂问题拆解为多次原子调用；所有结果以原始数据行为准，不要编造数据。""",

    "水务": """【GIS原子算子Skill库·使用说明】
可用数据图层：water_pipes(供排水管线,字段:gid,name,type[输水/配水/排水],material,diameter_mm,length_km,lay_year,geom)、water_hazards(水务隐患点,字段:gid,type[管网破损/排水淤积/水质异常],level[严重/一般],report_date,geom)、buildings、communities、roads、parcels、gas_pipelines、power_cables、dem_points。
可用POI：泄漏点/拟建化工厂/抢修出发点/事故点。

1. spatial_query(layer, where)：属性筛选原始记录，如查严重隐患 where="level = '严重'"。
2. attribute_agg：聚合统计，如各材质管线总长度 attribute_agg("water_pipes","sum","length_km","material")。
3. buffer_analysis / features_within_distance / nearest_features：缓冲、邻近筛选、KNN最近设施。
4. overlay_intersect：管线交叉冲突检测（如供水管与排水管）。
5. spatial_join：隐患点归属地块分析。
6. length_measure / area_measure：逐要素长度/面积量算。
7. clip_analysis / service_area / shortest_path / terrain_profile / density_heatmap / topology_check：裁剪、服务区、路径、剖面、密度、拓扑检查。
使用原则：一次一个原子算子，复杂任务逐步拆解，结果以原始行为准。""",

    "电务": """【GIS原子算子Skill库·使用说明】
可用数据图层：power_cables(电力缆线,字段:gid,name,voltage_kv,length_km,lay_year,geom)、power_towers(杆塔,字段:gid,code,height_m,type,geom)、buildings、communities、roads、parcels、gas_pipelines、water_pipes、dem_points。
可用POI：泄漏点/拟建化工厂/抢修出发点/事故点。

1. spatial_query：属性筛选（如 voltage_kv >= 110）。
2. attribute_agg：聚合（如各电压等级缆线总长）。
3. buffer_analysis / features_within_distance：保护区范围与范围内建筑分析。
4. overlay_intersect：电力线与建筑物/管线交叉检测。
5. nearest_features：离事故点最近杆塔。
6. shortest_path / service_area：抢修路径与供电服务区。
7. terrain_profile / topology_check / density_heatmap / spatial_join / clip_analysis / length_measure / area_measure：其余通用分析。
使用原则：一次一个原子算子，复杂任务逐步拆解，结果以原始行为准。""",
}


# =====================================================================
# 3. 自检入口（独立运行本文件可验证算子可用）
# =====================================================================
if __name__ == "__main__":
    print(spatial_query.invoke({"layer": "gas_pipelines", "where": "type = '高压'"}))
    print()
    print(attribute_agg.invoke({"layer": "gas_pipelines", "agg_func": "sum", "agg_field": "length_km", "group_by": "type"}))
    print()
    print(nearest_features.invoke({"layer": "gas_valves", "poi_name": "泄漏点", "top_k": 3}))
    print()
    print(overlay_intersect.invoke({"layer_a": "gas_pipelines", "layer_b": "water_pipes"}))
