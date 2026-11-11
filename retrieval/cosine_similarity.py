"""统一的文本相似度：TF-IDF 向量 + 余弦相似度。

本项目所有"知识 / 经验"检索（表结构、skill、共享经验池、智能体专属记忆）
都必须走这里，保证同一套度量：

    text --tokenize--> 词项 --*idf--> 稀疏向量 --L2 归一化--> 向量
    相似度 = 两个单位向量的点积（即余弦相似度）

中文按"单字 + 相邻二字"切分（不依赖分词库），英文/数字按单词切分。
后续若要接真实 embedding 模型，只需替换本模块的向量化实现，
各检索模块的调用方式不变。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable, Sequence

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-z0-9_]+")

# 高频虚词/疑问词，作为停用词剔除，避免"的/是/请"这类字把无关文本拉高分
_STOP_CHARS = set(
    "的了和与及或是在有对按并把被从到为以就都而及其这那些什么如何怎样怎么"
    "请帮我要们你他她它个中上下里外前后左右我你"
)

DEFAULT_MIN_SCORE = 0.0


def tokenize(text: str) -> list[str]:
    """中文单字 + 相邻二字 + 英文/数字词，去掉停用字。"""
    text = (text or "").lower()
    tokens: list[str] = [w for w in _WORD.findall(text) if w not in _STOP_CHARS]
    for run in _CJK_RUN.findall(text):
        chars = [c for c in run if c not in _STOP_CHARS]
        tokens.extend(chars)
        tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
    return tokens


def _l2_normalize(vec: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm <= 0:
        return {}
    return {k: v / norm for k, v in vec.items()}


def cosine(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """两个稀疏向量的余弦相似度（输入需已归一化，点积即余弦）。"""
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    return sum(w * vec_b.get(t, 0.0) for t, w in vec_a.items())


class TfidfIndex:
    """一段小语料的 TF-IDF 索引，支持余弦检索。

    用法：
        idx = TfidfIndex([doc1, doc2, ...])
        for score, doc_pos in idx.search("查询文本", top_k=3):
            ...
    """

    def __init__(self, docs: Sequence[str]):
        self.docs: list[str] = [d or "" for d in docs]
        self._counts: list[Counter[str]] = [Counter(tokenize(d)) for d in self.docs]

        df: Counter[str] = Counter()
        for counts in self._counts:
            df.update(counts.keys())
        n = max(len(self.docs), 1)
        self.idf: dict[str, float] = {
            t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()
        }
        self._vectors: list[dict[str, float]] = [
            self._vectorize(counts) for counts in self._counts
        ]

    # ------------------------------------------------------------ 内部
    def _vectorize(self, counts: Counter[str]) -> dict[str, float]:
        vec = {
            t: (1.0 + math.log(c)) * self.idf.get(t, 0.0)
            for t, c in counts.items()
            if c > 0
        }
        return _l2_normalize(vec)

    def query_vector(self, text: str) -> dict[str, float]:
        """把查询文本映射到**同一** IDF 空间（语料外的词 idf 记为 0，直接忽略）。"""
        return self._vectorize(Counter(tokenize(text)))

    # ------------------------------------------------------------ 检索
    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> list[tuple[float, int]]:
        """返回 [(余弦相似度, 文档下标)]，按相似度降序。"""
        qv = self.query_vector(query)
        if not qv:
            return []
        scored: list[tuple[float, int]] = []
        for pos, dv in enumerate(self._vectors):
            s = cosine(qv, dv)
            if s > 0 and s >= min_score:
                scored.append((s, pos))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[: max(1, top_k)]

    def best(self, query: str, min_score: float = DEFAULT_MIN_SCORE) -> tuple[float, int] | None:
        hits = self.search(query, top_k=1, min_score=min_score)
        return hits[0] if hits else None


def similarity(text_a: str, text_b: str) -> float:
    """两条文本之间的余弦相似度（以二者为语料临时建索引）。"""
    idx = TfidfIndex([text_a, text_b])
    hit = idx.search(text_a, top_k=1)
    return hit[0][0] if hit and hit[0][1] == 1 else 0.0


def rank(
    query: str,
    documents: Iterable[tuple[Any, str]],
    top_k: int = 3,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[tuple[float, Any]]:
    """通用检索：documents 为 [(payload, text)]，返回 [(余弦相似度, payload)]。"""
    items = list(documents)
    if not items:
        return []
    idx = TfidfIndex([text for _, text in items])
    return [(score, items[pos][0]) for score, pos in idx.search(query, top_k, min_score)]


def cut_relative(hits, ratio: float = 0.4, keep_min: int = 1):
    """相对截断：只保留相似度 >= 最高分 × ratio 的命中。

    top-k 检索在高相关结果很少时，会把相似度极低的条目也一并返回；
    这里按"相对最高分"再筛一次，保证注入的是同一量级的相关内容。
    """
    hits = list(hits)
    if not hits:
        return []
    cutoff = hits[0][0] * max(0.0, float(ratio))
    kept = [h for h in hits if h[0] >= cutoff]
    return kept if len(kept) >= keep_min else hits[:keep_min]
