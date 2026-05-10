from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import ToolMessage, AIMessage, HumanMessage
from agent_lab.app.schemas.base import AIRequest, AIResponse
from agent_lab.app.core.config import settings
from agent_lab.app.core.history import AsyncSQLiteHistory
from agent_lab.app.services.tools import agent_tools
import httpx
import asyncio

class AIService:
    def __init__(self):
        custom_client = httpx.AsyncClient(
            verify=not settings.SKIP_SSL_VERIFY,
            timeout=settings.REQUEST_TIMEOUT
        )

        self.llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            model=settings.MODEL_NAME,
            http_async_client=custom_client,
            max_retries=2,
            streaming=True
        ).bind_tools(agent_tools)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "你是一个专业的助手。如果用户要求你查时间或查文件，请调用相应的工具。调用完工具后，请根据工具返回的结果给用户一个最终的回答。"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{content}")
        ])

        self.base_chain = self.prompt | self.llm
        self.db_path = "chat_history.db"
        self.tools_map = {tool.name: tool for tool in agent_tools}

    def get_session_history(self, session_id: str):
        return AsyncSQLiteHistory(db_path=self.db_path, session_id=session_id)

    async def chat(self, request: AIRequest):
        """
        全异步流式对话，严格遵循 [Assistant Tool Call -> Tool Message] 协议
        """
        history_handler = self.get_session_history(request.session_id)
        
        # 1. 获取现有历史
        history_messages = await history_handler.aget_messages()
        
        # 2. 构造本次输入
        input_data = {"content": request.content, "history": history_messages}
        
        # 3. 第一次请求 LLM
        response = await self.base_chain.ainvoke(input_data)
        
        # --- 核心修复：协议严谨性 ---
        # 无论是否有工具调用，先保存当前用户消息
        await history_handler.aadd_messages([HumanMessage(content=request.content)])

        if response.tool_calls:
            # 必须先把 AI 的“调用申请”存入历史，否则后续 ToolMessage 会找不到爹
            await history_handler.aadd_messages([response])
            
            tool_messages = []
            for tool_call in response.tool_calls:
                tool = self.tools_map[tool_call["name"]]
                print(f"\n[系统动作] 执行工具: {tool.name}...", flush=True)
                
                # 执行工具
                observation = await tool.ainvoke(tool_call["args"])
                
                # 构造 ToolMessage，必须包含对应的 tool_call_id
                tool_messages.append(ToolMessage(
                    content=str(observation), 
                    tool_call_id=tool_call["id"]
                ))
            
            # 将所有工具结果存入历史
            await history_handler.aadd_messages(tool_messages)
            
            # 重新获取完整历史（包含 User -> AI(Tools) -> ToolsResult）再请求最终总结
            final_history = await history_handler.aget_messages()
            
            print(f"[{request.session_id}] AI > ", end="", flush=True)
            full_content = ""
            async for chunk in self.llm.astream(final_history):
                if chunk.content:
                    print(chunk.content, end="", flush=True)
                    full_content += chunk.content
            
            # 保存 AI 最终的总结性回答
            await history_handler.aadd_messages([AIMessage(content=full_content)])
            print()
        else:
            # 没有工具调用，直接流式输出
            print(f"[{request.session_id}] AI > ", end="", flush=True)
            full_content = ""
            # 注意：这里直接流式输出时也需要手动管理历史，因为我们已经退出了 RunnableWithMessageHistory 自动托管
            async for chunk in self.base_chain.astream(input_data):
                if chunk.content:
                    print(chunk.content, end="", flush=True)
                    full_content += chunk.content
            
            await history_handler.aadd_messages([AIMessage(content=full_content)])
            print()

# 单例导出
ai_service = AIService()
