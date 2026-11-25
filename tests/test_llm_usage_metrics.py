"""评测用模型调用/token 统计，不连接外部模型。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipeline import llm_client


@pytest.fixture(autouse=True)
def reset_metrics():
    llm_client.reset_usage_metrics()
    yield
    llm_client.reset_usage_metrics()


def test_chat_and_tool_calls_accumulate_reported_usage(monkeypatch):
    response = SimpleNamespace(content=" ok ", usage_metadata={
        "input_tokens": 10, "output_tokens": 4, "total_tokens": 14})
    model = Mock()
    model.invoke.return_value = response
    monkeypatch.setattr(llm_client, "get_model", lambda: model)
    monkeypatch.setattr(llm_client, "get_tool_model", lambda: model)
    assert llm_client.chat("hello") == "ok"
    assert llm_client.chat_with_tools([]) is response
    metrics = llm_client.usage_metrics()
    assert metrics["llm_calls"] == metrics["usage_reported_calls"] == 2
    assert metrics["input_tokens"] == 20
    assert metrics["output_tokens"] == 8
    assert metrics["total_tokens"] == 28
    metrics["input_tokens"] = 999
    assert llm_client.usage_metrics()["input_tokens"] == 20


def test_fallback_usage_and_unreported_response(monkeypatch):
    model = Mock()
    model.invoke.side_effect = [
        SimpleNamespace(content="ok", response_metadata={"token_usage": {
            "prompt_tokens": 3, "completion_tokens": 2}}),
        SimpleNamespace(content="ok"),
    ]
    monkeypatch.setattr(llm_client, "get_model", lambda: model)
    llm_client.chat("hello")
    llm_client.chat("hello")
    assert llm_client.usage_metrics()["llm_calls"] == 2
    assert llm_client.usage_metrics()["usage_reported_calls"] == 1
    assert llm_client.usage_metrics()["total_tokens"] == 5


def test_failed_invocation_is_counted_and_reset(monkeypatch):
    model = Mock()
    model.invoke.side_effect = RuntimeError("offline")
    monkeypatch.setattr(llm_client, "get_model", lambda: model)
    with pytest.raises(RuntimeError, match="offline"):
        llm_client.chat("hello")
    assert llm_client.usage_metrics()["llm_calls"] == 1
    assert llm_client.usage_metrics()["failed_calls"] == 1
    assert llm_client.usage_metrics()["usage_reported_calls"] == 0
    llm_client.reset_usage_metrics()
    assert llm_client.usage_metrics()["llm_calls"] == 0
