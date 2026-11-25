"""50 题空间分析基准与独立 PostGIS SQL 标准答案。

题目可以单独预览；正式评测必须先补齐、验证全部标准答案。
SQL 仅供离线生成标准答案，load_cases 不把 SQL 传给模型。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.dev20 import Case
from config import settings


SUITE_ID = "postgis_dev50_v1"
CASE_IDS = tuple(f"D{index:02d}" for index in range(1, 51))


def load_suite(bench_dir: str | Path | None = None, *, require_complete: bool = True) -> dict[str, Any]:
    base = Path(bench_dir or settings.BENCHMARK_DIR)
    suite = json.loads((base / "dev50.json").read_text(encoding="utf-8"))
    expected = json.loads((base / "dev50_expected.json").read_text(encoding="utf-8"))
    ids = [case.get("id") for case in suite.get("cases", [])]
    if ids != list(CASE_IDS):
        raise ValueError("dev50 题集必须按顺序恰好包含 D01-D50，不能缺题或重复")
    if suite.get("suite") != SUITE_ID or expected.get("suite") != SUITE_ID:
        raise ValueError("dev50 题集和标准答案的 suite 标识不匹配")
    answers = expected.get("cases", {})
    if not isinstance(answers, dict):
        raise ValueError("标准答案 cases 必须是题号到答案对象的映射")
    missing = [case_id for case_id in CASE_IDS if not isinstance(answers.get(case_id), dict) or not answers[case_id]]
    if set(answers) - set(CASE_IDS):
        raise ValueError("标准答案中包含未知题号")
    if require_complete and (missing or expected.get("status") != "complete" or expected.get("pending_case_ids")):
        raise ValueError("dev50 标准答案尚未完整生成，待计算: " + ", ".join(missing or expected.get("pending_case_ids", [])))
    for case in suite["cases"]:
        if case.get("level") not in {"L1", "L2", "L3"} or not case.get("question") or not case.get("output_contract"):
            raise ValueError(f"题目 {case.get('id')} 缺少题干、难度或输出契约")
    return {"suite": suite, "expected": expected}


def load_cases(bench_dir: str | Path | None = None, *, require_complete: bool = True) -> list[Case]:
    data = load_suite(bench_dir, require_complete=require_complete)
    answers = data["expected"]["cases"]
    return [Case(id=item["id"], level=item["level"], question=item["question"],
                 tags=list(item.get("tags", [])), semantics=item.get("semantics", ""),
                 output_contract=dict(item["output_contract"]), expected=answers.get(item["id"], {}))
            for item in data["suite"]["cases"]]


def _summary(expression: str, measure: str = "length") -> str:
    unit = "meter" if measure == "length" else "square_meter"
    return ("jsonb_build_object('value', COALESCE(SUM(" + expression + "), 0), "
            f"'unit', '{unit}', 'measure', '{measure}', 'measure_srid', 3857, 'feature_count', COUNT(*))")


def _single(measure: str, geometry: str = "geom") -> str:
    function, dimension, unit = ("ST_Length", 2, "meter") if measure == "length" else ("ST_Area", 3, "square_meter")
    return (f"jsonb_build_object('value', {function}(ST_CollectionExtract({geometry}, {dimension})), "
            f"'unit', '{unit}', 'measure', '{measure}', 'measure_srid', 3857, 'is_empty', ST_IsEmpty({geometry}))")


def _length(geometry: str = "clipped") -> str:
    return f"ST_Length(ST_CollectionExtract({geometry}, 2))"


def _area(geometry: str = "geom") -> str:
    return f"ST_Area(ST_CollectionExtract({geometry}, 3))"


def _clip(layer: str, target: str = "target", *, predicate: str = "TRUE") -> str:
    return (f"SELECT f.*, ST_Intersection(f.geom, t.geom) AS clipped FROM {layer} f CROSS JOIN {target} t "
            f"WHERE {predicate} AND ST_Intersects(f.geom, t.geom)")


def _groups(source: str, field: str, *, aggregate: str = "count", sort: str = "group_asc") -> str:
    value = "COUNT(*)" if aggregate == "count" else f"SUM({_length()})"
    order = "value DESC, " if sort == "value_desc" else ""
    return ("SELECT COALESCE(jsonb_agg(jsonb_build_object('group', jsonb_build_object('" + field + "', label), "
            "'value', value, 'feature_count', n) ORDER BY " + order + 'label COLLATE "C"), \'[]\'::jsonb) '
            f"FROM (SELECT {field} AS label, {value} AS value, COUNT(*) AS n FROM {source} "
            + ("WHERE NOT ST_IsEmpty(clipped) " if aggregate != "count" else "") + f"GROUP BY {field}) grouped")


def oracle_query(case_id: str, schema: str) -> tuple[str, list[Any]]:
    """为指定题生成独立的参数化只读 SQL；不调用项目工具或模型。"""
    from tools.db import quote_identifier

    qualified = quote_identifier(schema)
    # 统一用真实坐标转换；工具侧的完整要素集与结果压缩均不参与标准答案计算。
    base = ", ".join(f"{alias} AS (SELECT *, ST_Transform(geom, 3857) AS g3857 FROM {qualified}.{table})"
                     for alias, table in (("raw_areas", "construction_areas"), ("raw_gas", "gas_pipelines"),
                                          ("raw_water", "water_pipelines"), ("raw_devices", "gas_devices"),
                                          ("raw_roads", "demo_roads")))
    # 明确列名，避免 SELECT * 带来两个同名 geom。
    base += ", areas AS (SELECT id,code,g3857 AS geom FROM raw_areas)"
    base += ", gas AS (SELECT id,code,pressure_level,g3857 AS geom FROM raw_gas)"
    base += ", water AS (SELECT id,code,pipe_type,g3857 AS geom FROM raw_water)"
    base += ", devices AS (SELECT id,code,status,device_type,g3857 AS geom FROM raw_devices)"
    base += ", roads AS (SELECT id,code,g3857 AS geom FROM raw_roads)"
    statements: dict[str, tuple[str, list[Any]]] = {}

    def add(case: str, ctes: str, answer: str, params: list[Any] | None = None):
        statements[case] = ("WITH " + base + (", " + ctes if ctes else "") + " SELECT " + answer + " AS answer", params or [])

    def target(code: str = "A001") -> str:
        return "target AS (SELECT geom FROM areas WHERE code = %s)"

    def count_answer(source: str = "selected") -> str:
        return f"jsonb_build_object('count', (SELECT COUNT(*) FROM {source}))"

    def clipped_summary(layer: str, code: str, predicate: str = "TRUE") -> tuple[str, list[Any]]:
        return target() + ", clipped_features AS (" + _clip(layer, predicate=predicate) + ")", [code]

    for case, code, relation, statuses in (
        ("D01", "A001", "ST_Within", ["正常"]), ("D02", "A001", "ST_Intersects", ["正常", "告警"]),
        ("D03", "A003", "ST_Intersects", ["正常"]), ("D21", "A002", "ST_Within", ["正常"]),
        ("D22", "A002", "ST_Intersects", ["正常", "告警"]), ("D30", "A009", "ST_Within", ["正常"]),
    ):
        add(case, target() + f", selected AS (SELECT d.* FROM devices d CROSS JOIN target t WHERE {relation}(d.geom,t.geom) AND d.status = ANY(%s))",
            count_answer(), [code, statuses])

    add("D04", "selected AS (SELECT * FROM devices WHERE status=%s)",
        f"jsonb_build_object('unit','feature','groups',({_groups('selected','device_type')}))", ["正常"])
    add("D23", target() + ", selected AS (SELECT d.* FROM devices d CROSS JOIN target t WHERE ST_Intersects(d.geom,t.geom))",
        f"jsonb_build_object('unit','feature','groups',({_groups('selected','status')}))", ["A003"])
    add("D24", "", f"jsonb_build_object('unit','feature','groups',({_groups('gas','pressure_level')}))")
    add("D25", "", f"jsonb_build_object('unit','feature','groups',({_groups('water','pipe_type')}))")
    add("D29", "selected AS (SELECT * FROM devices WHERE status=%s)", count_answer(), ["__不存在的状态__"])

    gas_clip, gas_params = clipped_summary("gas", "A001")
    add("D05", gas_clip, f"jsonb_build_object('unit','meter','groups',({_groups('clipped_features','pressure_level',aggregate='sum',sort='value_desc')}))", gas_params)
    for case, layer, code, predicate in (("D06", "gas", "A003", "f.code = 'G006'"), ("D07", "water", "A003", "TRUE"),
                                         ("D12", "water", "A009", "TRUE"), ("D31", "gas", "A002", "TRUE")):
        ctes, params = clipped_summary(layer, code, predicate)
        add(case, ctes, f"jsonb_build_object('length',(SELECT {_summary(_length())} FROM clipped_features WHERE NOT ST_IsEmpty(clipped)))", params)

    for case, distance in (("D08", 300), ("D09", 700)):
        add(case, target() + ", buffered AS (SELECT ST_Buffer(geom,%s,'quad_segs=8') AS geom FROM devices WHERE code=%s), result AS (SELECT ST_Intersection(t.geom,b.geom) AS geom FROM target t CROSS JOIN buffered b)",
            f"jsonb_build_object('area',(SELECT {_single('area')} FROM result))", ["A001", distance, "D011"])

    for case, left, right, measure in (("D10", "A001", "A002", "length"), ("D11", "A001", "A008", "area"),
                                       ("D34", "A001", "A009", "area"), ("D38", "A002", "A008", "area")):
        add(case, "result AS (SELECT ST_Intersection(a.geom,b.geom) AS geom FROM areas a CROSS JOIN areas b WHERE a.code=%s AND b.code=%s)",
            f"jsonb_build_object('{measure}',(SELECT {_single(measure)} FROM result))", [left, right])

    coverage = (target() + ", selected AS (SELECT d.* FROM devices d CROSS JOIN target t WHERE ST_Intersects(d.geom,t.geom) AND d.status=ANY(%s)), "
                "buffered AS (SELECT ST_Buffer(geom,%s,'quad_segs=8') AS geom FROM selected), "
                "merged AS (SELECT COALESCE(ST_UnaryUnion(ST_Collect(geom)),ST_GeomFromText('GEOMETRYCOLLECTION EMPTY',3857)) AS geom FROM buffered), "
                "coverage AS (SELECT ST_Intersection(m.geom,t.geom) AS geom FROM merged m CROSS JOIN target t)")
    ratio_area = ("jsonb_build_object('value',100*" + _area("c.geom") + "/" + _area("t.geom") + ", 'unit','percent','numerator'," + _area("c.geom") + ",'denominator'," + _area("t.geom") + ")")
    for case, area_code, distance in (("D13", "A001", 300), ("D46", "A002", 150)):
        statuses = ["正常", "告警"] if case == "D13" else ["正常"]
        add(case, coverage, f"(SELECT jsonb_build_object('area',{_single('area','c.geom')},'coverage_percent',{ratio_area}) FROM coverage c CROSS JOIN target t)",
            [area_code, statuses, distance])

    influence = (target() + ", clipped_gas AS (" + _clip("gas", predicate="f.pressure_level = %s") + "), "
                 "influence AS (SELECT COALESCE(ST_UnaryUnion(ST_Collect(ST_Buffer(clipped,%s,'quad_segs=8'))),ST_GeomFromText('GEOMETRYCOLLECTION EMPTY',3857)) AS geom FROM clipped_gas), "
                 "effective AS (SELECT ST_Intersection(i.geom,t.geom) AS geom FROM influence i CROSS JOIN target t), "
                 "clipped_water AS (" + _clip("water", "effective") + ")")
    water_summary = f"(SELECT {_summary(_length())} FROM clipped_water WHERE NOT ST_IsEmpty(clipped))"
    water_groups = _groups("clipped_water", "code", aggregate="sum", sort="value_desc").replace("'code', label", "'source_code', label")
    add("D14", influence, f"jsonb_build_object('unit','meter','groups',({water_groups}),'total_length',{water_summary})", ["A001", "高压", 50])
    add("D42", influence, f"jsonb_build_object('length',{water_summary})", ["A002", "高压", 50])

    summed_buffers = (target() + ", selected AS (SELECT d.* FROM devices d CROSS JOIN target t WHERE ST_Intersects(d.geom,t.geom) AND d.status=ANY(%s)), "
                       "buffered AS (SELECT ST_Buffer(geom,%s,'quad_segs=8') AS geom FROM selected), "
                       "merged AS (SELECT COALESCE(ST_UnaryUnion(ST_Collect(geom)),ST_GeomFromText('GEOMETRYCOLLECTION EMPTY',3857)) AS geom FROM buffered)")
    summed_area = f"(SELECT {_summary(_area(), 'area')} FROM buffered)"
    union_area = f"(SELECT {_single('area')} FROM merged)"
    add("D15", summed_buffers, f"jsonb_build_object('union_area',{union_area},'summed_area',{summed_area})", ["A001", ["正常"], 200])

    add("D16", "selected AS (SELECT * FROM areas WHERE code=ANY(%s)), merged AS (SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom FROM selected), "
        "overlap AS (SELECT ST_Intersection(a.geom,b.geom) AS geom FROM areas a CROSS JOIN areas b WHERE a.code=%s AND b.code=%s)",
        f"jsonb_build_object('union_area',{union_area},'summed_area',(SELECT {_summary(_area(),'area')} FROM selected),'overlap_area',(SELECT {_single('area')} FROM overlap))",
        [["A001", "A008"], "A001", "A008"])
    add("D17", coverage + ", clipped_gas AS (" + _clip("gas", "coverage") + ")",
        f"jsonb_build_object('area',(SELECT {_single('area')} FROM coverage),'gas_length',(SELECT {_summary(_length())} FROM clipped_gas WHERE NOT ST_IsEmpty(clipped)))",
        ["A001", ["正常", "告警"], 300])
    add("D18", target() + ", clipped_gas AS (" + _clip("gas") + "), clipped_water AS (" + _clip("water") + ")",
        f"jsonb_build_object('unit','meter','gas_groups',({_groups('clipped_gas','pressure_level',aggregate='sum',sort='value_desc')}),'water_groups',({_groups('clipped_water','pipe_type',aggregate='sum',sort='value_desc')}))", ["A001"])

    def union_count(left: str, right: str, statuses: list[str], keys: tuple[str, str, str]):
        ctes = ("left_area AS (SELECT geom FROM areas WHERE code=%s), right_area AS (SELECT geom FROM areas WHERE code=%s), "
                "combined AS (SELECT ST_Union(l.geom,r.geom) AS geom FROM left_area l CROSS JOIN right_area r), "
                "selected AS (SELECT * FROM devices WHERE status=ANY(%s))")
        body = (f"jsonb_build_object('{keys[0]}',(SELECT COUNT(*) FROM selected d CROSS JOIN left_area a WHERE ST_Intersects(d.geom,a.geom)),"
                f"'{keys[1]}',(SELECT COUNT(*) FROM selected d CROSS JOIN right_area a WHERE ST_Intersects(d.geom,a.geom)),"
                f"'{keys[2]}',(SELECT COUNT(*) FROM selected d CROSS JOIN combined a WHERE ST_Intersects(d.geom,a.geom)))")
        return ctes, body, [left, right, statuses]

    ctes, body, params = union_count("A001", "A002", ["正常"], ("a001_count", "a002_count", "unique_count"))
    add("D19", ctes, body, params)
    add("D20", influence + ", selected_devices AS (SELECT d.* FROM devices d CROSS JOIN effective e WHERE ST_Intersects(d.geom,e.geom) AND d.status=ANY(%s))",
        f"jsonb_build_object('water_unit','meter','device_unit','feature','total_length',{water_summary},'water_groups',({water_groups}),'device_groups',({_groups('selected_devices','status')}))",
        ["A001", "高压", 50, ["正常", "告警"]])

    add("D26", target(), f"jsonb_build_object('area',(SELECT {_single('area')} FROM target))", ["A001"])
    add("D27", "selected AS (SELECT geom FROM gas WHERE code=%s)", f"jsonb_build_object('length',(SELECT {_single('length')} FROM selected))", ["G006"])
    add("D28", "", f"jsonb_build_object('length',(SELECT {_summary(_length('geom'))} FROM roads))")
    add("D32", target() + ", selected AS (SELECT w.* FROM water w CROSS JOIN target t WHERE ST_Within(w.geom,t.geom))", count_answer(), ["A001"])
    add("D33", "buffered AS (SELECT ST_Buffer(geom,%s,'quad_segs=8') AS geom FROM gas WHERE code=%s)",
        f"jsonb_build_object('area',(SELECT {_single('area')} FROM buffered))", [20, "G001"])
    add("D35", target() + ", selected AS (SELECT geom FROM gas WHERE code=%s), clipped_result AS (SELECT ST_Intersection(s.geom,t.geom) AS geom FROM selected s CROSS JOIN target t)",
        f"(SELECT jsonb_build_object('inside_length',{_single('length','c.geom')},'full_length',{_single('length','s.geom')},"
        f"'inside_percent',jsonb_build_object('value',100*{_length('c.geom')}/{_length('s.geom')},'unit','percent','numerator',{_length('c.geom')},'denominator',{_length('s.geom')})) FROM clipped_result c CROSS JOIN selected s)", ["A003", "G006"])
    ctes, params = clipped_summary("water", "A001")
    groups = _groups("clipped_features", "code", aggregate="sum", sort="value_desc").replace("'code', label", "'source_code', label")
    add("D36", ctes, f"jsonb_build_object('unit','meter','groups',({groups}))", params)
    add("D37", "target AS (SELECT ST_Buffer(geom,%s,'quad_segs=8') AS geom FROM devices WHERE code=%s), selected AS (SELECT d.* FROM devices d CROSS JOIN target t WHERE ST_Intersects(d.geom,t.geom))",
        f"jsonb_build_object('unit','feature','groups',({_groups('selected','status')}))", [100, "D011"])
    add("D39", "buffered AS (SELECT ST_Buffer(geom,%s,'quad_segs=8') AS geom FROM devices WHERE status=%s), merged AS (SELECT COALESCE(ST_UnaryUnion(ST_Collect(geom)),ST_GeomFromText('GEOMETRYCOLLECTION EMPTY',3857)) AS geom FROM buffered)",
        f"jsonb_build_object('area',(SELECT {_single('area')} FROM merged))", [100, "正常"])
    ctes, params = clipped_summary("water", "A003")
    add("D40", ctes + ", merged AS (SELECT COALESCE(ST_UnaryUnion(ST_Collect(ST_Buffer(clipped,%s,'quad_segs=8'))),ST_GeomFromText('GEOMETRYCOLLECTION EMPTY',3857)) AS geom FROM clipped_features WHERE NOT ST_IsEmpty(clipped))",
        f"jsonb_build_object('area',(SELECT {_single('area')} FROM merged))", params + [25])

    add("D41", target() + ", selected AS (SELECT d.* FROM devices d CROSS JOIN target t WHERE ST_Intersects(d.geom,t.geom) AND status=%s), "
        "small_buffer AS (SELECT ST_UnaryUnion(ST_Collect(ST_Buffer(geom,%s,'quad_segs=8'))) AS geom FROM selected), "
        "large_buffer AS (SELECT ST_UnaryUnion(ST_Collect(ST_Buffer(geom,%s,'quad_segs=8'))) AS geom FROM selected), "
        "small_coverage AS (SELECT ST_Intersection(b.geom,t.geom) AS geom FROM small_buffer b CROSS JOIN target t), "
        "large_coverage AS (SELECT ST_Intersection(b.geom,t.geom) AS geom FROM large_buffer b CROSS JOIN target t)",
        f"jsonb_build_object('area_100m',(SELECT {_single('area')} FROM small_coverage),'area_300m',(SELECT {_single('area')} FROM large_coverage))", ["A001", "正常", 100, 300])
    ctes, params = clipped_summary("gas", "A003")
    add("D43", ctes, f"jsonb_build_object('unit','meter','groups',({_groups('clipped_features','pressure_level',aggregate='sum',sort='value_desc')}))", params)
    ctes, body, params = union_count("A001", "A003", ["正常", "告警"], ("a001_count", "a003_count", "unique_count"))
    add("D44", ctes, body, params)
    add("D45", "target AS (SELECT ST_Intersection(a.geom,b.geom) AS geom FROM areas a CROSS JOIN areas b WHERE a.code=%s AND b.code=%s), "
        "clipped_gas AS (" + _clip("gas") + "), clipped_water AS (" + _clip("water") + ")",
        f"jsonb_build_object('gas_length',(SELECT {_summary(_length())} FROM clipped_gas WHERE NOT ST_IsEmpty(clipped)),'water_length',(SELECT {_summary(_length())} FROM clipped_water WHERE NOT ST_IsEmpty(clipped)))", ["A001", "A008"])
    add("D47", target() + ", clipped_gas AS (" + _clip("gas") + "), merged AS (SELECT ST_UnaryUnion(ST_Collect(ST_Buffer(clipped,%s,'quad_segs=8'))) AS geom FROM clipped_gas), "
        "coverage AS (SELECT ST_Intersection(m.geom,t.geom) AS geom FROM merged m CROSS JOIN target t)",
        f"(SELECT jsonb_build_object('area',{_single('area','c.geom')},'coverage_percent',{ratio_area}) FROM coverage c CROSS JOIN target t)", ["A001", 25])
    add("D48", summed_buffers + f", totals AS (SELECT SUM({_area()}) AS summed FROM buffered)",
        f"jsonb_build_object('union_area',{union_area},'summed_area',{summed_area},'union_percent',(SELECT jsonb_build_object('value',100*{_area('m.geom')}/t.summed,'unit','percent','numerator',{_area('m.geom')},'denominator',t.summed) FROM merged m CROSS JOIN totals t))", ["A001", ["正常", "告警"], 200])
    add("D49", target() + ", clipped_gas AS (" + _clip("gas") + "), totals AS (SELECT COALESCE(SUM(" + _length() + "),0) AS all_length, COALESCE(SUM(" + _length() + ") FILTER (WHERE pressure_level=%s),0) AS high_length FROM clipped_gas WHERE NOT ST_IsEmpty(clipped))",
        "(SELECT jsonb_build_object('total_length',all_length,'high_pressure_length',high_length,'unit','meter','high_pressure_percent',jsonb_build_object('value',100*high_length/all_length,'unit','percent','numerator',high_length,'denominator',all_length)) FROM totals)", ["A001", "高压"])
    add("D50", "target AS (SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom FROM areas WHERE code=ANY(%s)), "
        "selected AS (SELECT d.* FROM devices d CROSS JOIN target t WHERE ST_Intersects(d.geom,t.geom) AND d.status=%s), "
        "buffered AS (SELECT ST_Buffer(geom,%s,'quad_segs=8') AS geom FROM selected), merged AS (SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom FROM buffered), "
        "coverage AS (SELECT ST_Intersection(m.geom,t.geom) AS geom FROM merged m CROSS JOIN target t)",
        f"(SELECT jsonb_build_object('device_count',(SELECT COUNT(*) FROM selected),'area',{_single('area','c.geom')},'coverage_percent',{ratio_area}) FROM coverage c CROSS JOIN target t)", [["A001", "A002"], "正常", 200])
    try:
        return statements[case_id]
    except KeyError as exc:
        raise ValueError(f"未知 dev50 题号: {case_id}") from exc


def compute_expected(database_url: str | None = None, schema: str | None = None) -> dict[str, dict[str, Any]]:
    """在同一只读快照内计算全部 50 题，任一题失败均不返回部分标准答案。"""
    from psycopg.conninfo import make_conninfo
    from tools.db import get_connection, quote_identifier

    namespace = schema or settings.APP_SCHEMA
    qualified = quote_identifier(namespace)
    dsn = make_conninfo(database_url or settings.DATABASE_URL, connect_timeout=5)
    answers: dict[str, dict[str, Any]] = {}
    with get_connection(dsn) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '30s'")
        for table in ("construction_areas", "gas_pipelines", "water_pipelines", "gas_devices", "demo_roads"):
            count, bad = connection.execute(
                f"SELECT COUNT(*), COUNT(*) FILTER (WHERE geom IS NULL OR ST_SRID(geom)=0 OR NOT ST_IsValid(geom)) FROM {qualified}.{quote_identifier(table)}"
            ).fetchone()
            if count == 0 or bad:
                raise ValueError(f"图层 {table} 为空或包含无效/未声明坐标系的几何，拒绝生成答案")
        for table, codes in (("construction_areas", ["A001", "A002", "A003", "A008", "A009"]),
                             ("gas_devices", ["D011"]), ("gas_pipelines", ["G001", "G006"])):
            rows = connection.execute(
                f"SELECT code, COUNT(*) FROM {qualified}.{quote_identifier(table)} WHERE code = ANY(%s) GROUP BY code",
                [codes],
            ).fetchall()
            if dict(rows) != {code: 1 for code in codes}:
                raise ValueError(f"图层 {table} 缺少题目目标要素，或业务编码不唯一，拒绝生成答案")
        for case_id in CASE_IDS:
            sql, params = oracle_query(case_id, namespace)
            answer = connection.execute(sql, params).fetchone()[0]
            if not isinstance(answer, dict) or not answer:
                raise ValueError(f"{case_id} 独立 SQL 未产生有效答案")
            # JSON 序列化同时拒绝 NaN/Infinity；不存在的目标/零分母会使生成失败。
            json.dumps(answer, allow_nan=False)
            answers[case_id] = answer
    return answers
