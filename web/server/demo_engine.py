"""演示执行引擎：在浏览器端复现"五阶段流水线 + 能力进化"。

为什么需要它
------------
项目的真实执行链路依赖 LLM、LangGraph、PostGIS 与外部工具集。为了让网页在
任何机器上都能演示交互与执行流，这里提供一个**确定性可复现**的本地模拟引擎：

- 领域识别、任务类型判定、能力维度标注：关键词规则（与项目分类口径一致）
- 表结构 / skill / 经验 / 专属记忆检索：**真实调用项目的 TF-IDF 余弦检索**
- 路由、能力进化：**严格按 config/agents_capability.yaml 的公式与参数**
- 计划 DAG 与工具调用轨迹：按检索到的 skill 算子链生成（数值为模拟值）

执行流和能力状态仍写 `web/data/`；记忆写入位置可选：默认写演示记忆
`web/data/memory`，也可由用户显式选择写入项目真实记忆 `data/memory`。
不会修改 `data/agent_capabilities.json` 或经验池。页面上会明确标注"演示会话"。
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import time
import uuid
from typing import Any

import data_source as ds

_SPACE_WORDS = (
    "缓冲", "裁剪", "相交", "求交", "交集", "重叠", "空间", "几何", "长度", "面积",
    "位于", "覆盖", "合并", "量测", "范围", "孔洞", "边界", "距离", "缓冲", "邻接",
)
_ATTR_WORDS = ("查询", "筛选", "状态", "类型", "条件", "字段", "属性", "编号", "code")
_STAT_WORDS = (
    "统计", "计数", "数量", "分组", "汇总", "排序", "占比", "百分比", "总数",
    "求和", "汇总", "总和", "多少", "几个", "分别",
)
_MAP_WORDS = ("制图", "可视化", "专题图", "符号", "出图", "地图", "渲染")
_COMPLEX_WORDS = ("分别", "以及", "同时", "并且", "然后", "；", ";", "（1）", "(1)")

_DOMAIN_LAYERS = {
    "gas": ("gas_devices", "gas_pipelines"),
    "water": ("water_pipelines",),
    "power": ("power_line",),
    "general": ("construction_areas", "region_stat"),
}

_OP_LABELS = {
    "query_features": "要素查询",
    "buffer_features": "批量缓冲",
    "union_features": "合并去重",
    "clip_features": "裁剪到区域",
    "measure_features": "要素集量测",
    "summarize_features": "分组汇总",
    "calculate_ratio": "占比计算",
    "buffer_geometry": "单几何缓冲",
    "intersection_geometry": "几何求交",
    "measure_geometry": "单几何量测",
}

_COUNT_KEYS = ("数量", "个数", "计数", "多少")


def _digest(*parts: Any) -> int:
    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:12], 16)


def _rng(*parts: Any) -> random.Random:
    return random.Random(_digest(*parts))


def _round(x: float, nd: int = 1) -> float:
    return round(float(x), nd)


def _now_ms() -> int:
    return int(time.time() * 1000)


class DemoEngine:
    """一次演示运行的完整编排。"""

    def __init__(self) -> None:
        self.config = ds.CONFIG
        self.state = ds.demo_capability()
        self.run_id = "run_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
        self.started = _now_ms()
        self.question = ""
        self.truth = ""
        self.verdict_mode = "auto"
        self.domain = "general"
        self.task_type = "空间计算"
        self.dims: list[str] = []
        self.tables: list[dict] = []
        self.skills: list[dict] = []
        self.experience_hits: list[dict] = []
        self.subtasks: list[dict] = []
        self.timeline: list[dict] = []
        self.memory_target = "demo"
        self.memory_writes: list[dict] = []
        self.memory_errors: list[str] = []
        self.user_id = ""
        self.role = "analyst"
        self.role_name = "业务分析员"
        self.permission_denials: list[dict] = []
        self.validity: dict[str, Any] = {}
        self.t0 = _now_ms()

    # ------------------------------------------------------------------ 工具
    def _beat(self, stage: str, title: str, detail: str = "", kind: str = "info") -> None:
        self.timeline.append(
            {
                "stage": stage,
                "title": title,
                "detail": detail,
                "kind": kind,
                "at_ms": _now_ms() - self.t0,
            }
        )

    def _caps(self, agent_id: str) -> dict[str, float]:
        caps = (self.state.get("agents", {}).get(agent_id) or {}).get("capabilities") or {}
        return {d: float(caps.get(d, self.config.initial_capability)) for d in self.config.dimensions}

    def _vector(self, agent_id: str) -> list[float]:
        caps = self._caps(agent_id)
        return [caps[d] for d in self.config.dimensions]

    # ------------------------------------------------------------------ 权限
    def _allowed_tables(self) -> set[str]:
        return set(ds.PERMISSIONS.allowed_tables(self.role, "select"))

    def _check_node(self, node: dict) -> str:
        """返回空串=允许；否则返回拒绝原因。与工具执行器的表级校验同源。"""
        table = str((node.get("params") or {}).get("layer_name") or "")
        if not table:
            return ""
        result = ds.PERMISSIONS.check(self.role, table, "select")
        if result.allowed:
            return ""
        self.permission_denials.append(result.to_dict())
        return f"权限拒绝：{result.reason}"

    # ------------------------------------------------------------------ 问题不合法
    def _invalid_run(self, verdict: dict[str, Any], capability_before: dict[str, Any]) -> dict[str, Any]:
        """问题不合法：不拆解、不规划、不执行、不进化，只返回澄清追问。"""
        elapsed = _now_ms() - self.started
        reasons = list(verdict.get("reasons") or [])
        missing = list(verdict.get("missing_info") or [])
        clarification = str(verdict.get("clarification") or "")
        self.validity = verdict
        self._beat("understand", "问题不合法", "；".join(reasons) or "信息不足", "error")
        self._beat("understand", "本次执行已中止", "未拆分、未规划、未访问任何数据表", "warn")
        for slot in missing:
            self._beat("understand", "缺少信息 · " + str(slot.get("name")), str(slot.get("prompt") or ""), "warn")

        understand = {
            "stage": "understand",
            "status": "blocked",
            "elapsed_ms": 260,
            "domain": "invalid",
            "domain_label": "问题不合法",
            "task_type": "问题不合法",
            "refined_question": "",
            "tables": [],
            "skills": [],
            "knowledge": "",
            "context": "",
            "validity": verdict,
            "is_valid": False,
            "permission": {
                "role": self.role,
                "role_name": self.role_name,
                "allowed_tables": sorted(self._allowed_tables()),
            },
            "summary": "问题不合法：已中止执行并要求补充信息",
        }
        skipped = {
            "status": "skipped",
            "elapsed_ms": 0,
            "subtasks": [],
            "summary": "问题不合法，本阶段未执行",
        }
        decompose = {**skipped, "stage": "decompose", "refined_question": ""}
        plan_stage = {**skipped, "stage": "plan"}
        execute = {**skipped, "stage": "execute"}
        evaluate = {
            "stage": "evaluate",
            "status": "blocked",
            "elapsed_ms": 120,
            "evaluation": "clarification",
            "correct": None,
            "reason": "；".join(reasons) or "问题信息不足，需要用户补充",
            "final_answer": clarification,
            "answer": None,
            "answer_kind": "澄清追问",
            "changes": [],
            "missing_info": missing,
            "summary": "未执行任何算子，能力向量保持不变",
        }
        run = {
            "run_id": self.run_id,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "demo",
            "question": self.question,
            "truth": self.truth,
            "verdict_mode": self.verdict_mode,
            "memory_target": self.memory_target,
            "memory_writes": [],
            "memory_errors": [],
            "domain": "invalid",
            "domain_label": "问题不合法",
            "task_type": "问题不合法",
            "is_valid": False,
            "validity": verdict,
            "role": self.role,
            "role_name": self.role_name,
            "permission_denials": [],
            "dimensions": self.config.dimensions,
            "labels": self.config.labels,
            "flow": {
                "understand": understand,
                "decompose": decompose,
                "plan": plan_stage,
                "execute": execute,
                "evaluate": evaluate,
            },
            "subtasks": [],
            "capability_before": capability_before,
            "capability_after": capability_before,
            "timeline": self.timeline,
            "metrics": {
                "elapsed_ms": elapsed,
                "tool_calls": 0,
                "tool_errors": 0,
                "retrieval_hits": 0,
                "subtasks": 0,
                "agents_used": [],
            },
            "notes": [
                "演示会话：问题合法性规则与阶段① 共用 security/question_guard.py。",
                "问题不合法时不会进入拆解/规划/执行，也不会修改能力向量。",
                "请按追问补充分析对象、空间范围、筛选条件与输出指标后重新提交。",
            ],
        }
        ds.save_run(run)
        return run


    # ------------------------------------------------------------------ ① 理解
    def _classify_domain(self) -> str:
        text = self.question.lower()
        best, best_score = "general", 0
        for key, domain in self.config.domains.items():
            if (domain or {}).get("special"):
                continue  # invalid 是安全判定结果，不是业务行业
            score = 0
            for word in domain.get("keywords") or []:
                token = str(word).strip().lower()
                if token and token in text:
                    score += 2 if len(token) > 1 else 1
            for table in domain.get("typical_tables") or []:
                if str(table).lower() in text:
                    score += 2
            if score > best_score:
                best, best_score = key, score
        # 明确的图层名比关键词更可靠
        if re.search(r"gas_(devices|pipelines)", text):
            best = "gas"
        elif re.search(r"water_(pipelines|meters)", text):
            best = "water"
        elif re.search(r"水管|给水|排水|给排水", text):
            best = "water"
        elif re.search(r"燃气|调压|燃气管线", text):
            best = "gas"
        return best

    def _classify_task(self) -> str:
        text = self.question
        space = sum(1 for w in _SPACE_WORDS if w in text)
        stat = sum(1 for w in _STAT_WORDS if w in text)
        attr = sum(1 for w in _ATTR_WORDS if w in text)
        mapping = sum(1 for w in _MAP_WORDS if w in text)
        complex_hits = sum(1 for w in _COMPLEX_WORDS if w in text)

        if mapping and mapping >= max(space, stat, attr):
            return "制图可视化"
        if complex_hits >= 2 and len(text) > 45 and (space + stat + attr) >= 3:
            return "综合"
        if stat >= 2 and stat >= space:
            return "统计分析"
        if space >= 2 and space > stat:
            return "空间计算"
        if attr >= 2 and attr > space:
            return "属性查询"
        if stat > 0 and space == 0:
            return "统计分析"
        if space > 0:
            return "空间计算"
        return "属性查询"

    def _detect_dims(self) -> list[str]:
        text = self.question
        found: list[str] = []
        if any(w in text for w in _SPACE_WORDS):
            found.append("spatial_compute")
        if any(w in text for w in _ATTR_WORDS) or re.search(
            r"status|pressure_level|pipe_type|device_type|正常|告警|停用|高压|中压|低压|给水|排水", text
        ):
            found.append("attribute_query")
        if any(w in text for w in _STAT_WORDS):
            found.append("statistics")
        if any(w in text for w in _MAP_WORDS):
            found.append("mapping")
        if not found:
            found = list(self.config.task_type_capabilities.get(self.task_type) or [])
        if self.task_type == "综合":
            found = [d for d in self.config.dimensions if d in found] or list(self.config.dimensions)
        found = [d for d in self.config.dimensions if d in set(found)]
        return found or list(self.config.dimensions)

    def _detected_layers(self) -> list[str]:
        text = self.question.lower()
        layers: list[str] = []
        for table in ("construction_areas", "gas_devices", "gas_pipelines", "water_pipelines", "demo_roads", "region_stat"):
            if table in text:
                layers.append(table)
        if re.search(r"\bA0\d{2}\b", self.question) and "construction_areas" not in layers:
            layers.insert(0, "construction_areas")
        if re.search(r"\bG0\d{2}\b", self.question) and "gas_pipelines" not in layers:
            layers.append("gas_pipelines")
        if re.search(r"\bD0\d{2}\b", self.question) and "gas_devices" not in layers:
            layers.append("gas_devices")
        if re.search(r"\bW0\d{2}\b", self.question) and "water_pipelines" not in layers:
            layers.append("water_pipelines")
        if not layers:
            layers = list(_DOMAIN_LAYERS.get(self.domain, ("construction_areas",)))
        return layers

    def _formalize(self) -> str:
        text = self.question.strip().rstrip("。")
        layers = self._detected_layers()
        semantic = []
        if "严格" in text or "内部" in text:
            semantic.append("严格内部用 ST_Within（不含边界）")
        if "边界" in text or "包含边界" in text:
            semantic.append("边界接触按 ST_Intersects 计入")
        if "孔洞" in text:
            semantic.append("孔洞不属于实体区域，需排除")
        if "EPSG" not in text:
            semantic.append("平面坐标 EPSG:3857，长度 meter / 面积 square_meter")
        tail = "；".join(semantic)
        refined = f"在 PostGIS 数据集上，基于 {'、'.join(layers)} 图层完成：{text}。"
        if tail:
            refined += f"（语义约束：{tail}。）"
        return refined

    # ------------------------------------------------------------------ ② 拆解
    def _split_questions(self) -> list[str]:
        if self.task_type != "综合":
            return [self.refined_question]
        parts = [p.strip() for p in re.split(r"[；;]", self.question) if len(p.strip()) >= 8]
        if len(parts) >= 2:
            return parts[:2]
        match = re.search(r"分别[，,]?(.*)$", self.question)
        if match and len(match.group(1)) > 12:
            return [self.question[: match.start()].rstrip("，, ") + "。", "分别" + match.group(1)]
        return [self.refined_question]

    def _route(self, dims: list[str], subtask_id: str) -> dict[str, Any]:
        agents = sorted(self.state.get("agents") or {})
        scores = {
            aid: _round(sum(self._caps(aid)[d] for d in dims) / max(len(dims), 1), 6)
            for aid in agents
        }
        best = max(scores.values()) if scores else 0.0
        epsilon = float(self.config.routing.get("tie_epsilon", 0.0))
        tied = [aid for aid in agents if best - scores[aid] <= epsilon + 1e-12]
        rng = random.Random()
        chosen = rng.choice(tied) if len(tied) > 1 else tied[0]
        return {
            "agent_id": chosen,
            "agent_name": (self.state["agents"][chosen] or {}).get("name", chosen),
            "required": list(dims),
            "scores": scores,
            "best_score": _round(best, 6),
            "tied": tied,
            "random_pick": len(tied) > 1,
            "epsilon": epsilon,
            "pool": agents,
        }

    # ------------------------------------------------------------------ ③ 规划
    def _layer_for_plan(self) -> str | None:
        layers = [l for l in self._detected_layers() if l != "construction_areas"]
        if layers:
            return layers[0]
        q = self.question
        if any(w in q for w in ("设备", "阀门", "调压箱", "计量表")):
            return "gas_devices" if self.domain in ("gas", "general") else "gas_devices"
        if any(w in q for w in ("水管", "给水", "排水", "给排水")):
            return "water_pipelines"
        if any(w in q for w in ("燃气管线", "燃气管道", "管线", "管道", "管段")):
            return "water_pipelines" if self.domain == "water" else "gas_pipelines"
        if "道路" in q:
            return "demo_roads"
        if "人口" in q or "行政区" in q:
            return "region_stat"
        return None

    def _build_plan(self, subtask: dict, skill: dict | None) -> dict[str, Any]:
        """按问题语义组织算子链，生成计划 DAG。

        检索到的 skill 作为规划参考展示（见 plan_stage.skill），DAG 本身按
        实际任务要素生成：区域查询 → 目标要素查询 → 缓冲 → 合并 → 裁剪 →
        量测 → 汇总 → 占比，保证参数引用（$ref）始终指向已执行的步骤。
        """
        q = self.question
        layers = self._detected_layers()
        primary = self._layer_for_plan()
        codes = list(dict.fromkeys(re.findall(r"\bA0\d{2}\b", q)))[:2] or ["A001"]
        has_area = "construction_areas" in layers or bool(re.search(r"\bA0\d{2}\b", q)) or "施工区" in q
        target_layer = primary if primary != "construction_areas" else None

        wants_buffer = "缓冲" in q
        wants_union = any(w in q for w in ("合并", "去重", "联合"))
        wants_intersection = (
            any(w in q for w in ("求交", "交集", "重叠", "公共边界", "共边"))
            and target_layer is None
        )
        wants_ratio = any(w in q for w in ("占比", "百分比", "比例"))
        wants_sum = any(w in q for w in ("分组", "汇总", "求和", "排序"))
        wants_measure = any(w in q for w in ("长度", "面积", "量测", "覆盖", "影响范围"))
        wants_count = any(w in q for w in ("数量", "计数", "多少个", "几个", "统计"))
        wants_clip = has_area and target_layer is not None and wants_measure
        metric = self._metric(q, target_layer or primary or "")
        unit = "meter" if metric == "length" else "square_meter"
        group_field = self._group_field(q, target_layer or primary or "")
        filters = self._filters(q)
        relation = "ST_Within" if ("严格" in q or ("内部" in q and "边界" not in q)) else "ST_Intersects"
        distance = re.search(r"(\d{2,4})\s*米", q)
        distance_m = int(distance.group(1)) if distance else 300
        dedup_count = wants_union and (wants_count and not wants_measure) and target_layer is not None

        nodes: list[dict[str, Any]] = []

        def add(action: str, params: dict[str, Any], deps: list[str] | None = None) -> str:
            step_id = f"s{len(nodes) + 1}"
            clean = {k: v for k, v in params.items() if v is not None}
            nodes.append(
                {
                    "id": step_id,
                    "action": action,
                    "label": _OP_LABELS.get(action, action),
                    "params": clean,
                    "depends_on": list(deps or []),
                }
            )
            return step_id

        def fs_ref(step_id: str) -> dict[str, str]:
            return {"$ref": f"{step_id}.result.feature_set"}

        def geom_ref(step_id: str) -> dict[str, str]:
            return {"$ref": f"{step_id}.result.geometry"}

        area_ids: list[str] = []
        if has_area:
            if dedup_count and len(codes) > 1:
                area_ids.append(
                    add(
                        "query_features",
                        {
                            "layer_name": "construction_areas",
                            "filters": [{"field": "code", "operator": "in", "value": codes}],
                            "fields": ["code", "geom"],
                        },
                        [],
                    )
                )
            else:
                for code in codes:
                    area_ids.append(
                        add(
                            "query_features",
                            {
                                "layer_name": "construction_areas",
                                "filters": [{"field": "code", "operator": "eq", "value": code}],
                                "fields": ["code", "geom"],
                            },
                            [],
                        )
                    )
        area_geom = geom_ref(area_ids[0]) if area_ids else None

        # 面-面求交：两个施工区直接求交后量测
        if wants_intersection and len(area_ids) >= 2:
            inter = add(
                "intersection_geometry",
                {"left": geom_ref(area_ids[0]), "right": geom_ref(area_ids[1]), "crs": "EPSG:3857"},
                area_ids[:2],
            )
            measure = add(
                "measure_geometry",
                {"target": geom_ref(inter), "metric": metric, "unit": unit},
                [inter],
            )
            if wants_sum:
                add("summarize_features", {"input": {"$ref": f"{measure}.result"}, "aggregate": "sum"}, [measure])
            return self._finish_plan(nodes)

        # 单区域量测（问题只针对施工区本身）
        if target_layer is None and area_geom is not None:
            measure = add(
                "measure_geometry",
                {"target": area_geom, "metric": metric, "unit": unit},
                area_ids[:1],
            )
            return self._finish_plan(nodes)

        # 目标图层：属性筛选 / 空间筛选
        target_fields = ["code", "geom"]
        if group_field not in target_fields:
            target_fields.insert(1, group_field)
        target_filters = list(filters)
        for code in re.findall(r"\b([DGW])0\d{2}\b", q):
            value = re.search(rf"\b{code}0\d{{2}}\b", q)
            if value:
                target_filters.append({"field": "code", "operator": "eq", "value": value.group(0)})
                break

        if dedup_count and area_ids:
            merged = add("union_features", {"input": fs_ref(area_ids[0])}, [area_ids[0]])
            target = add(
                "query_features",
                {
                    "layer_name": target_layer,
                    "filters": target_filters,
                    "fields": target_fields,
                    "relation": relation,
                    "target": geom_ref(merged),
                },
                [merged],
            )
            if "分组" in q or "按" in q:
                add(
                    "summarize_features",
                    {
                        "input": fs_ref(target),
                        "aggregate": "count",
                        "group_by": group_field,
                        "sort": [[f"count_{group_field}", "desc"]],
                    },
                    [target],
                )
            return self._finish_plan(nodes)

        target_deps = area_ids[:1] if area_geom else []
        target = add(
            "query_features",
            {
                "layer_name": target_layer or primary,
                "filters": target_filters,
                "fields": target_fields,
                "relation": relation if area_geom else None,
                "target": area_geom,
            },
            target_deps,
        )
        chain = target

        if wants_buffer:
            chain = add("buffer_features", {"input": fs_ref(chain), "distance_m": distance_m, "segments": 32}, [chain])
        if wants_union:
            chain = add("union_features", {"input": fs_ref(chain)}, [chain])
        if wants_clip and area_geom is not None:
            chain = add(
                "clip_features",
                {"input": fs_ref(chain), "clip_geom": area_geom},
                [chain, *area_ids[:1]],
            )
        if wants_measure:
            measure = add(
                "measure_features",
                {"input": fs_ref(chain), "operation": "ST_Length" if metric == "length" else "ST_Area", "unit": unit},
                [chain],
            )
            chain = measure
        if wants_sum:
            aggregate = "sum" if wants_measure else "count"
            params: dict[str, Any] = {
                "input": fs_ref(chain),
                "aggregate": aggregate,
                "group_by": group_field,
                "sort": [[f"{aggregate}_{group_field}", "desc"]],
            }
            if aggregate == "sum":
                params["value_field"] = "length_m" if metric == "length" else "area_m2"
            chain = add("summarize_features", params, [chain])
        if wants_ratio and area_geom is not None:
            area_measure = add(
                "measure_geometry",
                {"target": area_geom, "metric": "area", "unit": "square_meter"},
                area_ids[:1],
            )
            add(
                "calculate_ratio",
                {"numerator": {"$ref": f"{chain}.result"}, "denominator": {"$ref": f"{area_measure}.result"}},
                [chain, area_measure],
            )
        return self._finish_plan(nodes)

    @staticmethod
    def _finish_plan(nodes: list[dict[str, Any]]) -> dict[str, Any]:
        edges = [[dep, n["id"]] for n in nodes for dep in n.get("depends_on") or []]
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _filters(q: str) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        if "正常" in q:
            filters.append({"field": "status", "operator": "eq", "value": "正常"})
        elif "告警" in q:
            filters.append({"field": "status", "operator": "eq", "value": "告警"})
        if "高压" in q:
            filters.append({"field": "pressure_level", "operator": "eq", "value": "高压"})
        elif "次高压" in q:
            filters.append({"field": "pressure_level", "operator": "eq", "value": "次高压"})
        elif "中压" in q:
            filters.append({"field": "pressure_level", "operator": "eq", "value": "中压"})
        if "给水" in q:
            filters.append({"field": "pipe_type", "operator": "eq", "value": "给水"})
        elif "排水" in q:
            filters.append({"field": "pipe_type", "operator": "eq", "value": "排水"})
        return filters

    @staticmethod
    def _group_field(q: str, layer: str) -> str:
        for field in ("pressure_level", "pipe_type", "device_type", "status", "area_type"):
            if field in q:
                return field
        if layer.endswith("pipelines"):
            return "pressure_level"
        if layer.endswith("devices"):
            return "device_type"
        return "status"

    @staticmethod
    def _metric(q: str, layer: str) -> str:
        i_len, i_area = q.find("长度"), q.find("面积")
        if i_len >= 0 and (i_area < 0 or i_len < i_area):
            return "length"
        if i_area >= 0:
            return "area"
        if layer.endswith("pipelines"):
            return "length"
        return "area"

    # ------------------------------------------------------------------ ④ 执行
    def _simulate_tool(self, node: dict, node_index: int, subtask_id: str) -> dict[str, Any]:
        tool = node["action"]
        params = node.get("params") or {}
        rng = _rng(self.question, subtask_id, node["id"], tool)
        refs: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                if set(value) == {"$ref"}:
                    sid = str(value["$ref"]).split(".")[0]
                    if sid not in refs:
                        refs.append(sid)
                else:
                    for v in value.values():
                        collect(v)
            elif isinstance(value, list):
                for v in value:
                    collect(v)

        collect(params)
        distance = int(params.get("distance_m") or 0)
        brief: dict[str, Any] = {}
        if tool == "query_features":
            brief = {"feature_count": rng.randint(2, 12)}
        elif tool == "buffer_features":
            brief = {"feature_count": rng.randint(3, 12), "distance_m": distance}
        elif tool == "buffer_geometry":
            brief = {"geometry_type": "Polygon", "radius_m": distance}
        elif tool == "union_features":
            brief = {"geometry_type": "MultiPolygon", "parts": rng.randint(2, 7)}
        elif tool == "clip_features":
            value = _round(rng.uniform(1200, 38000), 1)
            brief = {"feature_count": rng.randint(1, 8), "total_length_m": value}
        elif tool == "measure_features":
            value = _round(rng.uniform(1200, 52000), 1)
            brief = {"value": value, "unit": params.get("unit", "meter"), "feature_count": rng.randint(1, 8)}
        elif tool == "measure_geometry":
            value = _round(rng.uniform(35000, 260000), 1) if params.get("metric") == "area" else _round(rng.uniform(600, 9000), 1)
            brief = {"value": value, "unit": params.get("unit", "square_meter"), "metric": params.get("metric", "area")}
        elif tool == "summarize_features":
            groups = []
            aggregate = params.get("aggregate", "sum")
            values = (
                [float(rng.randint(1, 6)) for _ in range(3)]
                if aggregate == "count"
                else [rng.uniform(800, 24000) for _ in range(3)]
            )
            names = {
                "pressure_level": ["低压", "中压", "高压"],
                "pipe_type": ["给水", "排水"],
                "device_type": ["调压箱", "阀井", "计量表"],
                "status": ["正常", "告警", "停用"],
                "area_type": ["道路", "管网", "综合"],
            }.get(params.get("group_by"), ["分组1", "分组2", "分组3"])
            for i, value in enumerate(values):
                groups.append(
                    {
                        params.get("group_by", "group"): names[i % len(names)],
                        "value": int(value) if aggregate == "count" else _round(value, 1),
                        "feature_count": int(value) if aggregate == "count" else rng.randint(1, 5),
                    }
                )
            groups.sort(key=lambda g: g["value"], reverse=True)
            brief = {"groups": groups, "group_count": len(groups), "aggregate": aggregate}
        elif tool == "calculate_ratio":
            brief = {"percent": _round(rng.uniform(32, 88), 1)}
        elif tool == "intersection_geometry":
            brief = {"geometry_type": rng.choice(["Polygon", "LineString", "GeometryCollection"])}
        return {
            "step": node["id"],
            "tool": tool,
            "label": node.get("label", tool),
            "args": params,
            "refs": refs,
            "ok": True,
            "brief": brief,
            "elapsed_ms": rng.randint(180, 1400),
        }

    def _fail_error(self, node: dict) -> str:
        tool = node["action"]
        if tool == "summarize_features":
            return "字段 sum_length_m 不存在：上游量测结果输出字段为 length_m，分组汇总前需对齐字段名"
        if tool == "clip_features":
            return "裁剪失败：clip_geom 为空几何，面要素可能位于孔洞内"
        if tool == "measure_features":
            return "measure_features 不支持 operation='ST_Area'：线要素只能量测长度"
        if tool == "query_features":
            return "查询失败：目标区域几何为空，无法完成空间关系过滤（模拟错误）"
        if tool == "calculate_ratio":
            return "占比计算失败：分母为 0（施工区面积为 0 或查询为空）"
        return "算子执行异常：参数校验未通过（模拟错误）"

    # ------------------------------------------------------------------ ⑤ 评估
    def _answer_from_traces(self, traces: list[dict]) -> tuple[Any, str]:
        answer: dict[str, Any] = {}
        kinds: list[str] = []
        last_target_count: int | None = None
        for item in traces:
            brief = item.get("brief") or {}
            tool = item["tool"]
            if tool == "calculate_ratio" and "percent" in brief:
                answer["percent"] = brief["percent"]
                kinds.append("占比")
            elif tool == "summarize_features" and brief.get("groups"):
                answer["groups"] = [
                    {
                        "group": (
                            g.get("pressure_level")
                            or g.get("pipe_type")
                            or g.get("device_type")
                            or g.get("status")
                            or g.get("group")
                            or "分组"
                        ),
                        "value": g.get("value"),
                        "feature_count": g.get("feature_count"),
                    }
                    for g in brief["groups"]
                ]
                answer["aggregate"] = brief.get("aggregate", "sum")
                kinds.append("分组汇总")
            elif "value" in brief and "unit" in brief:
                key = "total_length_m" if brief.get("unit") == "meter" else "area_square_meter"
                answer[key] = brief["value"]
                kinds.append("量测")
            if tool == "query_features":
                layer = str((item.get("args") or {}).get("layer_name") or "")
                if not layer.endswith("construction_areas"):
                    last_target_count = brief.get("feature_count")
        wants_count = any(w in self.question for w in ("数量", "计数", "多少个", "几个"))
        if last_target_count is not None and (wants_count or not answer) and "groups" not in answer:
            answer["count"] = last_target_count
            kinds.append("计数")
        if not answer:
            answer["result"] = "执行完成"
            kinds.append("执行结果")
        return answer, "、".join(dict.fromkeys(kinds))

    def _judge(self, answer: Any, trace_ok: bool) -> tuple[Any, str]:
        """返回 (correct, reason)；correct 为 True/False/None（None 表示未判定）。"""
        if not trace_ok:
            return False, "子任务执行报错，未生成可用答案。"
        if self.verdict_mode == "success":
            return True, "演示模式：判为正确（成功经验）。"
        if self.verdict_mode == "failure":
            return False, "演示模式：判为错误（失败经验）。"
        if self.truth.strip():
            truth_nums = {_round(float(x), 2) for x in re.findall(r"-?\d+(?:\.\d+)?", self.truth)}
            answer_text = json.dumps(answer, ensure_ascii=False)
            answer_nums = {_round(float(x), 2) for x in re.findall(r"-?\d+(?:\.\d+)?", answer_text)}
            if truth_nums and truth_nums <= answer_nums:
                return True, "与参考真值中的数值一致。"
            return False, "结果与参考真值不一致（演示比对：数值不匹配）。"
        return None, "未提供参考答案：本次按「未判定」处理，不写入成功/失败经验，能力向量保持不变。"

    def _evolve(self, subtask: dict, outcome: str) -> dict[str, Any]:
        evo = self.config.evolution
        g_s = float(evo.get("success_gain", 0.10))
        g_f = float(evo.get("failure_loss", 0.08))
        v_min = float(evo.get("min_value", 0.05))
        v_max = float(evo.get("max_value", 0.99))
        nd = int(evo.get("decimals", 4))
        agent_id = subtask["agent_id"]
        dims = subtask.get("required_capabilities") or list(self.config.dimensions)
        agent = self.state["agents"][agent_id]
        caps = agent["capabilities"]
        before = {d: _round(caps.get(d, self.config.initial_capability), nd) for d in dims}
        vector_before = self._caps(agent_id)
        after: dict[str, float] = {}
        for d in dims:
            value = float(caps.get(d, self.config.initial_capability))
            new = value + g_s * (v_max - value) if outcome == "success" else value - g_f * (value - v_min)
            new = max(v_min, min(v_max, new))
            caps[d] = _round(new, nd)
            after[d] = _round(caps[d], nd)
        stats = agent.setdefault("stats", {"attempts": 0, "successes": 0, "failures": 0})
        stats["attempts"] = int(stats.get("attempts", 0)) + 1
        stats["successes" if outcome == "success" else "failures"] = int(
            stats.get("successes" if outcome == "success" else "failures", 0)
        ) + 1
        if outcome == "success":
            tools = subtask.get("tools_used") or []
            prefs = list(agent.get("preferred_tools") or [])
            for tool in tools:
                if tool and tool not in prefs:
                    prefs.append(tool)
            agent["preferred_tools"] = prefs[-int(evo.get("max_preferred_tools", 5)):]
        event = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "agent_id": agent_id,
            "agent_name": agent["name"],
            "dims": dims,
            "outcome": outcome,
            "question": subtask["question"],
            "task_signature": f"{self.domain}/{self.task_type}",
            "before": before,
            "after": after,
            "delta": {d: _round(after[d] - before[d], nd + 2) for d in dims},
            "vector_before": vector_before,
            "vector_after": self._caps(agent_id),
            "note": subtask.get("note", ""),
            "index": len(self.state.get("history") or []),
        }
        self.state.setdefault("history", []).append(event)
        return event

    def _write_memory(self, subtask: dict, outcome: str, answer: Any) -> None:
        """把本次子任务写入所选记忆空间：短期缓存必写，长期记录只收明确结局。"""
        agent_id = subtask["agent_id"]
        target = self.memory_target
        note = "executed" if outcome in ("success", "failed") else "unjudged"
        error = str(subtask.get("error") or "")
        if outcome == "failed":
            error = error or str(subtask.get("note") or "")
        try:
            ds.append_memory_step(
                target,
                agent_id,
                question=subtask["question"],
                plan=subtask.get("plan"),
                outcome=outcome,
                note=note,
                error=error,
            )
            self.memory_writes.append(
                {"type": "cache", "agent_id": agent_id, "target": target}
            )
            if outcome in ("success", "failed"):
                if outcome == "success" and answer is not None:
                    summary = json.dumps(answer, ensure_ascii=False)[:200]
                else:
                    summary = error or "执行失败"
                rid = ds.add_memory_record(
                    target,
                    agent_id,
                    question=subtask["question"],
                    plan=subtask.get("plan"),
                    result_summary=summary,
                    outcome=outcome,
                    error=error,
                )
                if rid:
                    self.memory_writes.append(
                        {"type": "record", "agent_id": agent_id, "target": target, "record_id": rid}
                    )
        except Exception as exc:  # 记忆写入失败不应中断主流程
            message = f"{type(exc).__name__}: {exc}"
            self.memory_errors.append(message)
            self._beat("evaluate", "记忆写入失败", message, "error")

    # ------------------------------------------------------------------ 主流程
    def run(self, question: str, truth: str = "", verdict: str = "auto",
            memory_target: str = "demo", role: str = "analyst",
            user_id: str = "") -> dict[str, Any]:
        self.question = (question or "").strip()
        self.truth = truth or ""
        self.verdict_mode = verdict if verdict in ("auto", "success", "failure") else "auto"
        self.memory_target = memory_target if memory_target in ds.MEMORY_SOURCES else "demo"
        self.user_id = user_id or ""
        self.role = ds.PERMISSIONS.resolve_role(self.user_id or role)
        self.role_name = ds.PERMISSIONS.role_name(self.role)
        if not self.question:
            raise ValueError("问题不能为空")
        capability_before = {
            "agents": copy.deepcopy(self.state["agents"]),
            "history_len": len(self.state.get("history") or []),
        }

        # ⓪ 问题合法性（阶段①内的判定，不新增流程步骤）
        validity = ds.validate_question(self.question)
        self.validity = validity
        if not validity.get("is_valid"):
            return self._invalid_run(validity, capability_before)

        # ① 理解 ---------------------------------------------------------
        stage_start = _now_ms()
        self.domain = self._classify_domain()
        self.task_type = self._classify_task()
        self.dims = self._detect_dims()
        self.refined_question = self._formalize()
        self.tables = ds.retrieve_tables(self.question, top_k=5, role=self.role)
        self.skills = ds.retrieve_skills(self.question, top_k=4)
        knowledge_key = self.domain if self.domain in ds.DOMAIN_KNOWLEDGE else "general"
        domain_knowledge = ds.DOMAIN_KNOWLEDGE.get(knowledge_key, "")
        self._beat("understand", "领域识别", f"{self.domain} / {self.task_type}", "ok")
        self._beat(
            "understand", "权限校验",
            f"{self.role_name}（{self.role}）可查询 {len(self._allowed_tables())} 张表",
            "info",
        )
        self._beat("understand", "检索相关表结构", "、".join(t["name"] for t in self.tables) or "未命中", "info")
        self._beat(
            "understand", "检索任务级 skill",
            "、".join(f"{s['name']}({s['score']:.2f})" for s in self.skills) or "未命中",
            "info",
        )
        understand = {
            "stage": "understand",
            "status": "done",
            "elapsed_ms": _now_ms() - stage_start + 640,
            "domain": self.domain,
            "domain_label": self.config.domain_names.get(self.domain, self.domain),
            "task_type": self.task_type,
            "refined_question": self.refined_question,
            "tables": self.tables,
            "skills": self.skills,
            "knowledge": domain_knowledge,
            "context": self._render_context(self.tables),
            "is_valid": True,
            "validity": validity,
            "permission": {
                "role": self.role,
                "role_name": self.role_name,
                "allowed_tables": sorted(self._allowed_tables()),
            },
            "summary": f"识别为「{self.config.domain_names.get(self.domain, self.domain)} / {self.task_type}」，"
                       f"命中 {len(self.tables)} 张表、{len(self.skills)} 个 skill",
        }

        # ② 拆解与路由 ----------------------------------------------------
        stage_start = _now_ms()
        questions = self._split_questions()
        self.subtasks = []
        for i, sub_question in enumerate(questions):
            dims = self.dims if len(questions) == 1 else self._dims_for_part(sub_question)
            decision = self._route(dims, f"t{i + 1}")
            self.subtasks.append(
                {
                    "subtask_id": f"t{i + 1}",
                    "question": sub_question,
                    "required_capabilities": decision["required"],
                    "agent_id": decision["agent_id"],
                    "agent_name": decision["agent_name"],
                    "routing": decision,
                }
            )
            self._beat(
                "decompose",
                f"子任务 {i + 1} 路由",
                f"所需能力 {'/'.join(decision['required'])} → 智能体 {decision['agent_name']}"
                + ("（能力并列，随机抽取）" if decision["random_pick"] else "（能力最高）"),
                "ok" if not decision["random_pick"] else "warn",
            )
        decompose = {
            "stage": "decompose",
            "status": "done",
            "elapsed_ms": _now_ms() - stage_start + 820,
            "refined_question": self.refined_question,
            "subtasks": self.subtasks,
            "summary": f"拆分为 {len(self.subtasks)} 个子任务，按能力向量完成路由",
        }

        # ③ 规划 ---------------------------------------------------------
        stage_start = _now_ms()
        plan_items = []
        for i, sub in enumerate(self.subtasks):
            skill = self.skills[min(i, len(self.skills) - 1)] if self.skills else None
            plan = self._build_plan(sub, skill)
            sub["plan"] = plan
            sub["skill"] = {
                "id": skill.get("id"), "name": skill.get("name"),
                "score": skill.get("score"), "operators": skill.get("operators"),
            } if skill else None
            sub["memory_hits"] = ds.retrieve_memory(
                sub["agent_id"], sub["question"], top_k=2, source=self.memory_target
            )
            sub["experience_hits"] = ds.retrieve_experience(sub["question"], top_k=2)
            sub["preferred_tools"] = list(
                (self.state["agents"][sub["agent_id"]] or {}).get("preferred_tools") or []
            )
            sub["capability_line"] = "、".join(
                f"{self.config.labels.get(d, d)} {self._caps(sub['agent_id'])[d]:.2f}"
                for d in self.config.dimensions
            )
            plan_items.append(
                {
                    "subtask_id": sub["subtask_id"],
                    "agent_id": sub["agent_id"],
                    "agent_name": sub["agent_name"],
                    "plan": plan,
                    "skill": sub["skill"],
                    "memory_hits": sub["memory_hits"],
                    "experience_hits": sub["experience_hits"],
                    "capability_line": sub["capability_line"],
                    "preferred_tools": sub["preferred_tools"],
                }
            )
            self._beat(
                "plan",
                f"子任务 {sub['subtask_id']} 生成 DAG",
                " → ".join(n["action"] for n in plan["nodes"]),
                "ok",
            )
        self.experience_hits = [h for item in plan_items for h in item["experience_hits"]][:3]
        plan_stage = {
            "stage": "plan",
            "status": "done",
            "elapsed_ms": _now_ms() - stage_start + 980,
            "subtasks": plan_items,
            "summary": f"生成 {sum(len(p['plan']['nodes']) for p in plan_items)} 个 DAG 节点",
        }

        # ④ 执行 ---------------------------------------------------------
        stage_start = _now_ms()
        exec_items = []
        failures = 0
        for sub in self.subtasks:
            nodes = sub["plan"]["nodes"]
            fail_at = len(nodes) - 1 if self.verdict_mode == "failure" and len(nodes) >= 2 else -1
            traces: list[dict] = []
            tools_used: list[str] = []
            error = ""
            for idx, node in enumerate(nodes):
                denied = self._check_node(node)
                if denied:
                    traces.append(
                        {
                            "step": node["id"],
                            "tool": node["action"],
                            "label": node.get("label", node["action"]),
                            "args": node.get("params") or {},
                            "refs": [],
                            "ok": False,
                            "denied": True,
                            "error": denied,
                            "brief": {},
                            "elapsed_ms": 0,
                        }
                    )
                    error = denied
                    self._beat(
                        "execute",
                        f"{sub['subtask_id']} · {node['action']} 越权拦截",
                        denied,
                        "error",
                    )
                    break
                trace = self._simulate_tool(node, idx, sub["subtask_id"])
                if idx == fail_at:
                    trace["ok"] = False
                    trace["error"] = self._fail_error(node)
                    trace["brief"] = {}
                    traces.append(trace)
                    error = trace["error"]
                    self._beat(
                        "execute",
                        f"{sub['subtask_id']} · {node['action']} 失败",
                        error,
                        "error",
                    )
                    break
                traces.append(trace)
                if node["action"] not in tools_used:
                    tools_used.append(node["action"])
                self._beat(
                    "execute",
                    f"{sub['subtask_id']} · {node['action']}",
                    f"{sub['agent_name']} 调用成功"
                    + (f"，引用 {'/'.join(trace['refs'])}" if trace["refs"] else ""),
                    "ok",
                )
            trace_ok = not error
            failures += 0 if trace_ok else 1
            sub["trace"] = traces
            sub["tools_used"] = tools_used
            sub["status"] = "success" if trace_ok else "failed"
            sub["error"] = error
            exec_items.append(
                {
                    "subtask_id": sub["subtask_id"],
                    "agent_id": sub["agent_id"],
                    "agent_name": sub["agent_name"],
                    "status": sub["status"],
                    "trace": traces,
                    "tools_used": tools_used,
                    "error": error,
                }
            )
        execute = {
            "stage": "execute",
            "status": "done" if failures == 0 else "failed",
            "elapsed_ms": _now_ms() - stage_start + 1600,
            "subtasks": exec_items,
            "summary": f"完成 {sum(len(i['trace']) for i in exec_items)} 次工具调用"
                       + (f"，{failures} 个子任务报错" if failures else ""),
        }

        # ⑤ 评估与进化 ----------------------------------------------------
        stage_start = _now_ms()
        trace_ok = failures == 0
        answer = None
        answer_kind = ""
        if trace_ok:
            merged_traces = [t for item in exec_items for t in item["trace"]]
            answer, answer_kind = self._answer_from_traces(merged_traces)
        correct, reason = self._judge(answer, trace_ok)
        judged = correct is not None
        changes = []
        for sub in self.subtasks:
            if not judged:
                # 未提供参考答案：按未知处理，不写入成功/失败经验
                sub["outcome"] = "unknown"
                sub["note"] = reason
                self._beat(
                    "evaluate",
                    f"子任务 {sub['subtask_id']} 未判定",
                    "未知结果 · 跳过能力进化",
                    "warn",
                )
                self._write_memory(sub, "unknown", answer)
                continue
            outcome = "success" if (sub["status"] == "success" and correct) else "failure"
            sub["outcome"] = outcome
            sub["note"] = "" if outcome == "success" else (sub["error"] or reason)
            event = self._evolve(sub, outcome)
            self._write_memory(sub, outcome, answer)
            change = {
                "subtask_id": sub["subtask_id"],
                "agent_id": event["agent_id"],
                "agent_name": event["agent_name"],
                "dims": event["dims"],
                "outcome": outcome,
                "before": event["before"],
                "after": event["after"],
                "delta": event["delta"],
                "note": sub["note"],
            }
            changes.append(change)
            detail = "、".join(
                f"{self.config.labels.get(d, d)} {event['before'][d]:.4f}→{event['after'][d]:.4f}"
                for d in event["dims"]
            )
            self._beat(
                "evaluate",
                f"智能体 {event['agent_name']} {('成功' if outcome == 'success' else '失败')}经验",
                detail,
                "ok" if outcome == "success" else "error",
            )

        if trace_ok:
            final_answer = json.dumps(answer, ensure_ascii=False, indent=2)
        else:
            final_answer = "执行失败：未生成最终答案。"
            self._beat("evaluate", "执行失败", changes[0]["note"] if changes else "工具调用报错", "error")
        if judged:
            self._beat("evaluate", "评估结论", reason, "ok" if correct else "error")
        else:
            self._beat("evaluate", "评估结论", reason, "warn")

        if judged:
            ds.save_demo_capability(self.state)
        capability_after = {
            "agents": copy.deepcopy(self.state["agents"]),
            "history_len": len(self.state.get("history") or []),
        }
        evaluate = {
            "stage": "evaluate",
            "status": "done",
            "elapsed_ms": _now_ms() - stage_start + 720,
            "evaluation": ("unknown" if not judged else ("success" if correct else "failed")),
            "correct": correct,
            "reason": reason,
            "final_answer": final_answer,
            "answer": answer,
            "answer_kind": answer_kind,
            "changes": changes,
            "summary": (
                "未提供参考答案 · 按未知处理，能力向量保持不变"
                if not judged
                else ("判定正确，能力向量已进化" if correct else "判定失败，按失败经验回落能力值")
            ),
        }

        elapsed_ms = _now_ms() - self.started
        run = {
            "run_id": self.run_id,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "demo",
            "question": self.question,
            "truth": self.truth,
            "verdict_mode": self.verdict_mode,
            "memory_target": self.memory_target,
            "memory_writes": list(self.memory_writes),
            "memory_errors": list(self.memory_errors),
            "domain": self.domain,
            "domain_label": self.config.domain_names.get(self.domain, self.domain),
            "task_type": self.task_type,
            "is_valid": True,
            "validity": self.validity,
            "role": self.role,
            "role_name": self.role_name,
            "permission_denials": list(self.permission_denials),
            "dimensions": self.config.dimensions,
            "labels": self.config.labels,
            "flow": {
                "understand": understand,
                "decompose": decompose,
                "plan": plan_stage,
                "execute": execute,
                "evaluate": evaluate,
            },
            "subtasks": [
                {
                    "subtask_id": sub["subtask_id"],
                    "question": sub["question"],
                    "required_capabilities": sub["required_capabilities"],
                    "agent_id": sub["agent_id"],
                    "agent_name": sub["agent_name"],
                    "routing": sub["routing"],
                    "plan": sub["plan"],
                    "trace": sub.get("trace") or [],
                    "tools_used": sub.get("tools_used") or [],
                    "status": sub.get("status"),
                    "outcome": sub.get("outcome"),
                    "error": sub.get("error", ""),
                    "skill": sub.get("skill"),
                }
                for sub in self.subtasks
            ],
            "capability_before": capability_before,
            "capability_after": capability_after,
            "timeline": self.timeline,
            "metrics": {
                "elapsed_ms": elapsed_ms,
                "tool_calls": sum(len(item["trace"]) for item in exec_items),
                "tool_errors": sum(1 for item in exec_items for t in item["trace"] if not t["ok"]),
                "retrieval_hits": len(self.tables) + len(self.skills),
                "subtasks": len(self.subtasks),
                "agents_used": sorted({sub["agent_id"] for sub in self.subtasks}),
            },
            "notes": [
                "演示会话：执行流与工具返回值为本地模拟，不调用 LLM、数据库或外部工具集。",
                "表结构 / skill / 经验 / 记忆检索、路由与能力进化公式均取自项目真实实现。",
                "问题合法性规则与用户权限表分别复用 security/question_guard.py 与 security/permissions.py。",
                (
                    "本次记忆写入：web/data/memory（演示记忆），不修改项目 data/memory。"
                    if self.memory_target == "demo"
                    else "本次记忆写入：data/memory（项目真实记忆）。"
                ),
            ],
        }
        ds.save_run(run)
        return run

    # ------------------------------------------------------------------ 辅助
    def _dims_for_part(self, question: str) -> list[str]:
        dims: list[str] = []
        if any(w in question for w in _SPACE_WORDS):
            dims.append("spatial_compute")
        if any(w in question for w in _ATTR_WORDS):
            dims.append("attribute_query")
        if any(w in question for w in _STAT_WORDS):
            dims.append("statistics")
        if any(w in question for w in _MAP_WORDS):
            dims.append("mapping")
        ordered = [d for d in self.config.dimensions if d in dims]
        return ordered or self.dims

    @staticmethod
    def _render_context(tables: list[dict]) -> str:
        parts = ["【数据库相关表结构（按余弦相似度检索）】"]
        for table in tables:
            parts.append(f"\n表 {table['name']}（{table['note']}）")
            for field in table.get("fields", []):
                samples = "；样例：" + "/".join(field.get("samples") or []) if field.get("samples") else ""
                parts.append(f"  - {field['name']}: {field['note']}（{field['type']}）{samples}")
        return "\n".join(parts)


def run_demo(question: str, truth: str = "", verdict: str = "auto",
             memory_target: str = "demo", role: str = "analyst",
             user_id: str = "") -> dict[str, Any]:
    return DemoEngine().run(
        question, truth=truth, verdict=verdict, memory_target=memory_target,
        role=role, user_id=user_id,
    )
