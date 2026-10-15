from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

from psycopg.rows import dict_row

from app.config.settings import get_settings
from app.db.connection import get_connection
from app.db.identifiers import quote_identifier
from app.tools.layers import ALLOWED_LAYERS, LayerSpec, get_layer_spec
from app.tools.schemas import (
    BufferQueryInput,
    ClipAndMeasureInput,
    NearestFeaturesInput,
    SpatialFilterInput,
    TargetGeometry,
)


class PostGISToolkit:
    """第一版 PostGIS Tool 集合。

    设计目标是直接、可读、可测试。LLM 只能调用这些方法，不能直接执行任意 SQL。
    """

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or get_settings().database_url

    def list_spatial_layers(self) -> dict[str, Any]:
        """列出当前可供空间分析工具访问的图层及其基本信息。

        功能：读取 PostGIS 的 geometry_columns 视图，筛选 gis_lab 下的
        白名单图层，并统计各业务表的记录数，供调用方了解可用数据。

        输入：无业务参数；数据库连接使用初始化工具集时提供的配置。

        输出：成功时返回包含 status、tool、elapsed_ms、result、error
        的字典，其中 result.layers 是按表名排序的图层列表。每项包含
        schema_name（模式名）、table_name（表名）、geometry_column
        （几何字段）、geometry_type（几何类型）、srid（坐标系编号）
        和 row_count（记录数），不返回具体空间要素。
        """

        started = time.perf_counter()
        sql = """
        SELECT
            c.f_table_schema AS schema_name,
            c.f_table_name AS table_name,
            c.f_geometry_column AS geometry_column,
            c.type AS geometry_type,
            c.srid,
            COALESCE(cnt.row_count, 0) AS row_count
        FROM geometry_columns c
        LEFT JOIN (
            SELECT 'construction_areas' AS table_name, COUNT(*)::bigint AS row_count FROM gis_lab.construction_areas
            UNION ALL SELECT 'gas_pipelines', COUNT(*)::bigint FROM gis_lab.gas_pipelines
            UNION ALL SELECT 'gas_devices', COUNT(*)::bigint FROM gis_lab.gas_devices
            UNION ALL SELECT 'water_pipelines', COUNT(*)::bigint FROM gis_lab.water_pipelines
            UNION ALL SELECT 'demo_roads', COUNT(*)::bigint FROM gis_lab.demo_roads
        ) cnt ON cnt.table_name = c.f_table_name
        WHERE c.f_table_schema = 'gis_lab'
          AND c.f_table_name = ANY(%s)
        ORDER BY c.f_table_name;
        """
        rows = self._fetch(sql, [list(ALLOWED_LAYERS)])
        return self._ok("list_spatial_layers", started, {"layers": rows})

    def describe_spatial_layer(self, layer_name: str, sample_limit: int = 5) -> dict[str, Any]:
        """查看一个空间图层的字段结构、坐标系和样例要素。

        功能：查询指定白名单图层的字段元数据和空间参考信息，并按
        要素 ID 读取少量样例，帮助调用方确定后续分析所需的字段。

        输入：
            layer_name：白名单中的图层名称，例如 gas_pipelines。
            sample_limit：样例数量，默认 5；本方法将其限制在 1～20。

        输出：成功时返回包含 status、tool、elapsed_ms、result、error
        的字典，其中 result 包含：
            layer：图层名称。
            columns：字段列表，每项包含 column_name、data_type、udt_name。
            spatial_ref：模式、表名、几何字段、几何类型和 SRID；未查到时为 None。
            samples：公开属性字段及 geometry 组成的样例列表。
        样例 geometry 为 GeoJSON 几何对象，坐标保持图层原有坐标系。
        """

        started = time.perf_counter()
        layer = get_layer_spec(layer_name)
        sample_limit = max(1, min(sample_limit, 20))

        columns_sql = """
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position;
        """
        spatial_sql = """
        SELECT
            f_table_schema AS schema_name,
            f_table_name AS table_name,
            f_geometry_column AS geometry_column,
            type AS geometry_type,
            srid
        FROM geometry_columns
        WHERE f_table_schema = %s AND f_table_name = %s;
        """
        sample_sql = f"""
        SELECT {self._select_public_columns(layer)},
               ST_AsGeoJSON({self._q(layer.geom_column)})::json AS geometry
        FROM {self._qualified(layer)}
        ORDER BY {self._q(layer.id_column)}
        LIMIT %s;
        """

        with get_connection(self.database_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(columns_sql, [layer.schema_name, layer.table_name])
                columns = [dict(row) for row in cur.fetchall()]
                cur.execute(spatial_sql, [layer.schema_name, layer.table_name])
                spatial_ref = cur.fetchone()
                cur.execute(sample_sql, [sample_limit])
                samples = [self._normalize_row(row) for row in cur.fetchall()]

        return self._ok(
            "describe_spatial_layer",
            started,
            {
                "layer": layer.name,
                "columns": columns,
                "spatial_ref": dict(spatial_ref) if spatial_ref else None,
                "samples": samples,
            },
        )

    def spatial_filter(self, request: SpatialFilterInput | dict[str, Any]) -> dict[str, Any]:
        """根据图层要素与目标几何之间的空间关系筛选要素。

        功能：按 relation 指定的关系执行筛选，关系参数顺序为
        “待查询图层的要素、目标几何”。ST_Intersects 判断两者是否相交
        （含边界接触）；ST_Within 判断要素是否位于目标内；ST_Contains
        判断要素是否包含目标。完全落在面边界上的点或线不满足 Within，
        对应的面也不 Contains 该点或线。

        输入：request 为 SpatialFilterInput 模型或同结构字典，包含：
            layer_name：待查询的白名单图层名称。
            target：目标，使用 layer_name 加 feature_id/feature_code
                指定已有要素，或使用 geometry 加 srid 传入 GeoJSON 几何。
            relation：ST_Intersects、ST_Within、ST_Contains 三者之一。
            max_results：最多返回多少个要素，默认 20，范围 1～100。
        本方法不自动统一坐标系，目标与待查询图层的 SRID 必须一致。

        输出：成功时返回包含 status、tool、elapsed_ms、result、error
        的字典。result 包含 matched_count（全部匹配数量）、features
        （按要素 ID 排序并截取的公开属性及 GeoJSON 几何）和 relation。
        features 中的 geometry 是原始要素几何，不是相交部分。
        """

        started = time.perf_counter()
        req = request if isinstance(request, SpatialFilterInput) else SpatialFilterInput(**request)
        layer = get_layer_spec(req.layer_name)
        relation_sql = req.relation
        target_sql, params = self._target_geometry_sql(req.target, alias="target")

        sql = f"""
        WITH target AS ({target_sql}),
        matched AS (
            SELECT f.*,
                   ST_AsGeoJSON(f.{self._q(layer.geom_column)})::json AS geometry
            FROM {self._qualified(layer)} f
            CROSS JOIN target t
            WHERE {relation_sql}(f.{self._q(layer.geom_column)}, t.geom)
            ORDER BY f.{self._q(layer.id_column)}
        )
        SELECT COUNT(*) OVER() AS matched_count,
               {self._select_public_columns(layer)},
               geometry
        FROM matched
        LIMIT %s;
        """
        rows = self._fetch(sql, [*params, req.max_results])
        total = rows[0]["matched_count"] if rows else 0
        for row in rows:
            row.pop("matched_count", None)
        return self._ok(
            "spatial_filter",
            started,
            {"matched_count": total, "features": rows, "relation": req.relation},
        )

    def buffer_query(self, request: BufferQueryInput | dict[str, Any]) -> dict[str, Any]:
        """在目标周围创建缓冲区，查询与缓冲区相交的图层要素。

        功能：将目标转换到 EPSG:3857，按指定距离创建缓冲区；将待查询
        要素也转换到 EPSG:3857 后判断相交，边界接触也算匹配。

        输入：request 为 BufferQueryInput 模型或同结构字典，包含：
            target：目标，使用图层名称加要素 ID/编码，或 GeoJSON 几何
                加 srid 指定；传入几何的 srid 默认 3857。
            distance_m：缓冲距离，单位为米，必须大于 0 且不超过 10000。
            query_layer_name：待查询的白名单图层名称。
            max_results：最多返回多少个要素，默认 20，范围 1～100。

        输出：成功时返回包含 status、tool、elapsed_ms、result、error
        的字典，其中 result 包含：
            distance_m：请求的缓冲距离。
            buffer：缓冲区的 GeoJSON 几何及 srid=3857；目标不存在时为 None。
            matched_count：全部匹配要素的数量。
            features：按要素 ID 排序并截取的公开属性、geometry 和 distance_m。
        要素 geometry 保留图层原坐标系；要素的 distance_m 是到缓冲区
        的最短距离，匹配要素因与缓冲区相交而为 0，不是到原始目标的距离。
        缓冲距离使用 EPSG:3857 平面单位，在不同纬度存在地面距离失真。
        """

        started = time.perf_counter()
        req = request if isinstance(request, BufferQueryInput) else BufferQueryInput(**request)
        layer = get_layer_spec(req.query_layer_name)
        target_sql, params = self._target_geometry_sql(req.target, alias="target")

        sql = f"""
        WITH target AS ({target_sql}),
        buffer AS (
            SELECT ST_Buffer(ST_Transform(geom, 3857), %s) AS geom_3857
            FROM target
        ),
        matched AS (
            SELECT f.*,
                   ST_Distance(ST_Transform(f.{self._q(layer.geom_column)}, 3857), b.geom_3857) AS distance_m,
                   ST_AsGeoJSON(f.{self._q(layer.geom_column)})::json AS geometry
            FROM {self._qualified(layer)} f
            CROSS JOIN buffer b
            WHERE ST_Intersects(ST_Transform(f.{self._q(layer.geom_column)}, 3857), b.geom_3857)
            ORDER BY f.{self._q(layer.id_column)}
        )
        SELECT COUNT(*) OVER() AS matched_count,
               {self._select_public_columns(layer)},
               ROUND(distance_m::numeric, 3) AS distance_m,
               geometry
        FROM matched
        LIMIT %s;
        """
        rows = self._fetch(sql, [*params, req.distance_m, req.max_results])
        total = rows[0]["matched_count"] if rows else 0
        for row in rows:
            row.pop("matched_count", None)

        buffer_sql = f"""
        WITH target AS ({target_sql})
        SELECT ST_AsGeoJSON(ST_Buffer(ST_Transform(geom, 3857), %s))::json AS geometry,
               3857 AS srid
        FROM target;
        """
        buffer_rows = self._fetch(buffer_sql, [*params, req.distance_m])
        return self._ok(
            "buffer_query",
            started,
            {
                "distance_m": req.distance_m,
                "buffer": buffer_rows[0] if buffer_rows else None,
                "matched_count": total,
                "features": rows,
            },
        )

    def clip_and_measure(self, request: ClipAndMeasureInput | dict[str, Any]) -> dict[str, Any]:
        """按目标区域裁剪图层要素，计算交集的长度或面积及合计值。

        功能：先筛选与目标相交的要素，再计算几何交集并剔除空几何。
        测量时提取交集中的线或面，转换到 EPSG:3857 后计算平面长度或面积。

        输入：request 为 ClipAndMeasureInput 模型或同结构字典，包含：
            layer_name：待裁剪的白名单图层名称。
            clip_target：裁剪目标，通常为面，可用已有图层要素或 GeoJSON
                几何指定；目标与待裁剪图层的 SRID 必须一致。
            measure：length 只测线长，area 只测面积；默认 auto，根据交集
                类型选择测量方式。auto 对点或几何集合等其他类型返回 0。

        输出：成功时返回包含 status、tool、elapsed_ms、result、error
        的字典。result 包含 measure、unit、feature_count（非空交集数量）、
        total_measure（各交集测量值之和）、features（按要素 ID 排序的明细）
        和 rules（测量规则）。每条明细包含原要素 ID/编码/名称、交集类型、
        measure_value 及裁剪后的 GeoJSON geometry，几何保留原坐标系。
        边界接触产生的点交集也会计数，但其长度、面积均为 0。
        长度单位为米，面积单位为平方米；当前 auto 的 unit 固定返回 meter，
        即使面交集实际计算的是面积，因此测面积时应显式指定 area。
        total_measure 直接求和，不会对不同要素间重叠的部分去重。
        """

        started = time.perf_counter()
        req = request if isinstance(request, ClipAndMeasureInput) else ClipAndMeasureInput(**request)
        layer = get_layer_spec(req.layer_name)
        target_sql, params = self._target_geometry_sql(req.clip_target, alias="target")

        measure_expr = self._measure_expression(req.measure)
        sql = f"""
        WITH target AS ({target_sql}),
        intersections AS (
            SELECT f.{self._q(layer.id_column)} AS feature_id,
                   f.{self._q(layer.code_column)} AS feature_code,
                   f.{self._q(layer.label_column)} AS feature_name,
                   GeometryType(ST_Intersection(f.{self._q(layer.geom_column)}, t.geom)) AS intersection_type,
                   ST_Intersection(f.{self._q(layer.geom_column)}, t.geom) AS geom
            FROM {self._qualified(layer)} f
            CROSS JOIN target t
            WHERE ST_Intersects(f.{self._q(layer.geom_column)}, t.geom)
        ),
        measured AS (
            SELECT feature_id,
                   feature_code,
                   feature_name,
                   intersection_type,
                   {measure_expr} AS measure_value,
                   ST_AsGeoJSON(geom)::json AS geometry
            FROM intersections
            WHERE NOT ST_IsEmpty(geom)
        )
        SELECT *,
               SUM(measure_value) OVER() AS total_measure
        FROM measured
        ORDER BY feature_id;
        """
        rows = self._fetch(sql, params)
        total = rows[0]["total_measure"] if rows else 0
        for row in rows:
            row.pop("total_measure", None)
        return self._ok(
            "clip_and_measure",
            started,
            {
                "measure": req.measure,
                "unit": "meter" if req.measure in {"auto", "length"} else "square_meter",
                "feature_count": len(rows),
                "total_measure": total,
                "features": rows,
                "rules": [
                    "线测量使用 ST_CollectionExtract(..., 2) 后按 EPSG:3857 计算长度。",
                    "面测量使用 ST_CollectionExtract(..., 3) 后按 EPSG:3857 计算面积。",
                    "点和非目标维度交集的测量值为 0。",
                ],
            },
        )

    def nearest_features(self, request: NearestFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """查询距离给定坐标点最近的若干要素，可限制最大搜索距离。

        功能：用输入坐标和 SRID 构造查询点；可先按最大距离筛选，再使用
        <-> 空间距离运算符执行 KNN 排序，返回距离最近的前 N 个要素。
        排序在图层坐标系下进行，返回距离在 EPSG:3857 下计算；当前白名单
        图层均为 EPSG:3857。距离指点到要素几何的最短距离，不是到其中心的距离。

        输入：request 为 NearestFeaturesInput 模型或同结构字典，包含：
            query_layer_name：待查询的白名单图层名称。
            x、y：查询点坐标；含义和单位由 srid 决定，例如 4326 时为经纬度。
            srid：输入坐标系编号，默认 3857，必须为正整数。
            limit：最多返回多少个要素，默认 5，范围 1～50。
            max_distance_m：可选最大搜索距离，单位为米，必须大于 0 且
                不超过 100000；默认 None，表示不限制搜索距离。

        输出：成功时返回包含 status、tool、elapsed_ms、result、error
        的字典。result.features 为按距离排序的要素列表，每项含公开属性、
        原图层坐标系下的 GeoJSON geometry 和保留三位小数的 distance_m；
        returned_count 为实际返回数量，used_knn_order=True 表示使用了 KNN
        排序，不代表数据库执行计划一定使用空间索引。没有符合条件的要素
        时返回空列表。距离采用 EPSG:3857 平面计算，存在随纬度变化的失真。
        """

        started = time.perf_counter()
        req = request if isinstance(request, NearestFeaturesInput) else NearestFeaturesInput(**request)
        layer = get_layer_spec(req.query_layer_name)
        radius_clause = ""
        params: list[Any] = [req.x, req.y, req.srid]
        if req.max_distance_m is not None:
            radius_clause = f"""
            WHERE ST_DWithin(
                ST_Transform(f.{self._q(layer.geom_column)}, 3857),
                ST_Transform(p.geom, 3857),
                %s
            )
            """
            params.append(req.max_distance_m)
        params.append(req.limit)

        sql = f"""
        WITH p AS (
            SELECT ST_SetSRID(ST_MakePoint(%s, %s), %s) AS geom
        )
        SELECT {self._select_public_columns(layer, alias="f")},
               ROUND(ST_Distance(
                   ST_Transform(f.{self._q(layer.geom_column)}, 3857),
                   ST_Transform(p.geom, 3857)
               )::numeric, 3) AS distance_m,
               ST_AsGeoJSON(f.{self._q(layer.geom_column)})::json AS geometry
        FROM {self._qualified(layer)} f
        CROSS JOIN p
        {radius_clause}
        ORDER BY f.{self._q(layer.geom_column)} <-> ST_Transform(p.geom, ST_SRID(f.{self._q(layer.geom_column)})),
                 distance_m ASC
        LIMIT %s;
        """
        rows = self._fetch(sql, params)
        return self._ok(
            "nearest_features",
            started,
            {"features": rows, "returned_count": len(rows), "used_knn_order": True},
        )

    def _fetch(self, sql: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
        with get_connection(self.database_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, list(params or []))
                return [self._normalize_row(row) for row in cur.fetchall()]

    def _target_geometry_sql(self, target: TargetGeometry, alias: str) -> tuple[str, list[Any]]:
        if target.geometry is not None:
            return (
                f"SELECT ST_SetSRID(ST_GeomFromGeoJSON(%s), %s) AS geom",
                [json.dumps(target.geometry), target.srid],
            )

        assert target.layer_name is not None
        layer = get_layer_spec(target.layer_name)
        if target.feature_id is not None:
            return (
                f"""
                SELECT {self._q(layer.geom_column)} AS geom
                FROM {self._qualified(layer)}
                WHERE {self._q(layer.id_column)} = %s
                """,
                [target.feature_id],
            )

        return (
            f"""
            SELECT {self._q(layer.geom_column)} AS geom
            FROM {self._qualified(layer)}
            WHERE {self._q(layer.code_column)} = %s
            """,
            [target.feature_code],
        )

    def _measure_expression(self, measure: str) -> str:
        if measure == "length":
            return "ST_Length(ST_Transform(ST_CollectionExtract(geom, 2), 3857))"
        if measure == "area":
            return "ST_Area(ST_Transform(ST_CollectionExtract(geom, 3), 3857))"
        return """
        CASE
            WHEN GeometryType(geom) ILIKE '%POLYGON%' THEN ST_Area(ST_Transform(ST_CollectionExtract(geom, 3), 3857))
            WHEN GeometryType(geom) ILIKE '%LINESTRING%' THEN ST_Length(ST_Transform(ST_CollectionExtract(geom, 2), 3857))
            ELSE 0
        END
        """

    def _select_public_columns(self, layer: LayerSpec, alias: str | None = None) -> str:
        prefix = f"{alias}." if alias else ""
        return ", ".join(f"{prefix}{self._q(column)}" for column in layer.public_columns)

    def _qualified(self, layer: LayerSpec) -> str:
        return f"{self._q(layer.schema_name)}.{self._q(layer.table_name)}"

    @staticmethod
    def _q(identifier: str) -> str:
        return quote_identifier(identifier)

    @staticmethod
    def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        for key, value in list(normalized.items()):
            if isinstance(value, str) and key in {"geometry", "geojson"}:
                normalized[key] = json.loads(value)
        return normalized

    @staticmethod
    def _ok(tool_name: str, started: float, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ok",
            "tool": tool_name,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "result": result,
            "error": None,
        }
