from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from agent_lab.app.services.msg_utils import sanitize_messages
from agent_lab.app.services.skill_registry import SkillRegistry
from agent_lab.app.core.logger import get_logger

logger = get_logger("shell_agent")

_PROMPT = SystemMessage(content=(
    "你是一个系统信息查询专家，只能使用 run_shell_command 工具执行命令。\n"
    "只执行只读/查询类命令，严禁写文件、删除、网络操作。\n"
    "完成后用中文简洁汇报结果。"
))


class ShellState(TypedDict):
    messages: Annotated[list, add_messages]
    active_tools: list[str]  # 本轮由 SkillRegistry 检索到的工具名列表


def build_shell_subgraph(llm, registry: SkillRegistry, checkpointer=None):
    """
    工厂函数：接收共享 llm 和 SkillRegistry，返回带动态工具检索的 Shell 操作子图。
    """

    async def skill_retrieval_node(state: ShellState) -> dict:
        query = next(
            m.content for m in reversed(state["messages"]) if m.type == "human"
        )
        retrieved = await registry.search(query, top_k=3)
        names = [t.name for t in retrieved]
        logger.info("[ShellAgent] skill_retrieval → %s", names)
        return {"active_tools": names}

    async def agent_node(state: ShellState) -> dict:
        tools = [registry.get(n) for n in state["active_tools"]]
        llm_dynamic = llm.bind_tools(tools)
        response = await llm_dynamic.ainvoke([_PROMPT] + sanitize_messages(state["messages"]))
        return {"messages": [response]}

    async def tools_node(state: ShellState) -> dict:
        last = state["messages"][-1]
        tools_map = {n: registry.get(n) for n in state["active_tools"]}
        results = []
        for tc in last.tool_calls:
            logger.info("[ShellAgent] 执行工具: %s", tc["name"])
            result = await tools_map[tc["name"]].ainvoke(tc["args"])
            results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        return {"messages": results}

    def should_continue(state: ShellState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    g = StateGraph(ShellState)
    g.add_node("skill_retrieval", skill_retrieval_node)
    g.add_node("agent",           agent_node)
    g.add_node("tools",           tools_node)

    g.set_entry_point("skill_retrieval")
    g.add_edge("skill_retrieval", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")

    return g.compile(checkpointer=checkpointer)
