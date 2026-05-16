# RAG 模块 - 渐进式学习
# 决策点1: Chunking      ✅ chunker.py  (RecursiveCharacterTextSplitter)
# 决策点2: Embedding     ✅ ai_service  (FastEmbed BAAI/bge-small-zh-v1.5)
# 决策点3: VectorStore   ✅ store.py    (Milvus + HNSW 索引)
# 决策点4: Retrieval     ✅ retriever.py (BM25 + 向量 + RRF 混合检索)
# 决策点5: Rerank        （暂不实现，当前准确率已满足需求）
#
# Agent 集成：
#   pipeline.py   - RAG 全链路管理器（单例）
#   rag_tools.py  - search_knowledge_base / ingest_document 工具
#   ai_service.py - 已注册 rag_tools，Agent 可直接调用
