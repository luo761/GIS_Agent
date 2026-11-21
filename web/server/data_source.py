"""项目数据接入层（零第三方依赖）。

网页端需要的所有业务数据都来自项目本身：

- 能力向量与进化历史：`data/agent_capabilities.json`（演示副本在 `web/data/demo_state.json`）
- 智能体构成、维度标签、进化/路由参数：`config/agents_capability.yaml`
- 领域分类：`config/domains_taxonomy.yaml`
- 技能库 / 领域知识：`knowledge/task_skill_library.py`（用 ast 静态读取，不执行模块）
- 共享经验池：`data/experience.json`
- 智能体专属记忆：`data/memory/<agent>/record/*.json`、`cache.json`
- 基准评测结果：`reports/dev20/*.json`

检索统一复用项目的 `retrieval/cosine_similarity.py`（通过文件路径加载），
保证网页里的相关度数值与项目内一致。
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import math
import os
import re
import shutil
import socket
import time
from pathlib import Path
from typing import Any

from yaml_lite import parse_yaml

WEB_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = WEB_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
REPORTS_DIR = PROJECT_ROOT / "reports"

WEB_DATA_DIR = WEB_DIR / "data"
DEMO_STATE_PATH = WEB_DATA_DIR / "demo_state.json"
DEMO_RUNS_PATH = WEB_DATA_DIR / "demo_runs.json"
SNAPSHOT_PATH = WEB_DATA_DIR / "snapshot.js"
DEMO_RUN_LIMIT = 40

# 系统管理页直接操作的项目真实文件
CAPABILITY_PATH = DATA_DIR / "agent_capabilities.json"
AGENTS_CONFIG_PATH = CONFIG_DIR / "agents_capability.yaml"
MEMORY_ROOT = DATA_DIR / "memory"
# 记忆长期记录目录（唯一规范目录）
RECORD_DIR_NAMES = ("record",)

# ---------------------------------------------------------------------------
# 项目检索模块（stdlib only）——与项目内所有检索点共用同一实现
# ---------------------------------------------------------------------------
def _load_cosine_module():
    path = PROJECT_ROOT / "retrieval" / "cosine_similarity.py"
    spec = importlib.util.spec_from_file_location("gis_web_cosine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


cosine = _load_cosine_module()


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
class Config:
    def __init__(self) -> None:
        self.agents_raw: dict[str, Any] = {}
        self.domains_raw: dict[str, Any] = {}
        self._load()

    def reload(self) -> None:
        """重新读取 config/*.yaml（系统管理页修改 tie_epsilon 后调用）。"""
        self._load()

    def _load(self) -> None:
        try:
            self.agents_raw = parse_yaml(
                AGENTS_CONFIG_PATH.read_text(encoding="utf-8")
            ) or {}
        except OSError:
            self.agents_raw = {}
        try:
            self.domains_raw = parse_yaml(
                (CONFIG_DIR / "domains_taxonomy.yaml").read_text(encoding="utf-8")
            ) or {}
        except OSError:
            self.domains_raw = {}

    @property
    def dimensions(self) -> list[str]:
        glossary = self.agents_raw.get("capability_glossary") or {}
        if glossary:
            return list(glossary)
        return ["spatial_compute", "attribute_query", "statistics", "mapping"]

    @property
    def labels(self) -> dict[str, str]:
        return dict(self.agents_raw.get("capability_labels") or {})

    @property
    def glossary(self) -> dict[str, str]:
        return dict(self.agents_raw.get("capability_glossary") or {})

    @property
    def initial_capability(self) -> float:
        return float(self.agents_raw.get("initial_capability", 0.5))

    @property
    def evolution(self) -> dict[str, Any]:
        return dict(self.agents_raw.get("evolution") or {})

    @property
    def routing(self) -> dict[str, Any]:
        return dict(self.agents_raw.get("routing") or {})

    @property
    def agent_defs(self) -> dict[str, dict[str, Any]]:
        return dict(self.agents_raw.get("agents") or {})

    @property
    def domains(self) -> dict[str, dict[str, Any]]:
        return dict(self.domains_raw.get("domains") or {})

    @property
    def task_types(self) -> list[str]:
        return list(self.domains_raw.get("task_types") or [])

    @property
    def task_type_capabilities(self) -> dict[str, list[str]]:
        return dict(self.domains_raw.get("task_type_capabilities") or {})

    @property
    def domain_names(self) -> dict[str, str]:
        return {k: str(v.get("name") or k) for k, v in self.domains.items()}


CONFIG = Config()


# ---------------------------------------------------------------------------
# 技能库与领域知识（ast 静态解析）
# ---------------------------------------------------------------------------
def _load_library_constants() -> tuple[list[dict], dict[str, str]]:
    source_path = PROJECT_ROOT / "knowledge" / "task_skill_library.py"
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return [], {}
    skills: list[dict] = []
    knowledge: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
            value_node = node.value
        else:
            continue
        try:
            value = ast.literal_eval(value_node)
        except (ValueError, SyntaxError, TypeError):
            continue
        for target in targets:
            if target.id == "SKILL_LIBRARY" and isinstance(value, list):
                skills = value
            elif target.id == "DOMAIN_KNOWLEDGE" and isinstance(value, dict):
                knowledge = value
    return skills, knowledge


SKILLS, DOMAIN_KNOWLEDGE = _load_library_constants()

# 技能 id → 业务领域标签（仅用于界面着色，不影响项目逻辑）
SKILL_GROUPS = {
    "attribute_filter_count": "属性",
    "spatial_query_count": "空间",
    "group_count": "统计",
    "buffer_intersect_measure": "空间",
    "intersection_measure": "空间",
    "clip_measure": "空间",
    "group_sum": "统计",
    "union_measure": "空间",
    "buffer_union_clip": "空间",
    "ratio_percent": "比例",
    "dedup_union_count": "去重",
    "multi_layer_summary": "综合",
}

# ---------------------------------------------------------------------------
# 表结构知识（无数据库时的内置视图；字段与样例与项目知识库保持一致）
# ---------------------------------------------------------------------------
SCHEMA_TABLES: list[dict[str, Any]] = [
    {
        "name": "construction_areas",
        "note": "施工区（面要素），按 code 引用，如 A001/A003",
        "fields": [
            {"name": "id", "type": "integer", "note": "主键"},
            {"name": "code", "type": "text", "note": "业务编号", "samples": ["A001", "A002", "A003", "A008", "A009"]},
            {"name": "name", "type": "text", "note": "施工区名称", "samples": ["滨江路施工段", "科技园施工区"]},
            {"name": "area_type", "type": "text", "note": "区域类型", "samples": ["道路", "管网", "综合"]},
            {"name": "geom", "type": "geometry(MultiPolygon,3857)", "note": "空间几何；A003 含孔洞"},
        ],
    },
    {
        "name": "gas_devices",
        "note": "燃气设备（点要素），按 code 引用，如 D001/D011",
        "fields": [
            {"name": "id", "type": "integer", "note": "主键"},
            {"name": "code", "type": "text", "note": "业务编号", "samples": ["D001", "D011", "D016"]},
            {"name": "device_type", "type": "text", "note": "设备类型", "samples": ["调压箱", "阀井", "计量表"]},
            {"name": "status", "type": "text", "note": "运行状态", "samples": ["正常", "告警", "停用"]},
            {"name": "geom", "type": "geometry(Point,3857)", "note": "空间几何（EPSG:3857）"},
        ],
    },
    {
        "name": "gas_pipelines",
        "note": "燃气管线（线要素），按 code 引用，如 G001/G006",
        "fields": [
            {"name": "id", "type": "integer", "note": "主键"},
            {"name": "code", "type": "text", "note": "业务编号", "samples": ["G001", "G006", "G012"]},
            {"name": "pressure_level", "type": "text", "note": "压力等级", "samples": ["低压", "中压", "次高压", "高压"]},
            {"name": "material", "type": "text", "note": "管材", "samples": ["PE", "钢管", "铸铁"]},
            {"name": "diameter_mm", "type": "integer", "note": "管径（毫米）", "samples": ["110", "200", "315"]},
            {"name": "geom", "type": "geometry(LineString,3857)", "note": "空间几何（EPSG:3857）"},
        ],
    },
    {
        "name": "water_pipelines",
        "note": "给排水管线（线要素），按 code 引用，如 W001/W008",
        "fields": [
            {"name": "id", "type": "integer", "note": "主键"},
            {"name": "code", "type": "text", "note": "业务编号", "samples": ["W001", "W008", "W015"]},
            {"name": "pipe_type", "type": "text", "note": "管线类型", "samples": ["给水", "排水"]},
            {"name": "material", "type": "text", "note": "管材", "samples": ["PE", "球墨铸铁", "混凝土"]},
            {"name": "diameter_mm", "type": "integer", "note": "管径（毫米）", "samples": ["200", "400", "600"]},
            {"name": "geom", "type": "geometry(LineString,3857)", "note": "空间几何（EPSG:3857）"},
        ],
    },
    {
        "name": "demo_roads",
        "note": "道路（线要素），如 R001",
        "fields": [
            {"name": "id", "type": "integer", "note": "主键"},
            {"name": "code", "type": "text", "note": "业务编号", "samples": ["R001", "R002"]},
            {"name": "road_type", "type": "text", "note": "道路类型", "samples": ["主干路", "次干路"]},
            {"name": "geom", "type": "geometry(LineString,3857)", "note": "空间几何"},
        ],
    },
    {
        "name": "region_stat",
        "note": "行政区统计（属性表）",
        "fields": [
            {"name": "region_code", "type": "text", "note": "行政区编码（GB/T 2260）", "samples": ["320102", "320104"]},
            {"name": "region_name", "type": "text", "note": "行政区名称", "samples": ["玄武区", "秦淮区"]},
            {"name": "population", "type": "integer", "note": "常住人口（人）"},
            {"name": "year", "type": "integer", "note": "统计年份", "samples": ["2023", "2024"]},
        ],
    },
]


def _table_document(table: dict[str, Any]) -> str:
    fields = " ".join(
        "{} {} {}".format(
            f.get("name", ""),
            f.get("note", ""),
            "/".join(f.get("samples") or []),
        )
        for f in table.get("fields", [])
    )
    return f"表 {table.get('name', '')} {table.get('note', '')} {fields}"


def _skill_document(skill: dict[str, Any]) -> str:
    return " ".join(
        [
            skill.get("name", ""),
            skill.get("desc", ""),
            skill.get("scenes", ""),
            skill.get("steps", ""),
            " ".join(skill.get("operators", [])),
        ]
    )


# ---------------------------------------------------------------------------
# 工具目录（对应 tools/postgis_tools.py 绑定的 10 个 PostGIS 算子）
# ---------------------------------------------------------------------------
TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "query_features",
        "label": "要素查询",
        "category": "要素集",
        "description": "按属性条件与空间关系查询图层要素，是每个任务的入口算子。",
        "params": "layer_name, filters, fields, target, relation (ST_Within / ST_Intersects)",
    },
    {
        "name": "buffer_features",
        "label": "批量缓冲",
        "category": "要素集",
        "description": "对要素集中的每个要素按指定距离缓冲，生成面要素集。",
        "params": "input, distance_m, segments",
    },
    {
        "name": "union_features",
        "label": "合并去重",
        "category": "要素集",
        "description": "合并要素集几何并去掉重叠，用于计算联合覆盖范围。",
        "params": "input",
    },
    {
        "name": "clip_features",
        "label": "裁剪",
        "category": "要素集",
        "description": "把要素裁剪到目标面内；默认保留边界接触并丢弃空几何，孔洞自动排除。",
        "params": "input, clip_geom, keep_empty",
    },
    {
        "name": "measure_features",
        "label": "要素集量测",
        "category": "要素集",
        "description": "对要素集逐要素量测长度/面积，可保留零长度但非空的接触记录。",
        "params": "input, operation (ST_Length / ST_Area), unit",
    },
    {
        "name": "summarize_features",
        "label": "分组汇总",
        "category": "要素集",
        "description": "按字段分组计数或求和，支持多字段排序并输出全部分组。",
        "params": "input, aggregate (count / sum), group_by, sort",
    },
    {
        "name": "calculate_ratio",
        "label": "占比计算",
        "category": "要素集",
        "description": "用两个同单位量测结果计算百分比，例如覆盖面积占区域面积的比例。",
        "params": "numerator, denominator",
    },
    {
        "name": "buffer_geometry",
        "label": "单几何缓冲",
        "category": "单几何",
        "description": "对单个几何建立缓冲区，常与求交、量测组合使用。",
        "params": "geometry, distance_m, crs",
    },
    {
        "name": "intersection_geometry",
        "label": "几何求交",
        "category": "单几何",
        "description": "两个几何求交；共边时交集为线，可直接量测公共边界长度。",
        "params": "left, right, crs",
    },
    {
        "name": "measure_geometry",
        "label": "单几何量测",
        "category": "单几何",
        "description": "量测单个几何的面积/长度；只接受单个几何，要素集请用 measure_features。",
        "params": "target, metric (area / length), unit",
    },
]


# ---------------------------------------------------------------------------
# 能力状态
# ---------------------------------------------------------------------------
def _default_capability_state() -> dict[str, Any]:
    agents: dict[str, Any] = {}
    for aid, cfg in CONFIG.agent_defs.items():
        agents[aid] = {
            "name": str(cfg.get("name", aid)),
            "capabilities": {
                d: float((cfg.get("capabilities") or {}).get(d, CONFIG.initial_capability))
                for d in CONFIG.dimensions
            },
            "preferred_tools": list(cfg.get("preferred_tools") or []),
            "stats": {"attempts": 0, "successes": 0, "failures": 0},
        }
    return {
        "schema_version": 1,
        "initial_capability": CONFIG.initial_capability,
        "dimensions": list(CONFIG.dimensions),
        "agents": agents,
        "history": [],
        "updated_at": _now(),
        "source": "initial",
    }


def _normalize_capability(state: dict[str, Any]) -> dict[str, Any]:
    """补齐维度与智能体，保证不同版本的落盘文件都能渲染。"""
    base = _default_capability_state()
    state = copy.deepcopy(state or {})
    agents = state.get("agents") or {}
    merged: dict[str, Any] = {}
    for aid, base_agent in base["agents"].items():
        cur = dict(agents.get(aid) or {})
        caps = dict(cur.get("capabilities") or {})
        for dim in CONFIG.dimensions:
            caps.setdefault(dim, base_agent["capabilities"][dim])
        merged[aid] = {
            "name": str(cur.get("name") or base_agent["name"]),
            "capabilities": {d: round(float(caps[d]), 4) for d in CONFIG.dimensions},
            "preferred_tools": list(cur.get("preferred_tools") or [])[-5:],
            "stats": {
                "attempts": int((cur.get("stats") or {}).get("attempts", 0)),
                "successes": int((cur.get("stats") or {}).get("successes", 0)),
                "failures": int((cur.get("stats") or {}).get("failures", 0)),
            },
        }
    history = [h for h in (state.get("history") or []) if isinstance(h, dict)]
    return {
        "schema_version": 1,
        "initial_capability": CONFIG.initial_capability,
        "dimensions": list(CONFIG.dimensions),
        "agents": merged,
        "history": history,
        "updated_at": str(state.get("updated_at") or ""),
        "source": str(state.get("source") or "real"),
    }


def capability_payload(state: dict[str, Any], *, source: str) -> dict[str, Any]:
    normalized = _normalize_capability(state)
    normalized["source"] = source
    return {
        "initial_capability": normalized["initial_capability"],
        "dimensions": normalized["dimensions"],
        "labels": CONFIG.labels,
        "glossary": CONFIG.glossary,
        "agents": normalized["agents"],
        "history": normalized["history"],
        "updated_at": normalized["updated_at"],
        "source": normalized["source"],
        "evolution": CONFIG.evolution,
        "routing": CONFIG.routing,
        "colors": AGENT_COLORS,
    }


AGENT_COLORS = {
    "agent_01": "#2563eb",
    "agent_02": "#e11d48",
    "agent_03": "#059669",
    "agent_04": "#d97706",
}
AGENT_COLOR_FALLBACKS = ["#2563eb", "#e11d48", "#059669", "#d97706", "#7c3aed", "#0891b2"]


def real_capability() -> dict[str, Any]:
    state = _read_json(DATA_DIR / "agent_capabilities.json", {})
    return _normalize_capability(state)


def _ensure_demo_state() -> dict[str, Any]:
    """首次访问时用项目真实能力快照初始化演示会话，之后只读写 web/data。"""
    state = _read_json(DEMO_STATE_PATH)
    if not isinstance(state, dict) or not state.get("agents"):
        state = real_capability()
        state["source"] = "initialized_from_real"
        _write_json(DEMO_STATE_PATH, state)
    return state


def demo_capability() -> dict[str, Any]:
    return _normalize_capability(_ensure_demo_state())


def save_demo_capability(state: dict[str, Any]) -> None:
    state = _normalize_capability(state)
    state["updated_at"] = _now()
    _write_json(DEMO_STATE_PATH, state)


def reset_demo_capability(*, seed: str = "initial") -> dict[str, Any]:
    if seed == "real":
        state = real_capability()
        state["source"] = "synced_from_real"
    else:
        state = _default_capability_state()
    state["updated_at"] = _now()
    _write_json(DEMO_STATE_PATH, state)
    return state


# ---------------------------------------------------------------------------
# 系统管理：真实能力向量 / 路由容差 / 记忆空间
# ---------------------------------------------------------------------------
def reset_real_capability(target: float | None = None) -> dict[str, Any]:
    """把项目真实能力向量表恢复到初始均衡值（默认 0.5）。

    同时清空进化历史、执行统计和工具偏好，保证能力值与历史记录一致。
    只写 data/agent_capabilities.json，不影响演示会话。
    """
    value = float(CONFIG.initial_capability if target is None else target)
    state = _default_capability_state()
    state["initial_capability"] = value
    for agent in state["agents"].values():
        agent["capabilities"] = {dim: value for dim in CONFIG.dimensions}
        agent["stats"] = {"attempts": 0, "successes": 0, "failures": 0}
        agent["preferred_tools"] = []
    state["history"] = []
    state["source"] = "reset_real"
    state["updated_at"] = _now()
    _write_json(CAPABILITY_PATH, state)
    return _normalize_capability(state)


def update_tie_epsilon(value: float) -> dict[str, Any]:
    """把 routing.tie_epsilon 写回 config/agents_capability.yaml，保留注释与排版。"""
    try:
        epsilon = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("tie_epsilon 必须是数字") from exc
    if not math.isfinite(epsilon) or epsilon < 0 or epsilon > 1:
        raise ValueError("tie_epsilon 必须在 0 到 1 之间")
    if not AGENTS_CONFIG_PATH.exists():
        raise ValueError("找不到 config/agents_capability.yaml")
    # newline="" 保留文件原有的 CRLF/LF，避免只改一个参数却重写整个文件的换行符
    with AGENTS_CONFIG_PATH.open("r", encoding="utf-8", newline="") as fp:
        text = fp.read()
    pattern = re.compile(
        r"(?m)^([ \t]*tie_epsilon[ \t]*:[ \t]*)"
        r"([-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?)"
        r"([ \t]*(?:#.*)?)(\r?)$"
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError("配置文件中未找到唯一的 routing.tie_epsilon")
    formatted = ("%.6f" % epsilon).rstrip("0").rstrip(".")
    if "." not in formatted and "e" not in formatted.lower():
        formatted += ".0"
    match = matches[0]
    new_text = (
        text[: match.start()] + match.group(1) + formatted
        + match.group(3) + match.group(4) + text[match.end():]
    )
    tmp = AGENTS_CONFIG_PATH.with_suffix(AGENTS_CONFIG_PATH.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fp:
        fp.write(new_text)
    tmp.replace(AGENTS_CONFIG_PATH)
    CONFIG.reload()
    effective = float(CONFIG.routing.get("tie_epsilon", epsilon))
    return {
        "ok": True,
        "tie_epsilon": effective,
        "path": _path_label(AGENTS_CONFIG_PATH),
        "routing": CONFIG.routing,
    }


def _remove_memory_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def mutate_agent_memory(agent_id: str, *, scope: str = "all", mode: str = "clear") -> dict[str, Any]:
    """清空或删除某个智能体的长期记录 / 短期缓存。

    scope: records | cache | all
    mode:  clear  = 保留目录/文件容器，只清内容（cache.json 写成 []）
           delete = 删除记录目录 / 缓存文件本身
    """
    if scope not in ("records", "cache", "all"):
        raise ValueError("scope 只能是 records / cache / all")
    if mode not in ("clear", "delete"):
        raise ValueError("mode 只能是 clear / delete")
    root = _agent_memory_root(agent_id)
    removed_files = 0
    freed_bytes = 0
    removed_records = 0
    removed_cache_entries = 0

    if scope in ("records", "all"):
        for record_dir in _record_dirs(root):
            if not record_dir.exists():
                continue
            removed_files += sum(1 for p in record_dir.rglob("*") if p.is_file())
            removed_records += sum(1 for _ in record_dir.glob("*.json"))
            freed_bytes += _dir_size(record_dir)
            _remove_memory_path(record_dir)
            if mode == "clear":
                record_dir.mkdir(parents=True, exist_ok=True)

    if scope in ("cache", "all"):
        cache_file = root / "cache.json"
        if cache_file.exists():
            cache = _read_json(cache_file, [])
            if isinstance(cache, list):
                removed_cache_entries = len(cache)
            removed_files += 1
            freed_bytes += _dir_size(cache_file)
            if mode == "delete":
                cache_file.unlink(missing_ok=True)
            else:
                _write_json(cache_file, [])
        elif mode == "clear":
            # 文件本来就不存在时，"清空"仍写入空缓存，保持一个明确的空状态
            _write_json(cache_file, [])

    return {
        "ok": True,
        "agent_id": agent_id,
        "scope": scope,
        "mode": mode,
        "root": _path_label(root),
        "removed_records": removed_records,
        "removed_cache_entries": removed_cache_entries,
        "removed_files": removed_files,
        "freed_bytes": freed_bytes,
        "memory": load_memory().get(agent_id) or {},
    }


def admin_payload() -> dict[str, Any]:
    """系统管理页所需的真实文件状态与可编辑参数。"""
    real = real_capability()
    return {
        "generated_at": _now(),
        "capability": capability_payload(real, source="real"),
        "capability_path": _path_label(CAPABILITY_PATH),
        "capability_exists": CAPABILITY_PATH.exists(),
        "routing": CONFIG.routing,
        "tie_epsilon": float(CONFIG.routing.get("tie_epsilon", 0.1)),
        "routing_path": _path_label(AGENTS_CONFIG_PATH),
        "memory": load_memory(),
        "memory_limits": MEMORY_LIMITS,
    }


# ---------------------------------------------------------------------------
# 记忆 / 经验 / 评测报告
# ---------------------------------------------------------------------------
def _load_memory_limits() -> dict[str, int]:
    """从 config/settings.py 读取记忆容量与注入条数（用 ast，不导入模块）。"""
    defaults = {
        "AGENT_MEMORY_CACHE_MAX": 5,
        "AGENT_MEMORY_RECORD_MAX": 10,
        "AGENT_MEMORY_CACHE_TOP_K": 3,
        "AGENT_MEMORY_RECORD_TOP_K": 2,
    }
    try:
        tree = ast.parse((CONFIG_DIR / "settings.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return defaults
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value_node = node.value
        else:
            continue
        for name in targets:
            if name not in defaults:
                continue
            try:
                value = ast.literal_eval(value_node)
            except (ValueError, SyntaxError, TypeError):
                continue
            if isinstance(value, int) and value >= 0:
                defaults[name] = value
    return defaults


MEMORY_LIMITS = _load_memory_limits()


def _path_label(path: Path) -> str:
    """把项目内路径显示为相对路径，避免前端出现机器绝对路径。"""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _agent_memory_root(agent_id: str) -> Path:
    """解析某智能体的记忆根目录，并限制在项目 data/memory 下，防止误删。"""
    if agent_id not in CONFIG.agent_defs:
        raise ValueError(f"未知智能体: {agent_id}")
    cfg = CONFIG.agent_defs.get(agent_id) or {}
    raw = cfg.get("memory_dir")
    if raw:
        root = Path(str(raw))
        if not root.is_absolute():
            root = PROJECT_ROOT / root
    else:
        root = MEMORY_ROOT / agent_id
    root = root.resolve()
    allowed = MEMORY_ROOT.resolve()
    if root != allowed and allowed not in root.parents:
        raise ValueError(f"拒绝操作 data/memory 之外的目录: {root}")
    return root


def _record_dirs(root: Path) -> list[Path]:
    return [root / name for name in RECORD_DIR_NAMES]


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def load_memory() -> dict[str, Any]:
    out: dict[str, Any] = {}
    cache_max = int(MEMORY_LIMITS["AGENT_MEMORY_CACHE_MAX"])
    record_max = int(MEMORY_LIMITS["AGENT_MEMORY_RECORD_MAX"])
    cache_top_k = int(MEMORY_LIMITS["AGENT_MEMORY_CACHE_TOP_K"])
    record_top_k = int(MEMORY_LIMITS["AGENT_MEMORY_RECORD_TOP_K"])
    for aid in sorted(CONFIG.agent_defs):
        root = _agent_memory_root(aid)
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        # 长期记录统一落在 record/ 目录
        for record_dir in _record_dirs(root):
            if not record_dir.exists():
                continue
            for path in record_dir.glob("*.json"):
                record = _read_json(path)
                if not isinstance(record, dict):
                    continue
                record.setdefault("id", path.stem)
                rid = str(record.get("id"))
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                record["_file"] = path.name
                record["_dir"] = record_dir.name
                record["_mtime"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)
                )
                records.append(record)
        records.sort(key=lambda r: (str(r.get("_mtime") or ""), str(r.get("id") or "")), reverse=True)
        cache_file = root / "cache.json"
        cache = _read_json(cache_file, [])
        if not isinstance(cache, list):
            cache = []
        out[aid] = {
            "agent_id": aid,
            "name": str((CONFIG.agent_defs.get(aid) or {}).get("name", aid)),
            "root": _path_label(root),
            # 原始文件内容 + 生效容量：文件可能来自旧版本配置，条数会暂时超过上限
            "records": records,
            "records_total": len(records),
            "records_bytes": sum(_dir_size(d) for d in _record_dirs(root)),
            "record_dirs": [d.name for d in _record_dirs(root) if d.exists()],
            "record_max": record_max,
            "record_top_k": record_top_k,
            "cache": cache,
            "cache_total": len(cache),
            "cache_bytes": _dir_size(cache_file),
            "cache_exists": cache_file.exists(),
            "cache_max": cache_max,
            "cache_top_k": cache_top_k,
        }
    return out


def load_experience() -> list[dict[str, Any]]:
    items = _read_json(DATA_DIR / "experience.json", [])
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, dict):
            item.setdefault("hits", 0)
    return items


def report_index() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not REPORTS_DIR.exists():
        return entries
    for path in sorted(REPORTS_DIR.glob("dev20/*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict) or "meta" not in payload or "results" not in payload:
            continue
        meta = payload.get("meta") or {}
        summary = payload.get("summary") or {}
        entries.append(
            {
                "name": path.name,
                "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "started_at": meta.get("started_at", ""),
                "model": meta.get("model", ""),
                "database": meta.get("database", ""),
                "elapsed_s": meta.get("total_elapsed_s"),
                "case_count": meta.get("case_count", len(payload.get("results") or [])),
                "accuracy": summary.get("accuracy"),
                "correct": summary.get("correct"),
                "total": summary.get("total"),
                "by_level": summary.get("by_level") or {},
                "latest": path.name == "dev20_latest.json",
            }
        )
    entries.sort(
        key=lambda e: (e["latest"], e.get("started_at") or "", e["name"]), reverse=True
    )
    # 同名时间戳报告较多时只保留最近 8 份，外加 latest
    trimmed: list[dict[str, Any]] = []
    seen = 0
    for entry in entries:
        if entry["latest"]:
            trimmed.append(entry)
            continue
        if seen >= 8:
            continue
        trimmed.append(entry)
        seen += 1
    return trimmed


def load_report(name: str) -> dict[str, Any] | None:
    allowed = {entry["name"] for entry in report_index()}
    if name not in allowed:
        return None
    return _read_json(REPORTS_DIR / "dev20" / name)


# ---------------------------------------------------------------------------
# 演示运行记录
# ---------------------------------------------------------------------------
def load_runs() -> list[dict[str, Any]]:
    runs = _read_json(DEMO_RUNS_PATH, [])
    return runs if isinstance(runs, list) else []


def save_run(run: dict[str, Any]) -> None:
    runs = load_runs()
    runs.insert(0, run)
    del runs[DEMO_RUN_LIMIT:]
    _write_json(DEMO_RUNS_PATH, runs)


def clear_runs() -> None:
    _write_json(DEMO_RUNS_PATH, [])


def get_run(run_id: str) -> dict[str, Any] | None:
    for run in load_runs():
        if run.get("run_id") == run_id:
            return run
    return None


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------
_SKILL_INDEX = cosine.TfidfIndex([_skill_document(s) for s in SKILLS])
_TABLE_INDEX = cosine.TfidfIndex([_table_document(t) for t in SCHEMA_TABLES])


def _relative_cut(hits: list[tuple[float, int]], ratio: float = 0.4) -> list[tuple[float, int]]:
    return cosine.cut_relative(hits, ratio)


def retrieve_skills(query: str, top_k: int = 4) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    hits = _SKILL_INDEX.search(query, top_k=top_k, min_score=0.0)
    out = []
    for score, pos in _relative_cut(hits):
        skill = SKILLS[pos]
        out.append({**skill, "score": round(float(score), 4), "group": SKILL_GROUPS.get(skill.get("id", ""), "其他")})
    return out


def retrieve_tables(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    hits = _TABLE_INDEX.search(query, top_k=top_k, min_score=0.0)
    out = []
    for score, pos in _relative_cut(hits):
        table = SCHEMA_TABLES[pos]
        out.append(
            {
                "name": table["name"],
                "note": table["note"],
                "fields": table["fields"],
                "score": round(float(score), 4),
            }
        )
    return out


def retrieve_experience(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    items = load_experience()
    if not items or not query.strip():
        return []
    docs = [
        " ".join([i.get("task_signature", ""), i.get("question_feat", ""), i.get("error_lesson", "")])
        for i in items
    ]
    index = cosine.TfidfIndex(docs)
    hits = index.search(query, top_k=top_k, min_score=0.0)
    out = []
    for score, pos in _relative_cut(hits):
        out.append({**items[pos], "score": round(float(score), 4)})
    return out


def retrieve_memory(agent_id: str, query: str, top_k: int = 3) -> list[dict[str, Any]]:
    memory = load_memory().get(agent_id) or {}
    records = [r for r in memory.get("records") or [] if r.get("question_feat")]
    if not records or not query.strip():
        return []
    index = cosine.TfidfIndex([r.get("question_feat", "") for r in records])
    hits = index.search(query, top_k=top_k, min_score=0.0)
    out = []
    for score, pos in _relative_cut(hits):
        out.append({**records[pos], "score": round(float(score), 4)})
    return out


def retrieval_playground(query: str, kind: str, agent: str = "agent_02") -> dict[str, Any]:
    if kind == "skills":
        return {"kind": kind, "query": query, "items": retrieve_skills(query, top_k=6)}
    if kind == "tables":
        return {"kind": kind, "query": query, "items": retrieve_tables(query, top_k=6)}
    if kind == "experience":
        return {"kind": kind, "query": query, "items": retrieve_experience(query, top_k=5)}
    if kind == "memory":
        return {"kind": kind, "query": query, "agent": agent,
                "items": retrieve_memory(agent, query, top_k=5)}
    return {"kind": kind, "query": query, "items": []}


# ---------------------------------------------------------------------------
# 健康检查 / 引导数据
# ---------------------------------------------------------------------------
def _port_open(host: str, port: int, timeout: float = 0.12) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def health() -> dict[str, Any]:
    env_file = PROJECT_ROOT / ".env"
    llm_env = any(
        os.getenv(key) for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY")
    )
    return {
        "generated_at": _now(),
        "project_root": str(PROJECT_ROOT),
        "web_root": str(WEB_DIR),
        "python": os.sys.version.split()[0],
        "database": {
            "configured": "5433",
            "reachable": _port_open("127.0.0.1", 5433),
            "url": "postgresql://gis_user@localhost:5433/gis_agent",
            "source": "内置示例表结构（只读展示）",
        },
        "llm": {
            "env_file": env_file.exists(),
            "key_present": bool(llm_env),
            "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        },
        "mode": "demo",
        "mode_label": "本地演示会话",
        "data_files": {
            "capability": (DATA_DIR / "agent_capabilities.json").exists(),
            "experience": (DATA_DIR / "experience.json").exists(),
            "memory": (DATA_DIR / "memory").exists(),
            "reports": (REPORTS_DIR / "dev20").exists(),
        },
    }


def bootstrap() -> dict[str, Any]:
    demo = demo_capability()
    real = real_capability()
    memory = load_memory()
    experience = load_experience()
    reports = report_index()
    runs = load_runs()
    counts = {
        "agents": len(demo["agents"]),
        "dimensions": len(CONFIG.dimensions),
        "skills": len(SKILLS),
        "tables": len(SCHEMA_TABLES),
        "tools": len(TOOL_CATALOG),
        "experience": len(experience),
        "memory_records": sum(len(m["records"]) for m in memory.values()),
        "memory_cache": sum(len(m["cache"]) for m in memory.values()),
        "evolution_events": len(demo.get("history") or []),
        "runs": len(runs),
        "reports": len(reports),
    }
    return {
        "generated_at": _now(),
        "project": {
            "name": "GIS 多智能体任务架构",
            "subtitle": "能力进化版 · 五阶段流水线",
            "root": str(PROJECT_ROOT),
            "readme": str(PROJECT_ROOT / "README.md"),
        },
        "dimensions": CONFIG.dimensions,
        "labels": CONFIG.labels,
        "glossary": CONFIG.glossary,
        "initial_capability": CONFIG.initial_capability,
        "evolution": CONFIG.evolution,
        "routing": CONFIG.routing,
        "colors": AGENT_COLORS,
        "capability": capability_payload(demo, source="demo"),
        "real_capability": capability_payload(real, source="real"),
        "skills": [
            {**s, "group": SKILL_GROUPS.get(s.get("id", ""), "其他")} for s in SKILLS
        ],
        "domain_knowledge": DOMAIN_KNOWLEDGE,
        "domains": CONFIG.domains,
        "domain_names": CONFIG.domain_names,
        "task_types": CONFIG.task_types,
        "task_type_capabilities": CONFIG.task_type_capabilities,
        "schema": {
            "source": "demo",
            "source_label": "内置示例表结构（字段来自项目知识库定义，未连接 PostGIS）",
            "tables": SCHEMA_TABLES,
        },
        "tools": TOOL_CATALOG,
        "experience": experience,
        "memory": memory,
        "reports": reports,
        "runs": runs[:10],
        "counts": counts,
        "health": health(),
        "examples": [
            "统计严格位于施工区 A001 内、状态为正常的燃气设备数量，边界上的设备不计入。",
            "统计与含孔洞的施工区 A003 相交、状态为正常的燃气设备数量，孔洞内的设备不计入，边界接触计入。",
            "将所有与 A001 相交的燃气管线裁剪到 A001，按 pressure_level 汇总区内长度（米），按总长度降序排列。",
            "以燃气设备 D011 为中心建立 300 米缓冲区，计算缓冲区位于 A001 内的面积（平方米）。",
            "计算所有水管位于施工区 A003 实体部分内的总长度（米），排除孔洞，包含边界接触。",
            "对与 A001 相交且正常或告警的设备分别建立 300 米缓冲区，合并后裁剪到 A001，求覆盖面积及占 A001 面积的百分比。",
            "分别统计与施工区 A001、A002 相交且状态正常的设备数，再将两个施工区合并后统计联合去重数量。",
        ],
    }


def write_snapshot() -> Path:
    payload = bootstrap()
    payload["snapshot_only"] = True
    text = "window.__GIS_SNAPSHOT__ = " + json.dumps(payload, ensure_ascii=False) + ";\n"
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(text, encoding="utf-8")
    return SNAPSHOT_PATH


def export_capability_chart() -> Path | None:
    """复制项目生成的动态能力图到 web 数据目录，供页面直接打开。"""
    src = DATA_DIR / "capability_vector_chart.html"
    if not src.exists():
        return None
    dst = WEB_DATA_DIR / "capability_vector_chart.html"
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


if __name__ == "__main__":
    path = write_snapshot()
    print(f"snapshot -> {path}")
