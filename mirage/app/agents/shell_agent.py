from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from mirage.app.services.msg_utils import sanitize_messages
from mirage.app.services.skill_registry import SkillRegistry
from mirage.app.core.logger import get_logger

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
            (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
        )
        retrieved = await registry.search(query, top_k=3)
        names = [t.name for t in retrieved]
        logger.info("[ShellAgent] skill_retrieval → %s", names)
        return {"active_tools": names}

    async def agent_node(state: ShellState) -> dict:
        # 防御性取工具：检索名与注册表理论同源，但并发热插拔时可能取不到——跳过而非 KeyError 崩图。
        tools = []
        for n in state["active_tools"]:
            try:
                tools.append(registry.get(n))
            except Exception:
                logger.warning("[ShellAgent] 跳过取不到的工具 %s", n)
        llm_dynamic = llm.bind_tools(tools)
        response = await llm_dynamic.ainvoke([_PROMPT] + sanitize_messages(state["messages"]))
        return {"messages": [response]}

    async def tools_node(state: ShellState) -> dict:
        last = state["messages"][-1]
        active = set(state.get("active_tools") or [])
        results = []
        for tc in last.tool_calls:
            name = tc["name"]
            logger.info("[ShellAgent] 执行工具: %s", name)
            # shell 子 agent 限定「只读/查询」：只执行本轮检索并绑定给它的工具(active_tools)。
            # 不在白名单内的名字一律拒绝——防 LLM 幻觉/注入越权调用别 agent 的写/删/GPU 工具
            # （共享注册表里有这些副作用工具，registry.get 取得到，故必须在执行前先按白名单挡）。
            # 取不到/执行失败也都返回占位结果而非崩图（与 code/general/video agent 的加固一致）。
            if name not in active:
                result = f"[工具不可用] {name}（shell 仅限本轮检索到的只读工具）"
            else:
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
