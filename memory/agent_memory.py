"""智能体专属记忆空间。

多智能体能力差异的来源之一：即使底层是同一个 LLM，
每个智能体拥有独立的记忆空间，包含两部分：
1. 长期任务记录（completed/）——自己完成过的完整任务案例（问题特征、计划、结果摘要、成败），
   容量上限由 settings.AGENT_MEMORY_RECORD_MAX 统一管理，超限按 FIFO 淘汰最旧。
   只收录结果明确（success/failed）或已被确认的记录；
   结果不确定的任务默认不归档——执行期间的单步碎片会自然留在缓存里，完整案例绝不进缓存。
2. 短期缓存（cache.json）——最近 settings.AGENT_MEMORY_CACHE_MAX 条步骤级执行上下文
   （子步骤问题、中间结果别名、参数偏好、单步教训），超过上限按 FIFO 淘汰。
   缓存只存小步骤，不存完整案例。

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
    容量参数默认全部取自全局配置 settings：
    - AGENT_MEMORY_CACHE_MAX：短期步骤缓存条数上限
    - AGENT_MEMORY_RECORD_MAX：长期任务记录容量上限
    - AGENT_MEMORY_CACEH_TOP_K：注入 prompt 的最近缓存条数
    - AGENT_MEMORY_RECORD_TOP_K：相似任务检索返回的最大记录数
    """

    def __init__(self, agent_id: str, base_dir: str | Path | None = None,
                 cache_max: int | None = None, record_max: int | None = None,
                 root_dir: str | Path | None = None):
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
        # 容量上限：未显式传入时一律读全局配置，本文件不出现魔法数字
        self.cache_max = settings.AGENT_MEMORY_CACHE_MAX if cache_max is None else cache_max
        self.record_max = settings.AGENT_MEMORY_RECORD_MAX if record_max is None else record_max
        self.completed_dir.mkdir(parents=True, exist_ok=True)
        # 短期缓存常驻内存，启动时加载
        self.cache: list[dict] = []
        if self.cache_file.exists():
            self.cache = json.loads(self.cache_file.read_text(encoding="utf-8"))

    # ---------- 短期缓存：只存步骤级碎片，FIFO 淘汰 ----------
    def push_step(self, step_question: str = "", note: str = "",
                  step_alias: str = "", params: dict | None = None,
                  lesson: str = "", **extra: Any) -> None:
        """记录一条步骤级执行上下文（子步骤问题、结果别名、参数偏好、单步教训）。

        只承载执行过程中的碎片信息；完整任务案例只能通过 record_task() 归档，
        绝不进缓存。所有字段均为可选，按需传入，透传的 **extra 可携带任意自定义字段。
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
        while len(self.cache) > self.cache_max:
            self.cache.pop(0)
        self._save_cache()

    def recent(self, k: int | None = None) -> list[dict]:
        """取最近 k 条缓存记录，供规划/执行 prompt 注入。

        k 未指定时取全局配置 settings.AGENT_MEMORY_CACEH_TOP_K。
        """
        if k is None:
            k = settings.AGENT_MEMORY_CACEH_TOP_K
        return self.cache[-k:]

    # ---------- 长期任务记录：有上限，只收结果明确或已确认的案例 ----------
    def record_task(self, question: str, plan: dict | None, result_summary: str,
                    outcome: str, error: str = "",
                    confirmed: bool = False) -> str | None:
        """任务结束后尝试写入长期记录；返回记录 id，不归档时返回 None。

        :param outcome: success / failed / uncertain
        :param confirmed: 归档开关（默认 False）。
            - outcome 为 success/failed：结果明确，无论开关如何都归档；
            - outcome 为 uncertain：只有显式 confirmed=True（人工/复核确认通过）
              才归档，否则直接 return None——不确定的结论不进长期记录。
        未归档时不会往缓存写任何"完整案例"：执行期间的单步碎片
        已经通过 push_step 留在缓存里，会随 FIFO 自然淘汰。
        """
        if outcome not in ("success", "failed") and not confirmed:
            return None

        tid = uuid.uuid4().hex[:8]
        record = {
            "id": tid,
            "agent_id": self.agent_id,
            "question_feat": question,
            "plan": plan,
            "result_summary": result_summary,
            "outcome": outcome,          # success / failed / uncertain(已确认)
            "error": error,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (self.completed_dir / f"{tid}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._evict_completed()
        return tid

    def _evict_completed(self):
        """长期记录超上限（settings.AGENT_MEMORY_RECORD_MAX）时，
        按文件修改时间从旧到新淘汰（FIFO）。"""
        files = sorted(self.completed_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
        overflow = len(files) - self.record_max
        for f in files[:max(0, overflow)]:
            f.unlink()

    def find_tasks(self, question: str, top_k: int | None = None,
                   outcome_filter: str | None = None) -> list[dict]:
        """在自己完成过的任务中按余弦相似度检索最相关的记录。

        top_k 未指定时取全局配置 settings.AGENT_MEMORY_RECORD_TOP_K。

        :param outcome_filter: 可选，只检索指定结局的记录（如 "success"），
                               默认不过滤——失败记录同样有价值（含教训）。
        """
        if not question.strip():
            return []
        if top_k is None:
            top_k = settings.AGENT_MEMORY_RECORD_TOP_K
        records: list[dict] = []
        for f in self.completed_dir.glob("*.json"):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if outcome_filter and r.get("outcome") != outcome_filter:
                continue
            records.append(r)
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
            lines.append("近期步骤缓存：")
            for c in recent:
                head = c.get("step_question", "")
                alias = f"（别名：{c['step_alias']}）" if c.get("step_alias") else ""
                tail = c.get("note") or c.get("lesson") or ""
                lines.append(f"  - {head}{alias} → {tail}".rstrip(" →"))
        # 相似任务检索优先命中成功案例；若无成功案例再放宽到全部记录
        own = self.find_tasks(question, outcome_filter="success") \
            or self.find_tasks(question)
        if own:
            lines.append("本人完成过的相似任务：")
            for t in own:
                tag = {"success": "成功", "failed": "失败",
                       "uncertain": "已确认的存疑"}.get(t.get("outcome"), t.get("outcome", ""))
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
    """按智能体配置获取其专属记忆空间（memory_dir 即该智能体自己的目录）。

    容量参数不在此处写死：未在 agents_capability.yaml 中针对该智能体
    单独覆盖时，直接沿用全局配置 settings 中的默认值。
    """
    if agents_cfg is None:
        agents_cfg = {}
    mem_dir = agents_cfg.get("memory_dir", settings.AGENT_MEMORY_BASE)
    return AgentMemory(
        agent_id,
        root_dir=mem_dir,
        cache_max=agents_cfg.get("cache_max"),      # None → 构造函数内回落到 settings
        record_max=agents_cfg.get("record_max"),    # None → 构造函数内回落到 settings
    )