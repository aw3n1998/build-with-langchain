"""
决策点2：分片策略（Chunking）
选型结论：RecursiveCharacterTextSplitter（递归字符分片）

=== 面试标准答案 ===

Q: 你们 RAG 的 chunk 怎么分片的？
A: 我们用的是递归字符分片（RecursiveCharacterTextSplitter）。
   原理是按优先级从高到低依次尝试分隔符：
   段落（\\n\\n）→ 句子（。！？）→ 词 → 字符兜底
   优先在语义完整的边界切割，尽量不截断句子。
   配合 overlap（重叠），保证相邻 chunk 有上下文衔接。

Q: chunk_size 怎么定的？
A: 需要结合两个约束来选：
   1. Embedding 模型的最大 token 限制（BGE 是 512 tokens）
   2. 业务文档的平均段落长度
   我们工程文档平均段落在 200-400 字，chunk_size 设 500 字符，
   overlap 设 80，既不超限也保留了段落完整性。

Q: 为什么不用固定大小分片？
A: 固定大小按字符数硬切，会把"施工验收"切成"施工"和"验收"分到两个
   chunk 里，导致语义丢失，检索时两个 chunk 都不准。

=== 参数选择逻辑 ===

chunk_size:
    - 太小（< 200）：单个 chunk 信息量不足，LLM 回答没上下文
    - 太大（> 1500）：噪音多，检索精度下降，超 Embedding 模型限制
    - 推荐：500-1000（中文工程文档）

chunk_overlap:
    - 目的：防止一个知识点被切断时完全丢失
    - 推荐：chunk_size 的 10-20%（chunk_size=500 → overlap=80）
    - 太大：冗余 chunk 太多，存储和检索成本上升
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from mirage.app.core.logger import get_logger

logger = get_logger("rag.chunker")

# ── 中文专用分隔符优先级列表 ──────────────────────────────────
# 越靠前优先级越高，RecursiveCharacterTextSplitter 从上往下尝试
# 找到能满足 chunk_size 的分隔符就用它，否则继续尝试下一个
CHINESE_SEPARATORS = [
    "\n\n",    # 1️⃣ 段落（优先级最高）- 最理想的切割点
    "\n",      # 2️⃣ 单个换行 - 次优
    "。",      # 3️⃣ 中文句号
    "！",      # 4️⃣ 叹号
    "？",      # 5️⃣ 问号
    "；",      # 6️⃣ 分号
    "，",      # 7️⃣ 逗号 - 只在上面都不够用时才切
    " ",       # 8️⃣ 空格
    "",        # 9️⃣ 字符级兜底 - 最后手段
]


def build_chunker(
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> RecursiveCharacterTextSplitter:
    """
    构建中文递归字符分片器。

    Args:
        chunk_size:    每个 chunk 的最大字符数
                       BGE-small 的 token 上限是 512，中文约 1 token ≈ 1.5 字符
                       → 500 字符 ≈ 333 tokens，安全范围内
        chunk_overlap: 相邻 chunk 的重叠字符数
                       保证跨 chunk 的知识点不会完全丢失
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=CHINESE_SEPARATORS,
        length_function=len,   # 用字符数计算长度（不是 token 数）
        is_separator_regex=False,
    )
    logger.info("[Chunker] 初始化完成 chunk_size=%d overlap=%d", chunk_size, chunk_overlap)
    return splitter


def split_documents(
    docs: list[Document],
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[Document]:
    """
    将文档列表切分为 chunks，保留 metadata（来源文件、页码等）。

    每个输入 Document 会被切成多个小 Document，
    metadata 原样复制到每个 chunk 上，方便溯源。
    """
    splitter = build_chunker(chunk_size, chunk_overlap)
    chunks = splitter.split_documents(docs)

    logger.info("[Chunker] 原始文档 %d 篇 → chunks %d 个 (avg %.0f 字/chunk)",
                len(docs),
                len(chunks),
                sum(len(c.page_content) for c in chunks) / max(len(chunks), 1))
    return chunks


def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 80) -> list[str]:
    """
    直接切纯文本（不带 metadata），用于快速测试。
    """
    splitter = build_chunker(chunk_size, chunk_overlap)
    return splitter.split_text(text)
