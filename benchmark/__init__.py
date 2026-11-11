"""dev20 基准评测：在本地 PostGIS 上跑通 20 道题并生成报告。"""
from benchmark.dev20 import (  # noqa: F401
    Case,
    compare,
    extract_json,
    format_requirement,
    load_cases,
)
