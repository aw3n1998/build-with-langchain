from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from agent_lab.app.services.skill_registry import SkillRegistry
from agent_lab.app.services.stream_events import emit_tool_call, emit_tool_result
from agent_lab.app.core.logger import get_logger

logger = get_logger("code_agent")

_PROMPT = SystemMessage(content=(
    "你是代码执行专家。用户提出编程需求时，调用 execute_python_code 工具编写并执行代码。"
    "若执行失败，分析错误，修正后重新执行，直到成功为止。"
))


class CodeState(TypedDict):
    messages: Annotated[list, add_messages]
    active_tools: list[str]  # 本轮由 SkillRegistry 检索到的工具名列表


def build_code_subgraph(llm, registry: SkillRegistry, checkpointer=None):
    """
    工厂函数：接收共享 llm 和 SkillRegistry，返回带动态工具检索的代码执行子图。

    图结构：
        skill_retrieval → agent → (有 tool_calls?) → tools → agent → ...
    """

    async def skill_retrieval_node(state: CodeState) -> dict:
        """语义检索：根据用户最新消息，从 Registry 中找出最相关的工具。"""
        query = next(
            m.content for m in reversed(state["messages"]) if m.type == "human"
        )
        retrieved = await registry.search(query, top_k=3)
        names = [t.name for t in retrieved]
        logger.info("[CodeAgent] skill_retrieval → %s", names)
        return {"active_tools": names}

    async def agent_node(state: CodeState) -> dict:
        """动态绑定工具：每次请求只把检索到的工具传给 LLM，不传全量工具。"""
        tools = [registry.get(n) for n in state["active_tools"]]
        llm_dynamic = llm.bind_tools(tools)
        response = await llm_dynamic.ainvoke([_PROMPT] + state["messages"])
        return {"messages": [response]}

    async def tools_node(state: CodeState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            name = tc["name"]
            logger.info("[CodeAgent] 执行工具: %s", name)
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

    def should_continue(state: CodeState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    g = StateGraph(CodeState)
    g.add_node("skill_retrieval", skill_retrieval_node)
    g.add_node("agent",           agent_node)
    g.add_node("tools",           tools_node)

    g.set_entry_point("skill_retrieval")
    g.add_edge("skill_retrieval", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")

    return g.compile(checkpointer=checkpointer)
