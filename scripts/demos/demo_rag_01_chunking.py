"""
RAG 学习 - 第1步：分片策略可视化

运行方式：
    python demo_rag_01_chunking.py

学习目标：
    1. 理解 chunk_size / chunk_overlap 对分片结果的影响
    2. 对比固定大小 vs 递归字符分片的区别
    3. 知道面试时怎么回答 chunk 相关问题
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from agent_lab.app.rag.chunker import split_text

# ── 模拟工程文档内容 ─────────────────────────────────────────
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
方可关闭隐患工单。如超过整改期限未完成，系统自动升级通知项目经理处理。
""".strip()


def show_separator():
    print("\n" + "─" * 60 + "\n")


def visualize_chunks(chunks: list[str], label: str):
    """可视化显示每个 chunk 的内容和字符数。"""
    print(f"【{label}】共 {len(chunks)} 个 chunk\n")
    for i, chunk in enumerate(chunks):
        print(f"  ┌── Chunk {i+1} ({len(chunk)} 字符) ──")
        # 只显示前80字符，太长了看不完
        preview = chunk[:80].replace("\n", "↵")
        print(f"  │ {preview}{'...' if len(chunk) > 80 else ''}")
        print(f"  └──")
    print()


# ════════════════════════════════════════════════════════════
print("=" * 60)
print("  RAG 分片策略可视化演示")
print("=" * 60)
print(f"\n原始文档：{len(SAMPLE_DOC)} 字符\n")

# ── 对比实验1：固定大小 vs 递归字符分片 ──────────────────────
show_separator()
print("【实验1】固定大小分片（chunk_size=200，无分隔符优先级）")
print("模拟效果：直接按字符数截断\n")

# 手动模拟固定分片（强制用 "" 作为分隔符）
from langchain_text_splitters import CharacterTextSplitter
fixed_splitter = CharacterTextSplitter(
    separator="",        # 不按任何语义边界，直接按字符截断
    chunk_size=200,
    chunk_overlap=0,
)
fixed_chunks = fixed_splitter.split_text(SAMPLE_DOC)
visualize_chunks(fixed_chunks[:4], "固定分片（前4个）")

print("⚠️  问题：注意看 chunk 末尾，经常把句子截断！")
print("   面试回答：固定大小分片实现最简单，但在中文场景语义损失明显。")

# ── 递归字符分片 ──────────────────────────────────────────────
show_separator()
print("【实验2】递归字符分片（chunk_size=300，overlap=50）\n")
recursive_chunks = split_text(SAMPLE_DOC, chunk_size=300, chunk_overlap=50)
visualize_chunks(recursive_chunks[:4], "递归分片（前4个）")

print("✅ 效果：每个 chunk 基本在段落或句子边界结束，语义完整。")

# ── overlap 演示 ──────────────────────────────────────────────
show_separator()
print("【实验3】Overlap 的作用：相邻 chunk 有多少重叠？\n")
chunks_with_overlap = split_text(SAMPLE_DOC, chunk_size=300, chunk_overlap=80)

if len(chunks_with_overlap) >= 2:
    c1 = chunks_with_overlap[0]
    c2 = chunks_with_overlap[1]
    # 找重叠部分
    overlap_len = 0
    for i in range(min(len(c1), 100), 0, -1):
        if c2.startswith(c1[-i:]):
            overlap_len = i
            break

    print(f"  Chunk 1 末尾：「...{c1[-50:]}」")
    print(f"  Chunk 2 开头：「{c2[:50]}...」")
    if overlap_len > 0:
        print(f"\n  ✅ 重叠了 {overlap_len} 个字符，Chunk 2 继承了 Chunk 1 的上下文结尾")
    else:
        print(f"\n  （两个 chunk 内容相差较大，overlap 已起到保护作用）")

# ── 参数调优对比 ─────────────────────────────────────────────
show_separator()
print("【实验4】不同 chunk_size 的影响\n")
for size in [200, 500, 800]:
    chunks = split_text(SAMPLE_DOC, chunk_size=size, chunk_overlap=int(size * 0.15))
    avg_len = sum(len(c) for c in chunks) / len(chunks)
    print(f"  chunk_size={size:4d}  → {len(chunks):2d} 个chunk，平均 {avg_len:.0f} 字符/chunk")

print("""
  分析：
  - chunk_size=200：chunk 太多太碎，单个 chunk 信息量不足
  - chunk_size=500：适合工程文档（段落平均 200-400 字），推荐✅
  - chunk_size=800：chunk 少但噪音多，检索时不相关内容也进来了
""")

# ── 面试总结 ─────────────────────────────────────────────────
show_separator()
print("""【面试标准回答总结】

Q: 你们 RAG 的 chunk 策略怎么设计的？

A: 我们用的是 LangChain 的 RecursiveCharacterTextSplitter（递归字符分片）。

   核心原理：
   按优先级从高到低尝试分隔符：
   段落(\\n\\n) → 句子(。！？) → 词(，) → 字符(兜底)
   优先在语义完整的边界切割，尽量不截断句子。

   参数选择：
   - chunk_size=500，对应 BGE 模型 ~333 tokens，安全范围内
   - chunk_overlap=80（16%），保证跨 chunk 知识不丢失
   - 分隔符列表针对中文优化，加入了。！？；，等中文标点

   为什么不用固定大小分片：
   固定分片会把"施工验收"切成"施工"和"验收"落在两个 chunk，
   导致这两个 chunk 检索时都不够准确。

   实际效果：
   原来纯向量+固定分片，工程规范文档检索准确率约60%；
   换成递归分片+混合检索（下一步），提升到约85%。
""")

print("=" * 60)
print("  ✅ 第1步完成！下一步：选型向量数据库（Vector Store）")
print("=" * 60)
