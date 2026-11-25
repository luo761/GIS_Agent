"""项目内 PostGIS 工具迁移、注册、模型绑定与执行器衔接的离线回归测试。"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from config import settings
from tools import db, gis_toolkit, postgis_tools, tool_registry


@pytest.mark.parametrize("toolset, expected_count", [("advanced", 10), ("composable", 3)])
def test_startup_uses_local_tools_without_external_project_or_database(toolset, expected_count):
    """独立进程验证首次导入；外部包和数据库连接都不可用。"""
    script = textwrap.dedent("""
        import importlib.abc
        import sys
        import psycopg

        class BlockExternalProject(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'app_development' or fullname.startswith('app_development.'):
                    raise AssertionError('Tool startup depends on external project')

        def deny_connection(*args, **kwargs):
            raise AssertionError('Tool startup attempted a database connection')

        sys.meta_path.insert(0, BlockExternalProject())
        psycopg.connect = deny_connection
        from tools import tool_registry, gis_toolkit
        assert len(tool_registry.list_tools()) == int(sys.argv[1])
        assert all(layer.schema_name == 'tenant_gis' for layer in gis_toolkit.ALLOWED_LAYERS.values())
        assert not any(name.startswith('app_development') for name in sys.modules)
    """)
    env = os.environ.copy()
    env.update(POSTGIS_TOOLSET=toolset, APP_SCHEMA="tenant_gis", POSTGIS_TOOLKIT_ROOT="missing-external-project")
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(expected_count)],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_legacy_import_matches_local_toolkit_when_available():
    if not (Path(__file__).resolve().parents[1] / "source" / "tool.py").exists():
        pytest.skip("旧 source 目录已移除，正式工具入口使用 tools.gis_toolkit")
    from source import tool as compatible_tool

    assert compatible_tool.FeatureSetToolkit is gis_toolkit.FeatureSetToolkit


def test_database_defaults_and_explicit_connection_share_project_settings(monkeypatch):
    default_url = "postgresql://localhost/offline_default"
    override_url = "postgresql://localhost/offline_override"
    monkeypatch.setattr(settings, "DATABASE_URL", default_url)
    connect = Mock(return_value=object())
    monkeypatch.setattr(db.psycopg, "connect", connect)

    assert gis_toolkit.PostGISToolkit().database_url == default_url
    assert gis_toolkit.PostGISToolkit(override_url).database_url == override_url
    db.get_connection()
    db.get_connection(override_url)
    assert [args.args for args in connect.call_args_list] == [(default_url,), (override_url,)]


@pytest.mark.parametrize("identifier", ["gas_devices; DROP TABLE gas_devices", "gis_lab.gas_devices", 'name"', ""])
def test_sql_identifiers_are_validated(identifier):
    assert db.quote_identifier("gas_devices") == '"gas_devices"'
    with pytest.raises(ValueError):
        db.quote_identifier(identifier)


def _measurement(value, unit="meter"):
    return {"value": value, "unit": unit, "measure_srid": 3857}


def _feature_set():
    features = []
    for index, category in enumerate(("valve", "station"), start=1):
        features.append({
            "key": f"gas_devices:{index}", "source_layer": "gas_devices",
            "source_id": index, "source_code": f"D{index:03d}",
            "source_keys": [f"gas_devices:{index}"],
            "properties": {"device_type": category},
            "geometry": {"type": "Point", "coordinates": [index, index]},
        })
    return {"srid": 3857, "is_complete": True, "feature_count": len(features),
            "property_fields": ["device_type"], "features": features}


def test_registered_ratio_calls_local_implementation_without_database(monkeypatch):
    monkeypatch.setattr(db.psycopg, "connect", Mock(side_effect=AssertionError("unexpected connection")))
    result = tool_registry.call("calculate_ratio", numerator=_measurement(25), denominator=_measurement(100))
    assert result["status"] == "ok"
    assert result["tool"] == "calculate_ratio"
    assert result["result"] == {"value": 25.0, "unit": "percent", "numerator": 25.0, "denominator": 100.0}


@pytest.mark.parametrize("parameters", [
    {"numerator": _measurement(1), "denominator": _measurement(0)},
    {"numerator": _measurement(1), "denominator": _measurement(2, "square_meter")},
    {"numerator": 1, "denominator": 2},
    {"numerator": _measurement(1), "denominator": _measurement(2), "unknown": True},
])
def test_registered_tools_keep_pydantic_validation(parameters):
    with pytest.raises(ValidationError):
        tool_registry.call("calculate_ratio", **parameters)


def test_registered_summary_preserves_identity_deduplication_and_groups():
    dataset = _feature_set()
    dataset["features"].append(copy.deepcopy(dataset["features"][0]))
    dataset["feature_count"] += 1
    result = tool_registry.call("summarize_features", features=dataset,
                                group_by=["device_type"], aggregate="count", sort="group_asc")["result"]
    assert result["input_count"] == 3
    assert result["unique_count"] == result["retained_count"] == 2
    assert result["groups"] == [
        {"group": {"device_type": "station"}, "value": 1.0, "feature_count": 1},
        {"group": {"device_type": "valve"}, "value": 1.0, "feature_count": 1},
    ]
    dataset["feature_count"] = 1
    with pytest.raises(ValidationError):
        tool_registry.call("summarize_features", features=dataset, aggregate="count")


def test_registered_schemas_keep_nested_constraints_and_inline_definitions():
    schemas = {schema["function"]["name"]: schema["function"]["parameters"]
               for schema in tool_registry.tool_schemas()}
    serialized = json.dumps(schemas)
    assert '"$ref"' not in serialized and '"$defs"' not in serialized
    layer = schemas["query_features"]["properties"]["layer_name"]
    assert set(layer["enum"]) == set(gis_toolkit.ALLOWED_LAYERS)
    buffer = schemas["buffer_geometry"]
    assert buffer["additionalProperties"] is False
    assert set(buffer["required"]) == {"target", "distance_m"}
    assert buffer["properties"]["distance_m"]["exclusiveMinimum"] == 0
    assert buffer["properties"]["distance_m"]["maximum"] == 10000
    assert buffer["properties"]["target"]["additionalProperties"] is False
    feature_set = schemas["summarize_features"]["properties"]["features"]
    assert feature_set["properties"]["is_complete"]["const"] is True
    assert feature_set["properties"]["features"]["maxItems"] == 10000


def test_local_tool_schemas_are_bound_to_model_once(monkeypatch):
    from pipeline import llm_client

    model = Mock()
    monkeypatch.setattr(llm_client, "get_model", lambda: model)
    monkeypatch.setattr(llm_client, "_tool_model", None)
    monkeypatch.setattr(llm_client, "_tool_names", ())
    bound = llm_client.get_tool_model()
    assert bound is model.bind_tools.return_value
    assert llm_client.get_tool_model() is bound
    model.bind_tools.assert_called_once_with(tool_registry.tool_schemas())


def test_executor_resolves_complete_feature_sets_and_measurements_between_local_tools(monkeypatch):
    from pipeline.stage4_execute import _run_tool_calls

    def fetch(sql, params=None):
        if "SELECT srid FROM spatial_ref_sys" in sql:
            return [{"srid": 3857}]
        if "ST_IsValid(geom) AS valid" in sql:
            return [{"position": index, "valid": True} for index in range(2)]
        assert "AS value FROM input ORDER BY position" in sql
        return [{"position": 0, "value": 10.0}, {"position": 1, "value": 30.0}]

    monkeypatch.setattr(postgis_tools.get_toolkit(), "_fetch", fetch)
    calls = [
        {"id": "measure", "name": "measure_features", "args": {"features": _feature_set(), "measure": "length"}},
        {"id": "summary", "name": "summarize_features", "args": {
            "features": {"$ref": "t1.result.feature_set"}, "aggregate": "sum", "group_by": ["device_type"]}},
        {"id": "ratio", "name": "calculate_ratio", "args": {
            "numerator": {"$ref": "t1.result.summary"}, "denominator": _measurement(80)}},
    ]
    trace, used, results = [], [], {}
    messages = _run_tool_calls(calls, trace, used, results)
    assert len(messages) == len(trace) == 3
    assert all(step["ok"] for step in trace)
    assert used == ["measure_features", "summarize_features", "calculate_ratio"]
    assert results["t1"]["result"]["feature_set"]["features"][1]["measure_value"] == 30.0
    assert results["t2"]["result"]["groups"][0]["value"] == 30.0
    assert results["t3"]["result"]["value"] == 50.0
    assert trace[1]["args"]["features"] == {"$ref": "t1.result.feature_set"}
    assert all(json.loads(message.content)["ok"] for message in messages)
    assert "coordinates" not in messages[0].content
