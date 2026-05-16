"""
RAG Pipeline —— 单例，负责管理整个 RAG 生命周期。

职责：
  1. 持有 MilvusStore + HybridRetriever（BM25 + 向量）
  2. ingest()：文档 → 分片 → Embed → 写入 Milvus + 重建 BM25
  3. search()：混合检索，返回格式化字符串（供 LLM 直接阅读）
  4. 启动时自动从 Milvus 加载历史 chunk，重建 BM25（防止重启丢索引）

为什么是单例？
  BM25 索引存在内存，Agent 每次调用工具共享同一份索引。
  Milvus 连接也应该复用，避免每次工具调用都重建连接。
"""

from __future__ import annotations

from langchain_core.documents import Document
from agent_lab.app.core.logger import get_logger

logger = get_logger("rag.pipeline")

_DEFAULT_COLLECTION = "rag_chunks"
_DEFAULT_PROJECT = "default"


class RAGPipeline:
    """
    RAG 全链路管理器。

    典型用法（ai_service.py 里初始化一次）：
        pipeline = RAGPipeline(embedder)
        await pipeline.connect()          # 连接 Milvus，重建 BM25
        await pipeline.ingest("xxx.pdf")  # 导入文档
        result = pipeline.search("问题") # 检索
    """

    def __init__(self, embedder, collection_name: str = _DEFAULT_COLLECTION):
        self._embedder = embedder
        self._collection_name = collection_name
        self._store = None      # MilvusStore，连接后赋值
        self._retriever = None  # HybridRetriever，连接后赋值
        self._connected = False
        self._chunks_cache: list[Document] = []  # 内存缓存，用于 BM25 重建

    # ── 连接 ─────────────────────────────────────────────────────

    def connect(self, host: str = "localhost", port: int = 19530) -> bool:
        """
        连接 Milvus，从已有数据重建 BM25 索引。
        返回 True 表示连接成功，False 表示 Milvus 不可用（降级为仅 BM25）。
        """
        from agent_lab.app.rag.store import MilvusStore
        from agent_lab.app.rag.retriever import HybridRetriever

        try:
            self._store = MilvusStore(
                embedder=self._embedder,
                collection_name=self._collection_name,
                host=host,
                port=port,
            ).connect()
            self._retriever = HybridRetriever(self._store)
            self._connected = True
            logger.info("[Pipeline] Milvus 连接成功")

            # 从 Milvus 加载历史 chunk，重建 BM25
            self._rebuild_bm25_from_milvus()
            return True

        except Exception as e:
            logger.warning("[Pipeline] Milvus 不可用，RAG 工具将返回提示信息：%s", e)
            self._connected = False
            return False

    def _rebuild_bm25_from_milvus(self):
        """从 Milvus 查询全部 chunk，重建内存 BM25 索引。"""
        if not self._connected or self._store is None:
            return
        try:
            # 查询已存储的所有 chunk（content 字段）
            results = self._store._collection.query(
                expr="chunk_index >= 0",
                output_fields=["content", "source", "project_id", "chunk_index"],
                limit=50000,  # 生产场景可以分页
            )
            if not results:
                logger.info("[Pipeline] Milvus 中暂无历史数据，BM25 索引为空")
                return

            self._chunks_cache = [
                Document(
                    page_content=r["content"],
                    metadata={
                        "source":      r["source"],
                        "project_id":  r["project_id"],
                        "chunk_index": r["chunk_index"],
                    },
                )
                for r in results
            ]
            self._retriever.build_bm25(self._chunks_cache)
            logger.info("[Pipeline] BM25 重建完成，共 %d 个 chunk", len(self._chunks_cache))
        except Exception as e:
            logger.warning("[Pipeline] BM25 重建失败（不影响向量检索）：%s", e)

    # ── 导入文档 ─────────────────────────────────────────────────

    def ingest(
        self,
        file_path: str,
        project_id: str = _DEFAULT_PROJECT,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
    ) -> str:
        """
        导入文档到 RAG 系统。

        流程：load → chunk → embed → 写入 Milvus → 追加到 BM25 索引

        Args:
            file_path:    文件路径（支持 .txt / .pdf / .docx）
            project_id:   项目 ID，用于多租户检索过滤
            chunk_size:   分片大小（字符数）
            chunk_overlap: 分片重叠（字符数）

        Returns:
            操作结果描述字符串
        """
        if not self._connected:
            return "❌ Milvus 未连接，请先启动 Milvus（docker compose up -d）"

        from agent_lab.app.rag.loader import load_file
        from agent_lab.app.rag.chunker import split_documents

        try:
            docs = load_file(file_path)
            chunks = split_documents(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

            n = self._store.add_documents(chunks, project_id=project_id)

            # 追加到 BM25 缓存并重建索引
            self._chunks_cache.extend(chunks)
            self._retriever.build_bm25(self._chunks_cache)

            return (
                f"✅ 导入成功：{file_path}\n"
                f"   生成 {n} 个 chunk，project_id={project_id}"
            )
        except Exception as e:
            logger.exception("[Pipeline] ingest 失败")
            return f"❌ 导入失败：{e}"

    def ingest_text(
        self,
        text: str,
        source_name: str = "inline",
        project_id: str = _DEFAULT_PROJECT,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
    ) -> str:
        """
        直接导入纯文本（不需要文件），方便测试和 API 调用。
        """
        if not self._connected:
            return "❌ Milvus 未连接"

        from agent_lab.app.rag.chunker import split_documents

        doc = Document(
            page_content=text,
            metadata={"source": source_name, "file_type": "text"},
        )
        chunks = split_documents([doc], chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        n = self._store.add_documents(chunks, project_id=project_id)

        self._chunks_cache.extend(chunks)
        self._retriever.build_bm25(self._chunks_cache)

        return f"✅ 文本导入成功，生成 {n} 个 chunk，project_id={project_id}"

    # ── 检索 ─────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        project_id: str | None = None,
    ) -> str:
        """
        混合检索，返回格式化字符串供 LLM 阅读。

        格式：
            【知识库检索结果】
            [1] 来源：xxx.txt
                防水层施工须进行蓄水试验，蓄水时间不少于24小时...
            [2] ...
        """
        if not self._connected:
            return (
                "【知识库不可用】Milvus 未连接，无法检索知识库。\n"
                "请启动 Milvus：docker compose up -d"
            )

        try:
            docs = self._retriever.search(query, top_k=top_k, project_id=project_id)

            if not docs:
                return f"【知识库检索结果】未找到与「{query}」相关的内容。"

            lines = ["【知识库检索结果】"]
            for i, doc in enumerate(docs, 1):
                source = doc.metadata.get("source", "未知来源")
                score = doc.metadata.get("rrf_score", "?")
                lines.append(f"\n[{i}] 来源：{source}（相关度 {score}）")
                lines.append(f"    {doc.page_content}")

            return "\n".join(lines)

        except Exception as e:
            logger.exception("[Pipeline] search 失败")
            return f"【知识库检索失败】{e}"

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def chunk_count(self) -> int:
        return len(self._chunks_cache)


# ── 全局单例（ai_service.py 和 rag_tools.py 共享） ────────────────
# 在 ai_service 里调用 rag_pipeline.connect() 完成初始化
rag_pipeline: RAGPipeline | None = None


def init_pipeline(embedder, collection_name: str = _DEFAULT_COLLECTION) -> RAGPipeline:
    """初始化全局 pipeline 单例，由 ai_service 在启动时调用一次。"""
    global rag_pipeline
    rag_pipeline = RAGPipeline(embedder, collection_name)
    return rag_pipeline


def get_pipeline() -> RAGPipeline | None:
    """获取全局 pipeline，工具函数通过此接口访问。"""
    return rag_pipeline
