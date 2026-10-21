"""图层白名单、参数模型、PostGIS 工具与注册表；由原有模块顺序合并，不调整业务逻辑。"""
from __future__ import annotations

from app_development.db import get_settings, get_connection, quote_identifier

# ===== 来源：app/tools/layers.py =====

from dataclasses import dataclass


@dataclass(frozen=True)
class LayerSpec:
    name: str
    schema_name: str
    table_name: str
    geom_column: str = "geom"
    id_column: str = "id"
    code_column: str = "code"
    label_column: str = "name"
    public_columns: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


ALLOWED_LAYERS: dict[str, LayerSpec] = {
    "construction_areas": LayerSpec(
        name="construction_areas",
        schema_name="gis_lab",
        table_name="construction_areas",
        public_columns=("id", "code", "name", "area_type", "note"),
    ),
    "gas_pipelines": LayerSpec(
        name="gas_pipelines",
        schema_name="gis_lab",
        table_name="gas_pipelines",
        public_columns=("id", "code", "name", "pipe_type", "pressure_level", "note"),
    ),
    "gas_devices": LayerSpec(
        name="gas_devices",
        schema_name="gis_lab",
        table_name="gas_devices",
        public_columns=("id", "code", "name", "device_type", "status", "note"),
    ),
    "water_pipelines": LayerSpec(
        name="water_pipelines",
        schema_name="gis_lab",
        table_name="water_pipelines",
        public_columns=("id", "code", "name", "pipe_type", "note"),
    ),
    "demo_roads": LayerSpec(
        name="demo_roads",
        schema_name="gis_lab",
        table_name="demo_roads",
        public_columns=("id", "code", "name", "road_type", "note"),
    ),
}


def get_layer_spec(layer_name: str) -> LayerSpec:
    try:
        return ALLOWED_LAYERS[layer_name]
    except KeyError as exc:
        allowed = ", ".join(sorted(ALLOWED_LAYERS))
        raise ValueError(f"不允许访问的空间图层: {layer_name}。允许值: {allowed}") from exc


# ===== 来源：app/tools/schemas.py =====

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SpatialRelation = Literal["ST_Intersects", "ST_Within", "ST_Contains"]
GeometryType = Literal["Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"]


class TargetGeometry(BaseModel):
    """二选一：图层名称 + 一个要素标识，或 GeoJSON 几何 + 输入 SRID。"""

    model_config = ConfigDict(extra="forbid")

    layer_name: str | None = None
    feature_id: int | None = Field(default=None, ge=1)
    feature_code: str | None = None
    geometry: dict[str, Any] | None = None
    srid: int = Field(default=3857, ge=1, description="GeoJSON 坐标的真实 SRID；引用已有要素时使用数据库中的 SRID。")

    @model_validator(mode="after")
    def validate_source(self) -> "TargetGeometry":
        has_layer_fields = any(value is not None for value in (self.layer_name, self.feature_id, self.feature_code))
        if self.geometry is not None:
            if has_layer_fields:
                raise ValueError("GeoJSON 几何不能与 layer_name、feature_id 或 feature_code 混用")
            if "crs" in self.geometry:
                raise ValueError("请使用 srid 声明输入坐标系，不要在 GeoJSON 几何中重复声明 crs")
        else:
            if self.layer_name is None or not self.layer_name.strip():
                raise ValueError("引用已有要素时必须提供非空 layer_name")
            if (self.feature_id is None) == (self.feature_code is None):
                raise ValueError("feature_id 和 feature_code 必须且只能提供一个")
            if self.feature_code is not None and not self.feature_code.strip():
                raise ValueError("feature_code 不能为空")
        return self

class BufferGeometryInput(BaseModel):
    """只生成缓冲几何，不夹带图层查询。"""

    model_config = ConfigDict(extra="forbid")
    target: TargetGeometry
    distance_m: float = Field(gt=0, le=10000)


class IntersectionGeometryInput(BaseModel):
    """将两个目标转换到统一坐标系后求交集，允许空交集。"""

    model_config = ConfigDict(extra="forbid")
    left: TargetGeometry
    right: TargetGeometry
    target_srid: int = Field(default=3857, ge=1)


class MeasureGeometryInput(BaseModel):
    """测量单个几何，显式指定维度，空几何的值为零。"""

    model_config = ConfigDict(extra="forbid")
    target: TargetGeometry
    measure: Literal["length", "area"]


# ===== 来源：app/tools/feature_schemas.py =====

"""第四阶段的完整要素集合同；展示用的截断列表不能直接作为 FeatureSet。"""

from typing import Any, Literal
import math

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator



class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1)
    source_layer: str = Field(min_length=1)
    source_id: int = Field(ge=1)
    source_code: str = Field(min_length=1)
    source_keys: list[str] = Field(min_length=1)
    properties: dict[str, JsonValue]
    geometry: dict[str, Any]
    measure_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_geometry(self):
        if "crs" in self.geometry:
            raise ValueError("FeatureSet 使用统一 srid，不接受内嵌 crs")
        if not all(self.source_keys):
            raise ValueError("来源标识不能为空")
        return self


class FeatureSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    srid: int = Field(ge=1)
    is_complete: Literal[True]
    feature_count: int = Field(ge=0, le=10000)
    property_fields: list[str]
    features: list[Feature] = Field(max_length=10000)
    measure: Literal["length", "area"] | None = None
    unit: Literal["meter", "square_meter"] | None = None
    measure_srid: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_completeness(self):
        if self.feature_count != len(self.features):
            raise ValueError("FeatureSet 数量不一致，不能将截断结果视为完整要素集")
        if len(set(self.property_fields)) != len(self.property_fields):
            raise ValueError("属性字段不能重复")
        for feature in self.features:
            if set(feature.properties) != set(self.property_fields):
                raise ValueError("要素属性与 property_fields 不一致")
        if self.measure is None:
            if self.unit is not None or self.measure_srid is not None or any(f.measure_value is not None for f in self.features):
                raise ValueError("未测量要素集不能携带过期的测量值或单位")
        else:
            expected = "meter" if self.measure == "length" else "square_meter"
            if self.unit != expected or self.measure_srid is None or any(f.measure_value is None for f in self.features):
                raise ValueError("测量方式、单位、坐标系和明细值必须一致")
        return self


class AttributeFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1)
    operator: Literal["eq", "ne", "in", "not_in", "gt", "ge", "lt", "le", "is_null", "is_not_null"] = "eq"
    value: str | int | float | bool | list[str | int | float | bool] | None = None

    @model_validator(mode="after")
    def check_value(self):
        values = self.value if isinstance(self.value, list) else [self.value]
        if any(isinstance(value, float) and not math.isfinite(value) for value in values):
            raise ValueError("筛选值不能是 NaN 或无穷大")
        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= 1000:
                raise ValueError("in/not_in 需要非空且不超过 1000 项的列表")
        elif isinstance(self.value, list):
            raise ValueError("该操作符不接受列表")
        if self.operator in {"is_null", "is_not_null"} and self.value is not None:
            raise ValueError("空值操作符不接受 value")
        if self.operator in {"gt", "ge", "lt", "le"} and self.value is None:
            raise ValueError("范围比较不能使用空值")
        return self


class QueryFeaturesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer_name: str
    filters: list[AttributeFilter] = Field(default_factory=list, max_length=50)
    target: TargetGeometry | None = None
    relation: SpatialRelation | None = None
    max_features: int = Field(default=10000, ge=1, le=10000)

    @model_validator(mode="after")
    def check_spatial_filter(self):
        if (self.target is None) != (self.relation is None):
            raise ValueError("空间筛选必须同时提供 target 和 relation")
        return self


class BufferFeaturesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: FeatureSet
    distance_m: float = Field(gt=0, le=10000)


class UnionFeaturesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: FeatureSet
    target_srid: int = Field(default=3857, ge=1)


class ClipFeaturesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: FeatureSet
    clip_target: TargetGeometry
    keep_empty: bool = False


class MeasureFeaturesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: FeatureSet
    measure: Literal["length", "area"]


class SummarizeFeaturesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: FeatureSet
    group_by: list[str] = Field(default_factory=list, max_length=8)
    aggregate: Literal["sum", "count"] = "sum"
    deduplicate: bool = True
    sort: Literal["value_desc", "value_asc", "group_asc"] = "value_desc"

    @model_validator(mode="after")
    def check_grouping(self):
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("分组字段不能重复")
        allowed = set(self.features.property_fields) | {"source_layer", "source_id", "source_code"}
        if not set(self.group_by) <= allowed:
            raise ValueError("不允许的分组字段")
        if self.aggregate == "sum" and self.features.measure is None:
            raise ValueError("sum 汇总前必须先 measure_features")
        return self


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: Literal["meter", "square_meter"]
    measure_srid: int = Field(default=3857, ge=1)
    measure: Literal["length", "area"] | None = None
    is_empty: bool | None = None
    feature_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_dimension(self):
        if self.measure is not None and self.unit != ("meter" if self.measure == "length" else "square_meter"):
            raise ValueError("测量方式和单位不一致")
        return self


class CalculateRatioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numerator: Measurement
    denominator: Measurement
    scale: Literal["percent", "fraction"] = "percent"

    @model_validator(mode="after")
    def check_units(self):
        if self.denominator.value <= 0:
            raise ValueError("比例分母必须大于 0")
        if (self.numerator.unit, self.numerator.measure_srid) != (self.denominator.unit, self.denominator.measure_srid):
            raise ValueError("比例两侧的单位和测量坐标系必须一致")
        return self


# ===== 来源：app/tools/postgis_tools.py =====

import json
import time
from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg.rows import dict_row



class TargetNotFoundError(ValueError):
    """目标要素不存在；与目标存在但查询结果为空区分。"""


class PostGISToolkit:
    """PostGIS 单几何工具与共享辅助方法。

    设计目标是直接、可读、可测试。LLM 只能调用这些方法，不能直接执行任意 SQL。
    """

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or get_settings().database_url

    def buffer_geometry(self, request: BufferGeometryInput | dict[str, Any]) -> dict[str, Any]:
        """仅生成缓冲几何，供后续步骤使用，不查询其他图层。

        输入：target 为已有要素或 GeoJSON + SRID，distance_m 为 (0, 10000] 米。
        输出：result.geometry 是可直接作为下一步 target 的 {geometry, srid}；
        另有 geometry_type、is_empty、is_valid、distance_m 和 quad_segs。
        统一在 EPSG:3857 计算，固定 quad_segs=8（圆弧折线近似）；不修复无效输入。
        空目标得到空缓冲，按合法结果继续传递。
        """
        started = time.perf_counter()
        req = request if isinstance(request, BufferGeometryInput) else BufferGeometryInput(**request)
        target_sql, params = self._prepare_target(req.target, 3857, allow_empty=True)
        sql = f"""
        WITH target AS ({target_sql})
        SELECT ST_Buffer(geom, %s, 'quad_segs=8') AS geom FROM target
        """
        result = self._geometry_result(sql, [*params, req.distance_m])
        result.update(distance_m=req.distance_m, quad_segs=8)
        return self._ok("buffer_geometry", started, result)

    def intersection_geometry(self, request: IntersectionGeometryInput | dict[str, Any]) -> dict[str, Any]:
        """对两个几何求交集，保留用于下一步操作的几何和 SRID。

        输入：left、right 为两个目标，target_srid 为求交坐标系，默认 3857。
        输出：result.geometry={geometry, srid}，以及 geometry_type、is_empty、is_valid。
        两个目标先实际转换坐标再求交；不相交返回合法空几何，而不是缺失目标错误。
        空结果统一编码为 GeometryCollection EMPTY，避免不同空几何的 GeoJSON 差异。
        """
        started = time.perf_counter()
        req = request if isinstance(request, IntersectionGeometryInput) else IntersectionGeometryInput(**request)
        self._validate_srid(req.target_srid)
        left_sql, left_params = self._prepare_target(req.left, req.target_srid, allow_empty=True)
        right_sql, right_params = self._prepare_target(req.right, req.target_srid, allow_empty=True)
        sql = f"""
        WITH left_target AS ({left_sql}), right_target AS ({right_sql})
        SELECT ST_Intersection(l.geom, r.geom) AS geom
        FROM left_target l CROSS JOIN right_target r
        """
        result = self._geometry_result(sql, [*left_params, *right_params])
        return self._ok("intersection_geometry", started, result)

    def measure_geometry(self, request: MeasureGeometryInput | dict[str, Any]) -> dict[str, Any]:
        """量测一个几何的线长或面积，不包含筛选、裁剪或跨要素汇总。

        输入：target 为几何或已有要素；measure 必须明确为 length 或 area。
        输出：result.value、unit、measure、measure_srid=3857 和 is_empty。
        提取对应维度并在 EPSG:3857 平面量测；空几何和非对应维度的部分值为 0。
        """
        started = time.perf_counter()
        req = request if isinstance(request, MeasureGeometryInput) else MeasureGeometryInput(**request)
        target_sql, params = self._prepare_target(req.target, 3857, allow_empty=True)
        sql = f"""
        WITH target AS ({target_sql})
        SELECT {self._measure_expression(req.measure)} AS value, ST_IsEmpty(geom) AS is_empty FROM target
        """
        row = self._fetch(sql, params)[0]
        return self._ok("measure_geometry", started, {
            "value": row["value"],
            "unit": "meter" if req.measure == "length" else "square_meter",
            "measure": req.measure,
            "measure_srid": 3857,
            "is_empty": row["is_empty"],
        })

    def _geometry_result(self, geometry_sql: str, params: list[Any]) -> dict[str, Any]:
        """组合工具的几何合同；不截断顶点，SRID 独立传递，不内嵌 crs。"""
        rows = self._fetch(f"""
            WITH computed AS ({geometry_sql}), normalized AS (
                SELECT CASE WHEN ST_IsEmpty(geom)
                            THEN ST_GeomFromText('GEOMETRYCOLLECTION EMPTY', ST_SRID(geom))
                            ELSE geom END AS geom
                FROM computed
            )
            SELECT ST_AsGeoJSON(geom, 15, 0)::json AS geometry, ST_SRID(geom) AS srid,
                   GeometryType(geom) AS geometry_type, ST_IsEmpty(geom) AS is_empty,
                   ST_IsValid(geom) AS is_valid
            FROM normalized
        """, params)
        row = rows[0]
        if not row["is_valid"]:
            raise ValueError("空间运算生成了无效几何，不自动修复，请检查输入与精度")
        return {
            "geometry": {"geometry": row["geometry"], "srid": row["srid"]},
            "geometry_type": row["geometry_type"],
            "is_empty": row["is_empty"],
            "is_valid": row["is_valid"],
        }

    def _fetch(self, sql: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
        with get_connection(self.database_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, list(params or []))
                return [self._normalize_row(row) for row in cur.fetchall()]

    def _layer_geometry_info(self, layer: LayerSpec) -> dict[str, Any]:
        """从数据库读取声明的类型与 SRID，避免在 Python 中维护第二套元数据。"""
        rows = self._fetch(
            """
            SELECT type AS geometry_type, srid
            FROM geometry_columns
            WHERE f_table_schema = %s AND f_table_name = %s AND f_geometry_column = %s
            """,
            [layer.schema_name, layer.table_name, layer.geom_column],
        )
        if not rows:
            raise ValueError(f"图层 {layer.name} 缺少空间字段元数据")
        self._validate_srid(rows[0]["srid"])
        return rows[0]

    def _validate_srid(self, srid: int) -> None:
        if srid <= 0 or not self._fetch("SELECT srid FROM spatial_ref_sys WHERE srid = %s", [srid]):
            raise ValueError(f"未知或未定义的 SRID: {srid}，请使用 spatial_ref_sys 中已注册的坐标系")

    def _prepare_target(
        self, target: TargetGeometry, output_srid: int, *, allow_empty: bool = False
    ) -> tuple[str, list[Any]]:
        """先检查目标，再以 EWKB 快照传递并转换坐标，避免重复查找和 SRID 误贴标签。

        已有要素以数据库实际 SRID 为准；srid 参数仅用于声明 GeoJSON 坐标。
        空查询结果属于目标不存在，不能当作正常的零匹配。此处不自动修复几何。
        """
        if target.geometry is not None:
            self._validate_srid(target.srid)
        sql, params = self._target_geometry_sql(target)
        try:
            rows = self._fetch(
                f"""
                WITH target AS ({sql})
                SELECT ST_AsEWKB(geom) AS geom_ewkb, ST_SRID(geom) AS srid,
                       ST_IsEmpty(geom) AS is_empty, ST_IsValid(geom) AS is_valid,
                       ST_IsValidReason(geom) AS validity_reason
                FROM target
                """,
                params,
            )
        except psycopg.DataError as exc:
            raise ValueError("目标几何解析失败，请提供合法的 GeoJSON Geometry，而不是 Feature 或 FeatureCollection") from exc
        except psycopg.InternalError as exc:
            raise ValueError("目标几何解析失败，请检查 GeoJSON 的类型、坐标和环结构") from exc
        if not rows:
            identifier = target.feature_id if target.feature_id is not None else target.feature_code
            raise TargetNotFoundError(f"目标要素不存在: {target.layer_name} / {identifier}")
        row = rows[0]
        if row["geom_ewkb"] is None or (row["is_empty"] and not allow_empty):
            raise ValueError("目标几何不能为空")
        if not row["is_valid"]:
            raise ValueError(f"目标几何无效: {row['validity_reason']}")
        self._validate_srid(row["srid"])
        geom_ewkb = row["geom_ewkb"]
        if row["srid"] != output_srid:
            try:
                transformed = self._fetch(
                    "SELECT ST_AsEWKB(ST_Transform(ST_GeomFromEWKB(%s), %s)) AS geom_ewkb",
                    [geom_ewkb, output_srid],
                )
            except (psycopg.DataError, psycopg.InternalError) as exc:
                raise ValueError(
                    f"目标坐标转换失败: EPSG:{row['srid']} → EPSG:{output_srid}，请检查真实坐标系和坐标范围"
                ) from exc
            geom_ewkb = transformed[0]["geom_ewkb"]
        return "SELECT ST_GeomFromEWKB(%s) AS geom", [geom_ewkb]

    def _target_geometry_sql(self, target: TargetGeometry) -> tuple[str, list[Any]]:
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
        raise ValueError(f"测量方式尚未解析: {measure}")

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


# ===== 来源：app/tools/feature_tools.py =====

"""完整要素集的批量操作；参数化 SQL、来源保留、超限失败，不使用展示截断结果。"""

import json
import math
import time
from typing import Any, cast

import psycopg



class FeatureSetToolkit(PostGISToolkit):
    """继承三个单几何组合工具，额外提供完整要素集操作。"""

    @staticmethod
    def _dataset(features: list[Feature], srid: int, fields: list[str], measure: str | None = None) -> FeatureSet:
        return FeatureSet.model_validate({
            "features": features, "srid": srid, "is_complete": True,
            "feature_count": len(features), "property_fields": fields, "measure": measure,
            "unit": None if measure is None else ("meter" if measure == "length" else "square_meter"),
            "measure_srid": 3857 if measure else None,
        })

    @staticmethod
    def _canonical_geometry(expression: str) -> str:
        return f"CASE WHEN ST_IsEmpty({expression}) THEN ST_GeomFromText('GEOMETRYCOLLECTION EMPTY', ST_SRID({expression})) ELSE {expression} END"

    def query_features(self, request: QueryFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """按公开属性（AND）和可选空间关系查询完整要素集。

        输入：白名单 layer_name、结构化 filters；空间条件必须同时有 target/relation。
        输出：result.feature_set，含全部匹配几何、属性、来源与 SRID。
        max_features 为安全上限而非返回条数：超过即报错，不返回截断数据。
        """
        started = time.perf_counter()
        req = request if isinstance(request, QueryFeaturesInput) else QueryFeaturesInput(**request)
        layer = get_layer_spec(req.layer_name)
        clauses, filter_params = [], []
        operators = {"eq": "=", "ne": "<>", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}
        for condition in req.filters:
            if condition.field not in layer.public_columns:
                raise ValueError(f"不允许筛选字段: {condition.field}")
            column = f"f.{self._q(condition.field)}"
            op, value = condition.operator, condition.value
            if op in {"is_null", "is_not_null"} or (value is None and op in {"eq", "ne"}):
                clauses.append(f"{column} IS {'NOT ' if op in {'is_not_null', 'ne'} else ''}NULL")
            elif op in {"in", "not_in"}:
                clauses.append(f"{column} {'= ANY' if op == 'in' else '<> ALL'}(%s)")
                filter_params.append(value)
            else:
                clauses.append(f"{column} {operators[op]} %s")
                filter_params.append(value)
        info = self._layer_geometry_info(layer)
        prefix, join, params = "", "", []
        if req.target is not None:
            target_sql, params = self._prepare_target(req.target, info["srid"], allow_empty=True)
            prefix, join = f"WITH target AS ({target_sql})", "CROSS JOIN target t"
            clauses.append(f"{req.relation}(f.{self._q(layer.geom_column)}, t.geom)")
        geom = f"f.{self._q(layer.geom_column)}"
        sql = f"""
        {prefix}
        SELECT {self._select_public_columns(layer, alias='f')},
               ST_AsGeoJSON({self._canonical_geometry(geom)}, 15, 0)::json AS geometry,
               ST_IsValid({geom}) AS geometry_valid
        FROM {self._qualified(layer)} f {join}
        WHERE {' AND '.join(clauses) if clauses else 'TRUE'}
        ORDER BY f.{self._q(layer.id_column)} LIMIT %s
        """
        rows = self._fetch(sql, [*params, *filter_params, req.max_features + 1])
        if len(rows) > req.max_features:
            raise ValueError(f"完整要素集超过安全上限 {req.max_features}，请收紧条件；未返回截断结果")
        features = []
        for row in rows:
            if not row["geometry_valid"]:
                raise ValueError(f"源要素几何无效: {layer.name}/{row[layer.code_column]}")
            key = f"{layer.name}:{row[layer.id_column]}"
            features.append(Feature(
                key=key, source_layer=layer.name, source_id=row[layer.id_column], source_code=row[layer.code_column],
                source_keys=[key], properties={name: row[name] for name in layer.public_columns}, geometry=row["geometry"],
            ))
        dataset = self._dataset(features, info["srid"], list(layer.public_columns))
        return self._ok("query_features", started, {"feature_set": dataset.model_dump()})

    def _feature_sql(self, dataset: FeatureSet) -> tuple[str, list[Any]]:
        self._validate_srid(dataset.srid)
        sql = """
        SELECT (e.ordinality - 1)::int AS position,
               ST_SetSRID(ST_GeomFromGeoJSON(e.value -> 'geometry'), %s) AS geom
        FROM jsonb_array_elements(%s::jsonb) WITH ORDINALITY AS e(value, ordinality)
        """
        params = [dataset.srid, json.dumps([{"geometry": f.geometry} for f in dataset.features], allow_nan=False)]
        try:
            checks = self._fetch(f"WITH input AS ({sql}) SELECT position, ST_IsValid(geom) AS valid FROM input", params)
        except (psycopg.DataError, psycopg.InternalError) as exc:
            raise ValueError("要素集几何解析失败，请检查 GeoJSON") from exc
        for row in checks:
            if not row["valid"]:
                raise ValueError(f"要素集含无效几何: {dataset.features[row['position']].key}")
        return sql, params

    def _geometry_rows(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        return self._fetch(f"""
            WITH computed AS ({sql})
            SELECT position, ST_AsGeoJSON({self._canonical_geometry('geom')}, 15, 0)::json AS geometry,
                   ST_IsValid(geom) AS valid
            FROM computed ORDER BY position
        """, params)

    def _rebuild(self, source: FeatureSet, rows: list[dict[str, Any]], srid: int) -> FeatureSet:
        features = []
        for row in rows:
            if not row["valid"]:
                raise ValueError("批量空间操作生成无效几何，不自动修复")
            value = source.features[row["position"]].model_dump()
            value.update(geometry=row["geometry"], measure_value=None)
            features.append(Feature.model_validate(value))
        return self._dataset(features, srid, source.property_fields)

    def buffer_features(self, request: BufferFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """逐要素生成 3857 缓冲，保留来源标识与属性，固定 quad_segs=8。"""
        started = time.perf_counter()
        req = request if isinstance(request, BufferFeaturesInput) else BufferFeaturesInput(**request)
        source_sql, params = self._feature_sql(req.features)
        sql = f"WITH input AS ({source_sql}) SELECT position, ST_Buffer(ST_Transform(geom,3857), %s, 'quad_segs=8') AS geom FROM input"
        result = self._rebuild(req.features, self._geometry_rows(sql, [*params, req.distance_m]), 3857)
        return self._ok("buffer_features", started, {"feature_set": result.model_dump(), "quad_segs": 8})

    def union_features(self, request: UnionFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """将全部几何合并去除空间重叠，返回单几何及来源集合；空集返回合法空几何。"""
        started = time.perf_counter()
        req = request if isinstance(request, UnionFeaturesInput) else UnionFeaturesInput(**request)
        self._validate_srid(req.target_srid)
        source_sql, params = self._feature_sql(req.features)
        sql = f"""
        WITH input AS ({source_sql})
        SELECT COALESCE(ST_UnaryUnion(ST_Collect(ST_Transform(geom,%s))),
                        ST_GeomFromText('GEOMETRYCOLLECTION EMPTY',%s)) AS geom FROM input
        """
        result = self._geometry_result(sql, [*params, req.target_srid, req.target_srid])
        keys = sorted({key for f in req.features.features for key in f.source_keys})
        result.update(source_keys=keys, source_feature_count=len(keys), input_count=req.features.feature_count)
        return self._ok("union_features", started, result)

    def clip_features(self, request: ClipFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """逐要素求交，保留原编码与来源；默认移除空几何，边界点/线交集仍保留。"""
        started = time.perf_counter()
        req = request if isinstance(request, ClipFeaturesInput) else ClipFeaturesInput(**request)
        source_sql, params = self._feature_sql(req.features)
        target_sql, target_params = self._prepare_target(req.clip_target, req.features.srid, allow_empty=True)
        sql = f"""
        WITH input AS ({source_sql}), target AS ({target_sql}), clipped AS (
            SELECT position, ST_Intersection(i.geom,t.geom) AS geom FROM input i CROSS JOIN target t
        ) SELECT position, geom FROM clipped {'WHERE NOT ST_IsEmpty(geom)' if not req.keep_empty else ''}
        """
        result = self._rebuild(req.features, self._geometry_rows(sql, [*params, *target_params]), req.features.srid)
        return self._ok("clip_features", started, {"feature_set": result.model_dump()})

    def measure_features(self, request: MeasureFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """每个要素分别量测并求和，不自动空间合并；返回要素集与小型 summary。"""
        started = time.perf_counter()
        req = request if isinstance(request, MeasureFeaturesInput) else MeasureFeaturesInput(**request)
        source_sql, params = self._feature_sql(req.features)
        rows = self._fetch(f"WITH input AS ({source_sql}) SELECT position, {self._measure_expression(req.measure)} AS value FROM input ORDER BY position", params)
        features = []
        for row in rows:
            value = req.features.features[row["position"]].model_dump()
            value["measure_value"] = row["value"]
            features.append(Feature.model_validate(value))
        result = self._dataset(features, req.features.srid, req.features.property_fields, req.measure)
        summary = {"value": math.fsum(cast(float, f.measure_value) for f in result.features), "unit": result.unit,
                   "measure": req.measure, "measure_srid": 3857, "feature_count": result.feature_count}
        return self._ok("measure_features", started, {"feature_set": result.model_dump(), "summary": summary})

    def summarize_features(self, request: SummarizeFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """按身份去重、分组求和/计数、全量排序；身份去重不等于几何空间合并。"""
        started = time.perf_counter()
        req = request if isinstance(request, SummarizeFeaturesInput) else SummarizeFeaturesInput(**request)
        rows, seen = [], {}
        for feature in req.features.features:
            if req.deduplicate and feature.key in seen:
                if feature != seen[feature.key]:
                    raise ValueError(f"同一 key 的要素内容冲突，不能任意去重: {feature.key}")
                continue
            seen[feature.key] = feature
            rows.append(feature)
        groups: dict[str, dict[str, Any]] = {}
        for feature in rows:
            group = {name: getattr(feature, name) if name in {"source_layer", "source_id", "source_code"}
                     else feature.properties[name] for name in req.group_by}
            if any(isinstance(value, (dict, list)) for value in group.values()):
                raise ValueError("分组值必须为标量")
            key = json.dumps(group, sort_keys=True, ensure_ascii=False, allow_nan=False)
            bucket = groups.setdefault(key, {"group": group, "values": [], "feature_count": 0})
            bucket["values"].append(feature.measure_value if req.aggregate == "sum" else 1)
            bucket["feature_count"] += 1
        result = [{"group": b["group"], "value": math.fsum(b["values"]), "feature_count": b["feature_count"]}
                  for b in groups.values()]
        def group_key(row):
            def scalar_key(value):
                if value is None:
                    return (0, "")
                if isinstance(value, bool):
                    return (1, value)
                if isinstance(value, (int, float)):
                    return (2, value)
                return (3, value)
            return tuple(scalar_key(row["group"][field]) for field in req.group_by)
        result.sort(key=lambda row: ((-row["value"] if req.sort == "value_desc" else row["value"]), group_key(row))
                    if req.sort != "group_asc" else (group_key(row),))
        return self._ok("summarize_features", started, {
            "groups": result, "aggregate": req.aggregate, "unit": req.features.unit if req.aggregate == "sum" else "feature",
            "measure_srid": req.features.measure_srid if req.aggregate == "sum" else None,
            "input_count": req.features.feature_count, "unique_count": len({f.key for f in rows}),
            "retained_count": len(rows), "group_count": len(result),
        })

    def calculate_ratio(self, request: CalculateRatioInput | dict[str, Any]) -> dict[str, Any]:
        """计算同单位、同测量坐标系的比例；拒绝零分母，不钳制超过 100% 的结果。"""
        started = time.perf_counter()
        req = request if isinstance(request, CalculateRatioInput) else CalculateRatioInput(**request)
        value = req.numerator.value / req.denominator.value * (100 if req.scale == "percent" else 1)
        if not math.isfinite(value):
            raise ValueError("比例结果超出有限数值范围")
        return self._ok("calculate_ratio", started, {"value": value, "unit": req.scale,
                        "numerator": req.numerator.value, "denominator": req.denominator.value})


# ===== 来源：app/tools/registry.py =====

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel


#定义工具的调用方式：无参数 关键字参数 参数模型对象
ToolInvocation = Literal["none", "kwargs", "request"]
Toolset = Literal["composable", "advanced"]


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


COMPOSABLE_TOOL_REGISTRY: dict[str, ToolSpec] = {
    "buffer_geometry": ToolSpec(
        name="buffer_geometry",
        method_name="buffer_geometry",
        args_schema=BufferGeometryInput,
        description="Create only a buffer geometry in EPSG:3857. Return geometry and SRID together for later steps.",
        invocation="request",
    ),
    "intersection_geometry": ToolSpec(
        name="intersection_geometry",
        method_name="intersection_geometry",
        args_schema=IntersectionGeometryInput,
        description="Transform two geometries to target_srid and return their intersection, including valid empty results.",
        invocation="request",
    ),
    "measure_geometry": ToolSpec(
        name="measure_geometry",
        method_name="measure_geometry",
        args_schema=MeasureGeometryInput,
        description="Measure one geometry in EPSG:3857. Explicitly select length or area. Empty geometry measures zero.",
        invocation="request",
    ),
}


ADVANCED_TOOL_REGISTRY: dict[str, ToolSpec] = {
    **COMPOSABLE_TOOL_REGISTRY,
    "query_features": ToolSpec("query_features", "query_features", QueryFeaturesInput,
        "Query a COMPLETE FeatureSet using whitelisted attribute AND filters and optional spatial target/relation. Returns result.feature_set. Exceeding max_features is an error, never a truncated result.", "request"),
    "buffer_features": ToolSpec("buffer_features", "buffer_features", BufferFeaturesInput,
        "Buffer every feature in EPSG:3857, preserving source IDs/properties. Returns result.feature_set. Does not merge overlap.", "request"),
    "union_features": ToolSpec("union_features", "union_features", UnionFeaturesInput,
        "Union all feature geometries to remove spatial overlap. Returns result.geometry (geometry+srid), source_keys and source_feature_count. Empty input produces valid empty geometry.", "request"),
    "clip_features": ToolSpec("clip_features", "clip_features", ClipFeaturesInput,
        "Clip each feature by clip_target, retaining codes and provenance. Returns result.feature_set. Drops empty intersections by default, but preserves boundary contacts.", "request"),
    "measure_features": ToolSpec("measure_features", "measure_features", MeasureFeaturesInput,
        "Measure each feature with explicit length/area. Returns result.feature_set with measure_value per feature and result.summary (value/unit/measure/measure_srid/feature_count). Sum is not a spatial union.", "request"),
    "summarize_features": ToolSpec("summarize_features", "summarize_features", SummarizeFeaturesInput,
        "Deduplicate by key, group by source metadata or public properties, aggregate sum/count, and sort all groups. Sum requires a measured FeatureSet. Returns result.groups and unit; no implicit top-20 limit.", "request"),
    "calculate_ratio": ToolSpec("calculate_ratio", "calculate_ratio", CalculateRatioInput,
        "Calculate a percent or fraction from two measurement objects with matching units/SRID. Rejects zero denominator. Reference whole measure_geometry.result or measure_features.result.summary, not bare numbers.", "request"),
}


def get_tool_registry(toolset: Toolset = "composable") -> dict[str, ToolSpec]:
    if toolset == "composable":
        return COMPOSABLE_TOOL_REGISTRY
    if toolset == "advanced":
        return ADVANCED_TOOL_REGISTRY
    raise ValueError(f"Unsupported toolset: {toolset}")


def create_toolkit(toolset: Toolset = "composable", database_url: str | None = None):
    """按工具集选择单几何或高级实现类。"""
    get_tool_registry(toolset)
    if toolset == "advanced":
        return FeatureSetToolkit(database_url=database_url)
    return PostGISToolkit(database_url=database_url)


#按名称查找工具，不存在时抛出异常
def get_tool_spec(name: str, *, toolset: Toolset = "composable") -> ToolSpec:
    registry = get_tool_registry(toolset)
    try:
        return registry[name]
    except KeyError as exc:
        allowed = ", ".join(sorted(registry))
        raise ValueError(f"Unsupported PostGIS tool: {name}. Allowed tools: {allowed}") from exc

#生成全部工具的LLM函数调用定义
def postgis_tool_definitions(*, toolset: Toolset = "composable") -> list[dict[str, Any]]:
    return [spec.llm_definition() for spec in get_tool_registry(toolset).values()]

#返回所有工具名称的集合
def postgis_tool_names(*, toolset: Toolset = "composable") -> set[str]:
    return set(get_tool_registry(toolset))

#将 Pydantic 模型转换成描述参数结构的 JSON Schema
def _tool_parameters_schema(args_schema: type[BaseModel]) -> dict[str, Any]:
    schema = args_schema.model_json_schema()
    schema.pop("title", None)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    _add_layer_enums(schema)
    return schema

#递归遍历 JSON Schema，为图层名称字段补充白名单枚举
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
