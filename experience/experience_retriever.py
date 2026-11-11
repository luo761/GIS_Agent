"""经验检索：阶段③规划前，检索最相关经验供智能体学习。"""
from __future__ import annotations
from experience.experience_pool import ExperiencePool
from config import settings

_store = ExperiencePool()


def retrieve_experiences(question: str, domain: str) -> list[dict]:
    """返回与问题最相关的经验列表（含成功范例与失败教训）。"""
    hits = _store.retrieve(f"{domain} {question}", settings.EXPERIENCE_TOP_K)
    for h in hits:
        _store.record_hit(h["id"])
    return hits


def render_experiences(experiences: list[dict]) -> str:
    """把经验渲染为注入规划 prompt 的文本。"""
    if not experiences:
        return "【经验池】暂无相关经验，请基于领域知识自行规划。"
    lines = ["【经验池 · 相关经验】"]
    for e in experiences:
        tag = "成功范例" if e.get("outcome") == "success" else "失败教训"
        lines.append(f"\n[{tag}] {e.get('question_feat', '')}")
        if e.get("plan"):
            lines.append(f"  计划: {e['plan']}")
        if e.get("trace"):
            lines.append(f"  轨迹: {e['trace']}")
        if e.get("error_lesson"):
            lines.append(f"  教训: {e['error_lesson']}")
    return "\n".join(lines)
