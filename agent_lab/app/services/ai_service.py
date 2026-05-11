from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessageChunk
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from agent_lab.app.core.config import settings
from agent_lab.app.core.logger import get_logger
from agent_lab.app.services.tools import agent_tools
import httpx
import sqlite3

logger = get_logger("ai_service")

_SYSTEM_PROMPT = (
    "你是一个专业的AI助手，可以查询时间、读取文件，以及编写并执行Python代码解决问题。"
    "当用户提出需要计算、数据处理或代码实现的需求时，主动调用 execute_python_code 工具编写并执行代码。"
    "若代码执行失败，分析错误信息，修正代码后重新执行，直到成功为止。"
)


class AIService:
    def __init__(self, db_path: str = "langgraph_checkpoint.db"):
        llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            model=settings.MODEL_NAME,
            http_async_client=httpx.AsyncClient(
                verify=not settings.SKIP_SSL_VERIFY,
                timeout=settings.REQUEST_TIMEOUT,
            ),
            max_retries=2,
        )
        conn = sqlite3.connect(db_path, check_same_thread=False)
        memory = SqliteSaver(conn)
        self._agent = create_react_agent(
            llm,
            agent_tools,
            prompt=_SYSTEM_PROMPT,
            checkpointer=memory,
        )

    async def chat(self, session_id: str, content: str):
        """接收用户输入，流式输出 AI 回复。工具调用（含代码执行）在 LangGraph 内部循环处理。"""
        config = {"configurable": {"thread_id": session_id}}
        logger.info("[%s] 用户: %s", session_id, content[:60])
        print(f"[{session_id}] AI > ", end="", flush=True)

        async for msg, meta in self._agent.astream(
            {"messages": [("user", content)]},
            config=config,
            stream_mode="messages",
        ):
            # 只打印 agent 节点产出的文本内容，跳过工具调用指令和工具结果
            if (
                isinstance(msg, AIMessageChunk)
                and msg.content
                and not getattr(msg, "tool_calls", None)
                and meta.get("langgraph_node") == "agent"
            ):
                print(msg.content, end="", flush=True)

        print()


# 单例导出
ai_service = AIService()
