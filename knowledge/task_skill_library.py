"""阶段①知识加载：领域知识 + 任务级 skill 检索（余弦相似度）。

## skill 是什么

一个 skill 是一个"典型小任务"的做法，而不是算子参数手册：

- 小任务：只调用**一个**算子，例如「属性条件筛选」→ `query_features`；
- 稍大但不复杂的典型任务：串联**几个**算子，例如
  「裁剪后量测」→ `query_features` → `clip_features` → `measure_features`。

skill 描述"这类问题通常怎么做、按什么顺序做"，规划阶段据此组织 DAG。

## 检索方式

问题进来后，用 TF-IDF 向量 + 余弦相似度（`retrieval/cosine_similarity.py`）在
`SKILL_LIBRARY` 中检索最相关的 top-k 个 skill，而不是按列表顺序截取前 k 个。

## 算子绑定

算子（`buffer_geometry`、`query_features`、`clip_features`、`measure_features`、
`summarize_features`、`calculate_ratio` 等）启动时已通过 `bind_tools` 与模型绑定
（见 `pipeline/llm_client.py` 与 `tools/postgis_tools.py`），不需要在提示词里罗列参数。
"""
from __future__ import annotations

from config import settings
from retrieval.cosine_similarity import TfidfIndex, cut_relative

# 领域知识（业务语义/编码约定等，不含题目答案）
DOMAIN_KNOWLEDGE: dict[str, str] = {
    "gas": (
        "燃气图层：gas_devices 按 status（正常/告警/停用）区分，gas_pipelines 按 "
        "pressure_level（低压/中压/高压）区分；施工区用 construction_areas.code"
        "（A001…）引用。"
    ),
    "water": (
        "水管图层：water_pipelines 按 pipe_type（给水/排水）区分，线要素可按"
        " code（W001…）引用；施工区用 construction_areas.code 引用。"
    ),
    "power": "当前库中没有电力图层，电务类问题按通用空间分析处理。",
    "general": (
        "全部矢量图层使用 EPSG:3857 平面坐标，长度单位 meter、面积单位 square_meter。"
        "ST_Within 表示严格位于内部（不含边界），ST_Intersects 表示相交（含边界接触）。"
        "施工区 A003 含孔洞，孔洞不属于实体区域。裁剪后量测的单位与 SRID 需保持一致。"
    ),
}

# ---------------------------------------------------------------------------
# 任务级 skill 库：一个 skill = 一个小任务，可能只用一个算子，也可能串联几个算子
# ---------------------------------------------------------------------------
SKILL_LIBRARY: list[dict] = [
    {
        "id": "attribute_filter_count",
        "name": "属性条件计数",
        "desc": "按属性条件筛选要素并统计数量，不涉及空间范围",
        "operators": ["query_features"],
        "steps": "query_features(layer_name, filters)",
        "scenes": "属性查询、按状态/类型计数",
    },
    {
        "id": "spatial_query_count",
        "name": "空间范围筛选计数",
        "desc": "在要素集合上叠加空间条件（严格内部用 ST_Within，含边界用 ST_Intersects）后统计数量",
        "operators": ["query_features"],
        "steps": "query_features(layer_name, filters, target, relation)",
        "scenes": "某施工区内的设备/管线数量、边界是否计入",
    },
    {
        "id": "group_count",
        "name": "分组计数",
        "desc": "按某字段分组统计要素数量，可按分组名升序或数值排序输出全部分组",
        "operators": ["query_features", "summarize_features"],
        "steps": "query_features → summarize_features(aggregate=count, group_by, sort)",
        "scenes": "按设备类型/状态分组计数",
    },
    {
        "id": "buffer_intersect_measure",
        "name": "缓冲区求交量测",
        "desc": "以某要素为中心建立缓冲区，与另一区域求交后量测面积或长度",
        "operators": ["buffer_geometry", "intersection_geometry", "measure_geometry"],
        "steps": "buffer_geometry → intersection_geometry → measure_geometry",
        "scenes": "缓冲区落在某施工区内的面积、距离影响范围",
    },
    {
        "id": "intersection_measure",
        "name": "两区域求交量测",
        "desc": "两个面要素求交，按交集维度量测长度或面积（共边时量长度而非面积）",
        "operators": ["intersection_geometry", "measure_geometry"],
        "steps": "intersection_geometry → measure_geometry",
        "scenes": "施工区重叠面积、公共边界长度",
    },
    {
        "id": "clip_measure",
        "name": "裁剪后量测",
        "desc": "把线要素裁剪到面要素内，再量测区内长度；孔洞需排除，边界接触需保留",
        "operators": ["query_features", "clip_features", "measure_features"],
        "steps": "query_features → clip_features → measure_features",
        "scenes": "施工区内管线长度、排除孔洞",
    },
    {
        "id": "group_sum",
        "name": "分组求和",
        "desc": "裁剪并量测后按字段分组汇总，输出全部分组及参与要素数，按值降序/分组名升序",
        "operators": ["query_features", "clip_features", "measure_features", "summarize_features"],
        "steps": "query_features → clip_features → measure_features → summarize_features(aggregate=sum, group_by)",
        "scenes": "按压力等级/管线类型分组统计区内长度",
    },
    {
        "id": "union_measure",
        "name": "合并去重量测",
        "desc": "先合并要素几何去掉重叠，再量测面积；与逐要素面积直接相加的结果区分开",
        "operators": ["query_features", "union_features", "measure_geometry"],
        "steps": "query_features → union_features → measure_geometry",
        "scenes": "缓冲覆盖联合面积、多区合并面积",
    },
    {
        "id": "buffer_union_clip",
        "name": "缓冲合并后裁剪",
        "desc": "对设备批量缓冲、合并去重，再裁剪到某施工区，得到影响范围的覆盖面积或覆盖管线长度",
        "operators": ["query_features", "buffer_features", "union_features", "clip_features", "measure_features"],
        "steps": "query_features → buffer_features → union_features → clip_features → measure_features",
        "scenes": "多设备影响范围覆盖面积、范围内管线长度",
    },
    {
        "id": "ratio_percent",
        "name": "占比计算",
        "desc": "用两个同单位量测结果计算百分比，例如覆盖面积占施工区面积的比例",
        "operators": ["measure_geometry", "calculate_ratio"],
        "steps": "measure_geometry ×2 → calculate_ratio",
        "scenes": "覆盖率、占比",
    },
    {
        "id": "dedup_union_count",
        "name": "合并后去重计数",
        "desc": "多个区域先合并，再统计与合并范围相交的要素数，避免同一要素重复计数",
        "operators": ["query_features", "union_features"],
        "steps": "query_features(区域) → union_features → query_features(目标, target=合并几何, relation=ST_Intersects)",
        "scenes": "跨区去重统计、联合范围计数",
    },
    {
        "id": "multi_layer_summary",
        "name": "多图层汇总",
        "desc": "对多种图层分别做空间筛选、裁剪、量测与分组汇总，结果合并为一个答案",
        "operators": ["query_features", "clip_features", "measure_features", "summarize_features"],
        "steps": "query_features(燃气) → clip_features → measure_features → summarize_features；水管同理",
        "scenes": "燃气与水管分别统计、综合任务",
    },
]


def _skill_text(skill: dict) -> str:
    """把一个 skill 拼成用于向量化的文本。"""
    return " ".join([
        skill.get("name", ""),
        skill.get("desc", ""),
        skill.get("scenes", ""),
        skill.get("steps", ""),
        " ".join(skill.get("operators", [])),
    ])


_SKILL_INDEX = TfidfIndex([_skill_text(s) for s in SKILL_LIBRARY])
_DOMAIN_INDEX = TfidfIndex(list(DOMAIN_KNOWLEDGE.values()))


def retrieve_skills(question: str, top_k: int | None = None) -> list[tuple[float, dict]]:
    """按余弦相似度检索最相关的 skill（再做相对截断，滤掉凑数的低相关项）。"""
    top_k = top_k or settings.SKILL_TOP_K
    hits = _SKILL_INDEX.search(question, top_k=top_k, min_score=settings.RETRIEVAL_MIN_SCORE)
    return [(score, SKILL_LIBRARY[pos])
            for score, pos in cut_relative(hits, settings.RETRIEVAL_RELATIVE_CUTOFF)]


def retrieve_domain_knowledge(question: str, domain: str = "") -> str:
    """按余弦相似度挑选领域知识；识别出的领域作为兜底。"""
    hit = _DOMAIN_INDEX.best(question, min_score=settings.RETRIEVAL_MIN_SCORE)
    if hit and hit[0] >= 0.05:
        keys = list(DOMAIN_KNOWLEDGE)
        return DOMAIN_KNOWLEDGE[keys[hit[1]]]
    return DOMAIN_KNOWLEDGE.get(domain, "")


def render_skills(hits: list[tuple[float, dict]]) -> str:
    if not hits:
        return ("【相关 skill】未检索到足够相关的 skill，请按通用 GIS 分析流程规划"
                "（算子已绑定在模型上，可直接调用）。")
    lines = ["【相关 skill（按余弦相似度检索，任务级做法，算子已绑定）】"]
    for score, s in hits:
        lines.append(f"- {s['name']}（相关度 {score:.2f}）")
        lines.append(f"  做法：{s['desc']}")
        lines.append(f"  典型步骤：{s['steps']}")
    return "\n".join(lines)


def load_skills(question: str = "", domain: str = "", top_k: int | None = None) -> str:
    """检索与当前问题最相关的领域知识 + skill，渲染为注入文本。

    注意：这里**不是**按库里的顺序取前 top_k 个，而是按余弦相似度排序后取 top_k。
    """
    lines: list[str] = []
    knowledge = retrieve_domain_knowledge(question, domain)
    if knowledge:
        lines.append(f"【领域知识】{knowledge}")
    lines.append(render_skills(retrieve_skills(question, top_k)))
    return "\n".join(lines)
