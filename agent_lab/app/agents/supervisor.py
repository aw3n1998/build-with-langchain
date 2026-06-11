from langchain_core.messages import SystemMessage, AIMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.types import Send
from agent_lab.app.agents.state import SupervisorState
from agent_lab.app.agents.code_agent import build_code_subgraph
from agent_lab.app.agents.file_agent import build_file_subgraph
from agent_lab.app.services.tools import code_tools, file_tools, shell_tools, general_tools
from agent_lab.app.services.stream_events import emit_tool_call, emit_tool_result
from agent_lab.app.services.skill_registry import SkillRegistry
from agent_lab.app.services.msg_utils import sanitize_messages
from agent_lab.app.core.logger import get_logger

logger = get_logger("supervisor")

_ROUTER_PROMPT = SystemMessage(content=(
    "你是一个任务分发器。根据用户最新消息，选择需要的处理器（可多选，逗号分隔）：\n"
    "- code    （需要编写或执行 Python 代码）\n"
    "- file    （需要列出目录或读取文件内容）\n"
    "- shell   （需要执行系统命令，如 ls/git/grep/ps 等）\n"
    "- general （可直接回答，如查时间、聊天、问答）\n\n"
    "只输出选中的词，用逗号分隔，例如：code,shell\n"
    "不要输出任何解释。"
))

_GENERAL_PROMPT = SystemMessage(content="你是专业AI助手，直接回答用户问题，可以查询当前时间。")

_AGGREGATE_PROMPT = SystemMessage(content=(
    "多个专业 Agent 已并行处理了用户的请求，以下是各 Agent 的结果。"
    "请将它们整合成一个连贯、清晰的回答，不要重复说明来源。"
))


def build_supervisor(llms: dict, registry: SkillRegistry):
    """
    并行多 Agent Supervisor，所有子 Agent 共用同一个 SkillRegistry。

    llms 格式：
        {"supervisor": llm_sup, "code": llm_code, "file": llm_file, "general": llm_general}
    缺失的键自动回退到 llms["supervisor"]，即主 Agent 的 LLM。

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
    # 从 llms 字典取各角色 LLM，缺失则用 supervisor LLM
    sup_llm     = llms["supervisor"]
    code_llm    = llms.get("code",    sup_llm)
    file_llm    = llms.get("file",    sup_llm)
    general_llm = llms.get("general", sup_llm)

    code_graph = build_code_subgraph(code_llm, registry)
    file_graph = build_file_subgraph(file_llm, registry)

    # ── 路由节点 ───────────────────────────────────────────────
    async def router_node(state: SupervisorState) -> dict:
        last_human = next(
            (m for m in reversed(state["messages"]) if m.type == "human"), None
        )
        decision = await sup_llm.ainvoke([_ROUTER_PROMPT, last_human])
        raw = decision.content.strip().lower()
        valid = ("code", "file", "shell", "general")
        agents = [a.strip() for a in raw.split(",") if a.strip() in valid]
        if not agents:
            agents = ["general"]
        logger.info("[Supervisor] 并行路由 → %s", agents)
        return {
            "selected_agents": agents,
            "code_result": "",
            "file_result": "",
            "shell_result": "",
            "general_result": "",
        }

    # ── Send 扇出函数（条件边）────────────────────────────────
    def fan_out(state: SupervisorState) -> list[Send]:
        node_map = {
            "code":    "code_agent",
            "file":    "file_agent",
            "shell":   "shell_agent",
            "general": "general",
        }
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

    async def shell_agent_node(state: SupervisorState) -> dict:
        """Shell Agent：执行白名单 shell 命令（ls/git/grep/ps 等只读命令）。"""
        logger.info("[ShellAgent] 开始执行")
        query = next(
            (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
        )
        shell_llm = llms.get("shell", sup_llm)
        llm_with_tools = shell_llm.bind_tools(shell_tools)
        tools_map = {t.name: t for t in shell_tools}
        _shell_prompt = SystemMessage(content=(
            "你是一个系统信息查询专家，只能使用 run_shell_command 工具执行命令。\n"
            "只执行只读/查询类命令，严禁写文件、删除、网络操作。\n"
            "完成后用中文简洁汇报结果。"
        ))
        response = await llm_with_tools.ainvoke([_shell_prompt] + sanitize_messages(state["messages"]))
        messages = [response]
        while getattr(messages[-1], "tool_calls", None):
            tool_results = []
            for tc in messages[-1].tool_calls:
                emit_tool_call(tc["name"], tc.get("args"))
                tool = tools_map.get(tc["name"])
                if tool:
                    try:
                        res = await tool.ainvoke(tc["args"])
                    except Exception as e:  # noqa: BLE001
                        res = f"[工具执行失败] {tc['name']}: {type(e).__name__}: {e}"
                    emit_tool_result(tc["name"], res)
                    tool_results.append(ToolMessage(content=str(res), tool_call_id=tc["id"]))
            messages.extend(tool_results)
            response = await llm_with_tools.ainvoke([_shell_prompt] + sanitize_messages(state["messages"]) + messages)
            messages.append(response)
        final = messages[-1]
        return {"shell_result": final.content if isinstance(final, AIMessage) else ""}

    async def general_node(state: SupervisorState) -> dict:
        """General Agent：动态检索工具，按需调用。使用 general_llm（可与 supervisor 不同）。"""
        logger.info("[General] 开始执行")
        query = next(
            (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
        )
        retrieved = await registry.search(query, top_k=3)
        logger.info("[General] skill_retrieval → %s", [t.name for t in retrieved])

        llm_dynamic = general_llm.bind_tools(retrieved)
        tools_map = {t.name: t for t in retrieved}

        response = await llm_dynamic.ainvoke([_GENERAL_PROMPT] + sanitize_messages(state["messages"]))
        messages = [response]
        while getattr(messages[-1], "tool_calls", None):
            tool_results = []
            for tc in messages[-1].tool_calls:
                emit_tool_call(tc["name"], tc.get("args"))
                tool = tools_map.get(tc["name"])
                if tool is None:  # 召回里没有时回退全局 registry，避免 KeyError 崩图
                    try:
                        tool = registry.get(tc["name"])
                    except Exception:
                        tool = None
                if tool is None:
                    result = f"[工具不可用] {tc['name']}"
                else:
                    try:
                        result = await tool.ainvoke(tc["args"])
                    except Exception as e:  # noqa: BLE001
                        result = f"[工具执行失败] {tc['name']}: {type(e).__name__}: {e}"
                emit_tool_result(tc["name"], result)
                tool_results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
            messages.extend(tool_results)
            follow_up = await llm_dynamic.ainvoke(
                [_GENERAL_PROMPT] + sanitize_messages(state["messages"]) + messages
            )
            messages.append(follow_up)
        return {"general_result": messages[-1].content}

    # ── 汇聚节点 ──────────────────────────────────────────────
    async def aggregator_node(state: SupervisorState) -> dict:
        active = {
            k: v for k, v in {
                "code":    state.get("code_result", ""),
                "file":    state.get("file_result", ""),
                "shell":   state.get("shell_result", ""),
                "general": state.get("general_result", ""),
            }.items() if v
        }
        logger.info("[Aggregator] 汇聚结果来自: %s", list(active.keys()))

        if len(active) == 1:
            final_answer = list(active.values())[0]
        else:
            combined = "\n\n".join(f"【{k} Agent】\n{v}" for k, v in active.items())
            synthesis = await sup_llm.ainvoke([
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
          - 真实 token 用量 < 窗口×比例：跳过
          - 达到阈值：把旧消息交给 LLM 总结成一段摘要，
            用摘要替换旧消息，只保留最近几条保持连贯性

        触发以**真实 token 用量**为准（与前端进度条一致），而非消息条数。
        """
        from agent_lab.app.services.context_meter import usage

        messages = state["messages"]
        KEEP_RECENT = 6

        u = usage(messages)
        if not u["will_compact"] or len(messages) <= KEEP_RECENT:
            return {}   # 未达上下文窗口阈值，跳过

        to_compress = messages[:-KEEP_RECENT]
        recent      = messages[-KEEP_RECENT:]

        logger.info("[Summarizer] token %d/%d 达阈值 %d，压缩 %d 条旧消息",
                    u["tokens"], u["window"], u["trigger_tokens"], len(to_compress))

        summary = await sup_llm.ainvoke([
            SystemMessage(
                "请简洁总结以下对话的核心内容，保留：已完成的事项、重要决策、关键结论。"
                "不要遗漏任何重要信息，但去掉无意义的闲聊。"
            ),
            *sanitize_messages(to_compress),
        ])

        compressed = [
            SystemMessage(content=f"【历史对话摘要】\n{summary.content}"),
            *recent,
        ]
        logger.info("[Summarizer] 压缩完成：%d 条 → %d 条", len(messages), len(compressed))
        return {"messages": compressed}

    # ── 组装图 ────────────────────────────────────────────────
    g = StateGraph(SupervisorState)

    g.add_node("summarizer",  summarizer_node)
    g.add_node("router",      router_node)
    g.add_node("code_agent",  code_agent_node)
    g.add_node("file_agent",  file_agent_node)
    g.add_node("shell_agent", shell_agent_node)
    g.add_node("general",     general_node)
    g.add_node("aggregator",  aggregator_node)

    g.set_entry_point("summarizer")
    g.add_edge("summarizer", "router")
    g.add_conditional_edges(
        "router", fan_out,
        ["code_agent", "file_agent", "shell_agent", "general"]
    )
    g.add_edge("code_agent",  "aggregator")
    g.add_edge("file_agent",  "aggregator")
    g.add_edge("shell_agent", "aggregator")
    g.add_edge("general",     "aggregator")
    g.add_edge("aggregator",  END)

    return g


# ── 模块级 graph（LangGraph Studio 入口）─────────────────────
from agent_lab.app.core.config import settings
from langchain_openai import ChatOpenAI
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
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

# 创建共享 SkillRegistry，使用本地 FastEmbed 模型（无需 API，首次运行自动下载）
try:
    _embedder = FastEmbedEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
    _registry = SkillRegistry(_embedder)
    _registry.register(code_tools + file_tools + shell_tools + general_tools)
    graph = build_supervisor({"supervisor": _llm}, _registry).compile()
except Exception as e:
    logger.warning("LangGraph Studio graph 初始化失败（首次运行需下载模型）: %s", e)
    graph = None
