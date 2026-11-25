"""恢复原 20 题并扩充为 50 题；可用独立 SQL 生成标准答案。

python scripts/build_dev50_suite.py
python scripts/build_dev50_suite.py --compute-expected
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark.dev20 import compare
from benchmark.dev50 import CASE_IDS, SUITE_ID, compute_expected, oracle_query


SEMANTICS = (
    "以数据库当前几何为准，在 EPSG:3857 平面计算米和平方米；缓冲固定 quad_segs=8。"
    "ST_Intersects 包含边界接触；点的 ST_Within 排除区域边界；孔洞不属于实体内部。"
    "裁剪只保留非空交集，保留非空但长度为零的边界接触记录。"
    "计数按来源图层和主键去重；逐要素量测求和与合并去重量测须分别计算。"
    "分组输出全部组，中文名称按 Unicode 升序；按值降序时同值按分组名称或编码升序。"
)

MEASURE = "量测对象，包含 value、unit、measure、measure_srid=3857、is_empty；面积单位 square_meter，长度单位 meter。"
SUMMARY = "要素集量测汇总，包含 value、unit、measure、measure_srid=3857、feature_count，空集合数量和值均为0。"
GROUPS = "全部分组数组；各项包含 group 对象、value、feature_count，顺序按题意。"
RATIO = "比例对象，包含 value、unit='percent'、numerator、denominator；value=100*numerator/denominator。"


NEW_CASES = [
    ("D21", "L1", "统计严格位于施工区 A002 内且状态为正常的燃气设备数量，区域边界上的设备不计入。", ["query", "within", "boundary"], {"count": "满足条件的源设备去重数量。"}),
    ("D22", "L1", "统计与施工区 A002 相交且状态为正常或告警的燃气设备数量，包含边界接触，同一设备只计一次。", ["query", "intersects", "attribute_in"], {"count": "满足条件的源设备去重数量。"}),
    ("D23", "L1", "查询与含孔洞施工区 A003 相交的全部燃气设备，按 status 分组计数，按状态名称升序输出全部分组；孔洞内设备不计入，边界接触计入。", ["query", "hole", "group_count"], {"unit": "固定为 feature。", "groups": GROUPS}),
    ("D24", "L1", "查询全部燃气管线，按 pressure_level 分组计数，按压力等级名称升序输出全部分组，不做空间筛选。", ["query", "group_count"], {"unit": "固定为 feature。", "groups": GROUPS}),
    ("D25", "L1", "查询全部水管，按 pipe_type 分组计数，按管线类型名称升序输出全部分组，不做空间筛选。", ["query", "group_count"], {"unit": "固定为 feature。", "groups": GROUPS}),
    ("D26", "L1", "计算施工区 A001 的实体面积（平方米），不要计算周长。", ["single_geometry", "area"], {"area": MEASURE}),
    ("D27", "L1", "计算燃气管线 G006 的完整长度（米），不与任何施工区裁剪。", ["single_geometry", "length"], {"length": MEASURE}),
    ("D28", "L1", "计算全部道路 demo_roads 的长度总和（米），并返回参与量测的源道路数量；道路逐条量测后求和，不做空间合并去重。", ["feature_measure", "sum"], {"length": SUMMARY}),
    ("D29", "L1", "查询燃气设备中 status 严格等于字符串“__不存在的状态__”的要素，返回匹配设备数量。没有匹配时返回0，不能当成目标要素不存在而报错。", ["query", "empty_set"], {"count": "满足指定属性条件的设备数量。"}),
    ("D30", "L1", "统计严格位于孤立施工区 A009 内且状态为正常的燃气设备数量，边界设备不计入；无匹配时返回0。", ["query", "within", "empty_set"], {"count": "满足条件的设备数量。"}),
    ("D31", "L2", "将所有与 A002 相交的燃气管线裁剪到 A002，计算区内总长度（米）与非空裁剪结果的源管线数量，保留非空零长度边界接触记录。", ["clip", "length", "boundary"], {"length": SUMMARY}),
    ("D32", "L2", "统计整条几何满足 ST_Within(水管, A001) 的水管数量，不做裁剪。此处严格采用 PostGIS ST_Within 的关系定义：线可以接触边界，但不能有部分位于区域外，且线内部与区域内部必须相交。", ["query", "within", "line_relation"], {"count": "满足完整线几何 ST_Within 关系的源水管数量。"}),
    ("D33", "L2", "对燃气管线 G001 的完整几何建立20米缓冲区，计算缓冲面积（平方米）；不按施工区裁剪，缓冲采用 quad_segs=8。", ["buffer", "area"], {"area": MEASURE}),
    ("D34", "L2", "计算施工区 A001 与孤立施工区 A009 的交集面积（平方米），允许合法空交集；空结果面积为0且 is_empty 为true。", ["intersection", "empty_geometry", "area"], {"area": MEASURE}),
    ("D35", "L2", "计算燃气管线 G006 在 A003 实体部分内的长度和其完整长度（米），再计算区内长度占完整长度的百分比。孔洞部分排除，边界接触计入。", ["clip", "length", "ratio"], {"inside_length": MEASURE, "full_length": MEASURE, "inside_percent": RATIO}),
    ("D36", "L2", "将所有与 A001 相交的水管裁剪到 A001，逐条量测区内长度（米），按源水管编码 source_code 分组，按长度降序、同长按编码升序输出全部分组，保留非空零长度边界接触记录。", ["clip", "group_sum", "length"], {"unit": "固定为 meter。", "groups": GROUPS}),
    ("D37", "L2", "以燃气设备 D011 为中心建立100米缓冲区，统计与该缓冲区相交的全部燃气设备，按 status 分组计数，按状态名称升序输出全部分组；包含 D011 自身及缓冲边界设备。", ["buffer", "query", "group_count"], {"unit": "固定为 feature。", "groups": GROUPS}),
    ("D38", "L2", "计算施工区 A002 与狭长施工区 A008 的交集面积（平方米），允许空交集，不把公共边界长度作为面积。", ["intersection", "area"], {"area": MEASURE}),
    ("D39", "L2", "查询全库状态为正常的燃气设备，分别建立100米缓冲区，合并消除重叠后计算总覆盖面积（平方米），不按施工区裁剪。", ["query", "buffer", "union", "area"], {"area": MEASURE}),
    ("D40", "L2", "先将所有与 A003 相交的水管裁剪到 A003 实体部分，排除孔洞，仅保留非空裁剪结果；再对各条裁剪结果建立25米缓冲区并合并去重，计算最终面积（平方米）。建立缓冲之后不再按 A003 裁剪。", ["clip", "buffer", "union", "hole"], {"area": MEASURE}),
    ("D41", "L3", "复用与 A001 相交且状态为正常的同一批燃气设备，分别建立100米和300米缓冲区；两个半径各自合并重叠后裁剪到 A001，分别计算覆盖面积（平方米），边界设备计入。", ["shared_source", "buffer", "union", "clip"], {"area_100m": MEASURE, "area_300m": MEASURE}),
    ("D42", "L3", "取与 A002 相交的高压燃气管线，先裁剪到 A002，再分别缓冲50米并合并。计算全部水管位于该影响范围且位于 A002 内的总长度（米）与非空裁剪结果的源水管数量，保留非空零长度接触。", ["buffer", "union", "double_clip", "length"], {"length": SUMMARY}),
    ("D43", "L3", "将所有与含孔洞施工区 A003 相交的燃气管线裁剪到其实体部分，按 pressure_level 汇总区内长度（米），按长度降序、同长按压力名称升序输出全部分组；排除孔洞，保留非空零长度接触记录。", ["hole", "clip", "group_sum"], {"unit": "固定为 meter。", "groups": GROUPS}),
    ("D44", "L3", "分别统计与 A001、A003 相交且状态为正常或告警的燃气设备数，再合并这两个施工区后统计该状态条件下的联合去重设备数。边界接触计入，不能直接把两区数量相加。", ["union", "query", "deduplicate"], {"a001_count": "A001的匹配设备数。", "a003_count": "A003的匹配设备数。", "unique_count": "两个区域联合范围内的源设备去重数量。"}),
    ("D45", "L3", "先求 A001 与 A008 的交集范围，复用这一范围，分别计算其中全部燃气管线和全部水管的裁剪后总长度（米）与非空源要素数量；边界接触计入，保留非空零长度记录。", ["shared_geometry", "intersection", "clip", "length"], {"gas_length": SUMMARY, "water_length": SUMMARY}),
    ("D46", "L3", "对与 A002 相交且状态为正常的燃气设备分别建立150米缓冲区，合并重叠后裁剪到 A002，计算覆盖面积（平方米）及其占 A002 实体面积的百分比；边界设备计入。", ["buffer", "union", "clip", "ratio"], {"area": MEASURE, "coverage_percent": RATIO}),
    ("D47", "L3", "将与 A001 相交的全部燃气管线先裁剪到 A001，再逐条缓冲25米并合并去重，最后再裁剪到 A001。计算最终覆盖面积（平方米）及其占 A001 面积的百分比。", ["clip", "buffer", "union", "ratio"], {"area": MEASURE, "coverage_percent": RATIO}),
    ("D48", "L3", "对与 A001 相交且正常或告警的燃气设备逐条建立200米缓冲区，不裁剪缓冲区。复用这批缓冲结果，分别计算逐要素面积直接相加、合并去重面积（平方米），再计算合并去重面积占直接相加面积的百分比。", ["buffer", "union_vs_sum", "ratio"], {"union_area": MEASURE, "summed_area": SUMMARY, "union_percent": RATIO}),
    ("D49", "L3", "将所有与 A001 相交的燃气管线裁剪到 A001，计算全部管线长度总和、其中高压管线长度总和（米），再计算高压长度占全部长度的百分比。长度逐条相加，保留非空零长度接触记录。", ["clip", "group_sum", "ratio"], {"total_length": "全部管线的裁剪后长度总和数值。", "high_pressure_length": "高压管线的裁剪后长度总和数值。", "unit": "固定为 meter。", "high_pressure_percent": RATIO}),
    ("D50", "L3", "先合并施工区 A001 与 A002，对与联合范围相交且状态正常的设备按源主键去重后分别建立200米缓冲区，合并缓冲重叠，再裁剪到施工区联合范围。返回源设备数量、覆盖面积（平方米）及其占施工区联合去重面积的百分比；区域公共边界设备仅计一次。", ["union", "deduplicate", "shared_geometry", "ratio"], {"device_count": "参与建立缓冲区的源设备去重数量。", "area": MEASURE, "coverage_percent": RATIO}),
]


def _write_json(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_suite(out_dir: Path, history: Path, *, calculate: bool = False) -> dict:
    run = json.loads(history.read_text(encoding="utf-8"))
    originals = sorted(run["results"], key=lambda item: item["id"])
    if [item["id"] for item in originals] != list(CASE_IDS[:20]):
        raise ValueError("历史结果必须恰好包含 D01-D20")
    original_answers = {item["id"]: item["expected"] for item in originals}
    if any(not isinstance(value, dict) or not value for value in original_answers.values()):
        raise ValueError("历史记录缺少 expected 标准答案，不能用模型 answer 替代")
    cases = []
    contracts = {"count": "源要素去重计数。", "unit": "计量单位，feature/meter/square_meter，按题意。",
                 "groups": GROUPS, "gas_groups": GROUPS, "water_groups": GROUPS, "device_groups": GROUPS,
                 "length": SUMMARY, "gas_length": SUMMARY, "total_length": SUMMARY, "area": MEASURE,
                 "union_area": MEASURE, "summed_area": SUMMARY, "overlap_area": MEASURE, "coverage_percent": RATIO,
                 "a001_count": "与A001相交的源设备去重数量。", "a002_count": "与A002相交的源设备去重数量。",
                 "unique_count": "联合范围内的源设备去重数量。", "water_unit": "固定为meter。", "device_unit": "固定为feature。"}
    for item in originals:
        contract = {key: contracts.get(key, "按题意返回此字段，结构见输出模板。") for key in item["expected"]}
        # 原题单几何长度含 is_empty，不含 feature_count；保留原标准答案形状。
        for key, value in item["expected"].items():
            if isinstance(value, dict) and "is_empty" in value and "measure" in value:
                contract[key] = MEASURE
        cases.append({"id": item["id"], "level": item["level"], "question": item["question"],
                      "tags": ["original_dev20"], "semantics": SEMANTICS, "output_contract": contract,
                      "origin": "reports/dev20/dev20_latest.json: results.expected and question; model answer excluded"})
    for case_id, level, question, tags, contract in NEW_CASES:
        cases.append({"id": case_id, "level": level, "question": question, "tags": tags,
                      "semantics": SEMANTICS, "output_contract": contract, "origin": "dev50 extension"})
    for item in cases:
        sql, params = oracle_query(item["id"], "__APP_SCHEMA__")
        item["reference_sql"] = sql
        item["reference_params"] = params
    suite = {"suite": SUITE_ID, "version": 1, "case_count": 50, "original_case_count": 20,
             "description": "原dev20保持不变并新增30题；标准答案由独立只读PostGIS SQL生成。",
             "semantics": SEMANTICS, "cases": cases}
    _write_json(out_dir / "dev20.json", {"suite": "postgis_dev20_v1", "cases": cases[:20]})
    _write_json(out_dir / "dev20_expected.json", {"suite": "postgis_dev20_v1", "cases": original_answers,
                                                "provenance": "Recovered results.expected from " + str(history.name)})
    _write_json(out_dir / "dev50.json", suite)
    expected_path = out_dir / "dev50_expected.json"
    expected = {"suite": SUITE_ID, "status": "pending", "cases": original_answers,
                "pending_case_ids": list(CASE_IDS[20:]),
                "provenance": {"D01-D20": "historical independent-SQL expected snapshot, recovered from results.expected",
                               "D21-D50": "pending: run build_dev50_suite.py --compute-expected against the original seeded PostGIS database"}}
    if not expected_path.exists():
        _write_json(expected_path, expected)
    if calculate:
        calculated = compute_expected()
        changed = [case_id for case_id, reference in original_answers.items() if compare(calculated[case_id], reference)]
        if changed:
            raise ValueError("当前数据库与原dev20标准答案不一致，拒绝混用数据集: " + ", ".join(changed))
        expected = {"suite": SUITE_ID, "status": "complete", "cases": calculated, "pending_case_ids": [],
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "provenance": {"method": "independent parameterized PostGIS SQL in one read-only REPEATABLE READ snapshot",
                                   "original_snapshot_check": "D01-D20 all match recovered historical expected answers",
                                   "oracle": "benchmark.dev50.oracle_query"}}
        _write_json(expected_path, expected)
    return {"case_count": len(cases), "original_case_count": len(originals), "expected_status":
            json.loads(expected_path.read_text(encoding="utf-8"))["status"], "out_dir": str(out_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "benchmarks")
    parser.add_argument("--history", type=Path, default=ROOT / "reports" / "dev20" / "dev20_latest.json")
    parser.add_argument("--compute-expected", action="store_true", help="连接原种子PostGIS，用独立SQL完整生成并核对50题标准答案")
    args = parser.parse_args()
    try:
        result = build_suite(args.out_dir, args.history, calculate=args.compute_expected)
    except Exception as exc:
        # 不把包含连接凭据的异常字符串写入终端。
        if isinstance(exc, ValueError):
            print(str(exc), file=sys.stderr)
        else:
            print(f"标准答案生成失败（{type(exc).__name__}）；请检查本机PostGIS连接及原种子数据。", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
