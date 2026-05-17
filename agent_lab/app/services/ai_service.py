from langchain_openai import ChatOpenAI
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent_lab.app.agents.supervisor    import build_supervisor
from agent_lab.app.agents.code_agent    import build_code_subgraph
from agent_lab.app.agents.file_agent    import build_file_subgraph
from agent_lab.app.agents.batch_agent   import build_batch_graph
from agent_lab.app.agents.general_agent import build_general_subgraph
from agent_lab.app.services.tools import code_tools, file_tools, general_tools
from agent_lab.app.services.skill_registry import SkillRegistry
from agent_lab.app.rag.pipeline import init_pipeline
from agent_lab.app.rag.rag_tools import rag_tools
from agent_lab.app.core.config import settings
from agent_lab.app.core.logger import get_logger
import httpx
import aiosqlite

logger = get_logger("ai_service")

_VALID_AGENTS = {"supervisor", "code", "file", "batch", "general"}


class AIService:
    def __init__(self, db_path: str = "langgraph_checkpoint.db"):
        self._db_path = db_path
        self._llm = self._make_llm_from_config(None)   # 默认 LLM（来自 .env）

        embedder = FastEmbedEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
        self._registry = SkillRegistry(embedder)

        self._agent = None          # Supervisor 图（懒初始化，使用默认 LLM）
        self._agents: dict = {}     # 子 Agent 图缓存（默认 LLM）

        self._rag_pipeline = init_pipeline(embedder)
        connected = self._rag_pipeline.connect()
        if connected:
            logger.info("[AIService] RAG Pipeline 就绪，知识库 chunk 数: %d",
                        self._rag_pipeline.chunk_count)
        else:
            logger.warning("[AIService] Milvus 未启动，RAG 工具降级运行")

    # ── LLM 工厂 ─────────────────────────────────────────────────

    def _make_llm_from_config(self, cfg) -> ChatOpenAI:
        """
        根据单个 AgentLLMConfig（或 None）构造 LLM。
        cfg 为 None / 字段全空时，回退到 settings.py 的默认值。
        """
        return ChatOpenAI(
            api_key  = (cfg and cfg.api_key)  or settings.OPENAI_API_KEY,
            base_url = (cfg and cfg.api_base) or settings.OPENAI_API_BASE,
            model    = (cfg and cfg.model)    or settings.MODEL_NAME,
            http_async_client=httpx.AsyncClient(
                verify=not settings.SKIP_SSL_VERIFY,
                timeout=settings.REQUEST_TIMEOUT,
                http2=False,
            ),
            max_retries=2,
        )

    def _build_llms_dict(self, agent_configs: dict | None) -> dict:
        """
        把前端传来的 agent_configs dict 转换为 llms 字典。
        agent_configs 键名：supervisor / code / file / general / batch
        缺失 / 全空的键使用默认 LLM（self._llm）。
        """
        result = {"supervisor": self._llm}
        if not agent_configs:
            return result
        for name in ("supervisor", "code", "file", "general", "batch"):
            cfg = agent_configs.get(name)
            if cfg and any([cfg.model, cfg.api_base, cfg.api_key]):
                result[name] = self._make_llm_from_config(cfg)
            else:
                result[name] = self._llm
        return result

    def _is_default_config(self, agent_configs: dict | None) -> bool:
        """是否全部使用默认配置（可走缓存路径）。"""
        if not agent_configs:
            return True
        return all(
            not any([cfg.model, cfg.api_base, cfg.api_key])
            for cfg in agent_configs.values()
            if cfg is not None
        )

    # ── 工具注册表初始化 ──────────────────────────────────────────

    def _ensure_registry(self):
        if not self._registry._names:
            logger.info("[AIService] 初始化 SkillRegistry，注册工具...")
            all_tools = code_tools + file_tools + general_tools + rag_tools
            self._registry.register(all_tools)

    # ── Supervisor 懒初始化 ───────────────────────────────────────

    async def _ensure_supervisor(self):
        """使用默认 LLM 初始化 Supervisor（仅在第一次调用时执行，之后复用）。"""
        if self._agent is None:
            self._ensure_registry()
            conn = await aiosqlite.connect(self._db_path)
            memory = AsyncSqliteSaver(conn)
            self._agent = build_supervisor(
                {"supervisor": self._llm}, self._registry
            ).compile(checkpointer=memory, interrupt_before=["code_agent"])
            logger.info("Supervisor 初始化完成，节点: %s",
                        list(self._agent.get_graph().nodes.keys()))
        return self._agent

    async def _build_supervisor_with_llms(self, llms: dict):
        """使用指定 llms 字典临时构建 Supervisor（不覆盖缓存，共享 SQLite DB）。"""
        self._ensure_registry()
        conn = await aiosqlite.connect(self._db_path)
        memory = AsyncSqliteSaver(conn)
        return build_supervisor(llms, self._registry).compile(
            checkpointer=memory, interrupt_before=["code_agent"]
        )

    # ── 子 Agent 懒初始化 ─────────────────────────────────────────

    async def _get_subagent(self, name: str):
        """使用默认 LLM 获取缓存的子 Agent 图。"""
        if name not in self._agents:
            self._ensure_registry()
            conn = await aiosqlite.connect(self._db_path)
            memory = AsyncSqliteSaver(conn)
            self._agents[name] = self._build_subagent(name, self._llm, memory)
            logger.info("[AIService] 子 Agent '%s' 初始化完成", name)
        return self._agents[name]

    def _build_subagent(self, name: str, llm, memory):
        """用指定 llm 和 memory 构建子 Agent 图（不缓存）。"""
        self._ensure_registry()
        builders = {
            "code":    lambda: build_code_subgraph(llm, self._registry, checkpointer=memory),
            "file":    lambda: build_file_subgraph(llm, self._registry, checkpointer=memory),
            "batch":   lambda: build_batch_graph(llm, checkpointer=memory),
            "general": lambda: build_general_subgraph(llm, self._registry, checkpointer=memory),
        }
        if name not in builders:
            raise ValueError(f"未知子 Agent: {name}")
        return builders[name]()

    # ── 核心流式接口 ─────────────────────────────────────────────

    async def astream_chat(
        self,
        session_id: str,
        content: str,
        agent: str = "supervisor",
        agent_configs: dict | None = None,
    ):
        """
        流式生成器：逐 chunk yield 事件 dict。

        事件格式：
          {"type": "chunk",     "content": "文本..."}       ← 正常 token
          {"type": "interrupt", "node": "code_agent",
           "content": "即将执行代码 Agent，是否确认继续？"}   ← HITL 暂停
          （"done" 由 SSE 层附加，此处不 yield）

        agent_configs 键名：supervisor / code / file / general / batch
        各键对应一个 AgentLLMConfig（model / api_base / api_key）。
        缺失 / 全空 → 使用后端 .env 默认值，并走缓存路径。
        """
        if agent not in _VALID_AGENTS:
            logger.warning("[AIService] 未知 agent '%s'，回退到 supervisor", agent)
            agent = "supervisor"

        use_default = self._is_default_config(agent_configs)
        llms = self._build_llms_dict(agent_configs)

        thread_id = f"{agent}:{session_id}"
        config = {"configurable": {"thread_id": thread_id}}

        logger.info("[%s/%s] 用户: %s (configs=%s)",
                    agent, session_id, content[:60],
                    "default" if use_default else list(llms.keys()))

        # ── Batch Agent：全量完成后一次性输出 ───────────────────
        if agent == "batch":
            batch_llm = llms.get("batch", self._llm)
            graph = (
                await self._get_subagent("batch")
                if use_default
                else self._build_subagent("batch", batch_llm, memory=None)
            )
            result = await graph.ainvoke(
                {"request": content, "subtasks": [], "results": [], "final_summary": ""},
                config=config,
            )
            yield {"type": "chunk", "content": result.get("final_summary", "（批处理完成，无汇总内容）")}
            return

        # ── Supervisor ───────────────────────────────────────────
        if agent == "supervisor":
            graph = (
                await self._ensure_supervisor()
                if use_default
                else await self._build_supervisor_with_llms(llms)
            )
        # ── 直连子 Agent ─────────────────────────────────────────
        else:
            agent_llm = llms.get(agent, self._llm)
            graph = (
                await self._get_subagent(agent)
                if use_default
                else self._build_subagent(agent, agent_llm, memory=None)
            )

        async for msg, _meta in graph.astream(
            {"messages": [("user", content)]},
            config=config,
            stream_mode="messages",
        ):
            if (
                isinstance(msg, AIMessageChunk)
                and msg.content
                and not getattr(msg, "tool_calls", None)
            ):
                yield {"type": "chunk", "content": msg.content}

        # ── HITL 检测：流结束后检查图是否处于暂停状态 ────────────
        if agent == "supervisor":
            state = await graph.aget_state(config)
            if state.next:
                pending = state.next[0]
                node_labels = {"code_agent": "代码执行 Agent"}
                label = node_labels.get(pending, pending)
                logger.info("[HITL] session=%s 图暂停，等待确认节点: %s", session_id, pending)
                yield {
                    "type": "interrupt",
                    "node": pending,
                    "content": f"即将执行「{label}」，是否确认继续？",
                }

    # ── HITL 恢复接口 ────────────────────────────────────────────

    async def aresume_chat(
        self,
        session_id: str,
        agent: str = "supervisor",
        approved: bool = True,
    ):
        """
        恢复被 HITL interrupt_before 暂停的 Supervisor 图。

        approved=True  → 继续执行被暂停的节点，流式输出结果
        approved=False → 向状态注入"已取消"结果，跳过暂停节点直接聚合
        """
        if agent != "supervisor":
            yield {"type": "error", "content": "HITL 仅支持 supervisor 模式"}
            return

        thread_id = f"{agent}:{session_id}"
        config = {"configurable": {"thread_id": thread_id}}
        graph = await self._ensure_supervisor()

        # 确认图确实处于暂停状态
        state = await graph.aget_state(config)
        if not state.next:
            yield {"type": "error", "content": "当前会话没有待确认的操作"}
            return

        pending_node = state.next[0]
        logger.info("[HITL] session=%s approved=%s node=%s", session_id, approved, pending_node)

        if not approved:
            # 以被暂停节点的身份注入"已取消"结果，让图继续走到 aggregator
            from langchain_core.messages import AIMessage
            await graph.aupdate_state(
                config,
                {"code_result": "用户已取消，代码 Agent 执行被中止。"},
                as_node=pending_node,
            )

        # 恢复图（None 表示不注入新消息，从当前 checkpoint 继续）
        async for msg, _meta in graph.astream(
            None,
            config=config,
            stream_mode="messages",
        ):
            if (
                isinstance(msg, AIMessageChunk)
                and msg.content
                and not getattr(msg, "tool_calls", None)
            ):
                yield {"type": "chunk", "content": msg.content}

        # 恢复后再次检测是否还有下一个 interrupt
        state = await graph.aget_state(config)
        if state.next:
            pending = state.next[0]
            node_labels = {"code_agent": "代码执行 Agent"}
            label = node_labels.get(pending, pending)
            yield {
                "type": "interrupt",
                "node": pending,
                "content": f"即将执行「{label}」，是否确认继续？",
            }

    # ── CLI 兼容接口 ─────────────────────────────────────────────

    async def chat(self, session_id: str, content: str):
        print(f"[{session_id}] AI > ", end="", flush=True)
        async for event in self.astream_chat(session_id, content):
            if event.get("type") == "chunk":
                print(event["content"], end="", flush=True)
        print()


ai_service = AIService()
