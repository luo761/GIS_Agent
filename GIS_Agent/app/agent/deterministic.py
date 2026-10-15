from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from app.agent.state import ToolCallRecord
from app.tools.postgis_tools import PostGISToolkit
from app.tools.registry import get_tool_spec


AREA_CODE_BY_NAME = {
    "施工一区": "A001",
    "一区": "A001",
    "A区": "A001",
    "A001": "A001",
    "施工二区": "A002",
    "二区": "A002",
    "B区": "A002",
    "A002": "A002",
    "施工三区": "A003",
    "三区": "A003",
    "C区": "A003",
    "A003": "A003",
}

LAYER_BY_TEXT = {
    "燃气管线": "gas_pipelines",
    "燃气设备": "gas_devices",
    "设备": "gas_devices",
    "施工区域": "construction_areas",
    "水务管线": "water_pipelines",
    "道路": "demo_roads",
}


@dataclass(frozen=True)
class PlannedToolCall:
    name: str
    arguments: dict[str, Any]


class DeterministicGISAgent:
    """不依赖 LLM 的确定性 GIS Agent。

    它用于测试和学习：先用规则把常见中文问题映射成 Tool 调用，
    再由 PostGISToolkit 访问数据库。后续接入真实 LLM 时，可以复用
    execute_plan 和 summarize 这两层。
    """

    def __init__(self, toolkit: PostGISToolkit | None = None) -> None:
        self.toolkit = toolkit or PostGISToolkit()

    def plan(self, question: str) -> list[PlannedToolCall]:
        normalized = question.strip()

        if self._mentions(normalized, "图层", "空间表", "数据表") and self._mentions(normalized, "查看", "列出", "有哪些", "查询"):
            return [PlannedToolCall("list_spatial_layers", {})]

        if self._mentions(normalized, "描述", "字段", "样例", "结构"):
            return [
                PlannedToolCall(
                    "describe_spatial_layer",
                    {"layer_name": self._detect_layer(normalized), "sample_limit": 5},
                )
            ]

        if self._mentions(normalized, "最近"):
            x, y = self._detect_point(normalized)
            return [
                PlannedToolCall(
                    "nearest_features",
                    {
                        "query_layer_name": self._detect_layer(normalized, default="gas_devices"),
                        "x": x,
                        "y": y,
                        "srid": 3857,
                        "limit": self._detect_limit(normalized, default=5),
                    },
                )
            ]

        if self._mentions(normalized, "缓冲", "范围内", "周围") and self._mentions(normalized, "米"):
            distance = self._detect_distance(normalized, default=500)
            target_code = self._detect_feature_code(normalized, default="D011")
            query_layer = "gas_pipelines" if self._mentions(normalized, "管线") else self._detect_layer(normalized)
            return [
                PlannedToolCall(
                    "buffer_query",
                    {
                        "target": {"layer_name": "gas_devices", "feature_code": target_code},
                        "distance_m": distance,
                        "query_layer_name": query_layer,
                        "max_results": 20,
                    },
                )
            ]

        if self._mentions(normalized, "长度", "总长", "裁剪"):
            return [
                PlannedToolCall(
                    "clip_and_measure",
                    {
                        "layer_name": self._detect_layer(normalized, default="gas_pipelines"),
                        "clip_target": {
                            "layer_name": "construction_areas",
                            "feature_code": self._detect_area_code(normalized),
                        },
                        "measure": "length",
                    },
                )
            ]

        if self._mentions(normalized, "相交", "穿过", "影响"):
            return [
                PlannedToolCall(
                    "spatial_filter",
                    {
                        "layer_name": self._detect_layer(normalized, default="gas_pipelines"),
                        "target": {
                            "layer_name": "construction_areas",
                            "feature_code": self._detect_area_code(normalized),
                        },
                        "relation": "ST_Intersects",
                        "max_results": 20,
                    },
                )
            ]

        if self._mentions(normalized, "内") and (
            self._mentions(normalized, "位于", "在", "设备", "要素") or self._mentions(normalized, "查询")
        ):
            return [
                PlannedToolCall(
                    "spatial_filter",
                    {
                        "layer_name": self._detect_layer(normalized, default="gas_devices"),
                        "target": {
                            "layer_name": "construction_areas",
                            "feature_code": self._detect_area_code(normalized),
                        },
                        "relation": "ST_Within",
                        "max_results": 20,
                    },
                )
            ]

        raise ValueError("暂不支持该问题。请尝试图层列表、图层描述、区域内设备、相交管线、缓冲查询、裁剪长度或最近邻问题。")

    def execute_plan(self, plan: list[PlannedToolCall]) -> list[ToolCallRecord]:
        records: list[ToolCallRecord] = []
        for call in plan:
            started = time.perf_counter()
            try:
                result = self._invoke_tool(call)
                elapsed_ms = float(result.get("elapsed_ms", (time.perf_counter() - started) * 1000))
                records.append(
                    {
                        "name": call.name,
                        "input": call.arguments,
                        "result": result,
                        "elapsed_ms": round(elapsed_ms, 3),
                        "error": None,
                    }
                )
            except Exception as exc:  # pragma: no cover - exercised by integration failures
                records.append(
                    {
                        "name": call.name,
                        "input": call.arguments,
                        "result": None,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                        "error": str(exc),
                    }
                )
                raise
        return records

    def run(self, question: str) -> dict[str, Any]:
        plan = self.plan(question)
        records = self.execute_plan(plan)
        return {
            "question": question,
            "plan": [call.__dict__ for call in plan],
            "tool_calls": records,
            "answer": self.summarize(question, records),
            "error": None,
        }

    def summarize(self, question: str, records: list[ToolCallRecord]) -> str:
        if not records:
            return "未执行任何空间分析步骤。"

        record = records[-1]
        result = record["result"] or {}
        payload = result.get("result", {})
        tool_name = record["name"]

        if tool_name == "list_spatial_layers":
            names = [item["table_name"] for item in payload.get("layers", [])]
            return f"已查询空间图层，共 {len(names)} 个：{', '.join(names)}。"

        if tool_name == "describe_spatial_layer":
            spatial_ref = payload.get("spatial_ref") or {}
            return f"已查看图层 {payload.get('layer')}，SRID 为 {spatial_ref.get('srid')}，返回 {len(payload.get('samples', []))} 条样例。"

        if tool_name == "spatial_filter":
            codes = [item.get("code") for item in payload.get("features", [])]
            return f"已执行 {payload.get('relation')} 空间筛选，匹配 {payload.get('matched_count', 0)} 个要素：{', '.join(codes)}。"

        if tool_name == "buffer_query":
            codes = [item.get("code") for item in payload.get("features", [])]
            return f"已创建 {payload.get('distance_m')} 米缓冲区并查询相交要素，匹配 {payload.get('matched_count', 0)} 个：{', '.join(codes)}。"

        if tool_name == "clip_and_measure":
            return f"已裁剪并测量 {payload.get('feature_count', 0)} 个要素，总长度 {float(payload.get('total_measure', 0)):.2f} 米。"

        if tool_name == "nearest_features":
            features = payload.get("features", [])
            if not features:
                return "未找到最近要素。"
            first = features[0]
            return f"已查询最近要素，最近的是 {first.get('code')}，距离 {float(first.get('distance_m', 0)):.2f} 米。"

        return f"已完成问题分析：{question}"

    def _invoke_tool(self, call: PlannedToolCall) -> dict[str, Any]:
        spec = get_tool_spec(call.name)
        arguments = spec.validate_arguments(call.arguments)
        method = getattr(self.toolkit, spec.method_name)
        if spec.invocation == "none":
            return method()
        if spec.invocation == "kwargs":
            return method(**arguments.model_dump(exclude_none=True))
        return method(arguments)

    @staticmethod
    def _mentions(text: str, *words: str) -> bool:
        return any(word in text for word in words)

    @staticmethod
    def _detect_distance(text: str, default: float) -> float:
        match = re.search(r"(\d+(?:\.\d+)?)\s*米", text)
        return float(match.group(1)) if match else default

    @staticmethod
    def _detect_limit(text: str, default: int) -> int:
        match = re.search(r"最近\s*(\d+)\s*个", text)
        return int(match.group(1)) if match else default

    @staticmethod
    def _detect_point(text: str) -> tuple[float, float]:
        match = re.search(r"(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)", text)
        if match:
            return float(match.group(1)), float(match.group(2))
        return 520.0, 520.0

    @staticmethod
    def _detect_feature_code(text: str, default: str) -> str:
        match = re.search(r"\b([A-Z]\d{3})\b", text)
        return match.group(1) if match else default

    @staticmethod
    def _detect_area_code(text: str) -> str:
        for name, code in AREA_CODE_BY_NAME.items():
            if name in text:
                return code
        return "A001"

    @staticmethod
    def _detect_layer(text: str, default: str = "gas_pipelines") -> str:
        for keyword, layer_name in LAYER_BY_TEXT.items():
            if keyword in text:
                return layer_name
        return default
