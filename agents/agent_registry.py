"""智能体注册表：只认编号，不预设专长。

`config/agents_capability.yaml` 提供的是**初始**定义——每个智能体只有编号、
能力值全为 0.5、工具偏好为空。这里不读取任何"擅长/description"字段，
因为初始状态下不存在专长；专长来自运行期进化的能力向量
（见 `agents/capability_store.py`）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from config import settings

_CONFIG: dict[str, Any] | None = None


def load_agents_config(path: str | Path | None = None) -> dict[str, Any]:
    """读取智能体能力向量表定义（带缓存）。"""
    global _CONFIG
    if _CONFIG is None or path is not None:
        p = Path(path) if path else settings.AGENTS_CONFIG_PATH
        _CONFIG = yaml.safe_load(p.read_text(encoding="utf-8"))
    return _CONFIG


def reload_config() -> dict[str, Any]:
    """强制重新读取配置文件（测试或人工改配置后使用）。"""
    global _CONFIG
    _CONFIG = None
    return load_agents_config()


def agents_config() -> dict[str, dict[str, Any]]:
    """{agent_id: 配置}，按编号排序，保证输出稳定。"""
    cfg = load_agents_config()["agents"]
    return {aid: cfg[aid] for aid in sorted(cfg)}


def agent_ids() -> list[str]:
    return list(agents_config())


def agent_name(agent_id: str) -> str:
    """智能体展示名——就是编号本身。"""
    return str(agents_config().get(agent_id, {}).get("name", agent_id))


def memory_dir(agent_id: str, fallback: str | Path | None = None) -> str | Path:
    return agents_config().get(agent_id, {}).get("memory_dir", fallback or settings.AGENT_MEMORY_BASE)


def cache_max(agent_id: str) -> int:
    return int(load_agents_config().get("short_term_cache", {}).get("max_entries", 10))


def dimensions() -> list[str]:
    """能力维度顺序（能力向量图的坐标轴顺序）。"""
    return list(load_agents_config()["capability_glossary"])


def dimension_labels() -> dict[str, str]:
    return dict(load_agents_config().get("capability_labels", {}))


def initial_value() -> float:
    return float(load_agents_config().get("initial_capability", settings.CAPABILITY_INITIAL))


def evolution_cfg() -> dict[str, Any]:
    return dict(load_agents_config().get("evolution", {}))


def routing_cfg() -> dict[str, Any]:
    return dict(load_agents_config().get("routing", {}))


def initial_vectors() -> dict[str, dict[str, float]]:
    """初始能力向量：每个智能体每个维度都是 0.5（完全均衡）。"""
    v = initial_value()
    return {
        aid: {d: float(cfg.get("capabilities", {}).get(d, v)) for d in dimensions()}
        for aid, cfg in agents_config().items()
    }
