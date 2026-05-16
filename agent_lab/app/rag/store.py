"""
决策点3：向量数据库（Vector Store）
选型结论：Milvus（分布式向量数据库）

=== 面试标准答案 ===

Q: 你们 RAG 用的什么向量库？为什么选 Milvus 不选 FAISS 或 ChromaDB？

A: 我们用的是 Milvus。
   选型对比如下：

   FAISS（Meta）：
   优点：速度极快，纯内存，适合离线批处理
   缺点：没有持久化，不支持 CRUD（删除/更新困难），不支持多租户
   适用：单机科研/离线任务，不适合生产 SaaS 系统

   ChromaDB：
   优点：安装简单（pip install），API 友好，适合原型验证
   缺点：单机，数据量大（>100万）性能下降明显，功能简单
   适用：个人项目/Demo，不适合多租户企业级系统

   Milvus：
   优点：分布式部署，支持十亿级向量，HNSW 索引检索快，
         支持多 Collection（多租户），支持 CRUD，
         支持标量过滤（结合 project_id、file_type 等元数据过滤）
   缺点：需要 Docker 部署，运维成本更高
   适用：生产级 SaaS 系统 ✅

   我们的工程 SaaS 有多个项目（多租户），文档量级预估50-200万条，
   需要按项目 ID 过滤检索，所以选 Milvus。

Q: Milvus 的索引类型怎么选？

A: 我们用 HNSW（Hierarchical Navigable Small World）。
   - HNSW 是图索引，检索准确率最高（Recall > 99%），速度比暴力搜索快100倍以上
   - 参数：M=16（连接数，越大越准但内存越多），ef_construction=200（构建时搜索范围）
   - 查询时设 ef=50，准确率和速度的最佳平衡点
   - 备选 IVF_FLAT：适合数据量特别大（>千万）且内存受限的场景

Q: Collection 的 Schema 怎么设计的？

A: 字段设计：
   - id：主键，VARCHAR，存 chunk 的 UUID
   - embedding：FLOAT_VECTOR，维度 512（对应 BGE-small 输出维度）
   - content：VARCHAR(65535)，chunk 原文
   - source：VARCHAR(256)，来源文件名
   - project_id：VARCHAR(64)，项目 ID（用于多租户过滤）
   - chunk_index：INT64，chunk 在文档中的序号（方便溯源）

=== 参数选择逻辑 ===

embedding 维度：
   BGE-small-zh-v1.5 输出 512 维，需要和 Collection Schema 对齐
   建议在 Schema 中硬编码，避免维度不匹配导致的运行时错误

HNSW 参数：
   M=16：每个节点的双向连接数，16 是工程默认值
         增大 M → 更高 Recall，但内存占用线性增加
   ef_construction=200：建图时搜索范围，越大越准但建图越慢
   ef=50：查询时搜索范围，一般设为 top_k 的 2-4 倍
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from agent_lab.app.core.logger import get_logger

logger = get_logger("rag.store")

# ── Milvus 连接默认值 ────────────────────────────────────────────
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 19530
DEFAULT_COLLECTION = "rag_chunks"
EMBEDDING_DIM = 512          # BGE-small-zh-v1.5 输出维度
HNSW_M = 16                  # HNSW 连接数（越大越准但更耗内存）
HNSW_EF_CONSTRUCTION = 200   # 建图时搜索范围
HNSW_EF = 50                 # 查询时搜索范围（一般为 top_k 的 2-4 倍）


def _get_milvus():
    """延迟导入 pymilvus，避免未安装时影响整个 RAG 模块加载。"""
    try:
        from pymilvus import (
            connections,
            Collection,
            CollectionSchema,
            FieldSchema,
            DataType,
            utility,
        )
        return connections, Collection, CollectionSchema, FieldSchema, DataType, utility
    except ImportError:
        raise ImportError(
            "请先安装 Milvus 客户端：pip install pymilvus\n"
            "并启动 Milvus 服务：docker compose up -d（见项目根目录 docker-compose.yml）"
        )


class MilvusStore:
    """
    Milvus 向量库封装。

    职责：
    1. 连接 Milvus，创建/复用 Collection
    2. 将 chunk 文本 embed 后写入 Milvus
    3. 提供相似度检索接口，返回 LangChain Document 对象
    """

    def __init__(
        self,
        embedder: Embeddings,
        collection_name: str = DEFAULT_COLLECTION,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ):
        self._embedder = embedder
        self._collection_name = collection_name
        self._host = host
        self._port = port
        self._collection = None

    # ── 连接 & 初始化 ────────────────────────────────────────────

    def connect(self) -> "MilvusStore":
        """
        连接 Milvus 并获取（或创建）Collection。
        返回 self，支持链式调用：store = MilvusStore(...).connect()
        """
        connections, Collection, CollectionSchema, FieldSchema, DataType, utility = _get_milvus()

        connections.connect(host=self._host, port=self._port)
        logger.info("[Store] 连接 Milvus %s:%d", self._host, self._port)

        if utility.has_collection(self._collection_name):
            self._collection = Collection(self._collection_name)
            self._collection.load()
            logger.info("[Store] 复用已有 Collection: %s", self._collection_name)
        else:
            self._collection = self._create_collection(
                Collection, CollectionSchema, FieldSchema, DataType
            )
            logger.info("[Store] 新建 Collection: %s", self._collection_name)

        return self

    def _create_collection(self, Collection, CollectionSchema, FieldSchema, DataType):
        """创建带 HNSW 索引的 Collection。"""
        schema = CollectionSchema(
            fields=[
                FieldSchema("id",          DataType.VARCHAR,       max_length=64,    is_primary=True),
                FieldSchema("embedding",   DataType.FLOAT_VECTOR,  dim=EMBEDDING_DIM),
                FieldSchema("content",     DataType.VARCHAR,       max_length=65535),
                FieldSchema("source",      DataType.VARCHAR,       max_length=256),
                FieldSchema("project_id",  DataType.VARCHAR,       max_length=64),
                FieldSchema("chunk_index", DataType.INT64),
            ],
            description="RAG chunk 向量库",
            enable_dynamic_field=False,
        )
        col = Collection(name=self._collection_name, schema=schema)

        # 创建 HNSW 索引
        col.create_index(
            field_name="embedding",
            index_params={
                "index_type": "HNSW",
                "metric_type": "COSINE",          # 余弦相似度，文本场景标准选择
                "params": {
                    "M": HNSW_M,
                    "efConstruction": HNSW_EF_CONSTRUCTION,
                },
            },
        )
        col.load()
        return col

    # ── 写入 ─────────────────────────────────────────────────────

    def add_documents(
        self,
        docs: list[Document],
        project_id: str = "default",
        batch_size: int = 64,
    ) -> int:
        """
        将 Document 列表 embed 后批量写入 Milvus。

        Args:
            docs:       LangChain Document 列表（每个是一个 chunk）
            project_id: 项目 ID，用于多租户过滤检索
            batch_size: 每批写入的文档数（避免单次请求过大）

        Returns:
            成功写入的 chunk 数
        """
        if self._collection is None:
            raise RuntimeError("请先调用 connect() 建立连接")

        total = 0
        for start in range(0, len(docs), batch_size):
            batch = docs[start: start + batch_size]
            texts = [d.page_content for d in batch]

            # ── Embed ───────────────────────────────────────────
            vectors = self._embedder.embed_documents(texts)

            # ── 构造 Milvus 行 ──────────────────────────────────
            rows = []
            for i, (doc, vec) in enumerate(zip(batch, vectors)):
                rows.append({
                    "id":          str(uuid.uuid4()),
                    "embedding":   vec,
                    "content":     doc.page_content[:65535],
                    "source":      doc.metadata.get("source", "unknown"),
                    "project_id":  project_id,
                    "chunk_index": start + i,
                })

            self._collection.insert(rows)
            total += len(rows)
            logger.info("[Store] 写入 %d/%d chunks", total, len(docs))

        self._collection.flush()
        logger.info("[Store] 全部写入完成，共 %d 条", total)
        return total

    # ── 检索 ─────────────────────────────────────────────────────

    def similarity_search(
        self,
        query: str,
        top_k: int = 5,
        project_id: str | None = None,
    ) -> list[Document]:
        """
        向量相似度检索。

        Args:
            query:      用户问题（会被 embed 成向量）
            top_k:      返回最相似的 top_k 个 chunk
            project_id: 不为 None 时只检索该项目的文档（多租户过滤）

        Returns:
            list[Document]，每个 Document 的 metadata 含 source、score
        """
        if self._collection is None:
            raise RuntimeError("请先调用 connect() 建立连接")

        # ── Embed 查询 ──────────────────────────────────────────
        query_vec = self._embedder.embed_query(query)

        # ── 构造过滤表达式（多租户） ─────────────────────────────
        expr = f'project_id == "{project_id}"' if project_id else None

        # ── 执行向量检索 ─────────────────────────────────────────
        results = self._collection.search(
            data=[query_vec],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": HNSW_EF}},
            limit=top_k,
            expr=expr,
            output_fields=["content", "source", "project_id", "chunk_index"],
        )

        # ── 转换为 LangChain Document ────────────────────────────
        docs = []
        for hit in results[0]:
            docs.append(Document(
                page_content=hit.entity.get("content", ""),
                metadata={
                    "source":      hit.entity.get("source", ""),
                    "project_id":  hit.entity.get("project_id", ""),
                    "chunk_index": hit.entity.get("chunk_index", -1),
                    "score":       round(hit.score, 4),
                },
            ))

        logger.info("[Store] 检索完成，query='%s'，返回 %d 条", query[:30], len(docs))
        return docs

    # ── 工具方法 ─────────────────────────────────────────────────

    def count(self, project_id: str | None = None) -> int:
        """返回当前 Collection 中的文档数量。"""
        if self._collection is None:
            return 0
        expr = f'project_id == "{project_id}"' if project_id else None
        return self._collection.query(
            expr=expr or "chunk_index >= 0",
            output_fields=["id"],
        ).__len__()

    def drop(self):
        """删除整个 Collection（危险操作，仅用于测试重置）。"""
        _, _, _, _, _, utility = _get_milvus()
        if utility.has_collection(self._collection_name):
            utility.drop_collection(self._collection_name)
            logger.warning("[Store] Collection %s 已删除", self._collection_name)
        self._collection = None
