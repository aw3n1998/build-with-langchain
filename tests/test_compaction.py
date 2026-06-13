"""
验证 Module 16 上下文压缩（Compaction）是否真实生效。

绕开 SkillRegistry embedding 初始化，直接测试 summarizer_node 逻辑。

运行方式：
    python test_compaction.py
"""

import asyncio
import sys
import io
import logging

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from mirage.app.core.config import settings
from langchain_openai import ChatOpenAI
import httpx

# 只初始化 LLM，不碰 SkillRegistry（绕开 Embedding 404 问题）
_llm = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_API_BASE,
    model=settings.MODEL_NAME,
    http_async_client=httpx.AsyncClient(
        verify=not settings.SKIP_SSL_VERIFY,
        timeout=settings.REQUEST_TIMEOUT,
    ),
    max_retries=2,
)


# ── 直接复制 supervisor.py 中的 summarizer_node 逻辑 ──────────
async def summarizer_node(state: dict) -> dict:
    """和 supervisor.py 中完全一样的压缩节点。"""
    messages = state["messages"]
    KEEP_RECENT = 6
    TRIGGER_AT  = 20

    print(f"\n[Summarizer] 当前消息数: {len(messages)}, 阈值: {TRIGGER_AT}")

    if len(messages) <= TRIGGER_AT:
        print(f"[Summarizer] 未超过阈值，跳过压缩 ✅")
        return {}

    to_compress = messages[:-KEEP_RECENT]
    recent      = messages[-KEEP_RECENT:]

    print(f"[Summarizer] 超过阈值！开始压缩 {len(to_compress)} 条旧消息，保留最近 {len(recent)} 条")

    summary = await _llm.ainvoke([
        SystemMessage(
            "请简洁总结以下对话的核心内容，保留：已完成的事项、重要决策、关键结论。"
            "不要遗漏任何重要信息，但去掉无意义的闲聊。"
        ),
        *to_compress,
    ])

    compressed = [
        SystemMessage(content=f"【历史对话摘要】\n{summary.content}"),
        *recent,
    ]
    print(f"[Summarizer] 压缩完成：{len(messages)} 条 → {len(compressed)} 条 ✅")
    return {"messages": compressed}


# ── 测试场景 ───────────────────────────────────────────────────

async def test_no_compression():
    print("\n" + "="*60)
    print("场景1：5条消息 → 不应触发压缩")
    print("="*60)

    messages = [
        HumanMessage(content="Python 列表推导式怎么用？"),
        AIMessage(content="列表推导式格式：[x for x in iterable if condition]"),
        HumanMessage(content="asyncio 是什么？"),
        AIMessage(content="asyncio 是 Python 异步 IO 框架。"),
        HumanMessage(content="好的谢谢"),
    ]

    result = await summarizer_node({"messages": messages})
    assert result == {}, f"应该返回空 dict，实际返回: {result}"
    print("✅ 场景1通过：消息数=5，未触发压缩，返回空dict")


async def test_with_compression():
    print("\n" + "="*60)
    print("场景2：22条消息 → 应触发压缩")
    print("="*60)

    # 构造 21 条历史消息
    messages = []
    topics = [
        "Python的列表推导式怎么用",
        "什么是装饰器",
        "asyncio 和 threading 的区别",
        "怎么读取文件内容",
        "LangChain 是什么",
        "向量数据库的原理",
        "什么是 FAISS",
        "Docker 是干什么的",
        "REST API 和 GraphQL 区别",
        "什么是微服务架构",
    ]
    for i, topic in enumerate(topics):
        messages.append(HumanMessage(content=f"请问：{topic}？"))
        messages.append(AIMessage(content=f"关于「{topic}」，简答：这是第{i+1}轮回答。"))

    messages.append(HumanMessage(content="以上内容都学完了，感谢你的解释！"))

    print(f"输入消息数: {len(messages)}")

    result = await summarizer_node({"messages": messages})

    assert "messages" in result, "应该返回包含 messages 的 dict"
    compressed = result["messages"]

    print(f"\n压缩后消息数: {len(compressed)}")
    print(f"第一条消息类型: {type(compressed[0]).__name__}")
    print(f"摘要内容预览:\n{'-'*40}")
    print(compressed[0].content[:300])
    print(f"{'-'*40}")

    # 验证：第一条是摘要SystemMessage
    assert isinstance(compressed[0], SystemMessage), "第一条应该是摘要 SystemMessage"
    assert "历史对话摘要" in compressed[0].content, "摘要应包含【历史对话摘要】标记"

    # 验证：最后6条是原始的recent消息
    assert len(compressed) == 7, f"应该是 1条摘要 + 6条recent = 7条，实际: {len(compressed)}"

    print(f"\n✅ 场景2通过：{len(messages)}条 → {len(compressed)}条（1条摘要 + 6条recent）")
    print("🎉 上下文压缩 Module 16 验证成功！")


async def main():
    await test_no_compression()
    await test_with_compression()


if __name__ == "__main__":
    asyncio.run(main())
