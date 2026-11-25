"""智能体专属记忆空间。

每个智能体有独立目录，包含两部分：
1. 长期任务记录（record/*.json）：完整任务案例，只收结果明确（success/failed）
   或显式确认（uncertain + confirmed）的案例；超过 AGENT_MEMORY_RECORD_MAX 按 mtime FIFO 淘汰。
2. 短期步骤缓存（cache.json）：子步骤问题、结果别名、参数偏好、单步教训等碎片，
   超过 AGENT_MEMORY_CACHE_MAX 时在加入瞬间弹出最旧；完整案例绝不进缓存。

与共享经验池相互独立；任务检索走 TF-IDF + 余弦相似度。
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

    目录由 root_dir 指定（对应 agents_capability.yaml 的 memory_dir）；
    未指定时回落到 ``settings.AGENT_MEMORY_BASE/<agent_id>``。
    容量参数默认取自 settings：
    - AGENT_MEMORY_CACHE_MAX：短期缓存条数上限
    - AGENT_MEMORY_RECORD_MAX：长期记录容量上限
    - AGENT_MEMORY_CACHE_TOP_K：注入 prompt 的最近缓存条数
    - AGENT_MEMORY_RECORD_TOP_K：相似任务检索返回的最大记录数
    """

    def __init__(self, agent_id: str, root_dir: str | Path | None = None,
                 cache_max: int | None = None, record_max: int | None = None):
        self.agent_id = agent_id
        root = Path(root_dir) if root_dir is not None else settings.AGENT_MEMORY_BASE / agent_id
        self.root = root if root.is_absolute() else settings.BASE_DIR / root
        self.record_dir = self.root / "record"
        self.cache_file = self.root / "cache.json"
        self.cache_max = settings.AGENT_MEMORY_CACHE_MAX if cache_max is None else cache_max
        self.record_max = settings.AGENT_MEMORY_RECORD_MAX if record_max is None else record_max
        self.record_dir.mkdir(parents=True, exist_ok=True)

        # 缓存常驻内存；文件损坏时按空缓存处理，不阻断任务
        self.cache: list[dict] = []
        if self.cache_file.exists():
            try:
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                self.cache = [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
            except (OSError, json.JSONDecodeError):
                self.cache = []

    def cache_step(self, step_question: str, note: str = "",
                   step_alias: str = "", params: dict | None = None,
                   lesson: str = "", **extra: Any) -> dict:
        """追加一条步骤级缓存并落盘。

        加入时检测容量：超过 cache_max 立即从最旧开始弹出（FIFO）。
        读取最近缓存直接用 ``self.cache[-AGENT_MEMORY_CACHE_TOP_K:]``。
        ``**extra`` 可携带任意步骤字段（如 outcome/plan）。
        """
        entry: dict[str, Any] = {
            "step_question": step_question,
            "step_alias": step_alias,          # 中间结果别名，供后续步骤引用
            "params": params or {},            # 该步骤的参数偏好
            "note": note,
            "lesson": lesson,                  # 单步失败教训
            **extra,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.cache.append(entry)
        if self.cache_max <= 0:
            self.cache.clear()
        elif len(self.cache) > self.cache_max:
            del self.cache[: len(self.cache) - self.cache_max]
        self.cache_file.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return entry

    def record_task(self, question: str, plan: dict | None, result_summary: str,
                    outcome: str, error: str = "", confirmed: bool = False) -> str | None:
        """写入一条长期任务记录并立即按容量淘汰；返回记录 id 或 None。

        :param outcome: success / failed / uncertain（其他值抛 ValueError）
        :param confirmed: only for uncertain；True 才归档，否则返回 None
        容量淘汰：超过 record_max 时按文件 mtime 从旧到新删除（FIFO）。
        """
        if outcome not in ("success", "failed", "uncertain"):
            raise ValueError("outcome 只能是 success / failed / uncertain")
        if outcome == "uncertain" and not confirmed:
            return None
        if self.record_max <= 0:
            return None

        tid = uuid.uuid4().hex[:8]
        record = {
            "id": tid,
            "agent_id": self.agent_id,
            "question_feat": question,
            "plan": plan,
            "result_summary": result_summary,
            "outcome": outcome,
            "error": error,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (self.record_dir / f"{tid}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        files = sorted(self.record_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
        for old in files[: max(0, len(files) - self.record_max)]:
            old.unlink(missing_ok=True)
        return tid

    def find_tasks(self, question: str, top_k: int | None = None,
                   outcome_filter: str | None = None) -> list[dict]:
        """在自己完成过的任务中按余弦相似度检索；top_k 默认 settings.AGENT_MEMORY_RECORD_TOP_K。"""
        if not question.strip():
            return []
        if top_k is None:
            top_k = settings.AGENT_MEMORY_RECORD_TOP_K
        records: list[dict] = []
        for path in self.record_dir.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if outcome_filter and record.get("outcome") != outcome_filter:
                continue
            records.append(record)
        if not records:
            return []
        index = TfidfIndex([record.get("question_feat", "") for record in records])
        hits = index.search(question, top_k=top_k, min_score=settings.RETRIEVAL_MIN_SCORE)
        return [records[pos] for _, pos in cut_relative(hits, settings.RETRIEVAL_RELATIVE_CUTOFF)]

    def render_memory(self, question: str) -> str:
        """把专属记忆渲染为注入 prompt 的文本。"""
        lines = [f"【{self.agent_id} 的专属记忆】"]
        top_k = max(0, int(settings.AGENT_MEMORY_CACHE_TOP_K))
        recent = self.cache[-top_k:] if top_k else []
        if recent:
            lines.append("近期步骤缓存：")
            for entry in recent:
                head = entry.get("step_question", "")
                alias = f"（别名：{entry['step_alias']}）" if entry.get("step_alias") else ""
                tail = entry.get("note") or entry.get("lesson") or ""
                lines.append(f"  - {head}{alias} → {tail}".rstrip(" →"))
        own = self.find_tasks(question, outcome_filter="success") or self.find_tasks(question)
        if own:
            lines.append("本人完成过的相似任务：")
            for task in own:
                tag = {"success": "成功", "failed": "失败",
                       "uncertain": "已确认的存疑"}.get(task.get("outcome"), task.get("outcome", ""))
                lines.append(f"  - [{tag}] {task['question_feat']}"
                             + (f"（教训：{task['error']}）" if task.get("error") else ""))
        if len(lines) == 1:
            lines.append("暂无相关记忆。")
        return "\n".join(lines)
