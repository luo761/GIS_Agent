"""多步 GIS Agent：完整计划、依赖校验、结果引用、串行执行和日志。

在 GIS_Agent 目录运行：
    python -m app_development.agent --help
    python -m app_development.agent "你的空间问题" --live --toolset advanced
--live 会调用真实模型并可能产生费用；命令入口设置数据库只读保护。
计划比较与题集评测位于 test.py，工具位于 tool.py，配置与数据库访问位于 db.py。
"""

from __future__ import annotations

# ========================================================================
# 合并来源：app/agent/plan_schemas.py
# ========================================================================
"""人工多步计划的 JSON 合同：步骤、依赖和结果引用，不负责调用 LLM。"""

from collections.abc import Iterator
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$", min_length=1, max_length=64)]


class ResultReference(BaseModel):
    """如 {\"$ref\": \"buffer.result.geometry\"}；只支持字典键和非负列表下标。"""

    model_config = ConfigDict(extra="forbid")
    ref: str = Field(
        alias="$ref", max_length=512,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|0|[1-9][0-9]*))*$",
    )

    @property
    def step_id(self) -> str:
        return self.ref.split(".", 1)[0]


def iter_references(value: Any) -> Iterator[ResultReference]:
    """识别整个引用对象；禁止把 $ref 与普通参数键混在同一对象中。"""
    if isinstance(value, ResultReference):
        yield value
    elif isinstance(value, dict):
        if "$ref" in value:
            yield ResultReference.model_validate(value)
        else:
            for item in value.values():
                yield from iter_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_references(item)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Identifier
    tool: Identifier
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[Identifier] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """有向无环计划；引用来源必须显式列入当前步骤的 depends_on。"""

    model_config = ConfigDict(extra="forbid")
    steps: list[PlanStep] = Field(min_length=1, max_length=100)
    outputs: dict[Identifier, ResultReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dependencies(self) -> "ExecutionPlan":
        ids = [step.id for step in self.steps]
        known_ids = set(ids)
        if len(known_ids) != len(ids):
            raise ValueError("步骤 ID 不能重复")
        for step in self.steps:
            if len(set(step.depends_on)) != len(step.depends_on):
                raise ValueError(f"步骤 {step.id} 的依赖不能重复")
            if step.id in step.depends_on:
                raise ValueError(f"步骤 {step.id} 不能依赖自身")
            missing = set(step.depends_on) - known_ids
            if missing:
                raise ValueError(f"步骤 {step.id} 依赖不存在的步骤: {', '.join(sorted(missing))}")
            for reference in iter_references(step.arguments):
                if reference.step_id not in known_ids:
                    raise ValueError(f"引用来源步骤不存在: {reference.step_id}")
                if reference.step_id not in step.depends_on:
                    raise ValueError(f"步骤 {step.id} 的引用来源 {reference.step_id} 必须列入 depends_on")
        for reference in self.outputs.values():
            if reference.step_id not in known_ids:
                raise ValueError(f"最终输出引用不存在的步骤: {reference.step_id}")
        self.ordered_steps()  # 执行前检查循环依赖。
        return self

    def ordered_steps(self) -> list[PlanStep]:
        """稳定拓扑排序：依赖优先；多个步骤就绪时保留计划中的先后顺序。"""
        pending = list(self.steps)
        ordered: list[PlanStep] = []
        completed: set[str] = set()
        while pending:
            ready = next((step for step in pending if set(step.depends_on) <= completed), None)
            if ready is None:
                raise ValueError("计划存在循环依赖")
            pending.remove(ready)
            ordered.append(ready)
            completed.add(ready.id)
        return ordered

# ========================================================================
# 合并来源：app/agent/result_store.py
# ========================================================================
"""单次执行的中间结果仓库；无全局状态、不写数据库、不解释任意表达式。"""

from copy import deepcopy
from typing import Any



class ReferenceResolutionError(ValueError):
    """引用的步骤尚无结果，或结果字段/列表下标不存在。"""


class ResultStore:
    def __init__(self) -> None:
        self._results: dict[str, dict[str, Any]] = {}

    def put(self, step_id: str, result: dict[str, Any]) -> None:
        if step_id in self._results:
            raise ValueError(f"步骤结果不能重复写入: {step_id}")
        self._results[step_id] = deepcopy(result)

    def get(self, reference: ResultReference) -> Any:
        if reference.step_id not in self._results:
            raise ReferenceResolutionError(f"引用步骤尚无成功结果: {reference.step_id}")
        current: Any = self._results[reference.step_id]
        for segment in reference.ref.split(".")[1:]:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            elif isinstance(current, list) and segment.isdecimal() and int(segment) < len(current):
                current = current[int(segment)]
            else:
                raise ReferenceResolutionError(f"引用路径不存在: {reference.ref}（无法访问 {segment}）")
        return deepcopy(current)

    def resolve(self, value: Any) -> Any:
        """递归替换参数中的引用；拿到的是副本，调用方不能修改仓库原结果。"""
        if isinstance(value, ResultReference):
            return self.get(value)
        if isinstance(value, dict):
            if "$ref" in value:
                return self.get(ResultReference.model_validate(value))
            return {key: self.resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        return deepcopy(value)

# ========================================================================
# 合并来源：app/agent/executor.py
# ========================================================================
"""先验证依赖，再串行执行计划；不重试、不并行调度。"""

import time
from copy import deepcopy
from typing import Any, Literal, cast

from app_development.tool import PostGISToolkit
from app_development.tool import Toolset, create_toolkit, get_tool_registry, get_tool_spec


class PlanExecutor:
    def __init__(
        self, toolkit: PostGISToolkit | None = None, *, toolset: Toolset = "composable",
        failure_policy: Literal["stop", "skip_dependents"] = "stop",
    ) -> None:
        get_tool_registry(toolset)  # 不接受未知工具集。
        if failure_policy not in {"stop", "skip_dependents"}:
            raise ValueError(f"未知失败策略: {failure_policy}")
        self.toolkit = toolkit or create_toolkit(toolset)
        self.toolset: Toolset = toolset
        self.failure_policy = failure_policy

    def run(self, plan: ExecutionPlan | dict[str, Any]) -> dict[str, Any]:
        """返回步骤明细、最终输出、耗时和错误。

        计划结构或工具白名单错误在任何执行前抛出。运行时失败则返回 status=error，
        保留成功记录。默认 stop 跳过所有余下步骤；skip_dependents 仅跳过失败的
        下游，继续执行独立分支。不自动重试，也不部分发布最终输出。
        每次 run 创建独立 ResultStore，同一执行器的前次结果不能被后次引用。
        """
        started = time.perf_counter()
        source = plan.model_dump(by_alias=True) if isinstance(plan, ExecutionPlan) else deepcopy(plan)
        validated = ExecutionPlan.model_validate(source)
        ordered = validated.ordered_steps()
        specs = {step.id: get_tool_spec(step.tool, toolset=cast(Toolset, self.toolset)) for step in ordered}
        store = ResultStore()
        records: list[dict[str, Any]] = []
        error: str | None = None
        failed_step: str | None = None
        outputs: dict[str, Any] = {}
        states: dict[str, str] = {}

        for step in ordered:
            record: dict[str, Any] = {
                "step_id": step.id, "tool": step.tool, "arguments": deepcopy(step.arguments),
                "resolved_arguments": None, "normalized_arguments": None,
                "status": "skipped", "result": None, "elapsed_ms": 0.0, "error": None, "blocked_by": [],
            }
            records.append(record)
            if error is not None and self.failure_policy == "stop":
                record["error"] = f"步骤 {failed_step} 失败，已停止后续执行"
                states[step.id] = "skipped"
                continue
            blocked = [dep for dep in step.depends_on if states[dep] != "ok"]
            if blocked:
                record["blocked_by"] = blocked
                record["error"] = f"依赖未成功: {', '.join(blocked)}"
                states[step.id] = "skipped"
                continue
            step_started = time.perf_counter()
            try:
                # 关键顺序：替换引用 → 工具参数模型校验/补齐默认值 → 调用。
                resolved = store.resolve(step.arguments)
                record["resolved_arguments"] = deepcopy(resolved)
                spec = specs[step.id]
                arguments = spec.validate_arguments(resolved)
                record["normalized_arguments"] = arguments.model_dump()
                method = getattr(self.toolkit, spec.method_name)
                if spec.invocation == "none":
                    result = method()
                elif spec.invocation == "kwargs":
                    result = method(**arguments.model_dump(exclude_none=True))
                else:
                    result = method(arguments)
                record["result"] = deepcopy(result)
                if not isinstance(result, dict) or result.get("status") != "ok":
                    raise ValueError("工具未返回成功结果")
                store.put(step.id, result)
                record["status"] = "ok"
            except Exception as exc:
                step_error = f"{type(exc).__name__}: {exc}"
                if error is None:
                    failed_step, error = step.id, step_error
                record["status"] = "error"
                record["error"] = step_error
            finally:
                states[step.id] = record["status"]
                record["elapsed_ms"] = round((time.perf_counter() - step_started) * 1000, 3)

        if error is None:
            try:
                outputs = store.resolve(validated.outputs)
            except Exception as exc:
                error = f"最终输出解析失败，{type(exc).__name__}: {exc}"

        return {
            "status": "ok" if error is None else "error",
            "plan": validated.model_dump(by_alias=True),
            "execution_order": [step.id for step in ordered],
            "failure_policy": self.failure_policy,
            "toolset": self.toolset,
            "steps": records,
            "outputs": outputs,
            "failed_step": failed_step,
            "error": error,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }

# ========================================================================
# 合并来源：app/agent/run_logging.py
# ========================================================================
"""运行记录按 UUID 单独保存，不序列化模型客户端、环境变量或连接字符串。"""

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


class JsonRunLogger:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()

    def write(self, run: dict[str, Any]) -> Path:
        run_id = run.get("run_id", "")
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("日志 run_id 必须为 UUID hex，不接受任意文件路径")
        path = self.directory / f"{run_id}.json"
        payload = deepcopy(run)
        payload["log_path"] = str(path)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        self.directory.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
        return path


def persist_run(run: dict[str, Any], logger: JsonRunLogger | None) -> None:
    """日志写入失败单独报告，不能悄悄吞掉，也不伪装成空间计算错误。"""
    if logger is not None:
        try:
            run["log_path"] = str(logger.write(run))
        except (OSError, TypeError, ValueError) as exc:
            run["logging_error"] = f"{type(exc).__name__}: {exc}"

# ========================================================================
# 合并来源：app/agent/multistep_agent.py
# ========================================================================
"""LLM 一次生成完整计划，本地验证与执行。"""

import json
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr

from app_development.db import get_settings
from app_development.tool import ALLOWED_LAYERS
from app_development.tool import FeatureSet
from app_development.tool import PostGISToolkit
from app_development.tool import Toolset, get_tool_spec, postgis_tool_definitions


PLAN_TOOL_NAME = "submit_execution_plan"


def execution_plan_definition() -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": PLAN_TOOL_NAME,
        "description": "Submit the complete spatial execution plan, including all steps, dependencies, references and outputs.",
        "parameters": ExecutionPlan.model_json_schema(by_alias=True),
    }}


def _default_model():
    from langchain_deepseek import ChatDeepSeek

    settings = get_settings()
    if not settings.llm_api_key:
        raise ValueError("真实模型需要配置 LLM_API_KEY 或 DEEPSEEK_API_KEY")
    return ChatDeepSeek(
        model=settings.llm_model, api_key=SecretStr(settings.llm_api_key), temperature=0,
        timeout=60, max_retries=0, extra_body={"thinking": {"type": "disabled"}},
    )


def _response_trace(response: Any) -> dict[str, Any]:
    metadata = getattr(response, "response_metadata", {}) or {}
    return {
        "content": deepcopy(getattr(response, "content", "")),
        "tool_calls": deepcopy(getattr(response, "tool_calls", []) or []),
        "invalid_tool_calls": deepcopy(getattr(response, "invalid_tool_calls", []) or []),
        "raw_tool_calls": deepcopy((getattr(response, "additional_kwargs", {}) or {}).get("tool_calls", [])),
        "usage": deepcopy(getattr(response, "usage_metadata", None)),
        "metadata": {key: deepcopy(metadata[key]) for key in ("model_name", "finish_reason", "token_usage") if key in metadata},
    }


def _plan_arguments(response: Any) -> dict[str, Any]:
    if getattr(response, "invalid_tool_calls", None):
        raise ValueError("模型包含无法解析的工具调用，不忽略这些调用")
    calls = getattr(response, "tool_calls", None) or []
    if not calls:
        raw_calls = (getattr(response, "additional_kwargs", {}) or {}).get("tool_calls", [])
        calls = [{"name": call.get("function", {}).get("name"),
                  "args": call.get("function", {}).get("arguments")} for call in raw_calls]
    if len(calls) != 1 or calls[0].get("name") != PLAN_TOOL_NAME:
        raise ValueError("模型必须恰好调用一次 submit_execution_plan，提交完整计划，而不是多个独立工具调用")
    arguments = calls[0].get("args")
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError("完整计划的 arguments 必须是 JSON 对象")
    return arguments


class MultiStepLLMGISAgent:
    def __init__(
        self, model: Any = None, *, toolkit: PostGISToolkit | None = None,
        logger: JsonRunLogger | None = None,
        toolset: Toolset = "composable",
    ) -> None:
        if toolset not in {"composable", "advanced"}:
            raise ValueError("多步 Agent 只支持 composable 或 advanced 工具集")
        self.model = model
        self.planner = None
        self.toolset: Toolset = toolset
        self.executor = PlanExecutor(toolkit, toolset=toolset, failure_policy="skip_dependents")
        self.logger = logger

    def system_prompt(self) -> str:
        tools = json.dumps(postgis_tool_definitions(toolset=cast(Toolset, self.toolset)), ensure_ascii=False)
        layer_fields = json.dumps({name: list(spec.public_columns) for name, spec in ALLOWED_LAYERS.items()}, ensure_ascii=False)
        advanced = """
advanced 额外规则：
query_features 用 filters=[{field,operator,value}] 按公开字段筛选；多条件 AND，in 表示多个可选值。
当前模拟数据字段值：gas_devices.status 为 正常/告警/停用；gas_pipelines.pressure_level 为 高压/中压/低压。
空间筛选同时提供 target 和 relation。含边界用 ST_Intersects，严格内部用 ST_Within。
query_features/buffer_features/clip_features/measure_features 的 result.feature_set 可整体引用到 features。
禁止复制或编造要素集坐标；超过安全上限应报错而非截断。
buffer_features 逐对象缓冲；求覆盖必须 union_features 合并去重，再与施工区求交，不能直接累加重叠缓冲面积。
union_features 返回 result.geometry (geometry+srid)，一个覆盖几何可供多个分支引用。
measure_features 返回 result.feature_set（逐项 measure_value）及 result.summary（小型量测对象）。
分组/排序先 measure_features，再 summarize_features；按原对象分组用 source_code/source_layer。
calculate_ratio 的 numerator/denominator 必须引用完整量测对象；单位/SRID一致，分母不得为0。
最终只输出小型量测 summary、calculate_ratio.result 或 summarize_features.result，不输出整个要素集。
""" if self.toolset == "advanced" else "不要使用未实现的 union 或属性筛选。"
        return f"""你是 GIS 多步规划器，不直接计算答案，不输出 SQL。
必须且只能调用一次 submit_execution_plan，arguments 为包含 steps 和 outputs 的完整计划。
steps 中 tool 只能使用下列注册工具；不要仅选择第一步，不要把整段分析塞进一个工具。
步骤必须有唯一 id、tool、arguments；依赖写 depends_on。计划最多 100 步，禁止循环。
后一步用 {{"$ref":"上游步骤ID.result.geometry"}} 整体引用几何和 srid，来源必须列入 depends_on。
不要编造或复制中间坐标，不要执行任意 SQL。
量测必须显式选择 length 或 area。量测最终输出引用完整的 步骤ID.result，保留 value 和 unit；
面积输出命名 area，长度命名 length。outputs 的值必须为 $ref 引用对象。
buffer_geometry 的 result.geometry 是 {{"geometry":GeoJSON几何,"srid":3857}}，
intersection_geometry 同样返回 result.geometry 和 is_empty/is_valid；空交集可继续量测为 0。
measure_geometry 返回 result.value、unit、measure、measure_srid 和 is_empty。
坐标默认 3857，已知经纬度须声明 4326；引用已有要素使用数据库 SRID。
允许图层：{', '.join(sorted(ALLOWED_LAYERS))}。
各图层公开属性字段：{layer_fields}
已知别名：施工一区/A区=A001，施工二区/B区=A002，施工三区/C区=A003。
若当前工具无法表达问题，不得伪造工具或数值，说明不支持并不提交可执行计划。
内部工具定义（仅描述 steps 中可选操作，不是额外模型工具）：{tools}
{advanced}
"""

    def _generate_plan(self, question: str, capture: dict[str, Any]) -> ExecutionPlan:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("问题不能为空")
        if self.planner is None:
            if self.model is None:
                self.model = _default_model()
            self.planner = self.model.bind_tools([execution_plan_definition()], tool_choice=PLAN_TOOL_NAME)
        response = self.planner.invoke([SystemMessage(content=self.system_prompt()), HumanMessage(content=question)])
        capture["model_response"] = _response_trace(response)
        arguments = _plan_arguments(response)
        capture["proposed_plan"] = deepcopy(arguments)
        plan = ExecutionPlan.model_validate(arguments)
        for step in plan.steps:
            spec = get_tool_spec(step.tool, toolset=cast(Toolset, self.toolset))
            field = spec.args_schema.model_fields.get("features")
            if self.toolset == "advanced" and field is not None and field.annotation is FeatureSet:
                value = step.arguments.get("features")
                if not isinstance(value, dict) or set(value) != {"$ref"}:
                    raise ValueError("模型的 FeatureSet 参数必须引用上游 result.feature_set，不接受模型编造的字面要素集")
                reference = ResultReference.model_validate(value)
                source = next(item for item in plan.steps if item.id == reference.step_id)
                if reference.ref.split(".")[1:] != ["result", "feature_set"] or source.tool not in {
                    "query_features", "buffer_features", "clip_features", "measure_features",
                }:
                    raise ValueError("FeatureSet 引用必须来自返回 result.feature_set 的完整集合工具")
        return plan

    def plan(self, question: str) -> ExecutionPlan:
        """仅规划；结构、工具白名单错误直接抛出。run() 才负责记录完整执行。"""
        return self._generate_plan(question, {})

    def run(self, question: str) -> dict[str, Any]:
        started = time.perf_counter()
        run: dict[str, Any] = {
            "run_id": uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(),
            "question": question, "toolset": self.toolset, "status": "error", "plan": None, "proposed_plan": None,
            "model_response": None, "planning_elapsed_ms": 0.0, "execution": None,
            "outputs": {}, "answer": None, "error": None, "error_stage": None,
            "log_path": None, "logging_error": None,
        }
        stage = "planning"
        try:
            try:
                plan = self._generate_plan(question, run)
            finally:
                run["planning_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            run["plan"] = plan.model_dump(by_alias=True)
            stage = "execution"
            execution = self.executor.run(plan)
            run["execution"] = execution
            run["status"], run["error"] = execution["status"], execution["error"]
            if execution["status"] == "ok":
                run["outputs"] = execution["outputs"]
                stage = "summary"
                run["answer"] = self.summarize(execution["outputs"])
            else:
                run["error_stage"] = "execution"
        except Exception as exc:
            run["status"], run["outputs"] = "error", {}
            run["error_stage"] = stage
            run["error"] = f"{type(exc).__name__}: {exc}"
        if run["status"] != "ok":
            run["answer"] = f"分析未完成（{run['error_stage']}）：{run['error']}"
        run["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        persist_run(run, self.logger)
        return run

    @staticmethod
    def summarize(outputs: dict[str, Any]) -> str:
        messages = []
        for name, value in outputs.items():
            if isinstance(value, dict) and "value" in value and value.get("unit") in {"meter", "square_meter", "percent", "fraction"}:
                unit = {"meter": "米", "square_meter": "平方米", "percent": "%", "fraction": "比例"}[value["unit"]]
                messages.append(f"{name}：{float(value['value']):.3f} {unit}")
            else:
                messages.append(f"{name}：{json.dumps(value, ensure_ascii=False, allow_nan=False)}")
        return "；".join(messages) + "。"

# ========================================================================
# 合并来源：scripts/run_multistep_llm.py
# ========================================================================
"""显式 --live 才调用真实模型；数据库只读，运行记录默认保存到 reports/runs。"""

import argparse
import json
from pathlib import Path

from psycopg.conninfo import make_conninfo

from app_development.db import get_settings
from app_development.tool import create_toolkit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTION = "计算燃气监测点 D011 周围 300 米缓冲区与施工一区的交集面积"


def main() -> int:
    parser = argparse.ArgumentParser(description="真实 LLM 多步规划与只读执行，调用可能产生模型费用")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--live", action="store_true", help="明确启用真实模型调用（可能产生费用）")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "reports" / "runs")
    parser.add_argument("--reference-plan", type=Path, help="可选：用与问题对应的人工计划作完整执行对比")
    parser.add_argument("--full", action="store_true", help="打印完整模型计划、每步参数及中间结果")
    parser.add_argument("--toolset", choices=["composable", "advanced"], default="composable")
    args = parser.parse_args()
    if not args.live:
        parser.error("不会默认调用付费模型；确认后请显式添加 --live")
    dsn = make_conninfo(
        get_settings().database_url, connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=10000",
    )
    toolkit = create_toolkit(args.toolset, dsn)
    reference = None
    if args.reference_plan is not None:
        plan = ExecutionPlan.model_validate(json.loads(args.reference_plan.read_text(encoding="utf-8")))
        reference = PlanExecutor(toolkit, toolset=args.toolset).run(plan)
        if reference["status"] != "ok":
            print(json.dumps({"error": "参考人工计划执行失败，未调用模型", "reference": reference}, ensure_ascii=False, indent=2))
            return 1
    run = MultiStepLLMGISAgent(toolkit=toolkit, toolset=args.toolset).run(args.question)
    if reference is not None:
        from app_development.test import compare_plan_runs

        run["reference_execution"] = reference
        run["comparison"] = compare_plan_runs(reference, run)
    persist_run(run, JsonRunLogger(args.log_dir))
    displayed = run if args.full else {key: run[key] for key in (
        "run_id", "status", "answer", "outputs", "error_stage", "error", "log_path", "logging_error",
    )}
    if "comparison" in run:
        displayed["comparison"] = run["comparison"]
    print(json.dumps(displayed, ensure_ascii=False, indent=2, allow_nan=False))
    matched = run.get("comparison", {}).get("matched", True)
    return 0 if run["status"] == "ok" and not run["logging_error"] and matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
