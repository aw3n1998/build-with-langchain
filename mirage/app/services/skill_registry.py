import numpy as np
import faiss
from langchain_core.tools import BaseTool
from langchain_core.embeddings import Embeddings
from mirage.app.core.logger import get_logger

logger = get_logger("skill_registry")


class SkillRegistry:
    """
    工具语义检索中心。

    原理（和 RAG 完全一样，只是把"文档"换成了"工具描述"）：
      注册阶段：工具 description → embedding → 存入 FAISS 索引
      检索阶段：用户问题   → embedding → 向量相似度搜索 → 返回 Top-K 工具

    这样不管注册了多少工具，每次 LLM 上下文里只出现最相关的 K 个，
    避免 token 浪费和注意力稀释。

    Embedder 可以是任意实现了 Embeddings 接口的对象，例如：
      - FastEmbedEmbeddings（本地模型，无需 API）← 当前使用
      - OpenAIEmbeddings（需要 OpenAI/兼容 API）
    """

    def __init__(self, embedder: Embeddings) -> None:
        self._embedder = embedder
        self._tools: dict[str, BaseTool] = {}  # name → tool 对象
        self._names: list[str] = []             # 与 FAISS 索引行对齐的名称列表
        self._index: faiss.IndexFlatIP | None = None

    def _build_index(self, vecs: np.ndarray, tools: list[BaseTool]) -> None:
        """内部方法：把向量加入 FAISS 索引，更新名称和工具映射。"""
        faiss.normalize_L2(vecs)  # L2 归一化后做内积 = 余弦相似度
        if self._index is None:
            self._index = faiss.IndexFlatIP(vecs.shape[1])
        self._index.add(vecs)
        for t in tools:
            self._tools[t.name] = t
            self._names.append(t.name)
        logger.info("[SkillRegistry] 注册完成，共 %d 个工具: %s",
                    len(self._names), self._names)

    def register(self, tools: list[BaseTool]) -> None:
        """同步注册（适合本地 embedding 模型）。在服务启动时调用一次。"""
        if not tools:
            return
        texts = [f"{t.name}: {t.description}" for t in tools]
        vecs = np.array(self._embedder.embed_documents(texts), dtype=np.float32)
        self._build_index(vecs, tools)

    async def aregister(self, tools: list[BaseTool]) -> None:
        """异步注册（适合远程 API embedding）。在 async 上下文的启动时调用一次。"""
        if not tools:
            return
        texts = [f"{t.name}: {t.description}" for t in tools]
        vecs = np.array(
            await self._embedder.aembed_documents(texts), dtype=np.float32
        )
        self._build_index(vecs, tools)

    def get(self, name: str) -> BaseTool:
        return self._tools[name]

    @property
    def all_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    async def search(self, query: str, top_k: int = 3) -> list[BaseTool]:
        """
        语义检索：返回与 query 最相关的 top_k 个工具。
        若索引为空（工具数为 0），返回空列表。
        """
        if self._index is None or not self._names:
            return []

        k = min(top_k, len(self._names))
        vec = np.array(
            await self._embedder.aembed_query(query), dtype=np.float32
        ).reshape(1, -1)
        faiss.normalize_L2(vec)

        scores, indices = self._index.search(vec, k)
        results = [
            self._tools[self._names[i]]
            for i in indices[0]
            if 0 <= i < len(self._names)
        ]

        logger.info("[SkillRegistry] 查询: '%.30s' → 检索到: %s | 相似度: %s",
                    query,
                    [t.name for t in results],
                    [f"{s:.3f}" for s in scores[0]])
        return results
