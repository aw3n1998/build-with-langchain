"""
决策点4：检索策略（Retrieval Strategy）
选型结论：混合检索（BM25 关键词 + 向量语义，RRF 融合排序）

=== 面试标准答案 ===

Q: 你们 RAG 的检索策略怎么设计的？

A: 我们用的是混合检索（Hybrid Retrieval），把 BM25 和向量检索的结果
   用 RRF（Reciprocal Rank Fusion）融合在一起。

   为什么不用纯向量？
   工程规范文档里有大量精确术语：GB50205、±10mm、24小时蓄水试验。
   纯向量搜"GB50205"时，模型对 GB50205 和 GB50206 的 embedding
   几乎相同（都是标准编号，语义空间距离极小），检索就会出错。
   BM25 是关键词精确匹配，能弥补这个短板。

Q: RRF 是什么原理？

A: Reciprocal Rank Fusion，倒数排名融合。
   公式：score = Σ 1 / (k + rank_i)，k 一般取 60。

   举例：
   某文档在向量检索里排第2，BM25 里排第5
   向量贡献：1/(60+2) = 0.0161
   BM25 贡献：1/(60+5) = 0.0154
   最终分：0.0161 + 0.0154 = 0.0315

   RRF 的好处：
   1. 不需要归一化两路的分数（两路分数范围完全不同，很难直接加权）
   2. 只用排名，对异常高分不敏感
   3. k=60 是经过大量实验的默认值，不需要调参

Q: BM25 的原理？

A: BM25 是 TF-IDF 的改进版，核心是：
   - TF（词频）：词在文档里出现越多，相关性越高，但有上限（饱和函数）
   - IDF（逆文档频率）：词在整个语料库里越罕见，越有区分度
   - 文档长度归一化：长文档里出现同样次数，比短文档权重低
   结果：罕见的专业词（GB50205）权重高，常见词（的/是）权重低

=== 实现说明 ===

HybridRetriever 类：
1. 持有 MilvusStore（向量检索）和 BM25Retriever（关键词检索）
2. 两路各自检索 top_k * 2 个候选（扩大候选池，融合后再截取 top_k）
3. RRF 融合，按最终分排序，返回 top_k 个 Document

BM25 实现：
   使用 rank_bm25 库，在内存里维护倒排索引
   生产场景可以换成 Elasticsearch 的 BM25（支持持久化和分布式）
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from agent_lab.app.core.logger import get_logger

if TYPE_CHECKING:
    from agent_lab.app.rag.store import MilvusStore

logger = get_logger("rag.retriever")

# RRF 公式中的 k 值（60 是学术界标准默认值）
RRF_K = 60


# ══════════════════════════════════════════════════════════════
# BM25 封装（内存版，适合 <10万 chunk 的场景）
# ══════════════════════════════════════════════════════════════

class BM25Retriever:
    """
    基于 rank_bm25 的关键词检索器。

    工作流程：
    1. build(docs)：对所有 chunk 分词，构建倒排索引
    2. search(query, top_k)：BM25 打分，返回 top_k 个 Document
    """

    def __init__(self):
        self._bm25 = None
        self._docs: list[Document] = []

    def build(self, docs: list[Document]) -> "BM25Retriever":
        """
        用 chunk 文档列表构建 BM25 索引。
        中文按字符切分（每个字一个 token），无需分词器。
        """
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            raise ImportError("请先安装：pip install rank-bm25")

        self._docs = docs
        # 中文直接按字符切分：['施','工','验','收',...]
        # 比按词切分更简单，且对工程术语效果更稳定
        tokenized = [list(doc.page_content) for doc in docs]
        self._bm25 = BM25Okapi(tokenized)
        logger.info("[BM25] 构建索引完成，共 %d 个文档", len(docs))
        return self

    def search(self, query: str, top_k: int = 10) -> list[tuple[Document, float]]:
        """
        BM25 检索，返回 (Document, bm25_score) 列表，按分数降序。
        """
        if self._bm25 is None:
            raise RuntimeError("请先调用 build() 构建索引")

        query_tokens = list(query)
        scores = self._bm25.get_scores(query_tokens)

        # 取 top_k，返回 (doc, score) 对
        ranked = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        return [(self._docs[idx], float(score)) for idx, score in ranked]


# ══════════════════════════════════════════════════════════════
# RRF 融合
# ══════════════════════════════════════════════════════════════

def rrf_fuse(
    ranked_lists: list[list[tuple[str, Document]]],
    top_k: int,
    k: int = RRF_K,
) -> list[Document]:
    """
    Reciprocal Rank Fusion：将多路检索结果融合为一个排序列表。

    Args:
        ranked_lists: 每路检索结果，格式为 [(doc_key, Document), ...]
                      doc_key 用于跨路去重（通常用 content[:50] 作为 key）
        top_k:        最终返回的文档数
        k:            RRF 公式平滑参数，默认 60

    Returns:
        融合后的 Document 列表，每个 Document 的 metadata 含 rrf_score
    """
    score_map: dict[str, float] = defaultdict(float)
    doc_map: dict[str, Document] = {}

    for ranked in ranked_lists:
        for rank, (key, doc) in enumerate(ranked, start=1):
            score_map[key] += 1.0 / (k + rank)
            doc_map[key] = doc  # 后写覆盖，保留最后一路的 metadata

    # 按 RRF 分降序排列
    sorted_keys = sorted(score_map, key=lambda x: score_map[x], reverse=True)[:top_k]

    result = []
    for key in sorted_keys:
        doc = doc_map[key]
        doc.metadata["rrf_score"] = round(score_map[key], 6)
        result.append(doc)

    return result


# ══════════════════════════════════════════════════════════════
# 混合检索器
# ══════════════════════════════════════════════════════════════

class HybridRetriever:
    """
    混合检索器：BM25（关键词）+ Milvus（向量语义）→ RRF 融合。

    典型使用流程：
        retriever = HybridRetriever(store, embedder)
        retriever.build_bm25(all_chunks)
        docs = retriever.search("验收流程是什么？", top_k=5)
    """

    def __init__(
        self,
        store: "MilvusStore",
        top_k_candidate: int = 20,
    ):
        """
        Args:
            store:           已连接的 MilvusStore 实例
            top_k_candidate: 每路检索的候选数（融合前）
                             建议为最终 top_k 的 2-4 倍
        """
        self._store = store
        self._bm25 = BM25Retriever()
        self._top_k_candidate = top_k_candidate

    def build_bm25(self, docs: list[Document]) -> "HybridRetriever":
        """用 chunk 列表构建 BM25 索引，返回 self 支持链式调用。"""
        self._bm25.build(docs)
        return self

    def search(
        self,
        query: str,
        top_k: int = 5,
        project_id: str | None = None,
    ) -> list[Document]:
        """
        执行混合检索，返回融合排序后的 top_k 个 Document。

        Args:
            query:      用户问题
            top_k:      最终返回数量
            project_id: 多租户过滤（透传给 Milvus）

        Returns:
            list[Document]，metadata 含 rrf_score、source、score
        """
        candidate_k = max(self._top_k_candidate, top_k * 3)

        # ── 路1：向量检索 ────────────────────────────────────────
        vec_results = self._store.similarity_search(
            query, top_k=candidate_k, project_id=project_id
        )
        vec_ranked = [
            (_doc_key(doc), doc) for doc in vec_results
        ]

        # ── 路2：BM25 关键词检索 ─────────────────────────────────
        bm25_results = self._bm25.search(query, top_k=candidate_k)
        bm25_ranked = [
            (_doc_key(doc), doc) for doc, _ in bm25_results
        ]

        # ── RRF 融合 ─────────────────────────────────────────────
        fused = rrf_fuse([vec_ranked, bm25_ranked], top_k=top_k)

        logger.info(
            "[Retriever] 混合检索 query='%s' → 向量 %d 条 + BM25 %d 条 → 融合后 %d 条",
            query[:30], len(vec_results), len(bm25_results), len(fused),
        )
        return fused

    def search_vector_only(
        self,
        query: str,
        top_k: int = 5,
        project_id: str | None = None,
    ) -> list[Document]:
        """仅向量检索，用于对比实验。"""
        return self._store.similarity_search(query, top_k=top_k, project_id=project_id)

    def search_bm25_only(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[Document]:
        """仅 BM25 检索，用于对比实验。"""
        return [doc for doc, _ in self._bm25.search(query, top_k=top_k)]


def _doc_key(doc: Document) -> str:
    """用 content 前80字符作为文档去重 key。"""
    return doc.page_content[:80]
