from langchain_core.messages import SystemMessage, AIMessage, HumanMessage, ToolMessage
from langchain_openai import OpenAIEmbeddings
from langgraph.graph import StateGraph, END
from langgraph.types import Send
from agent_lab.app.agents.state import SupervisorState
from agent_lab.app.agents.code_agent import build_code_subgraph
from agent_lab.app.agents.file_agent import build_file_subgraph
from agent_lab.app.services.tools import code_tools, file_tools, general_tools
from agent_lab.app.services.skill_registry import SkillRegistry
from agent_lab.app.core.logger import get_logger

logger = get_logger("supervisor")

_ROUTER_PROMPT = SystemMessage(content=(
    "你是一个任务分发器。根据用户最新消息，选择需要的处理器（可多选，逗号分隔）：\n"
    "- code    （需要编写或执行代码）\n"
    "- file    （需要列出目录或读取文件）\n"
    "- general （可直接回答，如查时间、聊天、问答）\n\n"
    "只输出选中的词，用逗号分隔，例如：code,file\n"
    "不要输出任何解释。"
))

_GENERAL_PROMPT = SystemMessage(content="你是专业AI助手，直接回答用户问题，可以查询当前时间。")

_AGGREGATE_PROMPT = SystemMessage(content=(
    "多个专业 Agent 已并行处理了用户的请求，以下是各 Agent 的结果。"
    "请将它们整合成一个连贯、清晰的回答，不要重复说明来源。"
))


def build_supervisor(llm, registry: SkillRegistry):
    """
    并行多 Agent Supervisor，所有子 Agent 共用同一个 SkillRegistry。

    拓扑结构：
        __start__
            ↓
        summarizer  ← 自动检查消息长度，超阈值压缩历史（Compaction）
            ↓
          router    ← LLM 决定选哪些 Agent（可多选）
            ↓  Send API 并行扇出
      ┌─────┼─────┐
   code   file  general
      └─────┼─────┘
            ↓  全部完成后汇聚
        aggregator
            ↓
         __end__

    每个子 Agent 内部都有 skill_retrieval 节点，动态从 registry 检索工具。
    """
    code_graph = build_code_subgraph(llm, registry)
    file_graph = build_file_subgraph(llm, registry)

    # ── 路由节点 ───────────────────────────────────────────────
    async def router_node(state: SupervisorState) -> dict:
        last_human = next(
            (m for m in reversed(state["messages"]) if m.type == "human"), None
        )
        decision = await llm.ainvoke([_ROUTER_PROMPT, last_human])
        raw = decision.content.strip().lower()
        agents = [a.strip() for a in raw.split(",") if a.strip() in ("code", "file", "general")]
        if not agents:
            agents = ["general"]
        logger.info("[Supervisor] 并行路由 → %s", agents)
        return {
            "selected_agents": agents,
            "code_result": "",
            "file_result": "",
            "general_result": "",
        }

    # ── Send 扇出函数（条件边）────────────────────────────────
    def fan_out(state: SupervisorState) -> list[Send]:
        node_map = {"code": "code_agent", "file": "file_agent", "general": "general"}
        return [
            Send(node_map[agent], {"messages": state["messages"]})
            for agent in state["selected_agents"]
            if agent in node_map
        ]

    # ── 并行子 Agent 节点 ─────────────────────────────────────
    async def code_agent_node(state: SupervisorState) -> dict:
        logger.info("[CodeAgent] 开始执行")
        result = await code_graph.ainvoke({"messages": state["messages"]})
        final = next((m for m in reversed(result["messages"]) if isinstance(m, AIMessage)), None)
        return {"code_result": final.content if final else ""}

    async def file_agent_node(state: SupervisorState) -> dict:
        logger.info("[FileAgent] 开始执行")
        result = await file_graph.ainvoke({"messages": state["messages"]})
        final = next((m for m in reversed(result["messages"]) if isinstance(m, AIMessage)), None)
        return {"file_result": final.content if final else ""}

    async def general_node(state: SupervisorState) -> dict:
        """General Agent：动态检索工具，按需调用。"""
        logger.info("[General] 开始执行")
        query = next(
            (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
        )
        retrieved = await registry.search(query, top_k=3)
        logger.info("[General] skill_retrieval → %s", [t.name for t in retrieved])

        llm_dynamic = llm.bind_tools(retrieved)
        tools_map = {t.name: t for t in retrieved}

        response = await llm_dynamic.ainvoke([_GENERAL_PROMPT] + state["messages"])
        messages = [response]
        while getattr(messages[-1], "tool_calls", None):
            tool_results = []
            for tc in messages[-1].tool_calls:
                result = await tools_map[tc["name"]].ainvoke(tc["args"])
                tool_results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
            messages.extend(tool_results)
            follow_up = await llm_dynamic.ainvoke(
                [_GENERAL_PROMPT] + state["messages"] + messages
            )
            messages.append(follow_up)
        return {"general_result": messages[-1].content}

    # ── 汇聚节点 ──────────────────────────────────────────────
    async def aggregator_node(state: SupervisorState) -> dict:
        active = {
            k: v for k, v in {
                "code": state.get("code_result", ""),
                "file": state.get("file_result", ""),
                "general": state.get("general_result", ""),
            }.items() if v
        }
        logger.info("[Aggregator] 汇聚结果来自: %s", list(active.keys()))

        if len(active) == 1:
            final_answer = list(active.values())[0]
        else:
            combined = "\n\n".join(f"【{k} Agent】\n{v}" for k, v in active.items())
            synthesis = await llm.ainvoke([
                _AGGREGATE_PROMPT,
                HumanMessage(content=combined),
            ])
            final_answer = synthesis.content

        return {"messages": [AIMessage(content=final_answer)]}

    # ── 上下文压缩节点（Compaction）─────────────────────────────
    async def summarizer_node(state: SupervisorState) -> dict:
        """
        长对话压缩节点，每次对话入口自动触发检查。

        原理（和 Claude Code /compact 一样）：
          - 消息数 ≤ 阈值：直接跳过，不做任何处理
          - 消息数 > 阈值：把旧消息交给 LLM 总结成一段摘要，
            用摘要替换旧消息，只保留最近几条保持连贯性

        效果：无论对话多长，传给 LLM 的 token 数始终可控。
        """
        messages = state["messages"]
        # 阈值：保留最近 6 条，超过 20 条总量时触发压缩
        KEEP_RECENT = 6
        TRIGGER_AT  = 20

        if len(messages) <= TRIGGER_AT:
            return {}   # 消息不多，直接跳过

        to_compress = messages[:-KEEP_RECENT]
        recent      = messages[-KEEP_RECENT:]

        logger.info("[Summarizer] 消息数 %d 超过阈值，开始压缩 %d 条旧消息",
                    len(messages), len(to_compress))

        summary = await llm.ainvoke([
            SystemMessage(
                "请简洁总结以下对话的核心内容，保留：已完成的事项、重要决策、关键结论。"
                "不要遗漏任何重要信息，但去掉无意义的闲聊。"
            ),
            *to_compress,
        ])

        compressed = [
            SystemMessage(content=f"【历史对话摘要】\n{summary.content}"),
            *recent,
        ]
        logger.info("[Summarizer] 压缩完成：%d 条 → %d 条", len(messages), len(compressed))
        return {"messages": compressed}

    # ── 组装图 ────────────────────────────────────────────────
    g = StateGraph(SupervisorState)

    g.add_node("summarizer",  summarizer_node)   # ← 新增：入口处自动压缩
    g.add_node("router",      router_node)
    g.add_node("code_agent",  code_agent_node)
    g.add_node("file_agent",  file_agent_node)
    g.add_node("general",     general_node)
    g.add_node("aggregator",  aggregator_node)

    g.set_entry_point("summarizer")              # ← 入口改为 summarizer
    g.add_edge("summarizer", "router")           # summarizer → router
    g.add_conditional_edges("router", fan_out, ["code_agent", "file_agent", "general"])
    g.add_edge("code_agent", "aggregator")
    g.add_edge("file_agent", "aggregator")
    g.add_edge("general",    "aggregator")
    g.add_edge("aggregator", END)

    return g


# ── 模块级 graph（LangGraph Studio 入口）─────────────────────
from agent_lab.app.core.config import settings
from langchain_openai import ChatOpenAI
import httpx

_llm = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_API_BASE,
    model=settings.MODEL_NAME,
    http_async_client=httpx.AsyncClient(
        verify=not settings.SKIP_SSL_VERIFY,
        timeout=settings.REQUEST_TIMEOUT,
    ),
    max_retries=2,
)

# 创建共享 SkillRegistry，注册所有工具的 embedding
_embedder = OpenAIEmbeddings(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_API_BASE,
    model=settings.EMBEDDING_MODEL_NAME,
    http_client=httpx.Client(verify=not settings.SKIP_SSL_VERIFY),
)

_registry = SkillRegistry(_embedder)
_registry.register(code_tools + file_tools + general_tools)

graph = build_supervisor(_llm, _registry).compile()
