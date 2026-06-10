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
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
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
        # 优先 supervisor；为空则在所有 agent 线程里取消息最多的那个。
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
            if ag == "supervisor" and messages:
                break  # supervisor 有内容就直接用

        import os as _os
        from urllib.parse import quote as _quote

        formatted_messages = []
        pending_images = []   # 收集 IMGFILE 标记，挂到下一条 assistant 文本上
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
                            formatted_messages.append({
                                "id": str(uuid.uuid4())[:8], "role": "param_form",
                                "params": p, "submitted": False, "streaming": False,
                            })
                        except Exception:
                            pass
                    elif s.startswith("VIDEO_PARAM_FORM::"):
                        try:
                            p = json.loads(s[len("VIDEO_PARAM_FORM::"):])
                            formatted_messages.append({
                                "id": str(uuid.uuid4())[:8], "role": "video_param_form",
                                "params": p, "submitted": False, "streaming": False,
                            })
                        except Exception:
                            pass
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

        if pending_images:  # 末尾还有未挂载的候选图，单独成一条
            formatted_messages.append({
                "id": str(uuid.uuid4())[:8], "role": "assistant", "content": "",
                "images": pending_images, "streaming": False,
            })
            
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
    """返回某会话的真实上下文用量（token / 窗口 / 压缩触发线），给前端进度条。"""
    from agent_lab.app.services.context_meter import usage
    try:
        await ai_service._ensure_supervisor()
        checkpointer = ai_service._agent.checkpointer
        config = {"configurable": {"thread_id": f"supervisor:{session_id}"}}
        c = await checkpointer.aget(config)
        messages = []
        if c:
            messages = c.get("channel_values", {}).get("messages", [])
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


@router.post("/pipeline/generate")
async def pipeline_generate(req: GenerateRequest) -> StreamingResponse:
    """参数卡确认后真正出图：用用户给定的全参数 + 工作目录跑 FLUX，SSE 推 tool_result + image。"""
    async def gen():
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

    return StreamingResponse(_events_to_sse(gen()), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/pipeline/render")
async def pipeline_render(req: RenderRequest) -> StreamingResponse:
    """出视频参数卡确认后真正出片：用给定参数 + 工作目录跑 Wan2.2，SSE 推 tool_result + video。"""
    async def gen():
        import asyncio
        from agent_lab.app.pipeline.runtime import set_workspace
        from agent_lab.app.pipeline.pipeline_tools import render_scene_video as _render_tool

        set_workspace(req.workspace)
        yield {"type": "tool_call", "name": "render_scene_video",
               "args": {"scene_id": req.scene_id, "size": req.size, "frame_num": req.frame_num}}
        try:
            out = await asyncio.to_thread(
                _render_tool.func,
                scene_id=req.scene_id, motion_prompt=req.motion_prompt,
                size=req.size, frame_num=req.frame_num, sample_steps=req.sample_steps,
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
                    AIMessage(content="Wan2.2 出片完成，已在下方内嵌播放。"),
                ]})
            except Exception:
                logger.exception("[render] 写回会话线程失败（不影响出片）")

    return StreamingResponse(_events_to_sse(gen()), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/pipeline/select")
async def pipeline_select(req: SelectRequest):
    """点击候选图=选图：推进分镜到 PENDING_VIDEO_GEN。"""
    from agent_lab.app.pipeline.runtime import set_workspace
    from agent_lab.app.pipeline.pipeline_tools import select_candidate as _sel_tool
    set_workspace(req.workspace)   # 用与出图相同的工作目录 DB，否则查不到该资产
    msg = _sel_tool.func(scene_id=req.scene_id, asset_id=req.asset_id)
    ok = msg.startswith("✅")
    return {"success": ok, "message": msg}
