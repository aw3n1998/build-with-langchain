from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from agent_lab.app.services.msg_utils import sanitize_messages
from agent_lab.app.services.skill_registry import SkillRegistry
from agent_lab.app.services.stream_events import emit_tool_call, emit_tool_result
from agent_lab.app.core.logger import get_logger

logger = get_logger("file_agent")

_PROMPT = SystemMessage(content=(
    "你是文件操作专家。根据用户需求调用 list_files 或 read_file_content 工具，并整理结果回答用户。"
))


class FileState(TypedDict):
    messages: Annotated[list, add_messages]
    active_tools: list[str]  # 本轮由 SkillRegistry 检索到的工具名列表


def build_file_subgraph(llm, registry: SkillRegistry, checkpointer=None):
    """
    工厂函数：接收共享 llm 和 SkillRegistry，返回带动态工具检索的文件操作子图。
    """

    async def skill_retrieval_node(state: FileState) -> dict:
        query = next(
            m.content for m in reversed(state["messages"]) if m.type == "human"
        )
        retrieved = await registry.search(query, top_k=3)
        names = [t.name for t in retrieved]
        logger.info("[FileAgent] skill_retrieval → %s", names)
        return {"active_tools": names}

    async def agent_node(state: FileState) -> dict:
        tools = [registry.get(n) for n in state["active_tools"]]
        llm_dynamic = llm.bind_tools(tools)
        response = await llm_dynamic.ainvoke([_PROMPT] + sanitize_messages(state["messages"]))
        return {"messages": [response]}

    async def tools_node(state: FileState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            name = tc["name"]
            logger.info("[FileAgent] 执行工具: %s", name)
            emit_tool_call(name, tc.get("args"))
            try:
                tool = registry.get(name)
            except Exception:
                tool = None
            if tool is None:
                result = f"[工具不可用] {name}"
            else:
                try:
                    result = await tool.ainvoke(tc["args"])
                except Exception as e:  # noqa: BLE001
                    result = f"[工具执行失败] {name}: {type(e).__name__}: {e}"
            emit_tool_result(name, result)
            results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        return {"messages": results}

    def should_continue(state: FileState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    g = StateGraph(FileState)
    g.add_node("skill_retrieval", skill_retrieval_node)
    g.add_node("agent",           agent_node)
    g.add_node("tools",           tools_node)

    g.set_entry_point("skill_retrieval")
    g.add_edge("skill_retrieval", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")

    return g.compile(checkpointer=checkpointer)
