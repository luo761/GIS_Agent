"""重规划开关、跨轮轨迹和失败反馈的离线回归测试。"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from pipeline import pipeline_graph, stage3_plan, stage5_evaluate
from pipeline.pipeline_state import PipelineState, SubTask


@pytest.fixture
def offline_pipeline(monkeypatch):
    """保留真实 LangGraph 路由和阶段⑤评估，隔离模型、数据库和持久状态。"""
    progress = {"executions": 0, "plans": 0, "success_on": None, "execution_error": False}

    def understand(state):
        return state

    def decompose(state):
        state.subtasks = [SubTask("s1", question="离线问题", assigned_agent="agent_01")]
        return state

    def plan(state):
        progress["plans"] += 1
        sub = state.subtasks[0]
        # 重规划必须清除旧错误、答复与工具轨迹，评估快照应保留旧内容。
        assert sub.status == "pending" and not sub.error and sub.result is None
        assert sub.trace == [] and sub.tools_used == []
        if state.replans:
            assert state.failure_feedback
        sub.plan = {"attempt": progress["plans"]}
        return state

    def execute(state):
        progress["executions"] += 1
        number = progress["executions"]
        sub = state.subtasks[0]
        sub.status = "failed" if progress["execution_error"] and number == 1 else "success"
        sub.error = "first execution failed" if sub.status == "failed" else ""
        sub.result = "correct" if number == progress["success_on"] else f"answer_{number}"
        sub.tools_used = [f"tool_{number}"]
        sub.trace = [{"step": f"t{index}", "tool": f"tool_{number}",
                      "args": {"attempt": number}, "ok": True,
                      "brief": {"index": index}} for index in range(1, number + 1)]
        return state

    def evolve(state, faulty):
        for sub in state.subtasks:
            sub.outcome = "success" if state.evaluation == "success" else "failure"

    monkeypatch.setattr(pipeline_graph.stage1_understand, "run", understand)
    monkeypatch.setattr(pipeline_graph.stage2_decompose, "run", decompose)
    monkeypatch.setattr(pipeline_graph.stage3_plan, "run", plan)
    monkeypatch.setattr(pipeline_graph.stage4_execute, "run", execute)
    monkeypatch.setattr(stage5_evaluate, "_evolve", evolve)
    monkeypatch.setattr(stage5_evaluate, "get_default_store", lambda: Mock(refresh_chart=lambda: {}))
    monkeypatch.setattr(stage5_evaluate, "_store", Mock())
    monkeypatch.setattr(stage5_evaluate, "_compress_experience", lambda state, outcome: {"outcome": outcome})
    monkeypatch.setattr(stage5_evaluate.llm, "chat", lambda *args, **kwargs: "execution failure")
    monkeypatch.setattr(stage5_evaluate, "_VERIFIER", lambda state: (
        state.subtasks[0].result == "correct", "$.answer: 数值不匹配"))
    return progress


@pytest.mark.parametrize("max_replans, attempts", [(0, 1), (2, 3), (8, 9)])
def test_replan_budget_counts_actual_replans_and_all_failed_attempts(offline_pipeline, max_replans, attempts):
    state = pipeline_graph.ask("离线问题", ground_truth="case_id", max_replans=max_replans)

    assert state.evaluation == "failed"
    assert state.max_replans == max_replans
    assert state.replans == max_replans
    assert state.failed_attempts == attempts
    assert offline_pipeline["executions"] == offline_pipeline["plans"] == attempts
    assert len(state.attempt_history) == attempts
    assert [item["attempt_index"] for item in state.attempt_history] == list(range(1, attempts + 1))
    assert all(not item["correct"] for item in state.attempt_history)
    assert sum(item["tool_call_count"] for item in state.attempt_history) == sum(range(1, attempts + 1))


def test_success_after_retry_keeps_first_failure_and_stops_early(offline_pipeline):
    offline_pipeline["success_on"] = 2
    state = pipeline_graph.ask("离线问题", ground_truth="case_id", max_replans=2)

    assert state.evaluation == "success" and state.final_answer == "correct"
    assert state.replans == state.failed_attempts == 1
    assert [item["correct"] for item in state.attempt_history] == [False, True]
    assert [item["tool_call_count"] for item in state.attempt_history] == [1, 2]
    assert state.attempt_history[0]["subtasks"][0]["plan"] == {"attempt": 1}
    assert state.attempt_history[0]["subtasks"][0]["result"] == "answer_1"
    assert state.attempt_history[0]["subtasks"][0]["outcome"] == "failure"
    assert state.attempt_history[1]["subtasks"][0]["outcome"] == "success"
    state.subtasks[0].trace[0]["args"]["attempt"] = 99
    assert state.attempt_history[0]["subtasks"][0]["trace"][0]["args"]["attempt"] == 1
    assert state.attempt_history[1]["subtasks"][0]["trace"][0]["args"]["attempt"] == 2


def test_initial_success_never_replans(offline_pipeline):
    offline_pipeline["success_on"] = 1
    state = pipeline_graph.ask("离线问题", ground_truth="case_id", max_replans=2)
    assert state.replans == state.failed_attempts == 0
    assert len(state.attempt_history) == 1 and state.attempt_history[0]["correct"]


def test_execution_failure_history_survives_retry_and_error_is_cleared(offline_pipeline):
    offline_pipeline.update(success_on=2, execution_error=True)
    state = pipeline_graph.ask("离线问题", ground_truth="case_id", max_replans=2)
    first, final = state.attempt_history
    assert first["subtasks"][0]["status"] == "failed"
    assert first["subtasks"][0]["error"] == "first execution failed"
    assert first["feedback"] == "execution failure"
    assert final["correct"] and final["subtasks"][0]["error"] == ""
    assert state.replans == 1 and state.failed_attempts == 1


def test_omitted_budget_uses_legacy_module_default(offline_pipeline, monkeypatch):
    monkeypatch.setattr(pipeline_graph, "MAX_REPLANS", 1)
    state = pipeline_graph.ask("离线问题", ground_truth="case_id")
    assert state.max_replans == state.replans == 1
    assert len(state.attempt_history) == 2


@pytest.mark.parametrize("value", [-1, 1.5, True, "2"])
def test_invalid_budget_is_rejected_before_graph_execution(value, monkeypatch):
    build = Mock(side_effect=AssertionError("graph should not be created"))
    monkeypatch.setattr(pipeline_graph, "build_graph", build)
    with pytest.raises(ValueError, match="max_replans"):
        pipeline_graph.ask("离线问题", max_replans=value)
    build.assert_not_called()


def test_replanning_prompt_receives_previous_failure_feedback(monkeypatch):
    memory = Mock(render_memory=lambda question: "own memory")
    monkeypatch.setattr(stage3_plan, "_agent_memory", lambda agent: memory)
    monkeypatch.setattr(stage3_plan, "_capability_line", lambda agent: "agent")
    monkeypatch.setattr(stage3_plan.experience_retriever, "retrieve_experiences", lambda *args: [])
    monkeypatch.setattr(stage3_plan.experience_retriever, "render_experiences", lambda exps: "")
    chat = Mock(return_value={"plan": {"nodes": [], "edges": []}})
    monkeypatch.setattr(stage3_plan.llm, "chat_json", chat)
    state = PipelineState(replans=1, failure_feedback="$.groups: 排序方向不匹配")
    sub = SubTask("s1", question="离线问题", assigned_agent="agent_01")

    stage3_plan.run_subtask(state, sub)
    prompt = chat.call_args.args[0]
    assert "第 2 轮作答" in prompt
    assert state.failure_feedback in prompt
    assert "修正后的计划" in prompt


def test_experience_summary_uses_actual_trace_argument_and_result_keys():
    state = PipelineState(subtasks=[SubTask("s1", trace=[
        {"tool": "query_features", "args": {"layer_name": "gas_devices"},
         "ok": True, "brief": {"feature_count": 2}},
        {"tool": "measure_features", "args": {"measure": "area"},
         "ok": False, "error": "invalid geometry"},
    ])])
    text = stage5_evaluate._traces_text(state)
    assert "gas_devices" in text and "feature_count" in text and "invalid geometry" in text
