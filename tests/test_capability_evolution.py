"""能力均衡、随机路由、经验进化、动态能力向量图的测试。

运行：
    python -m pytest tests -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import settings
from agents import agent_registry, capability_router
from agents.capability_store import CapabilityStore, set_default_store
from experience.experience_pool import ExperiencePool
from knowledge import db_schema_retriever, task_skill_library
from memory.agent_memory import AgentMemory
from tools import tool_registry
from visualization import capability_radar_chart


# ------------------------------------------------------------------ 夹具
@pytest.fixture()
def store(tmp_path):
    s = CapabilityStore(tmp_path / "agent_capabilities.json", with_chart=False)
    return s


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """把能力/经验/记忆/图表全部隔离到临时目录。"""
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "CAPABILITY_PATH", tmp_path / "agent_capabilities.json")
    monkeypatch.setattr(settings, "CAPABILITY_CHART_HTML", tmp_path / "capability_vector_chart.html")
    monkeypatch.setattr(settings, "CAPABILITY_CHART_PNG", tmp_path / "capability_vector_chart.png")
    monkeypatch.setattr(settings, "EXPERIENCE_PATH", tmp_path / "experience.json")

    s = CapabilityStore(tmp_path / "agent_capabilities.json", with_chart=True)
    set_default_store(s)

    import pipeline.stage5_evaluate as stage5
    from experience import experience_retriever as retrieval
    stage5._store = ExperiencePool(tmp_path / "experience.json")
    retrieval._store = ExperiencePool(tmp_path / "experience.json")
    return s


# ------------------------------------------------------------------ 初始状态
def test_initial_capabilities_all_balanced():
    vectors = agent_registry.initial_vectors()
    assert len(vectors) == 4
    assert list(vectors) == ["agent_01", "agent_02", "agent_03", "agent_04"]
    for caps in vectors.values():
        assert set(caps) == {"spatial_compute", "attribute_query", "statistics", "mapping"}
        assert all(v == 0.5 for v in caps.values())


def test_agents_are_named_by_number_only(store):
    assert [store.name(a) for a in sorted(store.agents)] == ["01", "02", "03", "04"]
    for aid in store.agents:
        assert store.stats(aid) == {"attempts": 0, "successes": 0, "failures": 0}
        assert store.preferred_tools(aid) == []


def test_no_preset_specialty_in_config():
    cfg = agent_registry.load_agents_config()
    for agent in cfg["agents"].values():
        assert "description" not in agent      # 不允许预设"擅长…"
        assert all(v == 0.5 for v in agent["capabilities"].values())


# ------------------------------------------------------------------ 路由
def test_equal_capability_is_random(store):
    capability_router.set_random_seed(2024)
    dims = ["statistics"]
    picks = [capability_router.route(store, dims) for _ in range(200)]
    assert all(d.random_pick for d in picks)
    assert all(d.tied == ["agent_01", "agent_02", "agent_03", "agent_04"] for d in picks)
    assert {d.agent_id for d in picks} == set(store.agents)  # 四个都被抽到过


def test_random_pick_is_uniform_ish(store):
    capability_router.set_random_seed(7)
    counter = {a: 0 for a in store.agents}
    for _ in range(400):
        counter[capability_router.route(store, ["mapping"]).agent_id] += 1
    # 均匀分布下每个约 100 次；给足容差避免抖动
    assert all(60 < n < 140 for n in counter.values())


def test_capability_advantage_wins_without_random(store):
    for _ in range(8):  # 反复成功，把 agent_03 的 statistics 拉高
        store.apply("agent_03", ["statistics"], "success")
    decision = capability_router.route(store, ["statistics"])
    assert decision.agent_id == "agent_03"
    assert decision.random_pick is False
    assert decision.scores["agent_03"] > decision.scores["agent_01"]


def test_only_required_dimensions_decide(store):
    store.apply("agent_02", ["mapping"], "success", refresh_chart=False)
    # 需要 statistics 时，agent_02 的制图优势不应生效
    decision = capability_router.route(store, ["statistics"])
    assert decision.random_pick is True
    assert decision.scores["agent_02"] == 0.5


# ------------------------------------------------------------------ 进化
def test_success_only_raises_required_dimensions(store):
    event = store.apply("agent_01", ["statistics"], "success", question="排序")
    caps = store.capabilities("agent_01")
    assert caps["statistics"] == pytest.approx(0.549, abs=1e-6)
    assert caps["spatial_compute"] == 0.5
    assert caps["attribute_query"] == 0.5
    assert caps["mapping"] == 0.5
    assert event["dims"] == ["statistics"]
    assert event["outcome"] == "success"
    assert store.stats("agent_01")["successes"] == 1
    assert store.stats("agent_01")["attempts"] == 1


def test_failure_lowers_required_dimensions(store):
    store.apply("agent_01", ["spatial_compute"], "failure", question="缓冲")
    caps = store.capabilities("agent_01")
    assert caps["spatial_compute"] == pytest.approx(0.464, abs=1e-6)
    assert caps["statistics"] == 0.5
    assert store.stats("agent_01")["failures"] == 1


def test_multi_dimension_subtask_updates_each(store):
    store.apply("agent_04", ["spatial_compute", "statistics"], "success")
    caps = store.capabilities("agent_04")
    assert caps["spatial_compute"] == pytest.approx(0.549, abs=1e-6)
    assert caps["statistics"] == pytest.approx(0.549, abs=1e-6)
    assert caps["mapping"] == 0.5


def test_values_stay_in_bounds_and_saturate(store):
    for _ in range(300):
        store.apply("agent_01", ["mapping"], "success", refresh_chart=False)
    assert store.capabilities("agent_01")["mapping"] <= 0.99
    for _ in range(400):
        store.apply("agent_01", ["mapping"], "failure", refresh_chart=False)
    assert store.capabilities("agent_01")["mapping"] >= 0.05


def test_success_records_preferred_tools(store):
    store.apply("agent_02", ["statistics"], "success",
                tools=["group_aggregate", "sort_rank", "group_aggregate"])
    assert store.preferred_tools("agent_02") == ["group_aggregate", "sort_rank"]


def test_state_persists_and_reloads(tmp_path):
    path = tmp_path / "caps.json"
    s1 = CapabilityStore(path, with_chart=False)
    s1.apply("agent_02", ["attribute_query"], "success", question="筛选")
    s2 = CapabilityStore(path, with_chart=False)
    assert s2.capabilities("agent_02")["attribute_query"] == pytest.approx(0.549, abs=1e-6)
    assert len(s2.history) == 1
    assert s2.state["initial_capability"] == 0.5


def test_reset_returns_to_balance(store):
    store.apply("agent_01", ["statistics"], "success")
    store.reset()
    assert store.capabilities("agent_01")["statistics"] == 0.5
    assert store.history == []
    assert store.stats("agent_01")["attempts"] == 0


def test_invalid_outcome_rejected(store):
    with pytest.raises(ValueError):
        store.apply("agent_01", ["statistics"], "maybe")


# ------------------------------------------------------------------ 能力向量图
def test_html_chart_contains_vectors_and_history(store, tmp_path):
    store.apply("agent_03", ["statistics"], "success", question="按地类统计面积")
    snapshot = store.snapshot()
    out = tmp_path / "chart.html"
    capability_radar_chart.render_html(snapshot, out)
    text = out.read_text(encoding="utf-8")
    assert "智能体能力向量图" in text
    assert "agent_03" in text and "0.549" in text
    assert "按地类统计面积" in text
    assert "__CAPABILITY_DATA__" not in text


def test_ascii_table_shows_all_agents(store):
    text = capability_radar_chart.render_ascii(store.snapshot())
    assert "智能体" in text and "空间计算" in text
    for name in ("01", "02", "03", "04"):
        assert f"智能体{name}" in text
    assert "0.5000" in text


def test_png_snapshot_renders(store, tmp_path):
    out = capability_radar_chart.render_png(store.snapshot(), tmp_path / "chart.png")
    if out is None:  # 未安装 matplotlib 时跳过
        pytest.skip("matplotlib 不可用")
    assert Path(out).exists() and Path(out).stat().st_size > 0


# ------------------------------------------------------------------ 端到端
class _StubAI:
    """模拟 AIMessage：要么带 tool_calls（调用算子），要么带最终 content。"""

    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


@tool_registry.register("test_probe")
def _test_probe(**kwargs):
    """测试用探针算子：不连接数据库，返回固定结果结构。"""
    return {"status": "ok", "tool": "test_probe", "elapsed_ms": 0,
            "result": {"feature_set": {"feature_count": 2}, "summary": {"value": 2.0}},
            "error": None}


class StubLLM:
    """按提示词特征返回固定内容的假模型（不访问网络、不绑定真实工具）。"""

    def __init__(self, correct: bool = True, first_tool_error: bool = False):
        self.correct = correct
        self.first_tool_error = first_tool_error
        self.json_calls = 0
        self.prompts: list[str] = []
        self.bad_tool_sent = False

    def chat(self, prompt: str, system: str = "") -> str:
        if "压缩为不超过200字" in prompt:
            return "stub 经验摘要"
        if "汇总为一份完整答案" in prompt:
            return "stub 汇总答案"
        if "避免措施" in prompt:
            return "stub 失败教训"
        return "stub"

    def chat_json(self, prompt: str, system: str = "") -> dict:
        self.json_calls += 1
        if "候选领域" in prompt:
            return {"domain": "general", "task_type": "统计分析", "reason": "stub"}
        if "formalize" in prompt:
            return {
                "formalized_question": "统计各省耕地面积并从大到小排序",
                "subtasks": [{
                    "subtask_id": "t1",
                    "question": "统计各省耕地面积并从大到小排序",
                    "required_capabilities": ["statistics"],
                }],
            }
        if "请参考你的专属记忆与共享经验" in prompt:
            return {"plan": {"nodes": [{
                "id": "s1", "action": "test_probe",
                "params": {}, "depends_on": [],
            }], "edges": []}}
        if "正确答案" in prompt:
            return {"correct": self.correct, "reason": "stub 判定",
                    "faulty_subtasks": ["t1"]}
        return {}

    def chat_with_tools(self, messages):
        """模拟绑定工具后的模型：第一轮发起 tool_call，之后给出最终答复。"""
        self.prompts.append("\n".join(str(getattr(m, "content", "")) for m in messages))
        tool_msgs = [m for m in messages if getattr(m, "type", "") == "tool"]
        if self.first_tool_error:
            if not self.bad_tool_sent:
                self.bad_tool_sent = True
                return _StubAI(tool_calls=[{"name": "no_such_tool", "args": {},
                                            "id": "call_bad"}])
            if len(tool_msgs) < 2:
                return _StubAI(tool_calls=[{"name": "test_probe", "args": {},
                                            "id": "call_2"}])
            return _StubAI(content="stub 各省耕地面积排序结果")
        if not tool_msgs:
            return _StubAI(tool_calls=[{"name": "test_probe", "args": {},
                                        "id": "call_1"}])
        return _StubAI(content="stub 各省耕地面积排序结果")


def _patch_llm(monkeypatch, stub):
    from pipeline import llm_client as llm
    monkeypatch.setattr(llm, "chat", stub.chat)
    monkeypatch.setattr(llm, "chat_json", stub.chat_json)
    monkeypatch.setattr(llm, "chat_with_tools", stub.chat_with_tools)


def test_pipeline_success_evolves_capability(sandbox, monkeypatch):
    from pipeline.pipeline_graph import ask

    stub = StubLLM(correct=True)
    _patch_llm(monkeypatch, stub)
    before = {a: sandbox.capabilities(a) for a in sandbox.agents}

    state = ask("各省耕地面积排序", ground_truth="正确的排序结果")

    assert state.evaluation == "success"
    assert len(state.subtasks) == 1
    sub = state.subtasks[0]
    assert sub.routing["random_pick"] is True          # 初始能力均等 → 随机
    assert sub.assigned_agent in sandbox.agents
    assert sub.required_capabilities == ["statistics"]

    caps = sandbox.capabilities(sub.assigned_agent)
    assert caps["statistics"] > 0.5
    other = [a for a in sandbox.agents if a != sub.assigned_agent]
    for a in other:                                     # 其他智能体不受影响
        assert sandbox.capabilities(a) == before[a]
    assert len(sandbox.history) == 1
    assert state.capability_changes[0]["subtask_id"] == "t1"
    assert Path(settings.CAPABILITY_CHART_HTML).exists()
    assert json.loads(Path(settings.EXPERIENCE_PATH).read_text(encoding="utf-8"))[0]["outcome"] == "success"


def test_pipeline_wrong_answer_penalises_agent(sandbox, monkeypatch):
    from pipeline.pipeline_graph import ask

    stub = StubLLM(correct=False)
    _patch_llm(monkeypatch, stub)
    state = ask("各省耕地面积排序", ground_truth="正确结果")

    assert state.evaluation == "failed"
    assert state.capability_changes
    agent = state.subtasks[0].assigned_agent
    assert sandbox.capabilities(agent)["statistics"] < 0.5
    assert len(sandbox.history) >= 1
    assert state.failure_feedback


def test_evolution_creates_measured_advantage(sandbox, monkeypatch):
    """连续成功 → 该智能体在统计维度逐渐领先 → 之后固定路由到它。"""
    from pipeline.pipeline_graph import ask

    stub = StubLLM(correct=True)
    _patch_llm(monkeypatch, stub)

    winners = []
    for _ in range(6):
        state = ask("各省耕地面积排序", ground_truth="正确结果")
        winners.append(state.subtasks[0].assigned_agent)

    # 初始全 0.5，随机选择；一旦某个智能体在统计维度积累成功，
    # 它会稳定胜出（后续不再随机）
    top = max(sandbox.agents, key=lambda a: sandbox.capabilities(a)["statistics"])
    assert sandbox.capabilities(top)["statistics"] > 0.7
    assert sandbox.stats(top)["successes"] >= 4
    assert capability_router.route(sandbox, ["statistics"]).agent_id == top
    assert winners[-1] == top


def test_executor_uses_bound_tools_not_prompt_list(sandbox, monkeypatch):
    """执行器走绑定工具：提示词里不再罗列算子，工具调用进入轨迹。"""
    from pipeline.pipeline_graph import ask

    stub = StubLLM(correct=True)
    _patch_llm(monkeypatch, stub)
    state = ask("各省耕地面积排序", ground_truth="正确结果")
    sub = state.subtasks[0]

    assert sub.status == "success"
    assert sub.tools_used == ["test_probe"]
    assert sub.trace and sub.trace[0]["tool"] == "test_probe"
    prompt = stub.prompts[0]
    assert "工具池可用算子" not in prompt
    assert "attribute_filter" not in prompt       # 不再罗列算子清单
    assert sub.result


def test_executor_recovers_from_tool_error(sandbox, monkeypatch):
    """工具报错会回填给模型，模型可调整后重试，而不是整个子任务直接失败。"""
    from pipeline.pipeline_graph import ask

    stub = StubLLM(correct=True, first_tool_error=True)
    _patch_llm(monkeypatch, stub)
    state = ask("各省耕地面积排序", ground_truth="正确结果")
    sub = state.subtasks[0]

    assert sub.status == "success"
    assert any(not t.get("ok", True) for t in sub.trace)   # 第一次调用的错误被记录
    assert sub.tools_used == ["test_probe"]                # 之后成功调用了正确算子
    assert state.evaluation == "success"


# ------------------------------------------------------------------ 检索
def test_skill_retrieval_is_relevance_based():
    hits = task_skill_library.retrieve_skills("查询与施工区 A001 相交的燃气设备，边界接触也要计入", top_k=3)
    assert hits and hits[0][0] > 0
    assert hits[0][1]["id"] == "spatial_query_count"
    assert all(score1 >= score2 for (score1, _), (score2, _) in zip(hits, hits[1:]))


def test_skill_retrieval_is_not_sequential_truncation():
    """库里靠后的 skill 也能被检索到（证明不是按顺序取前 k 个）。"""
    assert task_skill_library.SKILL_LIBRARY[-1]["id"] != "dedup_union_count"
    hits = task_skill_library.retrieve_skills("把两个施工区合并后统计设备的去重数量", top_k=2)
    assert hits[0][1]["id"] == "dedup_union_count"


def test_skill_may_contain_multiple_operators():
    multi = [s for s in task_skill_library.SKILL_LIBRARY if len(s["operators"]) > 1]
    assert multi, "skill 应当允许由多个算子组成的典型任务"
    rendered = task_skill_library.load_skills("燃气管线裁剪后按压力等级分组汇总长度")
    assert "典型步骤" in rendered
    assert "→" in rendered                         # 多算子串联过程
    assert "参数:" not in rendered                  # 不再罗列算子参数签名


def test_schema_retrieval_uses_cosine(monkeypatch):
    """demo 模式（不依赖数据库）验证余弦检索。"""
    monkeypatch.setattr(settings, "SCHEMA_SOURCE", "demo")
    db_schema_retriever.reset_schema_cache()
    try:
        assert db_schema_retriever.filter_relevant_tables("水表月用水量查询")[0] == "water_meter"
        assert "gas_pipeline" in db_schema_retriever.filter_relevant_tables("燃气管线管材和压力等级")
        text = db_schema_retriever.get_context("查询燃气阀门运行状态")
        assert "gas_valve" in text
    finally:
        db_schema_retriever.reset_schema_cache()


def _db_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(settings.DATABASE_URL, connect_timeout=2):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="本地 PostGIS 不可用")
def test_live_schema_is_read_from_postgis(monkeypatch):
    monkeypatch.setattr(settings, "SCHEMA_SOURCE", "postgis")
    db_schema_retriever.reset_schema_cache()
    try:
        tables = db_schema_retriever.filter_relevant_tables("统计施工区 A001 内的燃气设备")
        assert "construction_areas" in tables and "gas_devices" in tables
        context = db_schema_retriever.get_context("统计施工区 A001 内的燃气设备")
        assert "样例：A001" in context and "status" in context
    finally:
        db_schema_retriever.reset_schema_cache()


def test_experience_retrieval_uses_cosine(tmp_path):
    exp = ExperiencePool(tmp_path / "exp.json")
    exp.write({"task_signature": "gas/空间计算",
               "question_feat": "燃气管线泄漏缓冲影响范围统计",
               "plan": {}, "trace": "", "outcome": "success"})
    exp.write({"task_signature": "general/统计分析",
               "question_feat": "各省耕地面积从大到小排序",
               "plan": {}, "trace": "", "outcome": "success"})

    hits = exp.retrieve("燃气管线泄漏 缓冲区 影响阀门", top_k=1)
    assert hits and "燃气" in hits[0]["question_feat"]


def test_agent_memory_retrieval_uses_cosine(tmp_path):
    mem = AgentMemory("agent_01", root_dir=tmp_path / "m", cache_max=3)
    mem.record_task("统计各区县供水管网总长度", None, "ok", "success")
    mem.record_task("制作土地利用专题图并导出", None, "ok", "success")

    hits = mem.find_tasks("统计供水管网长度")
    assert hits and "供水" in hits[0]["question_feat"]


def test_tool_schemas_are_bound_at_startup():
    schemas = {s["function"]["name"]: s for s in tool_registry.tool_schemas()}
    for name in ("query_features", "clip_features", "buffer_geometry",
                 "measure_features", "summarize_features", "calculate_ratio"):
        assert name in schemas
    params = schemas["query_features"]["function"]["parameters"]
    assert "layer_name" in params["required"]
    layer = params["properties"]["layer_name"]
    assert layer["type"] == "string" and "gas_devices" in layer["enum"]
    clip = schemas["clip_features"]["function"]["parameters"]["properties"]
    assert "features" in clip and "clip_target" in clip


# ------------------------------------------------------------------ 结果引用与判分
def test_ref_resolution_and_errors():
    from pipeline.stage4_execute import _resolve_refs

    store = {"t1": {"status": "ok", "result": {"feature_set": {"feature_count": 3}}}}
    resolved = _resolve_refs(
        {"features": {"$ref": "t1.result.feature_set"}, "keep": True}, store)
    assert resolved["features"]["feature_count"] == 3
    assert resolved["keep"] is True
    with pytest.raises(KeyError):
        _resolve_refs({"$ref": "t9.result"}, store)


def test_benchmark_compare_extract_and_skeleton():
    from benchmark.dev20 import compare, extract_json, json_skeleton

    assert compare({"count": 2}, {"count": 2}) == []
    assert compare({"count": 2.0}, {"count": 2}) == []
    assert compare({"count": 2}, {"count": 3})
    assert compare(
        {"unit": "meter", "groups": [{"group": {"p": "a"}, "value": 1.0, "feature_count": 1}]},
        {"unit": "meter", "groups": [{"group": {"p": "a"}, "value": 1, "feature_count": 1}]},
    ) == []
    assert extract_json('说明：{"count": 2} 完毕') == {"count": 2}
    assert extract_json("没有 JSON") is None
    assert json_skeleton({"a": {"b": 1}, "c": "x", "d": [{"e": 2}]}) == {
        "a": {"b": 0.0}, "c": "", "d": [{"e": 0.0}]}


def test_answer_format_carries_output_structure():
    from benchmark.dev20 import format_requirement, load_cases

    case = next(c for c in load_cases() if c.id == "D04")
    text = format_requirement(case)
    assert '"group"' in text and "device_type" in text and "value" in text
