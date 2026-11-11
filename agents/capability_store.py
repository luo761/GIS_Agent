"""能力向量存储与"经验 → 能力"进化。

模型：
    每个智能体 i 的能力向量 C_i ∈ [0,1]^D，初始 C_i = [0.5, 0.5, 0.5, 0.5]，
    因此初始状态下四个智能体完全等价，路由只能随机抽取。

    一次子任务执行结束（阶段⑤判定）后，对**该子任务所需的每个能力维度**做一次更新：
        成功：v ← v + g_success * (v_max - v)      （越接近上限，增量越小）
        失败：v ← v - g_failure * (v - v_min)      （越接近下限，回落越小）
    只有与本次任务相关的能力维度发生变化，其余维度保持不变——
    这就是"通过不断执行、从成功/失败经验中补充自己在这方面的能力"。
    所有状态（向量、统计、历史帧）落盘到 data/agent_capabilities.json；
    每次更新都会重绘动态能力向量图（data/capability_vector_chart.html / .png）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

from agents import agent_registry
from config import settings


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class CapabilityStore:
    """运行期能力向量状态（可多实例，默认落到 settings.CAPABILITY_PATH）。"""

    def __init__(self, path: str | Path | None = None, *, with_chart: bool = True):
        self.path = Path(path or settings.CAPABILITY_PATH)
        self.dimensions: list[str] = agent_registry.dimensions()
        self.initial_value: float = agent_registry.initial_value()
        self.evo = agent_registry.evolution_cfg()
        self.with_chart = with_chart and settings.CAPABILITY_CHART_ENABLED
        self.state: dict[str, Any] = self._load()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ================= 初始化 / 持久化 =================
    def _base_state(self) -> dict[str, Any]:
        agents: dict[str, Any] = {}
        for aid, cfg in agent_registry.agents_config().items():
            name = str(cfg.get("name", aid))
            agents[aid] = {
                "name": name,
                "capabilities": {
                    d: float(cfg.get("capabilities", {}).get(d, self.initial_value))
                    for d in self.dimensions
                },
                "preferred_tools": list(cfg.get("preferred_tools") or []),
                "stats": {"attempts": 0, "successes": 0, "failures": 0},
            }
        return {
            "schema_version": 1,
            "initial_capability": self.initial_value,
            "dimensions": list(self.dimensions),
            "agents": agents,
            "history": [],
            "updated_at": _now(),
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            state = self._base_state()
            self._write(state)
            return state
        state = json.loads(self.path.read_text(encoding="utf-8"))
        # 兼容/修复：维度或智能体集合变化时补齐，缺失值回到初始经验值
        state.setdefault("agents", {})
        state.setdefault("history", [])
        base = self._base_state()
        for aid, base_agent in base["agents"].items():
            cur = state["agents"].get(aid)
            if not cur:
                state["agents"][aid] = base_agent
                continue
            cur.setdefault("name", base_agent["name"])
            cur.setdefault("preferred_tools", [])
            cur.setdefault("stats", {"attempts": 0, "successes": 0, "failures": 0})
            caps = cur.setdefault("capabilities", {})
            for d in self.dimensions:
                caps.setdefault(d, self.initial_value)
        for aid in list(state["agents"]):
            if aid not in base["agents"]:
                del state["agents"][aid]
        state["dimensions"] = list(self.dimensions)
        state["initial_capability"] = self.initial_value
        return state

    def _write(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def save(self) -> None:
        self._write(self.state)

    # ================= 读取 =================
    @property
    def agents(self) -> dict[str, Any]:
        return self.state["agents"]

    @property
    def history(self) -> list[dict[str, Any]]:
        return self.state["history"]

    def name(self, agent_id: str) -> str:
        return str(self.agents.get(agent_id, {}).get("name", agent_id))

    def capabilities(self, agent_id: str) -> dict[str, float]:
        caps = self.agents.get(agent_id, {}).get("capabilities", {})
        return {d: float(caps.get(d, self.initial_value)) for d in self.dimensions}

    def vector(self, agent_id: str) -> list[float]:
        caps = self.capabilities(agent_id)
        return [caps[d] for d in self.dimensions]

    def preferred_tools(self, agent_id: str) -> list[str]:
        return list(self.agents.get(agent_id, {}).get("preferred_tools") or [])

    def stats(self, agent_id: str) -> dict[str, int]:
        return dict(self.agents.get(agent_id, {}).get("stats") or {})

    def snapshot(self) -> dict[str, Any]:
        """给能力向量图/报告用的只读快照。"""
        return {
            "initial_capability": self.initial_value,
            "dimensions": list(self.dimensions),
            "labels": agent_registry.dimension_labels(),
            "agents": json.loads(json.dumps(self.agents, ensure_ascii=False)),
            "history": json.loads(json.dumps(self.history, ensure_ascii=False)),
            "updated_at": self.state.get("updated_at", ""),
        }

    def table(self) -> list[dict[str, Any]]:
        """[{agent, name, vector, stats}] —— 便于打印/测试。"""
        return [
            {
                "agent": aid,
                "name": self.name(aid),
                "vector": self.vector(aid),
                "stats": self.stats(aid),
            }
            for aid in sorted(self.agents)
        ]

    # ================= 进化 =================
    def apply(
        self,
        agent_id: str,
        dims: Iterable[str],
        outcome: str,
        *,
        question: str = "",
        task_signature: str = "",
        tools: Iterable[str] | None = None,
        note: str = "",
        refresh_chart: bool = True,
    ) -> dict[str, Any]:
        """按一次子任务的成败，更新该智能体在所需维度上的经验值。

        返回本次进化事件（同时追加到 history 并落盘）。
        """
        if agent_id not in self.agents:
            raise KeyError(f"未知智能体: {agent_id}")
        if outcome not in ("success", "failure"):
            raise ValueError(f"outcome 只能是 success / failure，收到 {outcome!r}")

        dims = [d for d in dict.fromkeys(dims) if d in self.dimensions]
        if not dims:  # 没识别出维度就按全部维度计入（综合任务）
            dims = list(self.dimensions)

        g_s = float(self.evo.get("success_gain", 0.10))
        g_f = float(self.evo.get("failure_loss", 0.08))
        v_min = float(self.evo.get("min_value", 0.05))
        v_max = float(self.evo.get("max_value", 0.99))
        nd = int(self.evo.get("decimals", 4))

        caps = self.agents[agent_id]["capabilities"]
        vector_before = self.capabilities(agent_id)
        before: dict[str, float] = {}
        after: dict[str, float] = {}
        for d in dims:
            v = float(caps.get(d, self.initial_value))
            before[d] = round(v, nd)
            v_new = v + g_s * (v_max - v) if outcome == "success" else v - g_f * (v - v_min)
            v_new = _clip(v_new, v_min, v_max)
            caps[d] = round(v_new, nd)
            after[d] = round(float(caps[d]), nd)

        agent = self.agents[agent_id]
        st = agent.setdefault("stats", {"attempts": 0, "successes": 0, "failures": 0})
        st["attempts"] = int(st.get("attempts", 0)) + 1
        st["successes" if outcome == "success" else "failures"] = (
            int(st.get("successes" if outcome == "success" else "failures", 0)) + 1
        )

        if outcome == "success" and tools:
            cap_tools = int(self.evo.get("max_preferred_tools", 5))
            prefs = list(agent.get("preferred_tools") or [])
            for t in tools:
                if t and t not in prefs:
                    prefs.append(t)
            agent["preferred_tools"] = prefs[-cap_tools:]

        event = {
            "ts": _now(),
            "agent_id": agent_id,
            "agent_name": self.name(agent_id),
            "dims": dims,
            "outcome": outcome,
            "question": question,
            "task_signature": task_signature,
            "before": before,
            "after": after,
            "delta": {d: round(after[d] - before[d], nd + 2) for d in dims},
            "vector_before": vector_before,
            "vector_after": self.capabilities(agent_id),
            "note": note,
            "index": len(self.history),
        }
        self.history.append(event)
        self.save()

        if refresh_chart and self.with_chart:
            self.refresh_chart()
        return event

    def refresh_chart(self) -> dict[str, str]:
        """重绘动态能力向量图（HTML 雷达图 + PNG 快照）。"""
        if not self.with_chart:
            return {}
        from visualization import capability_radar_chart

        return capability_radar_chart.render(self.snapshot())

    # ================= 复位 =================
    def reset(self) -> dict[str, Any]:
        """回到初始状态：所有能力值 = 0.5，历史清空。"""
        self.state = self._base_state()
        self.save()
        self.refresh_chart()
        return self.state


def load_store(*, with_chart: bool = True) -> CapabilityStore:
    return CapabilityStore(with_chart=with_chart)


# ---------------- 进程内共享实例 ----------------
# 五个阶段必须读写同一份能力状态，因此默认使用单例；
# 测试或脚本可以 set_default_store 换成临时目录下的实例。
_DEFAULT_STORE: CapabilityStore | None = None


def get_default_store(*, refresh: bool = False) -> CapabilityStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None or refresh:
        _DEFAULT_STORE = CapabilityStore()
    return _DEFAULT_STORE


def set_default_store(store: CapabilityStore) -> CapabilityStore:
    global _DEFAULT_STORE
    _DEFAULT_STORE = store
    return store
