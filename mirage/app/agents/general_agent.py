"""
General Agent — 通用子 Agent，直连模式专用。

与 Supervisor 内的 general_node 不同，这是一个独立的 LangGraph 子图，
可以单独编译、持久化会话历史（通过 checkpointer），直接接收用户消息。

能力：
  - 语义检索最相关工具（按工具描述的向量相似度召回）
  - 支持多轮工具调用（ReAct 循环）
"""

from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from mirage.app.services.msg_utils import sanitize_messages
from mirage.app.services.skill_registry import SkillRegistry
from mirage.app.core.logger import get_logger

logger = get_logger("general_agent")

_PROMPT = SystemMessage(content=(
    "你是一个专业的 AI 助手，可以回答问题、执行通用任务。"
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
            (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
        )
        retrieved = await registry.search(query, top_k=5)
        names = [t.name for t in retrieved]
        logger.info("[GeneralAgent] skill_retrieval → %s", names)
        return {"active_tools": names}

    async def agent_node(state: GeneralState) -> dict:
        tools = [registry.get(n) for n in state["active_tools"]]
        llm_dynamic = llm.bind_tools(tools) if tools else llm
        response = await llm_dynamic.ainvoke([_PROMPT] + sanitize_messages(state["messages"]))
        return {"messages": [response]}

    async def tools_node(state: GeneralState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            name = tc["name"]
            logger.info("[GeneralAgent] 执行工具: %s", name)
            # LLM 偶尔会调不在 active_tools / 未注册的工具；取不到就返回占位结果，
            # 避免整图 KeyError 崩溃（与 video_agent 的加固一致）。
            try:
                tool = registry.get(name)
            except Exception:  # 与 shell/code/file agent 对齐：registry.get 抛任何异常都回占位，不只 KeyError
                tool = None
            if tool is None:
                msg = f"[工具不可用] 未找到工具 `{name}`，请改用已注册的工具。"
                logger.warning("[GeneralAgent] %s", msg)
                results.append(ToolMessage(content=msg, tool_call_id=tc["id"]))
                continue
            try:
                result = await tool.ainvoke(tc["args"])
            except Exception as e:  # noqa: BLE001  工具执行失败回灌给 LLM，而非中断整图（与 code/file/video agent 一致）
                result = f"[工具执行失败] {name}: {type(e).__name__}: {e}"
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
