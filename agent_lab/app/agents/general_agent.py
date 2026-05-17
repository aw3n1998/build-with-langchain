"""
General Agent — 通用子 Agent，直连模式专用。

与 Supervisor 内的 general_node 不同，这是一个独立的 LangGraph 子图，
可以单独编译、持久化会话历史（通过 checkpointer），直接接收用户消息。

能力：
  - 语义检索最相关工具（RAG 检索、通用工具等）
  - 支持多轮工具调用（ReAct 循环）
"""

from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from agent_lab.app.services.skill_registry import SkillRegistry
from agent_lab.app.core.logger import get_logger

logger = get_logger("general_agent")

_PROMPT = SystemMessage(content=(
    "你是一个专业的 AI 助手，可以回答问题、检索知识库、执行通用任务。"
    "根据用户需求调用合适的工具，工具调用完成后给出清晰的最终回答。"
))


class GeneralState(TypedDict):
    messages: Annotated[list, add_messages]
    active_tools: list[str]   # 本轮由 SkillRegistry 检索到的工具名列表


def build_general_subgraph(llm, registry: SkillRegistry, checkpointer=None):
    """
    工厂函数：接收共享 llm 和 SkillRegistry，返回通用 ReAct 子图。

    图结构：
        skill_retrieval → agent → (有 tool_calls?) → tools → agent → ...
    """

    async def skill_retrieval_node(state: GeneralState) -> dict:
        query = next(
            m.content for m in reversed(state["messages"]) if m.type == "human"
        )
        retrieved = await registry.search(query, top_k=5)
        names = [t.name for t in retrieved]
        logger.info("[GeneralAgent] skill_retrieval → %s", names)
        return {"active_tools": names}

    async def agent_node(state: GeneralState) -> dict:
        tools = [registry.get(n) for n in state["active_tools"]]
        llm_dynamic = llm.bind_tools(tools) if tools else llm
        response = await llm_dynamic.ainvoke([_PROMPT] + state["messages"])
        return {"messages": [response]}

    async def tools_node(state: GeneralState) -> dict:
        last = state["messages"][-1]
        tools_map = {n: registry.get(n) for n in state["active_tools"]}
        results = []
        for tc in last.tool_calls:
            logger.info("[GeneralAgent] 执行工具: %s", tc["name"])
            result = await tools_map[tc["name"]].ainvoke(tc["args"])
            results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        return {"messages": results}

    def should_continue(state: GeneralState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    g = StateGraph(GeneralState)
    g.add_node("skill_retrieval", skill_retrieval_node)
    g.add_node("agent",           agent_node)
    g.add_node("tools",           tools_node)

    g.set_entry_point("skill_retrieval")
    g.add_edge("skill_retrieval", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")

    return g.compile(checkpointer=checkpointer)
