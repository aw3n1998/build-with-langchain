from typing import Annotated
from typing_extensions import TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessageChunk, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent_lab.app.core.config import settings
from agent_lab.app.core.logger import get_logger
from agent_lab.app.services.tools import agent_tools
import httpx
import aiosqlite

logger = get_logger("ai_service")

_SYSTEM_PROMPT = SystemMessage(content=(
    "你是一个专业的AI助手，可以查询时间、读取文件，以及编写并执行Python代码解决问题。"
    "当用户提出需要计算、数据处理或代码实现的需求时，主动调用 execute_python_code 工具编写并执行代码。"
    "若代码执行失败，分析错误信息，修正代码后重新执行，直到成功为止。"
))


class AgentState(TypedDict):
    # add_messages 是 LangGraph 内置的 reducer：
    # 每次节点返回新消息时，它会追加到列表而不是覆盖，实现对话历史积累
    messages: Annotated[list, add_messages]


class AIService:
    def __init__(self, db_path: str = "langgraph_checkpoint.db"):
        self._db_path = db_path
        self._llm_with_tools = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            model=settings.MODEL_NAME,
            http_async_client=httpx.AsyncClient(
                verify=not settings.SKIP_SSL_VERIFY,
                timeout=settings.REQUEST_TIMEOUT,
            ),
            max_retries=2,
        ).bind_tools(agent_tools)
        self._tools_map = {t.name: t for t in agent_tools}
        self._agent = None  # 延迟初始化，等第一次 chat 时再建立异步连接

    # ── 节点函数 ──────────────────────────────────────────────

    async def _agent_node(self, state: AgentState) -> dict:
        """agent 节点：把完整消息历史发给 LLM，得到回复（可能含工具调用）。"""
        messages = [_SYSTEM_PROMPT] + state["messages"]
        response = await self._llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    async def _tools_node(self, state: AgentState) -> dict:
        """tools 节点：执行 agent 节点请求的所有工具，返回 ToolMessage 列表。"""
        last_message = state["messages"][-1]
        tool_messages = []
        for tool_call in last_message.tool_calls:
            tool = self._tools_map[tool_call["name"]]
            logger.info("执行工具: %s", tool_call["name"])
            result = await tool.ainvoke(tool_call["args"])
            tool_messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            ))
        return {"messages": tool_messages}

    # ── 路由函数（条件边）────────────────────────────────────

    @staticmethod
    def _should_continue(state: AgentState) -> str:
        """检查最新 AI 消息是否包含工具调用，决定下一步走向。"""
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    # ── 图组装 ───────────────────────────────────────────────

    async def _build_agent(self):
        conn = await aiosqlite.connect(self._db_path)
        memory = AsyncSqliteSaver(conn)

        graph = StateGraph(AgentState)

        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._tools_node)

        graph.set_entry_point("agent")

        # 条件边：agent 有工具调用 → tools；否则 → 结束
        graph.add_conditional_edges(
            "agent",
            self._should_continue,
            {"tools": "tools", END: END},
        )

        # 固定边：tools 执行完毕后，永远回到 agent 继续推理
        graph.add_edge("tools", "agent")

        self._agent = graph.compile(checkpointer=memory)
        logger.info("Agent 图初始化完成，节点: %s", list(self._agent.get_graph().nodes.keys()))

    async def _ensure_initialized(self):
        if self._agent is None:
            await self._build_agent()

    # ── 对外接口 ─────────────────────────────────────────────

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
                and meta.get("langgraph_node") == "agent"
            ):
                print(msg.content, end="", flush=True)

        print()


ai_service = AIService()
