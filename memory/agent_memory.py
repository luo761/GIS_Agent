"""智能体专属记忆空间。

多智能体能力差异的来源之一：即使底层是同一个 LLM，
每个智能体拥有独立的记忆空间，包含两部分：
1. 长期任务记录（completed/）——自己完成过的任务（问题特征、计划、结果摘要、成功/失败），
   可在规划时检索复用；
2. 短期缓存（cache/）——最近 N 条任务的执行上下文（中间结果别名、参数偏好、失败教训），
   超过上限按 FIFO 淘汰。

与全局共享的 experience/经验池 相互独立：经验池跨智能体共享领域经验，
agent memory 只属于单个智能体，体现个体差异。
任务检索与经验池一致，走 TF-IDF 向量 + 余弦相似度。
"""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from typing import Any

from config import settings
from retrieval.cosine_similarity import TfidfIndex, cut_relative


class AgentMemory:
    """单个智能体的专属记忆空间（按 agent_id 隔离目录）。

    目录可以是"记忆根目录 + agent_id"（base_dir），
    也可以直接指定该智能体的记忆目录（root_dir，对应 agents_capability.yaml 的 memory_dir）。
    """

    def __init__(self, agent_id: str, base_dir: str | Path | None = None,
                 cache_max: int = 10, root_dir: str | Path | None = None):
        self.agent_id = agent_id
        if root_dir is not None:
            root = Path(root_dir)
        else:
            root = Path(base_dir or settings.AGENT_MEMORY_BASE) / agent_id
        if not root.is_absolute():
            root = settings.BASE_DIR / root
        self.root = root
        self.completed_dir = self.root / "completed"
        self.cache_file = self.root / "cache.json"
        self.cache_max = cache_max
        self.completed_dir.mkdir(parents=True, exist_ok=True)
        # 短期缓存常驻内存，启动时加载
        self.cache: list[dict] = []
        if self.cache_file.exists():
            self.cache = json.loads(self.cache_file.read_text(encoding="utf-8"))

    # ---------- 短期缓存 ----------
    def push_cache(self, entry: dict):
        """记录一条近期任务上下文（子任务问题、步骤别名、失败教训等），FIFO 淘汰。"""
        entry = {**entry, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.cache.append(entry)
        while len(self.cache) > self.cache_max:
            self.cache.pop(0)
        self._save_cache()

    def recent(self, k: int = 3) -> list[dict]:
        """取最近 k 条缓存记录，供规划/执行 prompt 注入。"""
        return self.cache[-k:]

    # ---------- 长期任务记录 ----------
    def record_task(self, question: str, plan: dict | None, result_summary: str,
                    outcome: str, error: str = "") -> str:
        """任务完成后写入一条长期记录（独立文件，便于检索与人工审计）。"""
        tid = uuid.uuid4().hex[:8]
        record = {
            "id": tid,
            "agent_id": self.agent_id,
            "question_feat": question,
            "plan": plan,
            "result_summary": result_summary,
            "outcome": outcome,          # success / failed
            "error": error,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (self.completed_dir / f"{tid}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return tid

    def find_tasks(self, question: str, top_k: int = 2) -> list[dict]:
        """在自己完成过的任务中按余弦相似度检索最相关的记录。"""
        if not question.strip():
            return []
        records: list[dict] = []
        for f in self.completed_dir.glob("*.json"):
            try:
                records.append(json.loads(f.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        if not records:
            return []
        index = TfidfIndex([r.get("question_feat", "") for r in records])
        hits = index.search(question, top_k=top_k, min_score=settings.RETRIEVAL_MIN_SCORE)
        return [records[pos] for _, pos in cut_relative(hits, settings.RETRIEVAL_RELATIVE_CUTOFF)]

    def render_memory(self, question: str) -> str:
        """把专属记忆渲染为注入 prompt 的文本。"""
        lines = [f"【{self.agent_id} 的专属记忆】"]
        recent = self.recent()
        if recent:
            lines.append("近期缓存：")
            for c in recent:
                lines.append(f"  - {c.get('question', '')} → {c.get('note', c.get('outcome', ''))}")
        own = self.find_tasks(question)
        if own:
            lines.append("本人完成过的相似任务：")
            for t in own:
                tag = "成功" if t["outcome"] == "success" else "失败"
                lines.append(f"  - [{tag}] {t['question_feat']}"
                             + (f"（教训：{t['error']}）" if t.get("error") else ""))
        if len(lines) == 1:
            lines.append("暂无相关记忆。")
        return "\n".join(lines)

    def _save_cache(self):
        self.cache_file.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def get_agent_memory(agent_id: str, agents_cfg: dict | None = None) -> AgentMemory:
    """按智能体配置获取其专属记忆空间（memory_dir 即该智能体自己的目录）。"""
    from config import settings
    agents_cfg = agents_cfg or {}
    mem_dir = agents_cfg.get("memory_dir", settings.AGENT_MEMORY_BASE)
    cache_max = agents_cfg.get("cache_max", 10)
    return AgentMemory(agent_id, root_dir=mem_dir, cache_max=cache_max)
