"""阶段①上下文注入：数据库表结构索引与相关性筛选。

支持两种表结构来源（`settings.SCHEMA_SOURCE`）：
  · `postgis`：连接当前 PostGIS 库，从 information_schema 读取表/字段，
    并采样少量真实取值（如 A001、正常、中压），一起注入提示词；
  · `demo`：使用内置示例（没有数据库时也能跑）。

相关表筛选走余弦相似度（`retrieval/cosine_similarity.py`）：
把每张表渲染成"表名 + 表说明 + 字段 + 字段含义 + 样例值"的文档，
用问题文本检索最相关的 top-k 张表。
"""
from __future__ import annotations

import logging
from typing import Any

from config import settings
from retrieval.cosine_similarity import TfidfIndex, cut_relative

logger = logging.getLogger(__name__)

# 演示用 schema（无数据库时的兜底）
DEMO_SCHEMA: dict[str, dict[str, str]] = {
    "gas_pipeline": {
        "fid": "管线唯一编号",
        "material": "管材，如 PE/钢管/铸铁",
        "diameter_mm": "管径，单位毫米",
        "pressure_level": "压力等级，0=低压 1=中压 2=次高压 3=高压",
        "lay_year": "敷设年份",
        "geometry": "管线空间几何（线要素）",
    },
    "gas_valve": {
        "fid": "阀门唯一编号",
        "valve_type": "阀门类型，如 闸阀/球阀",
        "status": "运行状态，open/closed/maintenance",
        "geometry": "阀门空间几何（点要素）",
    },
    "water_pipeline": {
        "fid": "管段唯一编号",
        "material": "管材",
        "diameter_mm": "管径，单位毫米",
        "flow_rate": "设计流量，单位立方米/小时",
        "geometry": "管段空间几何（线要素）",
    },
    "water_meter": {
        "fid": "水表唯一编号",
        "user_id": "用户编号",
        "monthly_usage": "月用水量，单位立方米",
        "geometry": "水表空间几何（点要素）",
    },
    "region_stat": {
        "region_code": "行政区编码（GB/T 2260）",
        "region_name": "行政区名称",
        "population": "常住人口，单位人",
        "year": "统计年份",
    },
}

# 图层业务含义（PostGIS 模式下的已知表；未知表退回英文表名）
TABLE_NOTES: dict[str, str] = {
    "construction_areas": "施工区（面要素），按 code 引用，如 A001/A003",
    "gas_pipelines": "燃气管线（线要素），按 code 引用，如 G001/G006",
    "gas_devices": "燃气设备（点要素），按 code 引用，如 D001/D011",
    "water_pipelines": "给排水管线（线要素），按 code 引用，如 W001/W008",
    "demo_roads": "道路（线要素），如 R001",
    "invalid_geometry_cases": "无效几何测试样例",
    "srid_input_examples": "坐标系转换样例",
    "import_batches": "数据导入批次记录",
}

COLUMN_NOTES: dict[str, str] = {
    "id": "主键",
    "code": "业务编号",
    "name": "名称",
    "area_type": "区域类型",
    "pipe_type": "管线类型",
    "pressure_level": "压力等级",
    "device_type": "设备类型",
    "status": "运行状态",
    "note": "备注",
    "geom": "空间几何（EPSG:3857）",
    "source_srid": "源坐标系",
    "target_srid": "目标坐标系",
    "expected_problem": "预期问题",
    "source_type": "来源类型",
    "source_name": "来源名称",
    "original_crs": "原始坐标系",
    "imported_count": "导入数量",
    "invalid_geometry_count": "无效几何数",
    "created_at": "创建时间",
    "metadata": "元数据",
}

_SAMPLE_COLUMNS = {
    "code", "name", "area_type", "pipe_type", "pressure_level",
    "device_type", "status", "road_type",
}

_SCHEMA: dict[str, dict[str, str]] | None = None
_INDEX: TfidfIndex | None = None
_TABLES: list[str] = []


def _quote(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"非法标识符: {identifier}")
    return f'"{identifier}"'


def _load_live_schema() -> dict[str, dict[str, str]]:
    """从 PostGIS 读取表/字段，并采样少量真实值。"""
    import psycopg

    schema = settings.APP_SCHEMA
    with psycopg.connect(settings.DATABASE_URL) as conn:
        rows = conn.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
            """,
            (schema,),
        ).fetchall()

        grouped: dict[str, list[tuple[str, str]]] = {}
        for table, column, dtype in rows:
            grouped.setdefault(table, []).append((column, dtype))

        result: dict[str, dict[str, str]] = {}
        for table, columns in grouped.items():
            fields: dict[str, str] = {}
            for column, dtype in columns:
                note = COLUMN_NOTES.get(column, column)
                meaning = f"{note}（{dtype}）"
                if column in _SAMPLE_COLUMNS and dtype in ("text", "character varying"):
                    try:
                        values = conn.execute(
                            f"SELECT DISTINCT {_quote(column)}::text AS v "
                            f"FROM {_quote(schema)}.{_quote(table)} "
                            f"WHERE {_quote(column)} IS NOT NULL "
                            f"ORDER BY 1 LIMIT 8"
                        ).fetchall()
                        samples = [v for (v,) in values if v is not None]
                        if samples:
                            meaning += "；样例：" + "/".join(samples)
                    except Exception:  # 采样失败不影响主流程
                        conn.rollback()
                fields[column] = meaning
            result[table] = fields
    return result


def _schema() -> dict[str, dict[str, str]]:
    global _SCHEMA, _INDEX, _TABLES
    if _SCHEMA is not None:
        return _SCHEMA

    if settings.SCHEMA_SOURCE == "postgis":
        try:
            _SCHEMA = _load_live_schema()
            logger.info("已从 PostGIS 读取表结构: %s 张表", len(_SCHEMA))
        except Exception as exc:  # 数据库不可用时退回示例
            logger.warning("读取 PostGIS 表结构失败，改用示例 schema: %s", exc)
            _SCHEMA = DEMO_SCHEMA
    else:
        _SCHEMA = DEMO_SCHEMA

    if not _SCHEMA:
        _SCHEMA = DEMO_SCHEMA
    _TABLES = list(_SCHEMA)
    _INDEX = TfidfIndex([_table_document(t) for t in _TABLES])
    return _SCHEMA


def reset_schema_cache() -> None:
    """表结构变化（或切换数据源）后调用。"""
    global _SCHEMA, _INDEX, _TABLES
    _SCHEMA = None
    _INDEX = None
    _TABLES = []


def _table_document(table: str) -> str:
    schema = _SCHEMA or {}
    note = TABLE_NOTES.get(table, table)
    fields = schema.get(table, {})
    return "表 {} {} {}".format(
        table, note, " ".join(f"{f} {m}" for f, m in fields.items())
    )


def filter_relevant_tables(question: str, domain: str = "",
                           top_k: int | None = None) -> list[str]:
    """按余弦相似度筛选与问题最相关的表。"""
    _schema()
    top_k = top_k or settings.SCHEMA_TOP_K
    assert _INDEX is not None
    hits = _INDEX.search(question, top_k=top_k, min_score=settings.RETRIEVAL_MIN_SCORE)
    hits = cut_relative(hits, settings.RETRIEVAL_RELATIVE_CUTOFF)
    if hits:
        return [_TABLES[pos] for _, pos in hits]
    return _TABLES[:top_k]


def render_schema_context(tables: list[str]) -> str:
    """把相关表结构渲染为注入 prompt 的文本。"""
    schema = _schema()
    parts = ["【数据库相关表结构（按余弦相似度检索）】"]
    for table in tables:
        note = TABLE_NOTES.get(table, "")
        parts.append(f"\n表 {table}" + (f"（{note}）" if note else "") + ":")
        for field, meaning in schema.get(table, {}).items():
            parts.append(f"  - {field}: {meaning}")
    return "\n".join(parts)


def get_context(question: str, domain: str = "") -> str:
    tables = filter_relevant_tables(question, domain)
    return render_schema_context(tables)
