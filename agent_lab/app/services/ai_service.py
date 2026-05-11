from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent_lab.app.agents.supervisor import build_supervisor
from agent_lab.app.services.tools import code_tools, file_tools, general_tools
from agent_lab.app.services.skill_registry import SkillRegistry
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
        embedder = OpenAIEmbeddings(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            model=settings.EMBEDDING_MODEL_NAME,
            http_client=httpx.Client(verify=not settings.SKIP_SSL_VERIFY),
        )
        self._registry = SkillRegistry(embedder)
        self._registry.register(code_tools + file_tools + general_tools)
        self._agent = None

    async def _ensure_initialized(self):
        if self._agent is None:
            conn = await aiosqlite.connect(self._db_path)
            memory = AsyncSqliteSaver(conn)
            self._agent = build_supervisor(self._llm, self._registry).compile(checkpointer=memory)
            logger.info("Supervisor 初始化完成，节点: %s",
                        list(self._agent.get_graph().nodes.keys()))

    async def chat(self, session_id: str, content: str):
        await self._ensure_initialized()
        config = {"configurable": {"thread_id": session_id}}
        logger.info("[%s] 用户: %s", session_id, content[:60])
        print(f"[{session_id}] AI > ", end="", flush=True)

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
                print(msg.content, end="", flush=True)

        print()


ai_service = AIService()
