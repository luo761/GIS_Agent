"""经验池存储：增 / 查 / 更新 / 容量淘汰。

经验条目结构：
{
  "id": "...",
  "task_signature": "任务类型签名（领域+任务模式）",
  "question_feat": "问题特征摘要",
  "plan": {计划表/DAG},
  "trace": [执行轨迹摘要],
  "outcome": "success" | "error",
  "error_lesson": "失败经验中总结的避免措施",
  "hits": 3,            # 命中次数（用于淘汰）
  "updated_at": "..."
}

写入策略（阶段⑤调用）：
- 余弦相似度 > 阈值 的同类任务 → 只更新对应条目
- 无同类 → 新写入
- 超过容量上限 → 淘汰 hits 最低、最久未更新的经验

检索（阶段③调用）：
- 用问题文本与每条经验的"签名 + 问题特征 + 失败教训"做 TF-IDF 向量，
  按余弦相似度排序取 top-k（`retrieval/cosine_similarity.py`）。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from config import settings
from retrieval.cosine_similarity import TfidfIndex, cut_relative


class ExperiencePool:
    def __init__(self, path: Path | None = None, max_size: int | None = None):
        self.path = Path(path or settings.EXPERIENCE_PATH)
        self.max_size = max_size or settings.EXPERIENCE_MAX_SIZE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.items: list[dict] = []
        if self.path.exists():
            try:
                self.items = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.items = []

    # ---------- 检索 ----------
    @staticmethod
    def _doc(item: dict) -> str:
        return " ".join([
            item.get("task_signature", ""),
            item.get("question_feat", ""),
            item.get("error_lesson", ""),
        ])

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        """按余弦相似度检索最相关的 top_k 条经验。"""
        top_k = top_k or settings.EXPERIENCE_TOP_K
        if not self.items or not query.strip():
            return []
        index = TfidfIndex([self._doc(i) for i in self.items])
        hits = index.search(query, top_k=top_k, min_score=settings.RETRIEVAL_MIN_SCORE)
        return [self.items[pos] for _, pos in cut_relative(hits, settings.RETRIEVAL_RELATIVE_CUTOFF)]

    def find_similar(self, signature: str, threshold: float | None = None) -> dict | None:
        """找同类任务（余弦相似度 > 阈值），用于决定更新而非新增。"""
        threshold = settings.EXPERIENCE_SIMILAR_THRESHOLD if threshold is None else threshold
        if not self.items:
            return None
        index = TfidfIndex([i.get("task_signature", "") for i in self.items])
        hit = index.best(signature, min_score=threshold)
        return self.items[hit[1]] if hit else None

    # ---------- 写入 ----------
    def write(self, entry: dict) -> str:
        """写入或更新一条经验（阶段⑤调用）。"""
        sig = entry.get("task_signature", "")
        similar = self.find_similar(sig)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if similar:  # 同类任务：更新
            similar.update(entry, updated_at=now, hits=similar.get("hits", 0) + 1)
            eid = similar["id"]
        else:        # 新经验：写入并淘汰
            entry.setdefault("id", uuid.uuid4().hex[:8])
            entry.setdefault("hits", 0)
            entry["updated_at"] = now
            self.items.append(entry)
            self._prune()
            eid = entry["id"]
        self._save()
        return eid

    def record_hit(self, entry_id: str):
        for item in self.items:
            if item.get("id") == entry_id:
                item["hits"] = item.get("hits", 0) + 1
        self._save()

    # ---------- 内部 ----------
    def _prune(self):
        while len(self.items) > self.max_size:
            victim = min(self.items, key=lambda x: (x.get("hits", 0), x.get("updated_at", "")))
            self.items.remove(victim)

    def _save(self):
        self.path.write_text(
            json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
