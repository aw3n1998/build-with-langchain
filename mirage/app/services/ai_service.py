from langchain_openai import ChatOpenAI
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_core.messages import AIMessageChunk, AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from mirage.app.agents.supervisor    import build_supervisor
from mirage.app.services.tools import code_tools, file_tools, shell_tools, general_tools
from mirage.app.services.skill_registry import SkillRegistry
from mirage.app.services.agent_registry import agent_registry
from mirage.app.pipeline.pipeline_tools import pipeline_tools
from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
import httpx
import aiosqlite
import os

logger = get_logger("ai_service")

_VALID_AGENTS = {"supervisor"} | agent_registry.get_valid_agents()


class AIService:
    def __init__(self, db_path: str = "langgraph_checkpoint.db"):
        self._db_path = db_path
        self._llm = self._make_llm_from_config(None)   # 默认 LLM（来自 .env）
        self._storyboard_llm = None                    # 分镜专属 LLM（懒构造；空配置=复用默认 _llm）

        embedder = FastEmbedEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
        self._registry = SkillRegistry(embedder)

        self._agent = None          # Supervisor 图（懒初始化，使用默认 LLM）
        self._agents: dict = {}     # 子 Agent 图缓存（默认 LLM）
        # 会话粘性路由：记住每个会话上次自动路由到的子 Agent。
        # 用户回「可以/继续/好的」这类无关键词短语时跟随上次，而不是掉回 supervisor——
        # 否则对话记忆会被切到另一条线程，表现为"agent 失忆"。
        self._session_agents: dict[str, str] = {}

    # ── LLM 工厂 ─────────────────────────────────────────────────

    def _make_llm_from_config(self, cfg) -> ChatOpenAI:
        """
        根据单个 AgentLLMConfig（或 None）构造 LLM。
        cfg 为 None / 字段全空时，回退到 settings.py 的默认值。

        代理说明：langchain-openai 传入 http_async_client 后会禁用环境变量代理自动检测，
        所以在此显式读取 HTTPS_PROXY / HTTP_PROXY 并传给 httpx.AsyncClient。
        """
        proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None
        max_tokens = (cfg and getattr(cfg, "max_tokens", None)) or settings.MAX_TOKENS
        # 占位 key 兜底：没配 LLM 也能构造(后端启动不崩)；真调用时才因假 key 报 401，对纯出片/出图无影响。
        api_key  = (cfg and cfg.api_key)  or settings.OPENAI_API_KEY or "sk-no-llm-key-set"
        base_url = (cfg and cfg.api_base) or settings.OPENAI_API_BASE
        model    = (cfg and cfg.model)    or settings.MODEL_NAME
        extra: dict = {}
        # OpenRouter 可选归属头(用了 openrouter base 才带;非必填,但部分免费模型/排行需要)。
        if "openrouter" in (base_url or "").lower():
            hdrs = {}
            if settings.OPENROUTER_REFERER:
                hdrs["HTTP-Referer"] = settings.OPENROUTER_REFERER
            if settings.OPENROUTER_TITLE:
                hdrs["X-Title"] = settings.OPENROUTER_TITLE
            if hdrs:
                extra["default_headers"] = hdrs
        return ChatOpenAI(
            api_key=api_key, base_url=base_url, model=model,
            max_tokens=max_tokens,
            http_async_client=httpx.AsyncClient(
                verify=not settings.SKIP_SSL_VERIFY,
                timeout=settings.REQUEST_TIMEOUT,
                http2=False,
                proxy=proxy_url,        # 显式传代理，绕过 langchain-openai 的 transport 覆盖
            ),
            max_retries=2,
            **extra,
        )

    @property
    def storyboard_llm(self):
        """分镜专属 LLM:配了 STORYBOARD_* 就用独立后端(如 OpenRouter/grok),否则复用默认 _llm。

        通用解耦:未配=分镜跟全局走同一个 LLM;配了=分镜单独走它(其余 agent 不受影响)。
        """
        if self._storyboard_llm is not None:
            return self._storyboard_llm
        if settings.STORYBOARD_API_KEY or settings.STORYBOARD_API_BASE or settings.STORYBOARD_MODEL:
            from types import SimpleNamespace
            cfg = SimpleNamespace(
                api_key=settings.STORYBOARD_API_KEY or settings.OPENAI_API_KEY,
                api_base=settings.STORYBOARD_API_BASE or settings.OPENAI_API_BASE,
                model=settings.STORYBOARD_MODEL or settings.MODEL_NAME,
                max_tokens=None,
            )
            self._storyboard_llm = self._make_llm_from_config(cfg)
        else:
            self._storyboard_llm = self._llm
        return self._storyboard_llm

    def storyboard_llm_for(self, cfg=None):
        """按前端「导演/分镜模型」现造分镜 LLM（通用解耦的回退链顶层）。

        - cfg 非空（前端 Settings 填了 model/api_base/api_key）→ 按它**现造**(UI 覆盖，不缓存，避免串配置)；
        - cfg 空 → 回退 storyboard_llm（→ STORYBOARD_* env → 全局默认 _llm）。
        cfg 可为 AgentLLMConfig 对象或 dict（前端经路由透传 supervisor 键）。
        """
        if cfg is not None:
            if isinstance(cfg, dict):
                from types import SimpleNamespace
                cfg = SimpleNamespace(
                    model=cfg.get("model"), api_base=cfg.get("api_base"),
                    api_key=cfg.get("api_key"), max_tokens=cfg.get("max_tokens"),
                )
            if any([getattr(cfg, "model", None), getattr(cfg, "api_base", None),
                    getattr(cfg, "api_key", None)]):
                return self._make_llm_from_config(cfg)
        return self.storyboard_llm

    def _build_llms_dict(self, agent_configs: dict | None) -> dict:
        """
        把前端传来的 agent_configs dict 转换为 llms 字典。
        agent_configs 键名：supervisor / code / file / general / batch
        缺失 / 全空的键使用默认 LLM（self._llm）。
        """
        result = {"supervisor": self._llm}
        if not agent_configs:
            return result
        for name in ("supervisor", "code", "file", "general", "batch", "shell"):
            cfg = agent_configs.get(name)
            if cfg and any([cfg.model, cfg.api_base, cfg.api_key,
                            getattr(cfg, "max_tokens", None)]):
                result[name] = self._make_llm_from_config(cfg)
            else:
                result[name] = self._llm
        return result

    def _is_default_config(self, agent_configs: dict | None) -> bool:
        """是否全部使用默认配置（可走缓存路径）。"""
        if not agent_configs:
            return True
        return all(
            not any([cfg.model, cfg.api_base, cfg.api_key,
                     getattr(cfg, "max_tokens", None)])
            for cfg in agent_configs.values()
            if cfg is not None
        )

    # ── 工具注册表初始化 ──────────────────────────────────────────

    def _ensure_registry(self):
        if not self._registry._names:
            logger.info("[AIService] 初始化 SkillRegistry，注册工具...")
            all_tools = code_tools + file_tools + shell_tools + general_tools + pipeline_tools
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
        """用指定 llm 和 memory 构建插拔式子 Agent 图（不缓存）。"""
        self._ensure_registry()
        import inspect

        agent_meta = agent_registry.get_agent(name)
        if not agent_meta:
            raise ValueError(f"未知子 Agent: {name}")

        builder = agent_meta.builder
        sig = inspect.signature(builder)
        kwargs = {}

        # 动态匹配与绑定参数
        if "llm" in sig.parameters:
            kwargs["llm"] = llm
        if "checkpointer" in sig.parameters:
            kwargs["checkpointer"] = memory
        elif "memory" in sig.parameters:
            kwargs["memory"] = memory
        if "registry" in sig.parameters:
            kwargs["registry"] = self._registry

        try:
            return builder(**kwargs)
        except TypeError:
            # 如果解包绑定失败，则按老的位置顺序传参（针对 core 预注册）
            args = []
            for param_name in sig.parameters.keys():
                if param_name == "llm":
                    args.append(llm)
                elif param_name == "registry":
                    args.append(self._registry)
                elif param_name in ("checkpointer", "memory"):
                    args.append(memory)
            return builder(*args)

    # ── 核心流式接口 ─────────────────────────────────────────────

    @staticmethod
    def _extract_tool_markers(text: str):
        """从工具返回文本里抽出机器可读标记，转成前端事件，并返回清理后的展示文本。

        识别：
          PARAM_FORM::{json}                       → {"type":"param_form", ...}   弹出图参数卡
          IMGFILE::<scene_id>::<asset_id>::<abspath>→ {"type":"image", scene_id, asset_id, url, name}
        """
        import json as _json
        from urllib.parse import quote

        events = []
        kept_lines = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("PARAM_FORM::"):
                try:
                    payload = _json.loads(s[len("PARAM_FORM::"):])
                    events.append({"type": "param_form", **payload})
                except Exception:
                    kept_lines.append(line)
            elif s.startswith("VIDEO_PARAM_FORM::"):
                try:
                    payload = _json.loads(s[len("VIDEO_PARAM_FORM::"):])
                    events.append({"type": "video_param_form", **payload})
                except Exception:
                    kept_lines.append(line)
            elif s.startswith("PRODUCTION::"):
                pid = s[len("PRODUCTION::"):].strip()
                if pid:
                    events.append({"type": "production", "project_id": pid})
            elif s.startswith("VIDFILE::"):
                parts = s.split("::", 2)
                if len(parts) == 3:
                    scene_id, abspath = parts[1], parts[2]
                    events.append({
                        "type": "video",
                        "scene_id": scene_id,
                        "name": os.path.basename(abspath),
                        "url": f"/api/file?path={quote(abspath)}",
                    })
                else:
                    kept_lines.append(line)
            elif s.startswith("IMGFILE::"):
                parts = s.split("::", 3)
                if len(parts) == 4:
                    scene_id, asset_id, abspath = parts[1], parts[2], parts[3]
                    events.append({
                        "type": "image",
                        "scene_id": scene_id,
                        "asset_id": asset_id,
                        "name": os.path.basename(abspath),
                        "url": f"/api/file?path={quote(abspath)}",
                    })
                else:
                    kept_lines.append(line)
            else:
                kept_lines.append(line)
        return "\n".join(kept_lines), events

    def _detect_agent_intent(self, content: str) -> str:
        """
        根据用户输入，自动检测并分发到特定的插拔式子 Agent 插件。
        """
        content_lower = content.lower()
        for name in agent_registry.get_valid_agents():
            meta = agent_registry.get_agent(name)
            if meta and meta.routing_keywords:
                if any(kw in content_lower for kw in meta.routing_keywords):
                    logger.info(f"[AIService] 发现关键词特征，自动重定向至插拔式子 Agent: '{name}'")
                    return name
        return "supervisor"

    async def astream_chat(
        self,
        session_id: str,
        content: str,
        agent: str = "supervisor",
        agent_configs: dict | None = None,
        workspace: str | None = None,
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
        # 设置本请求工作目录（出图/出视频落地根 + 静态服图根）
        from mirage.app.pipeline.runtime import set_workspace
        set_workspace(workspace)

        # 专用视频 Agent 模式：聊天直达视频 Agent，不再过 supervisor 的多路意图选择（功能专一）。
        # 不删其它 agent 文件/节点(避免 import/历史/interrupt_before 崩)，只是聊天不再路由到它们。
        from mirage.app.core.config import settings as _st
        if getattr(_st, "VIDEO_AGENT_ONLY", True) and agent == "supervisor":
            agent = "video"
            logger.info("[AIService] 专用视频模式：直达 video Agent")

        if agent == "supervisor":
            detected_agent = self._detect_agent_intent(content)
            if detected_agent == "supervisor":
                # 无关键词命中：跟随本会话上次的子 Agent（粘性路由），保证记忆连续
                sticky = self._session_agents.get(session_id, "supervisor")
                if sticky != "supervisor":
                    logger.info("[AIService] 无关键词，粘性跟随上次 agent: %s", sticky)
                    detected_agent = sticky
            if detected_agent != "supervisor":
                logger.info(f"[AIService] 意图自适应分发：supervisor ➔ {detected_agent}")
                agent = detected_agent
        if agent != "supervisor":
            self._session_agents[session_id] = agent   # 记住，供下一条短回复跟随

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
            # 子 Agent 没有专属配置时，继承 supervisor 的全局设置（思考程度/长度），
            # 这样输入栏的「思考/长度」也能作用到 video/file 等子 Agent。
            agent_llm = llms.get(agent) or llms.get("supervisor") or self._llm
            if use_default:
                graph = await self._get_subagent(agent)
            else:
                # 即使使用自定义 LLM，也必须传入 checkpointer
                # 因为 HITL 检测和补发逻辑都依赖 graph.aget_state()
                conn = await aiosqlite.connect(self._db_path)
                memory = AsyncSqliteSaver(conn)
                graph = self._build_subagent(agent, agent_llm, memory)

        # 只有声明为"用户可见"的节点的 LLM token 才推送给前端：
        #   supervisor  → general（通用问答）/ aggregator（多 Agent 汇聚）
        #   插拔式子 Agent → 由 AgentMetadata.user_facing_nodes 控制；None 则全部可见
        if agent == "supervisor":
            _USER_FACING_NODES = {"general", "aggregator"}
        else:
            meta = agent_registry.get_agent(agent)
            _USER_FACING_NODES = meta.user_facing_nodes if (meta and meta.user_facing_nodes) else None

        streamed_any = False
        async for item in graph.astream(
            {"messages": [("user", content)]},
            config=config,
            stream_mode=["messages", "custom"],
            subgraphs=True,   # 让子图（file/code/video）里发的 custom 工具事件冒泡上来
        ):
            # subgraphs=True 时每条是 (namespace, mode, payload)；否则 (mode, payload)
            if len(item) == 3:
                _ns, stream_mode, payload = item
            else:
                stream_mode, payload = item
            # ── 文本 token 流（用户可见节点的自然语言）──────────────
            if stream_mode == "messages":
                msg, _meta = payload
                node = _meta.get("langgraph_node", "")
                if _USER_FACING_NODES is not None and node not in _USER_FACING_NODES:
                    continue
                if (
                    isinstance(msg, AIMessageChunk)
                    and msg.content
                    and not getattr(msg, "tool_calls", None)
                ):
                    streamed_any = True
                    yield {"type": "chunk", "content": msg.content}
            # ── 自定义流：各 agent 节点主动上报的工具调用 / 结果 ──────
            # （general/shell/video 等节点用 stream_events.emit_* 发出，
            #   子图里发的也会冒泡到这里，从而"所有 agent 可见"）
            elif stream_mode == "custom":
                data = payload or {}
                kind = data.get("kind")
                if kind == "tool_call":
                    yield {"type": "tool_call", "name": data.get("name", ""),
                           "args": data.get("args", {})}
                elif kind == "tool_result":
                    clean, extra_events = self._extract_tool_markers(str(data.get("content", "")))
                    yield {"type": "tool_result", "name": data.get("name", ""),
                           "content": clean[:600]}
                    for ev in extra_events:
                        yield ev

        # ── 补发逻辑：若流式输出为空，检查最后一条 AI 消息并作为单个 chunk 输出 ──────────
        if not streamed_any:
            state = await graph.aget_state(config)
            messages = state.values.get("messages", [])
            if messages:
                last_msg = messages[-1]
                if isinstance(last_msg, AIMessage) and last_msg.content:
                    yield {"type": "chunk", "content": last_msg.content}

        # ── HITL 检测：流结束后检查图是否处于暂停状态 ────────────
        if agent in {"supervisor"} | agent_registry.get_valid_agents():
            state = await graph.aget_state(config)
            if state.next:
                pending = state.next[0]
                # 动态合并所有注册 Agent 的 node_labels 以支持热插拔
                global_node_labels = {}
                for a_name in agent_registry.get_valid_agents():
                    meta = agent_registry.get_agent(a_name)
                    if meta and meta.node_labels:
                        global_node_labels.update(meta.node_labels)
                label = global_node_labels.get(pending, pending)
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
        恢复被 HITL interrupt_before 暂停的 Supervisor 图或 Quality 图。

        approved=True  → 继续执行被暂停的节点，流式输出结果
        approved=False → 向状态注入"已取消"结果，跳过暂停节点直接聚合或返回中止消息
        """
        if agent == "supervisor":
            # 先检查 supervisor 图本身是否有挂起状态
            graph = await self._ensure_supervisor()
            state = await graph.aget_state({"configurable": {"thread_id": f"supervisor:{session_id}"}})
            if not state.next:
                # 若主 supervisor 图未挂起，扫描所有其他有效子 Agent 的线程状态进行自动重定向
                for a_name in agent_registry.get_valid_agents():
                    if a_name == "supervisor":
                        continue
                    sub_thread_id = f"{a_name}:{session_id}"
                    sub_config = {"configurable": {"thread_id": sub_thread_id}}
                    sub_graph = await self._get_subagent(a_name)
                    sub_state = await sub_graph.aget_state(sub_config)
                    if sub_state.next:
                        logger.info(f"[AIService] 检测到挂起的子 Agent 线程 '{a_name}'，自动重定向恢复")
                        agent = a_name
                        break

        if agent not in {"supervisor"} | agent_registry.get_valid_agents():
            yield {"type": "error", "content": f"HITL 不支持 {agent} 模式"}
            return

        thread_id = f"{agent}:{session_id}"
        config = {"configurable": {"thread_id": thread_id}}
        
        if agent == "supervisor":
            graph = await self._ensure_supervisor()
        else:
            graph = await self._get_subagent(agent)

        # 确认图确实处于暂停状态
        state = await graph.aget_state(config)
        if not state.next:
            yield {"type": "error", "content": "当前会话没有待确认的操作"}
            return

        pending_node = state.next[0]
        logger.info("[HITL] session=%s approved=%s node=%s", session_id, approved, pending_node)

        if agent == "quality":
            if approved:
                await graph.aupdate_state(
                    config,
                    {"confirmed": True},
                    as_node="draft_presenter",
                )
            else:
                await graph.aupdate_state(
                    config,
                    {"confirmed": False},
                    as_node="draft_presenter",
                )
        else:
            if not approved:
                # 以被暂停节点的身份注入"已取消"结果，让图继续走到 aggregator
                await graph.aupdate_state(
                    config,
                    {"code_result": "用户已取消，代码 Agent 执行被中止。"},
                    as_node=pending_node,
                )

        # 恢复图（None 表示不注入新消息，从当前 checkpoint 继续）
        streamed_any = False
        _USER_FACING_NODES = {"general", "aggregator"} if agent == "supervisor" else None
        async for msg, _meta in graph.astream(
            None,
            config=config,
            stream_mode="messages",
        ):
            node = _meta.get("langgraph_node", "")
            if _USER_FACING_NODES is not None and node not in _USER_FACING_NODES:
                continue
            if (
                isinstance(msg, AIMessageChunk)
                and msg.content
                and not getattr(msg, "tool_calls", None)
            ):
                streamed_any = True
                yield {"type": "chunk", "content": msg.content}

        # ── 补发逻辑：若流式输出为空，检查最后一条 AI 消息并作为单个 chunk 输出 ──────────
        if not streamed_any:
            state = await graph.aget_state(config)
            messages = state.values.get("messages", [])
            if messages:
                last_msg = messages[-1]
                if isinstance(last_msg, AIMessage) and last_msg.content:
                    yield {"type": "chunk", "content": last_msg.content}

        # 恢复后再次检测是否还有下一个 interrupt
        state = await graph.aget_state(config)
        if state.next:
            pending = state.next[0]
            # 动态合并所有注册 Agent 的 node_labels 以支持热插拔
            global_node_labels = {}
            for a_name in agent_registry.get_valid_agents():
                meta = agent_registry.get_agent(a_name)
                if meta and meta.node_labels:
                    global_node_labels.update(meta.node_labels)
            label = global_node_labels.get(pending, pending)
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
