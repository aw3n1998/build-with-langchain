"""
RAG 学习 - 第2步：向量数据库可视化（Milvus）

运行前置条件：
    1. 启动 Milvus：
       docker compose up -d          # 见项目根目录 docker-compose.yml
       或 docker run -d --name milvus-standalone \\
           -p 19530:19530 -p 9091:9091 \\
           milvusdb/milvus:v2.4.0 milvus run standalone

    2. 安装依赖：
       pip install pymilvus fastembed

    3. 运行：
       python demo_rag_02_vectorstore.py

学习目标：
    1. 理解 embedding → 向量 → 写入 Milvus 的全链路
    2. 理解 HNSW 索引参数的作用
    3. 看到 "向量相似度" 的实际数字，能解释给面试官听
    4. 知道多租户（project_id 过滤）的实现方式
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ── 环境检查 ─────────────────────────────────────────────────────
print("=" * 60)
print("  RAG 向量数据库演示（Milvus + BGE-small）")
print("=" * 60)

try:
    from pymilvus import connections
    connections.connect(host="localhost", port=19530)
    print("\n✅ Milvus 连接成功\n")
    connections.disconnect("default")
except Exception as e:
    print(f"\n❌ Milvus 未启动：{e}")
    print("\n请先运行：")
    print("  docker run -d --name milvus-standalone \\")
    print("    -p 19530:19530 -p 9091:9091 \\")
    print("    milvusdb/milvus:v2.4.0 milvus run standalone")
    print("\n等待约 30 秒后重试")
    sys.exit(1)

from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from mirage.app.rag.chunker import split_documents
from mirage.app.rag.loader import load_txt
from mirage.app.rag.store import MilvusStore
from langchain_core.documents import Document

# ── 准备 Embedder ────────────────────────────────────────────────
print("正在加载 Embedding 模型（首次运行会下载 ~50MB）...")
embedder = FastEmbedEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
print("✅ Embedding 模型就绪\n")

# ── 模拟工程文档 ─────────────────────────────────────────────────
SAMPLE_DOC = """
第一章 施工验收管理规范

1.1 验收流程概述

施工验收是确保工程质量的关键环节，主要包括以下步骤：
首先由施工单位自检，填写自检报告并上传系统。
自检通过后，由质检人员进行现场验收检查。
检查发现问题时，在系统中创建整改单，注明问题描述、整改要求和完成期限。
施工单位完成整改后，上传整改结果并申请复验。
复验通过后，由项目经理确认归档，验收流程结束。

1.2 质量标准

混凝土强度等级须符合设计要求，现场取样检测合格率须达到100%。
钢筋绑扎间距偏差不得超过±10mm，焊接质量须满足GB50205标准。
模板安装平整度偏差不超过5mm，垂直度偏差不超过3mm每米。
防水层施工须进行蓄水试验，蓄水时间不少于24小时，无渗漏为合格。

第二章 安全管理制度

2.1 日常巡检要求

安全员须每日对施工现场进行巡检，重点检查以下内容：
高空作业人员必须佩戴安全帽和安全带，安全网铺设完整。
施工用电须符合临时用电规范，配电箱加锁管理，严禁私拉乱接。
危险区域须设置明显警示标志，夜间作业须保证充足照明。
消防设施配备齐全，灭火器在有效期内，消防通道保持畅通。

2.2 隐患处理流程

发现安全隐患后，安全员须立即在系统中录入隐患信息，包括隐患类型、位置、
拍照存证，并指定整改负责人和整改期限。一般隐患须在5个工作日内完成整改，
重大隐患须立即停工整改，整改前不得恢复施工。整改完成后须经安全员复验确认，
方可关闭隐患工单。
""".strip()


def show_separator():
    print("\n" + "─" * 60 + "\n")


# ════════════════════════════════════════════════════════════
# 实验1：完整 Pipeline 展示
# ════════════════════════════════════════════════════════════
show_separator()
print("【实验1】完整 Pipeline：文档 → 分片 → Embed → 写入 Milvus\n")

# Step 1: 构造 Document
raw_doc = Document(
    page_content=SAMPLE_DOC,
    metadata={"source": "施工规范示例.txt", "file_type": "txt"}
)
print(f"  原始文档：{len(SAMPLE_DOC)} 字符")

# Step 2: 分片
chunks = split_documents([raw_doc], chunk_size=300, chunk_overlap=50)
print(f"  分片后：{len(chunks)} 个 chunk")

# Step 3: Embed 一个 chunk 看看维度
sample_vec = embedder.embed_query(chunks[0].page_content)
print(f"  Embedding 维度：{len(sample_vec)} 维（BGE-small-zh-v1.5 输出 512 维）\n")
print(f"  向量前5个值：{[round(v, 4) for v in sample_vec[:5]]}...")
print(f"\n  💡 每个 chunk 都变成 {len(sample_vec)} 维的浮点数向量")
print(f"     向量间的余弦相似度就是语义相似度的度量")

# Step 4: 写入 Milvus
show_separator()
print("【实验2】写入 Milvus，演示 Collection Schema 和 HNSW 索引\n")

store = MilvusStore(
    embedder=embedder,
    collection_name="demo_rag_chunks",  # 独立 collection，避免污染生产数据
)

# 清理旧数据（演示专用）
store.connect()
store.drop()
store.connect()  # 重建干净的 collection

n_written = store.add_documents(chunks, project_id="proj_demo")
print(f"\n  ✅ 成功写入 {n_written} 个 chunk 到 Milvus")
print(f"\n  Schema 说明：")
print(f"    id          : UUID，主键")
print(f"    embedding   : FLOAT_VECTOR(512)，向量数据")
print(f"    content     : VARCHAR，chunk 原文")
print(f"    source      : VARCHAR，来源文件名（溯源用）")
print(f"    project_id  : VARCHAR，项目ID（多租户过滤用）")
print(f"    chunk_index : INT64，chunk 序号（定位用）")
print(f"\n  索引：HNSW（M=16, efConstruction=200）")
print(f"    余弦相似度（COSINE），适合文本语义比较")


# ════════════════════════════════════════════════════════════
# 实验3：相似度检索，直观看分数
# ════════════════════════════════════════════════════════════
show_separator()
print("【实验3】相似度检索 —— 看懂 score 才能跟面试官聊\n")

test_queries = [
    ("验收流程是怎样的？",     "应该命中：验收流程相关 chunk"),
    ("钢筋焊接质量标准是什么？", "应该命中：质量标准相关 chunk"),
    ("安全隐患怎么处理？",      "应该命中：隐患处理流程 chunk"),
    ("今天天气怎么样？",        "不相关问题，score 应该明显偏低"),
]

for query, hint in test_queries:
    results = store.similarity_search(query, top_k=2, project_id="proj_demo")
    print(f"  问：{query}")
    print(f"  ({hint})")
    for i, doc in enumerate(results):
        preview = doc.page_content[:60].replace("\n", " ")
        print(f"    Top{i+1} score={doc.metadata['score']:.4f}  「{preview}...」")
    print()

print("  💡 score 解读（余弦相似度）：")
print("     > 0.85 ：高度相关，基本是正确答案")
print("     0.7-0.85：相关，但可能需要结合 Rerank 二次排序")
print("     < 0.7  ：不太相关，不相关问题通常在这个区间")


# ════════════════════════════════════════════════════════════
# 实验4：多租户过滤
# ════════════════════════════════════════════════════════════
show_separator()
print("【实验4】多租户过滤 —— 为什么需要 project_id\n")

# 写入另一个项目的文档
other_doc = Document(
    page_content="第三章 合同管理\n合同签订须经法务部门审核，大额合同须董事会审批。变更须以书面形式确认。",
    metadata={"source": "合同规范.txt", "file_type": "txt"}
)
other_chunks = split_documents([other_doc], chunk_size=300, chunk_overlap=50)
store.add_documents(other_chunks, project_id="proj_other")

# 不过滤：两个项目的结果都会出来
results_all = store.similarity_search("验收流程", top_k=3, project_id=None)
# 只查 proj_demo
results_filtered = store.similarity_search("验收流程", top_k=3, project_id="proj_demo")

print(f"  不过滤（全库检索）：返回 {len(results_all)} 条")
for r in results_all:
    print(f"    project={r.metadata['project_id']}  score={r.metadata['score']:.4f}  {r.page_content[:40]}...")

print(f"\n  只查 proj_demo：返回 {len(results_filtered)} 条")
for r in results_filtered:
    print(f"    project={r.metadata['project_id']}  score={r.metadata['score']:.4f}  {r.page_content[:40]}...")

print("""
  💡 多租户的核心：
     Milvus 支持 expr 标量过滤，检索时加 project_id == "xxx"
     既保证了数据隔离，又不需要为每个项目建独立 Collection
     FAISS 和 Chroma 默认不支持这种过滤（需要额外实现）
""")


# ════════════════════════════════════════════════════════════
# 清理
# ════════════════════════════════════════════════════════════
show_separator()
print("【清理】删除演示 Collection（生产环境不要这么做）\n")
store.drop()
print("  ✅ demo_rag_chunks 已删除")


# ════════════════════════════════════════════════════════════
# 面试总结
# ════════════════════════════════════════════════════════════
show_separator()
print("""【面试标准回答总结】

Q: 为什么选 Milvus 不选 FAISS 或 ChromaDB？

A: 核心对比：
   FAISS：速度极快，但无持久化、不支持 CRUD、不支持多租户
           → 适合离线批处理，不适合生产 SaaS
   ChromaDB：安装简单，适合 Demo，但单机扛不住百万级数据
           → 适合原型验证，不适合企业级
   Milvus：分布式，支持十亿级，HNSW 索引，支持标量过滤
           → 适合多租户工程 SaaS ✅

Q: Collection Schema 怎么设计的？

A: 6个字段：id(主键) + embedding(512维) + content(原文)
   + source(来源文件) + project_id(多租户) + chunk_index(序号)
   用 project_id 做标量过滤，一个 Collection 支撑多个项目

Q: HNSW 参数怎么选的？

A: M=16（连接数，工程默认），efConstruction=200（建图时搜索范围）
   查询时 ef=50（top_k 的 2-4 倍），Recall 约99%，速度远快于暴力搜索
""")

print("=" * 60)
print("  ✅ 第2步完成！下一步：检索策略（纯向量 vs 混合检索）")
print("=" * 60)
