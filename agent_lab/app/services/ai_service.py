from langchain_openai import ChatOpenAI
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent_lab.app.agents.supervisor import build_supervisor
from agent_lab.app.services.tools import code_tools, file_tools, general_tools
from agent_lab.app.services.skill_registry import SkillRegistry
from agent_lab.app.rag.pipeline import init_pipeline
from agent_lab.app.rag.rag_tools import rag_tools
from agent_lab.app.core.config import settings
from agent_lab.app.core.logger import get_logger
import httpx
import aiosqlite

logger = get_logger("ai_service")


class AIService:
    def __init__(self, db_path: str = "langgraph_checkpoint.db"):
        self._db_path = db_path
        self._llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            model=settings.MODEL_NAME,
            http_async_client=httpx.AsyncClient(
                verify=not settings.SKIP_SSL_VERIFY,
                timeout=settings.REQUEST_TIMEOUT,
            ),
            max_retries=2,
        )
        # 本地 Embedding 模型，首次运行自动下载 (~50MB)，无需 API
        # 使用多语言模型，支持中文工具描述和用户查询
        embedder = FastEmbedEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
        self._registry = SkillRegistry(embedder)
        self._agent = None

        # 初始化 RAG Pipeline 单例（工具函数通过 get_pipeline() 访问）
        # connect() 是轻量操作，Milvus 不可用时自动降级，不影响启动
        self._rag_pipeline = init_pipeline(embedder)
        connected = self._rag_pipeline.connect()
        if connected:
            logger.info("[AIService] RAG Pipeline 就绪，知识库 chunk 数: %d",
                        self._rag_pipeline.chunk_count)
        else:
            logger.warning("[AIService] Milvus 未启动，RAG 工具降级运行（搜索会返回提示信息）")

    async def _ensure_initialized(self):
        if self._agent is None:
            # 首次初始化：注册工具（同步，本地 embedding 极快）
            if not self._registry._names:
                logger.info("[AIService] 初始化 SkillRegistry，注册工具...")
                all_tools = code_tools + file_tools + general_tools + rag_tools
                self._registry.register(all_tools)

            conn = await aiosqlite.connect(self._db_path)
            memory = AsyncSqliteSaver(conn)
            self._agent = build_supervisor(self._llm, self._registry).compile(checkpointer=memory)
            logger.info("Supervisor 初始化完成，节点: %s",
                        list(self._agent.get_graph().nodes.keys()))

    async def astream_chat(self, session_id: str, content: str):
        """
        流式生成器：逐 chunk yield AI 回复文本。
        供 FastAPI SSE 接口使用，也可被 CLI 消费。

        Usage:
            async for chunk in ai_service.astream_chat(sid, msg):
                print(chunk, end="", flush=True)
        """
        await self._ensure_initialized()
        config = {"configurable": {"thread_id": session_id}}
        logger.info("[%s] 用户: %s", session_id, content[:60])

        async for msg, meta in self._agent.astream(
            {"messages": [("user", content)]},
            config=config,
            stream_mode="messages",
        ):
            if (
                isinstance(msg, AIMessageChunk)
                and msg.content
                and not getattr(msg, "tool_calls", None)
            ):
                yield msg.content

    async def chat(self, session_id: str, content: str):
        """CLI 模式：直接 print 输出（保持向后兼容）。"""
        print(f"[{session_id}] AI > ", end="", flush=True)
        async for chunk in self.astream_chat(session_id, content):
            print(chunk, end="", flush=True)
        print()


ai_service = AIService()
