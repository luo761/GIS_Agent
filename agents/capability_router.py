"""能力路由：按能力向量选智能体，能力均等时随机抽取。

规则（对应"初始能力均衡 → 均等就随机抽取"）：
    1. 对子任务所需的每个能力维度 d，取各智能体在该维度的经验值；
    2. 智能体得分 score = 所需维度的平均经验值；
    3. 取最高分；所有与最高分相差不超过 tie_epsilon 的智能体构成"并列组"；
    4. 并列组只有 1 个 → 直接选用；多于 1 个 → 在并列组内**随机抽取**。

初始状态下四个智能体的四个维度都是 0.5，得分完全相同，因此每次路由
都是随机抽取（不会因为编号靠前就总被选中）。进化之后，能力强的智能体
才会获得稳定优势。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable

from agents import agent_registry
from agents.capability_store import CapabilityStore
from config import settings

_AGENTS_CFG = agent_registry.load_agents_config()

_TASK_TYPE_CAPS: dict[str, list[str]] = dict(_AGENTS_CFG.get("task_type_capabilities", {}))

_RNG = random.Random(agent_registry.routing_cfg().get("random_seed"))


def set_random_seed(seed: int | None) -> None:
    """固定/重置路由随机源（测试用）。"""
    global _RNG
    _RNG = random.Random(seed)


def _default_epsilon() -> float:
    cfg = agent_registry.routing_cfg()
    return float(cfg.get("tie_epsilon", settings.ROUTING_TIE_EPSILON))


def normalize_dimensions(dims: Iterable[str] | None, task_type: str = "") -> list[str]:
    """清洗能力维度：只保留已定义的维度；缺失时按任务类型回退。"""
    valid = set(agent_registry.dimensions())
    cleaned = [d for d in dict.fromkeys(dims or []) if d in valid]
    if cleaned:
        return cleaned
    fallback = _TASK_TYPE_CAPS.get(task_type) or list(agent_registry.dimensions())
    return [d for d in fallback if d in valid]


def score_agent(store: CapabilityStore, agent_id: str, dims: list[str]) -> float:
    caps = store.capabilities(agent_id)
    if not dims:
        return 0.0
    return sum(caps[d] for d in dims) / len(dims)


@dataclass
class RoutingDecision:
    """一次路由的完整过程记录（可审计、可复现）。"""

    agent_id: str
    agent_name: str
    required: list[str]
    scores: dict[str, float]
    best_score: float
    tied: list[str]
    random_pick: bool
    epsilon: float
    pool: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "required": list(self.required),
            "scores": dict(self.scores),
            "best_score": round(self.best_score, 6),
            "tied": list(self.tied),
            "random_pick": self.random_pick,
            "epsilon": self.epsilon,
            "pool": list(self.pool),
        }

    def explain(self) -> str:
        s = "、".join(f"{k}={v:.4f}" for k, v in self.scores.items())
        if self.random_pick:
            return (f"所需能力 {self.required}｜得分 {s}｜最高分 {self.best_score:.4f} 并列，"
                    f"在 [{', '.join(self.tied)}] 中随机抽取 → {self.agent_id}")
        return f"所需能力 {self.required}｜得分 {s}｜能力最高 → {self.agent_id}"


def route(
    store: CapabilityStore,
    dims: Iterable[str] | None,
    *,
    task_type: str = "",
    epsilon: float | None = None,
    rng: random.Random | None = None,
) -> RoutingDecision:
    """给一个子任务选智能体。"""
    required = normalize_dimensions(dims, task_type)
    epsilon = _default_epsilon() if epsilon is None else float(epsilon)
    rng = rng or _RNG

    agents = sorted(store.agents)
    scores = {aid: score_agent(store, aid, required) for aid in agents}
    best = max(scores.values()) if scores else 0.0
    tied = [aid for aid in agents if best - scores[aid] <= epsilon + 1e-12]
    chosen = rng.choice(tied) if len(tied) > 1 else tied[0]

    return RoutingDecision(
        agent_id=chosen,
        agent_name=store.name(chosen),
        required=required,
        scores=scores,
        best_score=best,
        tied=tied,
        random_pick=len(tied) > 1,
        epsilon=epsilon,
        pool=agents,
    )
