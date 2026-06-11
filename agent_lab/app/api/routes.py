"""
FastAPI 路由层

接口设计原则：
  1. 聊天用 SSE（Server-Sent Events）流式推送，前端实时显示，不等整个回答完成
  2. RAG 导入用普通 POST，返回操作结果
  3. 所有接口统一返回结构，方便前端解析

SSE 格式（text/event-stream）：
  data: {"type": "chunk", "content": "你好"}
  data: {"type": "chunk", "content": "，我"}
  data: {"type": "done", "content": ""}

  每条消息以 \\n\\n 结尾，前端用 EventSource API 接收。
"""

import json
import os
import posixpath
import uuid
from typing import AsyncGenerator

from agent_lab.app.core.config import settings

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_lab.app.services.ai_service import ai_service
from agent_lab.app.core.logger import get_logger

logger = get_logger("api.routes")

router = APIRouter()


# ── 请求 / 响应 Schema ──────────────────────────────────────────

class AgentLLMConfig(BaseModel):
    """单个 Agent 的 LLM 配置，任意字段为 None 时回退到后端 .env 默认值。"""
    model:    str | None = Field(default=None, description="模型标识符")
    api_base: str | None = Field(default=None, description="LLM API base URL")
    api_key:  str | None = Field(default=None, description="LLM API key")
    max_tokens: int | None = Field(default=None, description="最大输出 token（上下文/回复长度）")


class ChatRequest(BaseModel):
    session_id: str = Field(
        default_factory=lambda: f"sid-{str(uuid.uuid4())[:8]}",
        description="会话 ID，同一个 session_id 共享对话历史",
    )
    content: str = Field(..., min_length=1, description="用户消息")
    agent: str = Field(
        default="supervisor",
        description="路由目标：supervisor | code | file | batch | general",
    )
    agent_configs: dict[str, AgentLLMConfig] | None = Field(
        default=None,
        description=(
            "各 Agent 的 LLM 配置（键名：supervisor/code/file/general/batch）。"
            "缺失的键使用后端 .env 默认值；整个字段为 null 时全部使用默认值。"
        ),
    )
    workspace: str | None = Field(
        default=None,
        description="本次对话的工作目录（出图/出视频落地根）；为空则用默认 agent_workspace。",
    )


class ResumeRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID，必须与原 chat 请求一致")
    agent: str = Field(default="supervisor", description="当前 agent（目前仅 supervisor 支持 HITL）")
    approved: bool = Field(default=True, description="True=继续执行，False=取消")


class IngestResponse(BaseModel):
    success: bool
    message: str
    session_id: str | None = None


class StatusResponse(BaseModel):
    rag_connected: bool
    chunk_count: int
    model: str


# ── 工具函数 ────────────────────────────────────────────────────

async def _events_to_sse(gen) -> AsyncGenerator[str, None]:
    """
    将 ai_service 事件生成器转成 SSE 格式字符串。
    ai_service 已经 yield dict（type/content/node），直接序列化转发。
    流结束后追加 done 帧。
    """
    try:
        async for event in gen:
            payload = json.dumps(event, ensure_ascii=False)
            yield f"data: {payload}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"
    except Exception as e:
        logger.exception("[SSE] 异常")
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"


async def sse_generator(
    session_id: str,
    content: str,
    agent: str = "supervisor",
    agent_configs: dict | None = None,
    workspace: str | None = None,
) -> AsyncGenerator[str, None]:
    """把 ai_service.astream_chat() 的事件流转成 SSE 格式。"""
    gen = ai_service.astream_chat(
        session_id, content, agent=agent, agent_configs=agent_configs, workspace=workspace
    )
    async for frame in _events_to_sse(gen):
        yield frame


async def sse_resume_generator(
    session_id: str,
    agent: str,
    approved: bool,
) -> AsyncGenerator[str, None]:
    """把 ai_service.aresume_chat() 的事件流转成 SSE 格式。"""
    gen = ai_service.aresume_chat(session_id, agent=agent, approved=approved)
    async for frame in _events_to_sse(gen):
        yield frame


# ── 路由 ────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """与 AI Agent 对话（SSE 流式）。"""
    # 汇总 agent_configs 日志（只记录非空的 agent）
    cfg_summary = {
        k: v.model or "default"
        for k, v in (request.agent_configs or {}).items()
        if v and v.model
    } or "default"
    logger.info("[Chat] session=%s agent=%s configs=%s msg=%s",
                request.session_id, request.agent, cfg_summary,
                request.content[:40])

    return StreamingResponse(
        sse_generator(
            request.session_id,
            request.content,
            request.agent,
            request.agent_configs,
            request.workspace,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/submit")
async def chat_submit(request: ChatRequest):
    """对话改后台任务：提交即返回 job_id，回合在服务端独立跑完（切会话/断网不丢）。

    前端用 /pipeline/jobs/{id}/events 跟随；停止生成用 /pipeline/jobs/{id}/cancel。
    """
    from agent_lab.app.services.job_manager import job_manager
    logger.info("[ChatSubmit] session=%s agent=%s msg=%s",
                request.session_id, request.agent, request.content[:40])
    job_id = job_manager.submit(
        "chat",
        lambda: ai_service.astream_chat(
            request.session_id, request.content, agent=request.agent,
            agent_configs=request.agent_configs, workspace=request.workspace),
        lane="chat",
        meta={"session_id": request.session_id},
    )
    return {"job_id": job_id}


@router.post("/chat/resume_submit")
async def chat_resume_submit(request: ResumeRequest):
    """HITL 恢复也走后台任务（与 /chat/submit 同语义）。"""
    from agent_lab.app.services.job_manager import job_manager
    job_id = job_manager.submit(
        "chat",
        lambda: ai_service.aresume_chat(
            request.session_id, agent=request.agent, approved=request.approved),
        lane="chat",
        meta={"session_id": request.session_id},
    )
    return {"job_id": job_id}


@router.websocket("/ws/jobs")
async def ws_jobs(websocket: WebSocket):
    """任务状态推送：连接即收到所有未完任务快照，此后每次状态变化实时推送。

    消息格式 {"type":"job_update","job_id","kind","status","session_id","error"}。
    前端据此点亮侧边栏绿点、并在所在会话任务完成时自动刷新历史。
    """
    from agent_lab.app.services.job_manager import job_manager
    await websocket.accept()
    q = job_manager.subscribe()
    try:
        while True:
            msg = await q.get()
            await websocket.send_json(msg)
    except (WebSocketDisconnect, Exception):  # noqa: BLE001 - 断开即清理
        pass
    finally:
        job_manager.unsubscribe(q)


@router.post("/pipeline/jobs/{job_id}/cancel")
async def pipeline_job_cancel(job_id: str):
    """取消任务：chat 回合可真取消；GPU 任务不可中断（返回 cancelled=false）。"""
    from agent_lab.app.services.job_manager import job_manager
    return {"cancelled": job_manager.cancel(job_id)}


@router.post("/chat/resume")
async def chat_resume(request: ResumeRequest) -> StreamingResponse:
    """
    恢复被 HITL 暂停的对话（SSE 流式）。

    前端在收到 {"type": "interrupt"} 后，由用户点击确认/取消，
    然后调用此接口继续或中止图的执行。
    """
    logger.info("[Resume] session=%s agent=%s approved=%s",
                request.session_id, request.agent, request.approved)
    return StreamingResponse(
        sse_resume_generator(request.session_id, request.agent, request.approved),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/rag/ingest/file", response_model=IngestResponse)
async def ingest_file(
    file: UploadFile = File(..., description="要导入的文档（.txt / .pdf / .docx）"),
    project_id: str = Form(default="default", description="项目 ID，多租户隔离用"),
):
    import tempfile, os, pathlib
    suffix = pathlib.Path(file.filename).suffix.lower()
    allowed = {".txt", ".pdf", ".docx"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型 {suffix}，支持：{allowed}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        pipeline = ai_service._rag_pipeline
        result = pipeline.ingest(tmp_path, project_id=project_id)
        success = result.startswith("✅")
        return IngestResponse(success=success, message=result)
    finally:
        os.unlink(tmp_path)


@router.post("/rag/ingest/text", response_model=IngestResponse)
async def ingest_text(
    content: str = Form(..., description="要导入的纯文本内容"),
    source_name: str = Form(default="inline", description="来源名称（显示在检索结果里）"),
    project_id: str = Form(default="default"),
):
    pipeline = ai_service._rag_pipeline
    result = pipeline.ingest_text(content, source_name=source_name, project_id=project_id)
    return IngestResponse(success=result.startswith("✅"), message=result)


@router.get("/rag/status", response_model=StatusResponse)
async def rag_status():
    from agent_lab.app.core.config import settings
    pipeline = ai_service._rag_pipeline
    return StatusResponse(
        rag_connected=pipeline.is_connected if pipeline else False,
        chunk_count=pipeline.chunk_count if pipeline else 0,
        model=settings.MODEL_NAME,
    )


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/history")
async def get_history():
    """获取所有历史会话"""
    try:
        await ai_service._ensure_supervisor()
        checkpointer = ai_service._agent.checkpointer
        
        # 一个页面会话可能跨多个 agent 线程（supervisor:sid / video:sid …）。
        # 按 session_id 归并去重：标题取首条用户消息，时间取最新，优先用 supervisor 线程。
        sessions = {}
        async for c in checkpointer.alist(None):
            thread_id = c.config.get("configurable", {}).get("thread_id", "")
            if ":" not in thread_id:
                continue
            agent_name, session_id = thread_id.split(":", 1)
            channel_values = c.checkpoint.get("channel_values", {})
            messages = channel_values.get("messages", [])
            if not messages:
                continue

            first_user_msg = next((m.content for m in messages if m.type == "human"), "")
            ts = c.checkpoint.get("ts")
            prev = sessions.get(session_id)
            # 选择规则：优先 supervisor 线程的标题；时间取所有线程里最新
            prefer = (agent_name == "supervisor")
            if prev is None:
                sessions[session_id] = {
                    "session_id": session_id,
                    "title": (first_user_msg[:40] if first_user_msg else "新会话"),
                    "updated_at": ts,
                    "message_count": len(messages),
                    "_from_supervisor": prefer,
                }
            else:
                if ts and (prev["updated_at"] is None or ts > prev["updated_at"]):
                    prev["updated_at"] = ts
                # 标题：若之前不是来自 supervisor，而当前是，则用当前的更可靠标题
                if prefer and not prev["_from_supervisor"] and first_user_msg:
                    prev["title"] = first_user_msg[:40]
                    prev["_from_supervisor"] = True
                prev["message_count"] = max(prev["message_count"], len(messages))

        for s in sessions.values():
            s.pop("_from_supervisor", None)
        sorted_sessions = sorted(
            sessions.values(), key=lambda x: x["updated_at"] or "", reverse=True
        )
        return sorted_sessions
    except Exception as e:
        logger.exception("Failed to get history")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{session_id}")
async def get_session_history(session_id: str):
    """加载指定会话的完整历史消息"""
    try:
        await ai_service._ensure_supervisor()
        checkpointer = ai_service._agent.checkpointer

        # 一个会话可能落在不同 agent 线程（supervisor / video / file …）。
        # 取**消息最多**的那个线程作为该会话的完整记录——不能一看到 supervisor
        # 有内容就直接用，否则当真实对话在 video 线程、supervisor 只有零星消息时会丢内容。
        from agent_lab.app.services.agent_registry import agent_registry
        candidates = ["supervisor"] + sorted(agent_registry.get_valid_agents())
        messages = []
        for ag in candidates:
            cfg = {"configurable": {"thread_id": f"{ag}:{session_id}"}}
            c = await checkpointer.aget(cfg)
            if not c:
                continue
            msgs = c.get("channel_values", {}).get("messages", [])
            if len(msgs) > len(messages):
                messages = msgs

        import os as _os
        from urllib.parse import quote as _quote

        formatted_messages = []
        pending_images = []   # 收集 IMGFILE 标记，挂到下一条 assistant 文本上
        held_cards = []       # 参数卡暂存：放到本轮 assistant 总结文字之后，避免被夹在中间
        for msg in messages:
            if msg.type == "system":
                continue
            content = msg.content if isinstance(msg.content, str) else ""

            # 工具消息：重建参数卡 / 图片墙 / 视频播放器（刷新后这些交互卡才不会丢）
            if msg.type == "tool":
                for line in content.splitlines():
                    s = line.strip()
                    if s.startswith("PARAM_FORM::"):
                        try:
                            p = json.loads(s[len("PARAM_FORM::"):])
                            held_cards.append({
                                "id": str(uuid.uuid4())[:8], "role": "param_form",
                                "params": p, "submitted": False, "streaming": False,
                            })
                        except Exception:
                            pass
                    elif s.startswith("VIDEO_PARAM_FORM::"):
                        try:
                            p = json.loads(s[len("VIDEO_PARAM_FORM::"):])
                            held_cards.append({
                                "id": str(uuid.uuid4())[:8], "role": "video_param_form",
                                "params": p, "submitted": False, "streaming": False,
                            })
                        except Exception:
                            pass
                    elif s.startswith("PRODUCTION::"):
                        pid = s[len("PRODUCTION::"):].strip()
                        if pid:
                            held_cards.append({
                                "id": str(uuid.uuid4())[:8], "role": "production",
                                "project_id": pid, "streaming": False,
                            })
                    elif s.startswith("IMGFILE::"):
                        parts = s.split("::", 3)
                        if len(parts) == 4:
                            pending_images.append({
                                "sceneId": parts[1], "assetId": parts[2],
                                "name": _os.path.basename(parts[3]),
                                "url": f"/api/file?path={_quote(parts[3])}",
                            })
                    elif s.startswith("VIDFILE::"):
                        parts = s.split("::", 2)
                        if len(parts) == 3:
                            formatted_messages.append({
                                "id": str(uuid.uuid4())[:8], "role": "assistant",
                                "content": "", "streaming": False,
                                "video": {"sceneId": parts[1],
                                          "name": _os.path.basename(parts[2]),
                                          "url": f"/api/file?path={_quote(parts[2])}"},
                            })
                continue

            if not content.strip():
                continue
            role = "user" if msg.type == "human" else "assistant"
            m = {
                "id": getattr(msg, "id", None) or str(uuid.uuid4())[:8],
                "role": role, "content": content, "streaming": False,
                "agentLabel": getattr(msg, "response_metadata", {}).get("agent", "supervisor"),
            }
            if role == "assistant" and pending_images:
                m["images"] = pending_images
                pending_images = []
            formatted_messages.append(m)
            # 本轮总结文字落地后，把暂存的参数卡接在其后（卡片在对话最下面）
            if role == "assistant" and held_cards:
                formatted_messages.extend(held_cards)
                held_cards = []

        if pending_images:  # 末尾还有未挂载的候选图，单独成一条
            formatted_messages.append({
                "id": str(uuid.uuid4())[:8], "role": "assistant", "content": "",
                "images": pending_images, "streaming": False,
            })
        if held_cards:  # 末尾仍有未挂载的参数卡（本轮没有后续文字），直接收尾
            formatted_messages.extend(held_cards)

        return {"messages": formatted_messages}
    except Exception as e:
        logger.exception(f"Failed to get session history for {session_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/history/{session_id}")
async def delete_session(session_id: str):
    """删除指定的历史会话"""
    try:
        await ai_service._ensure_supervisor()
        checkpointer = ai_service._agent.checkpointer

        # 删除该会话的**所有** agent 线程（supervisor + 全部注册子 Agent，含 video）。
        # 否则按线程归并的历史里会因残留 video:sid 线程而"删不掉"。
        from agent_lab.app.services.agent_registry import agent_registry
        agents = {"supervisor"} | set(agent_registry.get_valid_agents()) | {
            "code", "file", "batch", "general", "shell", "video", "quality"
        }
        for ag in agents:
            try:
                await checkpointer.adelete_thread(f"{ag}:{session_id}")
            except Exception:
                pass  # 某个 agent 没有该会话线程时跳过

        return {"success": True}
    except Exception as e:
        logger.exception(f"Failed to delete session {session_id}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 小说转视频：工作目录 / 服图 / 参数卡出图 / 选图 ────────────────────

class GenerateRequest(BaseModel):
    scene_id: str
    image_prompt: str = ""
    n: int = 0
    steps: int = 0
    guidance: float = -1.0
    width: int = 0
    height: int = 0
    seed: int = -1
    offload: str = ""
    workspace: str | None = None
    session_id: str | None = None   # 用于把出图结果写回会话线程，刷新后可重建图片墙


class SelectRequest(BaseModel):
    scene_id: str
    asset_id: str
    workspace: str | None = None


class RenderRequest(BaseModel):
    scene_id: str
    motion_prompt: str = ""
    model: str = ""                       # 视频模型名（wan2.2 / ltx ...）；空=默认
    params: dict = {}                     # 该模型的专属参数（由参数卡 schema 决定）
    # 旧字段保留向后兼容（老前端/老会话仍可用）；若提供会并入 params
    size: str = ""
    frame_num: int = 0
    sample_steps: int = 0
    workspace: str | None = None
    session_id: str | None = None


@router.get("/agents")
async def list_agents():
    """列出当前可用的 Agent（supervisor + 所有热插拔注册的子 Agent）。

    前端据此动态渲染 Agent 选择器——注册了新 Agent 就自动出现，无需改前端代码。
    """
    from agent_lab.app.services.agent_registry import agent_registry

    _LABELS = {
        "supervisor": "Supervisor", "general": "General", "code": "Code",
        "file": "File", "shell": "Shell", "batch": "Batch",
        "video": "Video", "quality": "Quality",
    }
    _ORDER = ["supervisor", "general", "code", "file", "shell", "batch", "video", "quality"]

    items = [{
        "id": "supervisor", "label": "Supervisor",
        "desc": "Auto-route to best agent",
    }]
    for name in sorted(agent_registry.get_valid_agents()):
        if name == "supervisor":
            continue
        meta = agent_registry.get_agent(name)
        items.append({
            "id": name,
            "label": _LABELS.get(name, name.capitalize()),
            "desc": (meta.description if meta and meta.description else name),
        })
    # 稳定排序：已知顺序优先，未知的排后面
    items.sort(key=lambda x: (_ORDER.index(x["id"]) if x["id"] in _ORDER else 999, x["id"]))
    return items


@router.get("/context/{session_id}")
async def context_usage(session_id: str):
    """返回某会话的真实上下文用量（token / 窗口 / 压缩触发线），给前端进度条。

    会话可能落在不同 agent 线程（supervisor / video / …），取消息最多的那条——
    只读 supervisor 会在对话实际发生在 video 线程时永远显示 0。
    """
    from agent_lab.app.services.context_meter import usage
    from agent_lab.app.services.agent_registry import agent_registry
    try:
        await ai_service._ensure_supervisor()
        checkpointer = ai_service._agent.checkpointer
        messages = []
        for ag in ["supervisor"] + sorted(agent_registry.get_valid_agents()):
            c = await checkpointer.aget({"configurable": {"thread_id": f"{ag}:{session_id}"}})
            if not c:
                continue
            msgs = c.get("channel_values", {}).get("messages", [])
            if len(msgs) > len(messages):
                messages = msgs
        return usage(messages)
    except Exception as e:
        logger.exception("context usage failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context/{session_id}/compact")
async def context_compact(session_id: str):
    """手动触发真实上下文压缩：把旧消息总结成摘要替换，仅保留最近若干条。"""
    from langchain_core.messages import RemoveMessage, SystemMessage
    from langgraph.graph.message import REMOVE_ALL_MESSAGES
    from agent_lab.app.services.context_meter import usage
    try:
        graph = await ai_service._ensure_supervisor()
        config = {"configurable": {"thread_id": f"supervisor:{session_id}"}}
        c = await graph.checkpointer.aget(config)
        messages = c.get("channel_values", {}).get("messages", []) if c else []
        before = usage(messages)
        KEEP_RECENT = 6
        if len(messages) <= KEEP_RECENT:
            return {"success": False, "message": "对话过短，无需压缩", **before}

        to_compress, recent = messages[:-KEEP_RECENT], messages[-KEEP_RECENT:]
        summary = await ai_service._llm.ainvoke([
            SystemMessage(content=(
                "请简洁总结以下对话的核心内容，保留：已完成的事项、重要决策、关键结论。"
                "去掉无意义闲聊。"
            )),
            *to_compress,
        ])
        compressed = [SystemMessage(content=f"【历史对话摘要】\n{summary.content}"), *recent]
        # 先清空再写入压缩后的消息（add_messages reducer 支持 REMOVE_ALL_MESSAGES 整体替换）
        await graph.aupdate_state(
            config,
            {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *compressed]},
        )
        after = usage(compressed)
        return {"success": True, "message": f"已压缩 {len(messages)}→{len(compressed)} 条",
                "before": before, "after": after}
    except Exception as e:
        logger.exception("compact failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/file")
async def serve_file(path: str):
    """静态服图/服视频：仅允许落在已知工作目录根下的文件（防目录穿越）。"""
    import os
    from fastapi.responses import FileResponse
    from agent_lab.app.pipeline.runtime import is_within_known_root

    if not os.path.isfile(path) or not is_within_known_root(path):
        raise HTTPException(status_code=404, detail="文件不存在或不在允许目录内")
    return FileResponse(path)


@router.post("/workspace/init")
async def workspace_init(path: str):
    """选定工作目录时立即创建 .agent 结构（config.json/pipeline.db/candidates/video_out）。"""
    import os
    from agent_lab.app.pipeline.runtime import set_workspace, agent_dir
    if not path or not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="目录不存在")
    set_workspace(path)
    ad = agent_dir()
    return {"agent_dir": ad, "items": sorted(os.listdir(ad))}


@router.get("/fs/list")
async def fs_list(path: str = ""):
    """目录浏览：列出 path 下的子目录，供前端文件夹选择器。path 为空时列盘符/根。"""
    import os
    try:
        if not path:
            if os.name == "nt":
                import string
                drives = [f"{d}:\\" for d in string.ascii_uppercase
                          if os.path.exists(f"{d}:\\")]
                return {"path": "", "parent": None, "dirs": drives}
            path = "/"
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail="不是有效目录")
        dirs = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            try:
                if os.path.isdir(full) and not name.startswith("."):
                    dirs.append(full)
            except Exception:
                continue
        parent = os.path.dirname(path.rstrip("\\/")) or None
        if os.name == "nt" and parent and len(parent) <= 2:  # 到盘符根再上一级=列盘符
            parent = ""
        return {"path": path, "parent": parent, "dirs": dirs}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _generate_events(req: GenerateRequest):
    """出图任务的事件流（被 job_manager 在后台 worker 里消费）。"""
    import asyncio
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.pipeline_tools import generate_candidates as _gen_tool

    set_workspace(req.workspace)
    yield {"type": "tool_call", "name": "generate_candidates",
           "args": {"scene_id": req.scene_id, "n": req.n, "steps": req.steps}}
    try:
        # generate_candidates 是同步阻塞（走 SSH/GPU），放线程池避免卡事件循环
        out = await asyncio.to_thread(
            _gen_tool.func,
            scene_id=req.scene_id, image_prompt=req.image_prompt, n=req.n,
            steps=req.steps, guidance=req.guidance, width=req.width,
            height=req.height, seed=req.seed, offload=req.offload,
        )
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "generate_candidates",
               "content": f"❌ 出图失败: {type(e).__name__}: {e}"}
        return
    clean, events = ai_service._extract_tool_markers(out)
    yield {"type": "tool_result", "name": "generate_candidates", "content": clean[:600]}
    for ev in events:
        yield ev

    # 把出图结果写回会话的 video 线程，刷新后 getSessionHistory 能重建图片墙
    if req.session_id:
        try:
            from langchain_core.messages import AIMessage, ToolMessage
            from uuid import uuid4
            graph = await ai_service._get_subagent("video")
            cfg = {"configurable": {"thread_id": f"video:{req.session_id}"}}
            tcid = "genimg_" + uuid4().hex[:8]
            await graph.aupdate_state(cfg, {"messages": [
                AIMessage(content="", tool_calls=[{
                    "id": tcid, "name": "generate_candidates",
                    "args": {"scene_id": req.scene_id},
                }]),
                ToolMessage(content=out, tool_call_id=tcid, name="generate_candidates"),
                AIMessage(content="🎨 已生成候选图，请在图片墙中点选一张。"),
            ]})
        except Exception:
            logger.exception("[generate] 写回会话线程失败（不影响出图）")


@router.post("/pipeline/generate")
async def pipeline_generate(req: GenerateRequest):
    """参数卡确认后出图：提交为后台任务，立即返回 job_id（单飞队列，不再占着连接）。"""
    from agent_lab.app.services.job_manager import job_manager
    job_id = job_manager.submit("generate", lambda: _generate_events(req))
    return {"job_id": job_id}


async def _render_events(req: RenderRequest):
    """出片任务的事件流（被 job_manager 在后台 worker 里消费）。"""
    import asyncio
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.pipeline_tools import do_render_scene_video

    set_workspace(req.workspace)
    # 合并参数：旧扁平字段并入 params（params 优先）
    params = dict(req.params or {})
    if req.size and "size" not in params:
        params["size"] = req.size
    if req.frame_num and "frame_num" not in params:
        params["frame_num"] = req.frame_num
    if req.sample_steps and "sample_steps" not in params:
        params["sample_steps"] = req.sample_steps

    yield {"type": "tool_call", "name": "render_scene_video",
           "args": {"scene_id": req.scene_id, "model": req.model or "default", **params}}
    try:
        out = await asyncio.to_thread(
            do_render_scene_video,
            req.scene_id, req.motion_prompt, req.model, params,
        )
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "render_scene_video",
               "content": f"出视频失败: {type(e).__name__}: {e}"}
        return
    clean, events = ai_service._extract_tool_markers(out)
    yield {"type": "tool_result", "name": "render_scene_video", "content": clean[:600]}
    for ev in events:
        yield ev

    # 写回会话 video 线程，刷新后可重建视频播放器
    if req.session_id:
        try:
            from langchain_core.messages import AIMessage, ToolMessage
            from uuid import uuid4
            graph = await ai_service._get_subagent("video")
            cfg = {"configurable": {"thread_id": f"video:{req.session_id}"}}
            tcid = "render_" + uuid4().hex[:8]
            await graph.aupdate_state(cfg, {"messages": [
                AIMessage(content="", tool_calls=[{
                    "id": tcid, "name": "render_scene_video",
                    "args": {"scene_id": req.scene_id},
                }]),
                ToolMessage(content=out, tool_call_id=tcid, name="render_scene_video"),
                AIMessage(content="出片完成，已在下方内嵌播放。"),
            ]})
        except Exception:
            logger.exception("[render] 写回会话线程失败（不影响出片）")


@router.post("/pipeline/render")
async def pipeline_render(req: RenderRequest):
    """出视频参数卡确认后出片：提交为后台任务，立即返回 job_id（单飞队列）。"""
    from agent_lab.app.services.job_manager import job_manager
    job_id = job_manager.submit("render", lambda: _render_events(req))
    return {"job_id": job_id}


@router.get("/pipeline/jobs/{job_id}/events")
async def pipeline_job_events(job_id: str, since: int = 0) -> StreamingResponse:
    """SSE：回放并实时跟随某个 GPU 任务的事件，直到完成。

    断线重连：客户端记录已收事件数 N，重连传 ?since=N，不重不漏。
    任务在后台 worker 里独立运行，浏览器断开也不影响其完成与落库。
    """
    from agent_lab.app.services.job_manager import job_manager
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return StreamingResponse(_events_to_sse(job.stream(since)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/pipeline/jobs/{job_id}")
async def pipeline_job_status(job_id: str):
    """查询任务状态快照（轮询兜底用）。"""
    from agent_lab.app.services.job_manager import job_manager
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return {"job_id": job.id, "kind": job.kind, "status": job.status,
            "event_count": len(job.events), "error": job.error}


@router.get("/video/providers")
async def list_video_providers():
    """列出已注册的视频模型及各自参数 schema（前端可据此构建模型选择/参数卡）。

    新增模型（在 pipeline/providers 注册）后自动出现，无需改前端。
    """
    from agent_lab.app.pipeline.providers import video_provider_registry
    return {
        "default": video_provider_registry.default_name,
        "providers": video_provider_registry.list_providers(),
    }


@router.post("/pipeline/select")
async def pipeline_select(req: SelectRequest):
    """点击候选图=选图：推进分镜到 PENDING_VIDEO_GEN。"""
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.pipeline_tools import select_candidate as _sel_tool
    set_workspace(req.workspace)   # 用与出图相同的工作目录 DB，否则查不到该资产
    msg = _sel_tool.func(scene_id=req.scene_id, asset_id=req.asset_id)
    # 成功消息形如「已选定 … → PENDING_VIDEO_GEN」；失败为「分镜不存在/未找到/不属于该分镜」等。
    # （早先按 ✅ 前缀判断，但 emoji 已统一移除，导致永远判为失败、前端不给「出视频」按钮）
    ok = ("已选定" in msg) or ("PENDING_VIDEO_GEN" in msg)
    return {"success": ok, "message": msg}


# ── 制作面板：确定性、DB 驱动的整片流程（出图/选图/出片/合成全用按钮，不绕 agent）──

def _scene_candidates(store, scene_id: str):
    """某分镜的候选图（带本地可访问 URL + 是否选中）。"""
    import os
    import posixpath
    from urllib.parse import quote as _quote
    from agent_lab.app.pipeline.runtime import candidates_dir
    out = []
    cdir = candidates_dir(scene_id)
    for a in store.list_assets(scene_id, "IMAGE"):
        name = posixpath.basename(a["storage_path"])
        lp = os.path.join(cdir, name)
        out.append({
            "assetId": a["id"], "sceneId": scene_id, "name": name,
            "selected": bool(a.get("is_selected")),
            "url": f"/api/file?path={_quote(lp)}" if os.path.exists(lp) else "",
        })
    return out


@router.get("/pipeline/projects")
async def pipeline_projects(workspace: str | None = None):
    """当前工作目录下的项目列表（新→旧）。底部「制作面板」常驻按钮据此找最新项目。"""
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.store import get_store
    set_workspace(workspace)
    store = get_store()
    out = []
    for p in store.list_projects():
        scenes = store.list_scenes(p["id"])
        out.append({"project_id": p["id"], "title": p.get("title") or "",
                    "created_at": p.get("created_at") or "", "scenes": len(scenes)})
    return {"projects": out}


@router.get("/pipeline/project/{project_id}")
async def pipeline_project(project_id: str, workspace: str | None = None):
    """制作面板的数据源：项目下所有分镜 + 候选图 + 选中态 + 成片（全部从 DB/本地文件读，刷新不丢）。"""
    import os
    from urllib.parse import quote as _quote
    from agent_lab.app.pipeline.runtime import set_workspace, video_dir
    from agent_lab.app.pipeline.store import get_store
    set_workspace(workspace)
    store = get_store()
    try:
        st = store.status(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    vdir = video_dir()
    scenes = []
    for s in sorted(st["scenes"], key=lambda x: x["scene_number"]):
        cands = _scene_candidates(store, s["id"])
        vlocal = os.path.join(vdir, f"{s['scene_number']:02d}_{s['id']}.mp4")
        scenes.append({
            "scene_id": s["id"], "scene_number": s["scene_number"],
            "title": s.get("title") or "", "state": s["state"],
            "narration": s.get("narration") or "",
            "image_prompt": s.get("image_prompt") or "",
            "motion_prompt": s.get("motion_prompt") or "",
            "candidates": cands,
            "selected": any(c["selected"] for c in cands),
            "video": ({"url": f"/api/file?path={_quote(vlocal)}",
                       "name": os.path.basename(vlocal)} if os.path.exists(vlocal) else None),
        })
    episode = os.path.join(vdir, f"episode_{project_id}.mp4")
    return {
        "project_id": project_id, "title": st["project"].get("title") or "",
        "scenes": scenes,
        "counts": {
            "total": len(scenes),
            "with_candidates": sum(1 for s in scenes if s["candidates"]),
            "selected": sum(1 for s in scenes if s["selected"]),
            "done": sum(1 for s in scenes if s["video"]),
        },
        "episode": ({"url": f"/api/file?path={_quote(episode)}",
                     "name": os.path.basename(episode)} if os.path.exists(episode) else None),
    }


class BatchRequest(BaseModel):
    project_id: str
    workspace: str | None = None
    session_id: str | None = None
    # 出视频参数（面板可选）
    model: str = ""
    segments: int = 1
    size: str = ""            # 出片分辨率（如 704*1280）；空=默认
    video_params: dict = {}   # 「更多参数」：所选模型的专业参数（schema 驱动，如 fps/steps/guidance/seed）
    # 出图参数（面板可选）
    n: int = 0                # 每镜候选张数；0=默认
    width: int = 0
    height: int = 0
    # 出图「更多参数」（专业档；默认值=不覆盖）
    img_steps: int = 0
    img_guidance: float = -1.0
    img_seed: int = -1
    img_offload: str = ""


async def _batch_generate_events(req: BatchRequest):
    """批量出图：对所有"还没候选图"的分镜逐个跑 FLUX（用分镜自带 image_prompt + 默认参数）。"""
    import asyncio
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.store import get_store
    from agent_lab.app.pipeline.pipeline_tools import generate_candidates as _gen_tool

    set_workspace(req.workspace)
    store = get_store()
    st = store.status(req.project_id)
    todo = [s for s in sorted(st["scenes"], key=lambda x: x["scene_number"])
            if len(store.list_assets(s["id"], "IMAGE")) == 0]
    if not todo:
        yield {"type": "tool_result", "name": "batch_generate", "content": "所有分镜都已出过图。"}
        return
    yield {"type": "tool_result", "name": "batch_generate",
           "content": f"开始批量出图：共 {len(todo)} 个分镜待出图。"}
    for i, s in enumerate(todo, 1):
        yield {"type": "batch_progress", "phase": "generate",
               "scene_id": s["id"], "index": i, "total": len(todo),
               "label": f"出图 {i}/{len(todo)}：#{s['scene_number']} {s.get('title') or ''}"}
        try:
            out = await asyncio.to_thread(
                _gen_tool.func, scene_id=s["id"],
                n=req.n, width=req.width, height=req.height,
                steps=req.img_steps, guidance=req.img_guidance,
                seed=req.img_seed, offload=req.img_offload)
        except Exception as e:  # noqa: BLE001
            yield {"type": "tool_result", "name": "batch_generate",
                   "content": f"#{s['scene_number']} 出图失败: {type(e).__name__}: {e}"}
            continue
        _clean, events = ai_service._extract_tool_markers(out)
        for ev in events:
            yield ev   # image 事件带 scene_id，前端按分镜归位
        yield {"type": "scene_ready", "scene_id": s["id"]}
    yield {"type": "tool_result", "name": "batch_generate", "content": "批量出图完成，请逐个分镜点选一张候选图。"}


async def _batch_finish_events(req: BatchRequest):
    """批量出片 + 合成：对所有已选图的分镜出片，再合成整集。"""
    import asyncio
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.store import get_store, SceneState
    from agent_lab.app.pipeline.pipeline_tools import do_render_scene_video, assemble_episode as _asm_tool

    set_workspace(req.workspace)
    store = get_store()
    st = store.status(req.project_id)
    scenes = sorted(st["scenes"], key=lambda x: x["scene_number"])
    # 以「已选定一张图且尚未出片」为准（state 可能漂移，但选中资产是可靠信号）
    todo = [s for s in scenes
            if s.get("selected_asset_id") and s["state"] != SceneState.COMPLETED.value]
    already = [s for s in scenes if s["state"] == SceneState.COMPLETED.value]
    if not todo and not already:
        yield {"type": "tool_result", "name": "batch_finish",
               "content": "还没有任何分镜选好图，请先逐个分镜点选一张候选图。"}
        return
    # 「更多参数」打底，常用项（段数/分辨率）覆盖在上
    params: dict = dict(req.video_params or {})
    if req.segments and req.segments > 1:
        params["segments"] = req.segments
    if req.size:
        params["size"] = req.size
    for i, s in enumerate(todo, 1):
        yield {"type": "batch_progress", "phase": "render",
               "scene_id": s["id"], "index": i, "total": len(todo),
               "label": f"出片 {i}/{len(todo)}：#{s['scene_number']} {s.get('title') or ''}"}
        try:
            out = await asyncio.to_thread(
                do_render_scene_video, s["id"], "", req.model, dict(params))
        except Exception as e:  # noqa: BLE001
            yield {"type": "tool_result", "name": "batch_finish",
                   "content": f"#{s['scene_number']} 出片失败: {type(e).__name__}: {e}"}
            continue
        _clean, events = ai_service._extract_tool_markers(out)
        for ev in events:
            yield ev
        yield {"type": "scene_ready", "scene_id": s["id"]}
    # 合成整集
    yield {"type": "batch_progress", "phase": "assemble", "label": "合成整集（拼接 + 旁白 + 字幕）…"}
    try:
        out = await asyncio.to_thread(_asm_tool.func, project_id=req.project_id)
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "batch_finish", "content": f"合成失败: {type(e).__name__}: {e}"}
        return
    clean, events = ai_service._extract_tool_markers(out)
    yield {"type": "tool_result", "name": "batch_finish", "content": clean[:400]}
    for ev in events:
        yield ev


class ScenePromptsRequest(BaseModel):
    scene_id: str
    workspace: str | None = None
    image_prompt: str | None = None    # None=不改；空串=清空
    motion_prompt: str | None = None
    narration: str | None = None


@router.post("/pipeline/scene_prompts")
async def pipeline_scene_prompts(req: ScenePromptsRequest):
    """更新分镜提示词/旁白：AI 生成的提示词在面板上可见、可改，改完再出图/出片。"""
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.store import get_store
    set_workspace(req.workspace)
    store = get_store()
    if not store.get_scene(req.scene_id):
        raise HTTPException(status_code=404, detail=f"分镜不存在: {req.scene_id}")
    s = store.update_scene_prompts(
        req.scene_id, image_prompt=req.image_prompt,
        motion_prompt=req.motion_prompt, narration=req.narration)
    return {"scene_id": s["id"], "image_prompt": s.get("image_prompt") or "",
            "motion_prompt": s.get("motion_prompt") or "", "narration": s.get("narration") or ""}


@router.post("/pipeline/upload_candidate")
async def pipeline_upload_candidate(
    scene_id: str = Form(...),
    workspace: str = Form(default=""),
    file: UploadFile = File(...),
):
    """已有分镜图直接上传当候选，无需 GPU 生图。

    本地存入工作目录 candidates/<scene>/；登记的 storage_path 用 GPU 侧约定路径——
    出片时的「参考图就绪保障」发现 GPU 上没有该文件，会自动用本地副本回传，链路无缝。
    """
    import os as _os
    import pathlib
    from uuid import uuid4
    from agent_lab.app.pipeline.runtime import set_workspace, candidates_dir
    from agent_lab.app.pipeline.store import get_store, SceneState

    suffix = pathlib.Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail=f"不支持的图片类型 {suffix}（支持 png/jpg/webp）")
    set_workspace(workspace or None)
    store = get_store()
    scene = store.get_scene(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail=f"分镜不存在: {scene_id}")

    name = f"upload_{uuid4().hex[:8]}{suffix}"
    local = _os.path.join(candidates_dir(scene_id), name)
    with open(local, "wb") as f:
        f.write(await file.read())
    remote = posixpath.join(settings.GPU_FLUX_OUT_ROOT, scene_id, name)  # 出片时自动回传
    asset = store.add_asset(scene_id=scene_id, storage_path=remote, asset_type="IMAGE")
    if scene["state"] in ("DRAFT", "PENDING_FLUX_GEN", "FAILED"):
        store.set_scene_state(scene_id, SceneState.PENDING_HUMAN_SELECTION, force=True)
    from urllib.parse import quote as _quote
    return {"asset_id": asset["id"], "name": name,
            "url": f"/api/file?path={_quote(local)}"}


def _rm_local(path: str) -> None:
    """删本地文件，吞掉不存在/被占用等错误（产物清理不应让接口失败）。"""
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


class DeleteCandidateRequest(BaseModel):
    asset_id: str
    workspace: str | None = None


@router.post("/pipeline/delete_candidate")
async def pipeline_delete_candidate(req: DeleteCandidateRequest):
    """删除一张候选图（DB + 本地文件）。删的是选中图则分镜回退到待选图。"""
    from agent_lab.app.pipeline.runtime import set_workspace, candidates_dir
    from agent_lab.app.pipeline.store import get_store
    set_workspace(req.workspace)
    store = get_store()
    asset = store.get_asset(req.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="候选图不存在")
    scene_id = asset["scene_id"]
    storage = store.delete_asset(req.asset_id)
    if storage:
        _rm_local(os.path.join(candidates_dir(scene_id), posixpath.basename(storage)))
    return {"ok": True}


class SceneRequest(BaseModel):
    scene_id: str
    workspace: str | None = None


@router.post("/pipeline/delete_scene_video")
async def pipeline_delete_scene_video(req: SceneRequest):
    """删除某分镜的成片（本地 mp4 + DB），回到「待出片」，可重新出片。"""
    from agent_lab.app.pipeline.runtime import set_workspace, video_dir
    from agent_lab.app.pipeline.store import get_store
    set_workspace(req.workspace)
    store = get_store()
    scene = store.get_scene(req.scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="分镜不存在")
    _rm_local(os.path.join(video_dir(), f"{scene['scene_number']:02d}_{req.scene_id}.mp4"))
    store.clear_scene_video(req.scene_id)
    return {"ok": True}


class EpisodeRequest(BaseModel):
    project_id: str
    workspace: str | None = None


@router.post("/pipeline/delete_episode")
async def pipeline_delete_episode(req: EpisodeRequest):
    """删除整集成片文件（不动各分镜，可重新合成）。删除是尽力而为，路径异常也不报错。"""
    from agent_lab.app.pipeline.runtime import set_workspace, video_dir
    try:
        set_workspace(req.workspace)
        _rm_local(os.path.join(video_dir(), f"episode_{req.project_id}.mp4"))
    except OSError:
        pass
    return {"ok": True}


async def _scene_generate_events(req: "SceneGenRequest"):
    """单个分镜出图（面板上点某镜的「出图」）。"""
    import asyncio
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.pipeline_tools import generate_candidates as _gen_tool
    set_workspace(req.workspace)
    yield {"type": "batch_progress", "phase": "generate", "scene_id": req.scene_id,
           "label": "出图中…"}
    try:
        out = await asyncio.to_thread(
            _gen_tool.func, scene_id=req.scene_id,
            n=req.n, width=req.width, height=req.height,
            steps=req.img_steps, guidance=req.img_guidance,
            seed=req.img_seed, offload=req.img_offload)
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "generate_candidates",
               "content": f"出图失败: {type(e).__name__}: {e}"}
        return
    _clean, events = ai_service._extract_tool_markers(out)
    for ev in events:
        yield ev
    yield {"type": "scene_ready", "scene_id": req.scene_id}


async def _scene_render_events(req: "SceneRenderRequest"):
    """单个分镜出片（面板上点某镜的「出视频」）。"""
    import asyncio
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.pipeline_tools import do_render_scene_video
    set_workspace(req.workspace)
    params: dict = dict(req.video_params or {})
    if req.segments and req.segments > 1:
        params["segments"] = req.segments
    if req.size:
        params["size"] = req.size
    yield {"type": "batch_progress", "phase": "render", "scene_id": req.scene_id,
           "label": "出片中…"}
    try:
        out = await asyncio.to_thread(
            do_render_scene_video, req.scene_id, "", req.model, params)
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "render_scene_video",
               "content": f"出片失败: {type(e).__name__}: {e}"}
        return
    _clean, events = ai_service._extract_tool_markers(out)
    for ev in events:
        yield ev
    yield {"type": "scene_ready", "scene_id": req.scene_id}


class SceneGenRequest(BaseModel):
    scene_id: str
    workspace: str | None = None
    session_id: str | None = None
    n: int = 0
    width: int = 0
    height: int = 0
    img_steps: int = 0
    img_guidance: float = -1.0
    img_seed: int = -1
    img_offload: str = ""


class SceneRenderRequest(BaseModel):
    scene_id: str
    workspace: str | None = None
    session_id: str | None = None
    model: str = ""
    segments: int = 1
    size: str = ""
    video_params: dict = {}


def _scene_project_id(scene_id: str, workspace: str | None) -> str | None:
    """查某分镜归属的项目 ID（给任务带上，供刷新后按项目重连）。"""
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.store import get_store
    try:
        set_workspace(workspace)
        sc = get_store().get_scene(scene_id)
        return sc["project_id"] if sc else None
    except Exception:
        return None


@router.post("/pipeline/scene_generate")
async def pipeline_scene_generate(req: SceneGenRequest):
    """单镜出图：后台任务，返回 job_id。"""
    from agent_lab.app.services.job_manager import job_manager
    meta = {"session_id": req.session_id, "scene_id": req.scene_id,
            "project_id": _scene_project_id(req.scene_id, req.workspace)}
    return {"job_id": job_manager.submit(
        "generate", lambda: _scene_generate_events(req), meta=meta)}


@router.post("/pipeline/scene_render")
async def pipeline_scene_render(req: SceneRenderRequest):
    """单镜出片：后台任务，返回 job_id。"""
    from agent_lab.app.services.job_manager import job_manager
    meta = {"session_id": req.session_id, "scene_id": req.scene_id,
            "project_id": _scene_project_id(req.scene_id, req.workspace)}
    return {"job_id": job_manager.submit(
        "render", lambda: _scene_render_events(req), meta=meta)}


@router.get("/pipeline/jobs")
async def pipeline_active_jobs(project_id: str | None = None, session_id: str | None = None):
    """列出在跑/排队的任务，供刷新后面板重连（显示进度 + 停止按钮）。"""
    from agent_lab.app.services.job_manager import job_manager
    return {"jobs": job_manager.list_active(project_id, session_id)}


@router.post("/pipeline/batch_generate")
async def pipeline_batch_generate(req: BatchRequest):
    """一键全部出图：后台单飞任务，返回 job_id。"""
    from agent_lab.app.services.job_manager import job_manager
    return {"job_id": job_manager.submit("batch_generate", lambda: _batch_generate_events(req), meta={"session_id": req.session_id, "project_id": req.project_id})}


@router.post("/pipeline/batch_finish")
async def pipeline_batch_finish(req: BatchRequest):
    """一键全部出片并合成整集：后台单飞任务，返回 job_id。"""
    from agent_lab.app.services.job_manager import job_manager
    return {"job_id": job_manager.submit("batch_finish", lambda: _batch_finish_events(req), meta={"session_id": req.session_id, "project_id": req.project_id})}
