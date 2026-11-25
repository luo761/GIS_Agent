"""项目内置 PostGIS 工具集：图层白名单、参数模型、空间运算与工具定义。

由 source/tool.py 迁入，数据库连接与配置统一使用本项目模块。
"""
from __future__ import annotations

from config import settings
from tools.db import get_connection, quote_identifier

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
        schema_name=settings.APP_SCHEMA,
        table_name="construction_areas",
        public_columns=("id", "code", "name", "area_type", "note"),
    ),
    "gas_pipelines": LayerSpec(
        name="gas_pipelines",
        schema_name=settings.APP_SCHEMA,
        table_name="gas_pipelines",
        public_columns=("id", "code", "name", "pipe_type", "pressure_level", "note"),
    ),
    "gas_devices": LayerSpec(
        name="gas_devices",
        schema_name=settings.APP_SCHEMA,
        table_name="gas_devices",
        public_columns=("id", "code", "name", "device_type", "status", "note"),
    ),
    "water_pipelines": LayerSpec(
        name="water_pipelines",
        schema_name=settings.APP_SCHEMA,
        table_name="water_pipelines",
        public_columns=("id", "code", "name", "pipe_type", "note"),
    ),
    "demo_roads": LayerSpec(
        name="demo_roads",
        schema_name=settings.APP_SCHEMA,
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
    """这个模型用 Pydantic 的字段约束 + 模型级校验器，强制用户要么引用数据库里的已有要素（图层名 + ID/编码），要么传入 GeoJSON 几何
    （+ 外层 SRID），两种路径互斥且各自有完整的必填项校验。"""

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
    # 禁止在 Feature 模型顶层传入未声明的字段。
    model_config = ConfigDict(extra="forbid")
    # 要素标识，供去重和追踪使用；查询时通常按“源图层:源主键”生成，如 gas_devices:1。
    key: str = Field(min_length=1)
    # 原始要素所在图层的名称，如 gas_devices；缓冲、裁剪后仍保留来源。
    source_layer: str = Field(min_length=1)
    # 原始要素在数据库中的主键 ID，必须大于等于 1。
    source_id: int = Field(ge=1)
    # 原始要素的业务编码，如 D011，用于展示、追踪和按源对象分组。
    source_code: str = Field(min_length=1)
    # 原始要素标识列表，用于追踪数据来源；至少一项，且每项都不能为空字符串。
    source_keys: list[str] = Field(min_length=1)
    # 属性字典（字段名 → JSON 值），键集合须与所属 FeatureSet.property_fields 一致。
    properties: dict[str, JsonValue]
    # GeoJSON 几何字典，坐标系由所属 FeatureSet.srid 统一声明，不允许内嵌 crs。
    geometry: dict[str, Any]
    # 当前要素的长度或面积；未量测时为 None，量测后为非负有限数，单位见集合的 unit。
    measure_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_geometry(self):
        if "crs" in self.geometry:
            raise ValueError("FeatureSet 使用统一 srid，不接受内嵌 crs")
        if not all(self.source_keys):
            raise ValueError("来源标识不能为空")
        return self


class FeatureSet(BaseModel):
    # 禁止在 FeatureSet 模型顶层传入未声明的字段。
    model_config = ConfigDict(extra="forbid")
    # 所有要素几何共同使用的坐标参考系编号（SRID），必须为正整数。
    srid: int = Field(ge=1)
    # 完整性声明，必须为 True；工具需保证集合完整，不能用截断列表冒充完整结果。
    is_complete: Literal[True]
    # 要素数量，范围为 0～10000，且必须等于 features 列表的实际长度。
    feature_count: int = Field(ge=0, le=10000)
    # 集合统一的属性字段名列表，不可重复；每个要素的 properties 必须使用同一组字段。
    property_fields: list[str]
    # 要素明细列表，每项为一个 Feature；允许空集合，最多包含 10000 项。
    features: list[Feature] = Field(max_length=10000)
    # 当前量测类型：length 为长度、area 为面积；None 表示尚未量测，不得残留量测数据。
    measure: Literal["length", "area"] | None = None
    # 量测单位：length 对应 meter，area 对应 square_meter；未量测时必须为 None。
    unit: Literal["meter", "square_meter"] | None = None
    # 量测使用的 SRID，可与几何的 srid 不同；量测后必须提供正整数，未量测时为 None。
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
        self.database_url = database_url or settings.DATABASE_URL

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
        """执行几何运算 SQL，将结果整理成组合工具统一使用的几何结构。

        输入：geometry_sql 是内部构造的 SQL，预期返回一行名为 geom 的几何字段；
        params 是其中 %s 占位符对应的参数，按占位符顺序传入。
        输出：包含 geometry、geometry_type、is_empty、is_valid 的字典。
        外层 geometry 是 {geometry: GeoJSON 几何, srid: 坐标系编号}，
        内层 geometry 才是具体的 GeoJSON 几何对象（如 type、coordinates），
        这样下一步便能把几何与 SRID 一起引用。
        不截断顶点数量，GeoJSON 不内嵌 crs；无效几何直接报错，不自动修复。
        """
        # computed 执行传入的运算；normalized 将不同类型的空结果统一为空几何集合，保留 SRID。
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
        # 当前调用方均按单个几何组织 SQL，因此取第一行，而不是返回整个行列表。
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
        """执行参数化 SQL，并把查询结果读取为字典列表。

        输入：sql 为 SQL 文本；params 为占位符参数，可省略，省略时使用空列表。
        输出：每行对应一个“列名 → 值”的字典；查询没有匹配行时返回 []。
        本函数负责访问数据库，其他只生成 SQL 字符串的函数并不会自动执行查询。
        """
        # with 管理连接和游标的生命周期；dict_row 让查询行可以用 row["字段名"] 访问。
        with get_connection(self.database_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # 值由驱动绑定到 %s，不把用户输入的值直接拼进 SQL 文本。
                cur.execute(sql, list(params or []))
                # fetchall 读取全部查询行，再逐行处理可能以字符串形式返回的 GeoJSON。
                return [self._normalize_row(row) for row in cur.fetchall()]

    def _layer_geometry_info(self, layer: LayerSpec) -> dict[str, Any]:
        """读取图层空间字段声明的几何类型和坐标系。

        输入：layer 为图层配置，包含 schema、表名和几何字段名。
        输出：如 {"geometry_type": "MULTILINESTRING", "srid": 3857}。
        从 PostGIS 的 geometry_columns 视图读取声明信息，而不是检查每个要素；
        缺少元数据或 SRID 未注册时直接报错，避免在 Python 中维护第二套元数据。
        """
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
        """检查坐标系编号是否为正数，且已在数据库 spatial_ref_sys 中注册。

        输入：srid 为坐标系编号，例如 3857 或 4326。
        输出：检查通过时不返回业务数据（即 None），否则抛出 ValueError。
        这里只确认编号存在，不负责判断输入坐标是否真的属于该坐标系。
        """
        if srid <= 0 or not self._fetch("SELECT srid FROM spatial_ref_sys WHERE srid = %s", [srid]):
            raise ValueError(f"未知或未定义的 SRID: {srid}，请使用 spatial_ref_sys 中已注册的坐标系")

    def _prepare_target(
        self, target: TargetGeometry, output_srid: int, *, allow_empty: bool = False
    ) -> tuple[str, list[Any]]:
        """读取并检查目标几何，按需转换坐标，再生成可供后续 SQL 使用的几何快照。

        输入：target 为 GeoJSON 几何或“图层 + 要素 ID/编码”；output_srid 为期望的
        输出坐标系。allow_empty 控制是否允许空几何，默认为 False；若指定它，
        必须写成 allow_empty=True/False 的关键字形式，不能按位置传入。
        输出：(SQL 字符串, 参数列表)，SQL 通过参数中的 EWKB 还原出名为 geom 的字段。
        EWKB 是携带坐标系信息的几何二进制格式，此处用它保存本次已读取的几何，
        使后续运算不必再按 ID/编码查询原表；返回的不是 GeoJSON，也不会新建表。
        已有要素以数据库实际 SRID 为准；srid 参数仅用于声明 GeoJSON 坐标。
        空查询结果属于目标不存在，不能当作正常的零匹配。此处不自动修复几何。
        """
        # GeoJSON 自身不携带本项目所需的 SRID，因此先检查调用方声明的坐标系编号。
        if target.geometry is not None:
            self._validate_srid(target.srid)
        # 先生成“从哪里取得几何”的 SQL，再真正执行查询，取得几何及其检查信息。
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
        # 没有查询行表示要素不存在；这与“要素存在，但它的几何为空”是两种情况。
        if not rows:
            identifier = target.feature_id if target.feature_id is not None else target.feature_code
            raise TargetNotFoundError(f"目标要素不存在: {target.layer_name} / {identifier}")
        row = rows[0]
        if row["geom_ewkb"] is None or (row["is_empty"] and not allow_empty):
            raise ValueError("目标几何不能为空")
        if not row["is_valid"]:
            raise ValueError(f"目标几何无效: {row['validity_reason']}")
        # 对已有数据库要素使用实际读到的 SRID，不能用 target.srid 覆盖它。
        self._validate_srid(row["srid"])
        geom_ewkb = row["geom_ewkb"]
        # 坐标系不同时用 ST_Transform 实际转换坐标值，而不是只修改 SRID 标签。
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
        # 后续 SQL 可把这条 SELECT 放入 WITH 子句，以统一的 geom 字段继续运算。
        return "SELECT ST_GeomFromEWKB(%s) AS geom", [geom_ewkb]

    def _target_geometry_sql(self, target: TargetGeometry) -> tuple[str, list[Any]]:
        """根据目标的来源生成取几何的 SQL，不在本函数中执行查询。

        输入：已通过参数模型校验的 TargetGeometry。
        输出：(SQL 字符串, 参数列表)，SQL 统一将目标几何命名为 geom。
        支持三种来源：直接提供 GeoJSON、按图层中的要素 ID 查询、按要素编码查询。
        表名和字段名取自图层白名单；具体坐标、SRID、ID、编码通过 %s 参数传入。
        """
        # ST_GeomFromGeoJSON 解析几何；ST_SetSRID 只声明输入坐标系，不转换坐标值。
        if target.geometry is not None:
            return (
                f"SELECT ST_SetSRID(ST_GeomFromGeoJSON(%s), %s) AS geom",
                [json.dumps(target.geometry), target.srid],
            )

        # 非 GeoJSON 模式下，参数模型应已保证提供图层名以及 ID/编码二者之一。
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

        # 未提供 feature_id 时使用 feature_code 查询；是否确实存在由 _prepare_target 检查。
        return (
            f"""
            SELECT {self._q(layer.geom_column)} AS geom
            FROM {self._qualified(layer)}
            WHERE {self._q(layer.code_column)} = %s
            """,
            [target.feature_code],
        )

    def _measure_expression(self, measure: str) -> str:
        """根据量测方式返回 SQL 表达式，本函数不执行量测，也不返回数值。

        输入：measure 为 length（长度）或 area（面积），其他值报错。
        输出：可嵌入 SELECT 的表达式，使用名为 geom 的几何字段。
        ST_CollectionExtract 的 2 表示提取线，3 表示提取面；再转换到 EPSG:3857，
        分别用 ST_Length 或 ST_Area 做平面量测，结果单位为米或平方米。
        """
        if measure == "length":
            return "ST_Length(ST_Transform(ST_CollectionExtract(geom, 2), 3857))"
        if measure == "area":
            return "ST_Area(ST_Transform(ST_CollectionExtract(geom, 3), 3857))"
        raise ValueError(f"测量方式尚未解析: {measure}")

    def _select_public_columns(self, layer: LayerSpec, alias: str | None = None) -> str:
        """生成 SELECT 使用的公开字段列表，不读取字段值。

        输入：layer 提供允许公开的字段；alias 是可选的内部 SQL 表别名。
        输出：逗号分隔的 SQL 字段字符串；提供别名时给每个字段加上“别名.”前缀。
        只选择 layer.public_columns，避免直接使用 SELECT * 暴露其他字段。
        """
        prefix = f"{alias}." if alias else ""
        return ", ".join(f"{prefix}{self._q(column)}" for column in layer.public_columns)

    def _qualified(self, layer: LayerSpec) -> str:
        """将图层的 schema 名和表名分别处理后，拼成 SQL 中使用的完整表名。

        输入：LayerSpec 图层配置；输出：形如 "gis_lab"."gas_devices" 的字符串。
        schema 名和表名是两个独立标识符，不能把带点的完整名称作为一个标识符处理。
        """
        return f"{self._q(layer.schema_name)}.{self._q(layer.table_name)}"

    @staticmethod
    def _q(identifier: str) -> str:
        """统一调用 quote_identifier，检查并引用 SQL 标识符。

        输入：表名、字段名等名称字符串；输出：处理后的 SQL 标识符字符串。
        它用于处理 SQL 中的“名称”，而不是“值”；具体查询值仍使用 %s 参数绑定。
        """
        return quote_identifier(identifier)

    @staticmethod
    def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        """将查询行中字符串形式的几何 JSON 转成 Python 对象。

        输入：一行查询结果字典；输出：处理后的新字典，不直接改动原字典。
        仅当列名为 geometry 或 geojson 且值为字符串时执行 json.loads；
        驱动已解析的对象以及其他字段保持原样，不进行坐标转换或几何运算。
        """
        normalized = dict(row)
        for key, value in list(normalized.items()):
            if isinstance(value, str) and key in {"geometry", "geojson"}:
                normalized[key] = json.loads(value)
        return normalized

    @staticmethod
    def _ok(tool_name: str, started: float, result: dict[str, Any]) -> dict[str, Any]:
        """将工具的业务结果包装成统一的成功响应，供执行器检查和记录。

        输入：tool_name 为工具名；started 为 time.perf_counter() 记录的开始时间；
        result 为业务结果，例如几何、要素集或量测数值。
        输出：包含 status、tool、elapsed_ms、result、error 的字典。
        status 固定为 ok，error 为 None；耗时转换为毫秒并保留三位小数。
        这里仅包装成功结果，不捕获异常，也不代表已经验证了模型的规划语义。
        """
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
    """在单几何工具的基础上，增加完整要素集的查询、批量运算和统计功能。

    继承父类的三个单几何工具，以及数据库访问、坐标转换、结果包装等辅助方法。
    query/buffer/clip/measure_features 返回可继续传递的 result.feature_set；
    union_features 返回单个合并几何，summarize_features 和 calculate_ratio 返回统计结果。
    """

    @staticmethod
    def _dataset(features: list[Feature], srid: int, fields: list[str], measure: str | None = None) -> FeatureSet:
        """将要素列表和集合元数据包装、校验为 FeatureSet 对象，不查询数据库。

        输入：features 为要素列表；srid 为这些几何的共同坐标系；fields 为公开属性字段名；
        measure 为 None（未量测）、length 或 area。有量测时，每个要素需已有 measure_value。
        输出：通过数量、属性字段、量测信息等一致性检查的 FeatureSet 模型对象，而非字典。
        几何保留传入的 srid；量测信息存在时，记录其量测坐标系为本项目使用的 3857。
        is_complete=True 是完整性声明，调用方仍需保证未将截断数据冒充完整结果。
        """
        return FeatureSet.model_validate({
            "features": features, "srid": srid, "is_complete": True,
            "feature_count": len(features), "property_fields": fields, "measure": measure,
            "unit": None if measure is None else ("meter" if measure == "length" else "square_meter"),
            "measure_srid": 3857 if measure else None,
        })

    @staticmethod
    def _canonical_geometry(expression: str) -> str:
        """生成统一空几何表示的 SQL 表达式，不执行查询，也不自动修复无效几何。

        输入：内部 SQL 几何表达式，如 geom 或 f.geom。
        输出：CASE 表达式字符串；为空时替换为同 SRID 的空几何集合，否则保留原几何。
        """
        return f"CASE WHEN ST_IsEmpty({expression}) THEN ST_GeomFromText('GEOMETRYCOLLECTION EMPTY', ST_SRID({expression})) ELSE {expression} END"

    def query_features(self, request: QueryFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """按公开属性（AND）和可选空间关系查询完整要素集。

        输入：QueryFeaturesInput 或同结构字典，包含白名单图层 layer_name、属性 filters、
        可选空间条件 target/relation 和安全上限 max_features。空间条件必须同时提供二者。
        多个属性条件同时满足（AND）；单个 in 条件表示可选值列表中的任意一个。
        输出：统一成功响应，其 result.feature_set 为包含几何、公开属性、来源和 SRID 的字典。
        无匹配时返回空的完整要素集；超过 max_features 或遇到无效几何时直接报错，
        不返回前 N 条冒充完整集合。例如可查询“与 A001 相交且状态为正常的燃气设备”。
        """
        started = time.perf_counter()
        req = request if isinstance(request, QueryFeaturesInput) else QueryFeaturesInput(**request)
        # 图层名只能来自白名单；筛选字段也必须是该图层允许公开的字段。
        layer = get_layer_spec(req.layer_name)
        clauses, filter_params = [], []
        operators = {"eq": "=", "ne": "<>", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}
        for condition in req.filters:
            if condition.field not in layer.public_columns:
                raise ValueError(f"不允许筛选字段: {condition.field}")
            column = f"f.{self._q(condition.field)}"
            op, value = condition.operator, condition.value
            # SQL 中判断空值必须用 IS NULL / IS NOT NULL，不能用 = NULL / <> NULL。
            if op in {"is_null", "is_not_null"} or (value is None and op in {"eq", "ne"}):
                clauses.append(f"{column} IS {'NOT ' if op in {'is_not_null', 'ne'} else ''}NULL")
            elif op in {"in", "not_in"}:
                # 列表整体作为一个参数：ANY 匹配任一值，ALL 要求与列表中各值均不相等。
                clauses.append(f"{column} {'= ANY' if op == 'in' else '<> ALL'}(%s)")
                filter_params.append(value)
            else:
                clauses.append(f"{column} {operators[op]} %s")
                filter_params.append(value)
        info = self._layer_geometry_info(layer)
        prefix, join, params = "", "", []
        if req.target is not None:
            # 将空间筛选目标转换到图层实际 SRID，再与表中每个要素判断指定的空间关系。
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
        # 按 SQL 中占位符出现的顺序绑定参数；多取一条只用于判断是否超限，不用于截断返回。
        rows = self._fetch(sql, [*params, *filter_params, req.max_features + 1])
        if len(rows) > req.max_features:
            raise ValueError(f"完整要素集超过安全上限 {req.max_features}，请收紧条件；未返回截断结果")
        features = []
        for row in rows:
            if not row["geometry_valid"]:
                raise ValueError(f"源要素几何无效: {layer.name}/{row[layer.code_column]}")
            # 为每条原始记录生成身份标识；后续缓冲、裁剪仍可据此追踪来源或按身份去重。
            key = f"{layer.name}:{row[layer.id_column]}"
            features.append(Feature(
                key=key, source_layer=layer.name, source_id=row[layer.id_column], source_code=row[layer.code_column],
                source_keys=[key], properties={name: row[name] for name in layer.public_columns}, geometry=row["geometry"],
            ))
        dataset = self._dataset(features, info["srid"], list(layer.public_columns))
        # model_dump 将模型转为普通字典，供日志序列化及下一步通过 $ref 引用。
        return self._ok("query_features", started, {"feature_set": dataset.model_dump()})

    def _feature_sql(self, dataset: FeatureSet) -> tuple[str, list[Any]]:
        """把内存中的要素集几何展开为 SQL 行，供后续批量运算使用。

        输入：FeatureSet 模型，包含统一 SRID 和要素列表。
        输出：(SQL 字符串, 参数列表)，执行该 SQL 可得到 position 和 geom 两列。
        position 是要素在原列表中的下标，用来在运算后找回原属性和来源。
        本函数会先执行一次几何解析及有效性检查，成功后才返回可复用的 SQL 和参数。
        """
        self._validate_srid(dataset.srid)
        # JSON 数组展开后每个要素成为一行；ordinality 从 1 开始，减 1 后对应 Python 列表下标。
        # ST_SetSRID 仅声明这些输入坐标所属的坐标系，此处不改变坐标值。
        sql = """
        SELECT (e.ordinality - 1)::int AS position,
               ST_SetSRID(ST_GeomFromGeoJSON(e.value -> 'geometry'), %s) AS geom
        FROM jsonb_array_elements(%s::jsonb) WITH ORDINALITY AS e(value, ordinality)
        """
        # 只把几何送入数据库运算；属性和来源仍保存在 dataset 中，通过 position 关联回来。
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
        """执行批量几何运算，并按原要素位置整理每行的几何结果。

        输入：返回 position、geom 两列的内部 SQL，以及对应的占位符参数。
        输出：按 position 排序的字典列表，每行包含 position、GeoJSON geometry 和 valid。
        空几何统一编码；这里只返回有效性标记，由 _rebuild 决定是否报错。
        """
        return self._fetch(f"""
            WITH computed AS ({sql})
            SELECT position, ST_AsGeoJSON({self._canonical_geometry('geom')}, 15, 0)::json AS geometry,
                   ST_IsValid(geom) AS valid
            FROM computed ORDER BY position
        """, params)

    def _rebuild(self, source: FeatureSet, rows: list[dict[str, Any]], srid: int) -> FeatureSet:
        """把运算后的几何与原要素的属性、来源重新组合成新的未量测要素集。

        输入：source 为原集合；rows 为带 position、geometry、valid 的运算结果；
        srid 为新几何实际采用的坐标系。rows 可以仅包含裁剪后保留的部分要素。
        输出：新的 FeatureSet，保留各要素身份、公开属性和来源，但更新几何与集合数量。
        几何改变后旧量测值不可沿用，因此清空 measure_value 及集合的量测信息；
        任一结果几何无效则报错，不自动修复，也不修改传入的原集合。
        """
        features = []
        for row in rows:
            if not row["valid"]:
                raise ValueError("批量空间操作生成无效几何，不自动修复")
            # position 对应原列表下标，即使裁剪删除了中间某些要素，也能准确找回各自来源。
            value = source.features[row["position"]].model_dump()
            value.update(geometry=row["geometry"], measure_value=None)
            features.append(Feature.model_validate(value))
        return self._dataset(features, srid, source.property_fields)

    def buffer_features(self, request: BufferFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """对要素集中的每个对象分别生成缓冲区，不合并对象之间的重叠部分。

        输入：BufferFeaturesInput 或同结构字典，包含完整 features 集合和距离 distance_m。
        输出：result.feature_set 为 EPSG:3857 下的缓冲要素集；result.quad_segs 固定为 8，
        表示每个四分之一圆弧用 8 段直线近似。原属性和来源保留，旧量测信息清空。
        若要求整体覆盖面积，应随后用 union_features 合并重叠，不能直接累加各缓冲面积。
        """
        started = time.perf_counter()
        req = request if isinstance(request, BufferFeaturesInput) else BufferFeaturesInput(**request)
        source_sql, params = self._feature_sql(req.features)
        # 每行独立转换到 3857 后做平面缓冲；position 随结果传递，用于重建要素。
        sql = f"WITH input AS ({source_sql}) SELECT position, ST_Buffer(ST_Transform(geom,3857), %s, 'quad_segs=8') AS geom FROM input"
        result = self._rebuild(req.features, self._geometry_rows(sql, [*params, req.distance_m]), 3857)
        return self._ok("buffer_features", started, {"feature_set": result.model_dump(), "quad_segs": 8})

    def union_features(self, request: UnionFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """将全部要素的几何做空间合并，消除重叠，供覆盖面积等后续计算使用。

        输入：UnionFeaturesInput 或同结构字典，包含 features 和输出坐标系 target_srid。
        输出：result.geometry={geometry: GeoJSON, srid: 坐标系编号}，以及几何类型、
        空/有效标记、去重后的 source_keys、来源数 source_feature_count 和输入数 input_count。
        返回的是一个合并几何，不是 FeatureSet；不再逐条保留原要素属性。
        输入集合为空时返回指定坐标系下的合法空几何，而不是报“目标不存在”。
        """
        started = time.perf_counter()
        req = request if isinstance(request, UnionFeaturesInput) else UnionFeaturesInput(**request)
        self._validate_srid(req.target_srid)
        source_sql, params = self._feature_sql(req.features)
        # 先统一坐标系，再收集、合并所有几何；无输入行产生 NULL 时，用合法空几何替代。
        sql = f"""
        WITH input AS ({source_sql})
        SELECT COALESCE(ST_UnaryUnion(ST_Collect(ST_Transform(geom,%s))),
                        ST_GeomFromText('GEOMETRYCOLLECTION EMPTY',%s)) AS geom FROM input
        """
        result = self._geometry_result(sql, [*params, req.target_srid, req.target_srid])
        # 来源数按原始 source_keys 去重计算，可能与当前输入要素条数不同，不是输出几何的片段数。
        keys = sorted({key for f in req.features.features for key in f.source_keys})
        result.update(source_keys=keys, source_feature_count=len(keys), input_count=req.features.feature_count)
        return self._ok("union_features", started, result)

    def clip_features(self, request: ClipFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """把每个要素分别与裁剪目标求交，保留交集几何及各自原属性和来源。

        输入：ClipFeaturesInput 或同结构字典，包含 features、clip_target 和 keep_empty。
        输出：result.feature_set，几何坐标系与输入集合一致，旧量测信息清空。
        裁剪目标会转换到输入集合的坐标系；keep_empty 默认为 False，仅删除空交集。
        只在边界接触而产生的点或线交集仍保留，即使其面积或长度量测可能为 0。
        """
        started = time.perf_counter()
        req = request if isinstance(request, ClipFeaturesInput) else ClipFeaturesInput(**request)
        source_sql, params = self._feature_sql(req.features)
        target_sql, target_params = self._prepare_target(req.clip_target, req.features.srid, allow_empty=True)
        # 同一个裁剪目标用于所有输入要素；保留 position，过滤空交集后也不重新编号。
        sql = f"""
        WITH input AS ({source_sql}), target AS ({target_sql}), clipped AS (
            SELECT position, ST_Intersection(i.geom,t.geom) AS geom FROM input i CROSS JOIN target t
        ) SELECT position, geom FROM clipped {'WHERE NOT ST_IsEmpty(geom)' if not req.keep_empty else ''}
        """
        result = self._rebuild(req.features, self._geometry_rows(sql, [*params, *target_params]), req.features.srid)
        return self._ok("clip_features", started, {"feature_set": result.model_dump()})

    def measure_features(self, request: MeasureFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """逐个量测要素，并将所有明细值直接求和，不做身份去重或空间合并。

        输入：MeasureFeaturesInput 或同结构字典，包含 features 和量测方式 length/area。
        输出：result.feature_set 为每项填入 measure_value 的要素集；result.summary 包含
        总值 value、单位 unit、量测方式 measure、measure_srid=3857 和 feature_count。
        量测在 EPSG:3857 平面进行，但返回要素的几何及其原始 srid 不变。
        多个要素重叠时重叠部分会被重复计入；求覆盖面积应先 union_features，
        再用 measure_geometry 量测其返回的单个合并几何，而不是直接累加逐项面积。
        """
        started = time.perf_counter()
        req = request if isinstance(request, MeasureFeaturesInput) else MeasureFeaturesInput(**request)
        source_sql, params = self._feature_sql(req.features)
        # 这里只返回位置和量测数值，不改写输入几何；具体提取线/面及转换由父类表达式完成。
        rows = self._fetch(f"WITH input AS ({source_sql}) SELECT position, {self._measure_expression(req.measure)} AS value FROM input ORDER BY position", params)
        features = []
        for row in rows:
            value = req.features.features[row["position"]].model_dump()
            value["measure_value"] = row["value"]
            features.append(Feature.model_validate(value))
        result = self._dataset(features, req.features.srid, req.features.property_fields, req.measure)
        # math.fsum 对所有明细值求和，减少浮点累加误差；summary 可作为最终输出或比例输入。
        summary = {"value": math.fsum(cast(float, f.measure_value) for f in result.features), "unit": result.unit,
                   "measure": req.measure, "measure_srid": 3857, "feature_count": result.feature_count}
        return self._ok("measure_features", started, {"feature_set": result.model_dump(), "summary": summary})

    def summarize_features(self, request: SummarizeFeaturesInput | dict[str, Any]) -> dict[str, Any]:
        """在 Python 内完成按身份去重、分组、求和/计数和全量排序，不查询数据库。

        输入：SummarizeFeaturesInput 或同结构字典；features 为要素集，group_by 为分组字段，
        aggregate 为 sum/count，deduplicate 控制是否按 key 去重，sort 指定排序方式。
        sum 要求集合已量测；count 可直接统计要素数。未指定分组字段时，所有保留要素归一组。
        输出：result.groups 中每项含 group（分组字段和值）、value（汇总值）、feature_count。
        另返回统计方式、单位、量测坐标系、输入数 input_count、唯一身份数 unique_count、
        实际保留数 retained_count 和分组数 group_count，不隐式截取前若干组。
        key 去重只消除重复身份，不消除不同要素之间的几何重叠。
        """
        started = time.perf_counter()
        req = request if isinstance(request, SummarizeFeaturesInput) else SummarizeFeaturesInput(**request)
        rows, seen = [], {}
        # 同 key 且内容相同才可去重；内容冲突时报错，避免任意丢弃其中一份数据。
        for feature in req.features.features:
            if req.deduplicate and feature.key in seen:
                if feature != seen[feature.key]:
                    raise ValueError(f"同一 key 的要素内容冲突，不能任意去重: {feature.key}")
                continue
            seen[feature.key] = feature
            rows.append(feature)
        groups: dict[str, dict[str, Any]] = {}
        for feature in rows:
            # 来源字段从 Feature 顶层取，普通公开字段从 properties 中取；分组值不能是列表或字典。
            group = {name: getattr(feature, name) if name in {"source_layer", "source_id", "source_code"}
                     else feature.properties[name] for name in req.group_by}
            if any(isinstance(value, (dict, list)) for value in group.values()):
                raise ValueError("分组值必须为标量")
            # 将分组条件稳定编码成字典键；相同分组共用一个 bucket（存放明细值和计数）。
            key = json.dumps(group, sort_keys=True, ensure_ascii=False, allow_nan=False)
            bucket = groups.setdefault(key, {"group": group, "values": [], "feature_count": 0})
            bucket["values"].append(feature.measure_value if req.aggregate == "sum" else 1)
            bucket["feature_count"] += 1
        # sum 累加量测值；count 累加每个要素贡献的 1。空输入不会创建分组，结果为 []。
        result = [{"group": b["group"], "value": math.fsum(b["values"]), "feature_count": b["feature_count"]}
                  for b in groups.values()]
        def group_key(row):
            """把一组的字段值转换为可比较的元组，供分组升序及汇总值相同时排序。"""
            def scalar_key(value):
                """给单个分组值附加类型顺序，避免 None、数字、字符串之间直接比较报错。"""
                # 顺序为：空值、布尔值、数字、字符串；bool 是 int 的子类，必须先判断 bool。
                if value is None:
                    return (0, "")
                if isinstance(value, bool):
                    return (1, value)
                if isinstance(value, (int, float)):
                    return (2, value)
                return (3, value)
            return tuple(scalar_key(row["group"][field]) for field in req.group_by)
        # Python 默认升序，给 value 取负数即可实现降序；按值排序时再用分组键确定同值顺序。
        result.sort(key=lambda row: ((-row["value"] if req.sort == "value_desc" else row["value"]), group_key(row))
                    if req.sort != "group_asc" else (group_key(row),))
        # 关闭去重时 retained_count 可大于 unique_count；count 的单位是 feature，而不是米/平方米。
        return self._ok("summarize_features", started, {
            "groups": result, "aggregate": req.aggregate, "unit": req.features.unit if req.aggregate == "sum" else "feature",
            "measure_srid": req.features.measure_srid if req.aggregate == "sum" else None,
            "input_count": req.features.feature_count, "unique_count": len({f.key for f in rows}),
            "retained_count": len(rows), "group_count": len(result),
        })

    def calculate_ratio(self, request: CalculateRatioInput | dict[str, Any]) -> dict[str, Any]:
        """根据两个完整量测对象计算百分比或普通比值，不进行几何运算或数据库查询。

        输入：CalculateRatioInput 或同结构字典，numerator/denominator 各含数值、单位及
        量测坐标系；模型校验要求两侧单位和坐标系一致，且分母大于 0。
        输出：result.value 为比例，unit 为 percent/fraction，并记录分子和分母的原数值。
        例如分子 25、分母 100，percent 输出 25，fraction 输出 0.25。
        拒绝非有限数值结果，但不会把大于 100% 的结果强制改成 100%。
        """
        started = time.perf_counter()
        req = request if isinstance(request, CalculateRatioInput) else CalculateRatioInput(**request)
        # percent 将普通比值乘 100；fraction 保留原比值，二者只改变表达形式，不改变输入单位。
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
        description="仅在 EPSG:3857 坐标系下生成缓冲区几何。将几何与 SRID 一并返回，供后续步骤使用。",
        invocation="request",
    ),
    "intersection_geometry": ToolSpec(
        name="intersection_geometry",
        method_name="intersection_geometry",
        args_schema=IntersectionGeometryInput,
        description="将两个几何转换到 target_srid 指定的坐标系后求交，返回交集，包括合法的空几何结果。",
        invocation="request",
    ),
    "measure_geometry": ToolSpec(
        name="measure_geometry",
        method_name="measure_geometry",
        args_schema=MeasureGeometryInput,
        description="在 EPSG:3857 坐标系下量测单个几何，必须明确选择 length（长度）或 area（面积）。空几何的量测值为 0。",
        invocation="request",
    ),
}


ADVANCED_TOOL_REGISTRY: dict[str, ToolSpec] = {
    **COMPOSABLE_TOOL_REGISTRY,
    "query_features": ToolSpec("query_features", "query_features", QueryFeaturesInput,
        "使用白名单字段的属性条件（多条件按 AND 组合）及可选的空间目标和关系，查询完整的 FeatureSet（要素集）。返回 result.feature_set。超过 max_features 时直接报错，不返回截断结果。", "request"),
    "buffer_features": ToolSpec("buffer_features", "buffer_features", BufferFeaturesInput,
        "在 EPSG:3857 坐标系下逐要素建立缓冲区，保留来源标识和属性。返回 result.feature_set，不合并重叠部分。", "request"),
    "union_features": ToolSpec("union_features", "union_features", UnionFeaturesInput,
        "合并全部要素的几何以消除空间重叠。返回 result.geometry（包含 geometry 和 srid）、source_keys 和 source_feature_count。空输入返回合法的空几何。", "request"),
    "clip_features": ToolSpec("clip_features", "clip_features", ClipFeaturesInput,
        "使用 clip_target 逐要素裁剪，保留编码和来源信息。返回 result.feature_set。默认丢弃空交集，但保留边界接触结果。", "request"),
    "measure_features": ToolSpec("measure_features", "measure_features", MeasureFeaturesInput,
        "明确选择 length（长度）或 area（面积），逐要素量测。返回带有各要素 measure_value 的 result.feature_set，以及 result.summary（包含 value、unit、measure、measure_srid、feature_count）。量测值求和不等于空间合并。", "request"),
    "summarize_features": ToolSpec("summarize_features", "summarize_features", SummarizeFeaturesInput,
        "按 key 去重，按来源元数据或公开属性分组，进行 sum（求和）或 count（计数）汇总，并对全部分组排序。sum 要求输入为已量测的 FeatureSet。返回 result.groups 和 unit，不隐式截取前 20 组。", "request"),
    "calculate_ratio": ToolSpec("calculate_ratio", "calculate_ratio", CalculateRatioInput,
        "对两个单位和 SRID 一致的量测对象计算百分比或比例，拒绝分母为 0。参数应引用完整的 measure_geometry.result 或 measure_features.result.summary，不能只传裸数值。", "request"),
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
