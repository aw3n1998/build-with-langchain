"""
FastAPI 路由层

接口设计原则：
  1. 聊天用 SSE（Server-Sent Events）流式推送，前端实时显示，不等整个回答完成
  2. 所有接口统一返回结构，方便前端解析

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

from mirage.app.core.config import settings

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mirage.app.services.ai_service import ai_service
from mirage.app.core.logger import get_logger

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
        description="本次对话的工作目录（出图/出视频落地根）；为空则用默认 mirage_workspace。",
    )
    # 多租户预留口子：toC 时由鉴权中间件自动填，按用户隔离数据/工作目录/session。现默认 None（单用户无感）。
    user_id: str | None = Field(default=None, description="（预留）用户标识，多租户隔离用；现可不传。")


class ResumeRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID，必须与原 chat 请求一致")
    agent: str = Field(default="supervisor", description="当前 agent（目前仅 supervisor 支持 HITL）")
    approved: bool = Field(default=True, description="True=继续执行，False=取消")


class StatusResponse(BaseModel):
    model: str
    # 视频专用模式：True 时前端隐藏多 agent 选择器/配置等误导性 UI（后端基础设施仍保留，供切回多 agent）。
    video_agent_only: bool = True


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
    from mirage.app.services.job_manager import job_manager
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
    from mirage.app.services.job_manager import job_manager
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
    from mirage.app.services.job_manager import job_manager
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
    """取消任务：停止本地跟随 + 跳过后续步骤；GPU 任务额外杀掉远程推理进程释放显卡。"""
    import asyncio
    from mirage.app.services.job_manager import job_manager
    job = job_manager.get(job_id)
    cancelled = job_manager.cancel(job_id)
    # GPU 任务：取消只停本地，远程进程不会自己死 → 顺手杀掉，避免僵尸进程占卡堆积
    if cancelled and job and job.kind in ("generate", "render", "batch_generate", "batch_finish"):
        try:
            from mirage.app.pipeline.gpu_client import get_gpu_client
            await asyncio.to_thread(get_gpu_client().kill_inference)
        except Exception:  # noqa: BLE001
            logger.warning("[cancel] 远程推理进程清理失败（不影响取消）")
    return {"cancelled": cancelled}


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


@router.get("/status", response_model=StatusResponse)
async def status():
    """应用状态：当前模型 + 是否视频专用模式（前端顶栏/输入区用）。"""
    from mirage.app.core.config import settings
    return StatusResponse(
        model=settings.MODEL_NAME,
        video_agent_only=getattr(settings, "VIDEO_AGENT_ONLY", True),
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
        from mirage.app.services.agent_registry import agent_registry
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
        from mirage.app.services.agent_registry import agent_registry
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
    image_model: str = ""
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


class UpscaleRequest(BaseModel):
    kind: str = "scene"          # scene / episode
    scene_id: str = ""
    project_id: str = ""
    width: int = 0               # 目标宽高（前端按规格预设或自定义解析后传入）
    height: int = 0
    method: str = "auto"         # auto / comfyui(AI 超分) / ffmpeg(快缩)
    workspace: str | None = None
    session_id: str | None = None


class Flf2vRequest(BaseModel):
    scene_id: str
    auto: bool = True            # True=自动从已有成片等距抽关键帧(零人工);False=用下方 asset_ids 手动关键帧
    asset_ids: list[str] = []    # 手动模式:有序关键帧(≥2，不同时刻/构图)
    source_video: str = ""       # 自动模式可选:指定源成片路径;空=用该分镜当前成片
    num_keyframes: int = 0       # 自动模式:关键帧数;0=按时长自动定
    motion_prompt: str = ""
    width: int = 0
    height: int = 0
    frames: int = 0              # 每段(相邻关键帧之间)帧数;0=用默认
    workspace: str | None = None
    session_id: str | None = None


class FaceSwapRequest(BaseModel):
    kind: str = "scene"          # scene / episode
    scene_id: str = ""
    project_id: str = ""
    face_path: str = ""          # 服务端已保存的源脸图路径(由上传端点填)
    workspace: str | None = None
    session_id: str | None = None


@router.get("/agents")
async def list_agents():
    """列出当前可用的 Agent（supervisor + 所有热插拔注册的子 Agent）。

    前端据此动态渲染 Agent 选择器——注册了新 Agent 就自动出现，无需改前端代码。
    """
    from mirage.app.services.agent_registry import agent_registry

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
    from mirage.app.services.context_meter import usage
    from mirage.app.services.agent_registry import agent_registry
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
    from mirage.app.services.context_meter import usage
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
    from mirage.app.pipeline.runtime import is_within_known_root

    if not os.path.isfile(path) or not is_within_known_root(path):
        raise HTTPException(status_code=404, detail="文件不存在或不在允许目录内")
    return FileResponse(path)


@router.post("/workspace/init")
async def workspace_init(path: str):
    """选定工作目录时立即创建 .agent 结构（config.json/pipeline.db/candidates/video_out）。"""
    import os
    from mirage.app.pipeline.runtime import set_workspace, agent_dir
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
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import generate_candidates as _gen_tool

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
            model=req.image_model,
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
    from mirage.app.services.job_manager import job_manager
    job_id = job_manager.submit("generate", lambda: _generate_events(req))
    return {"job_id": job_id}


async def _render_events(req: RenderRequest):
    """出片任务的事件流（被 job_manager 在后台 worker 里消费）。"""
    import asyncio
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import do_render_scene_video

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
    from mirage.app.services.job_manager import job_manager
    job_id = job_manager.submit("render", lambda: _render_events(req))
    return {"job_id": job_id}


async def _upscale_events(req: UpscaleRequest):
    """一键转规格任务事件流（后台 worker 消费）：放大某成片到目标分辨率，产物落独立新文件。"""
    import asyncio
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import upscale_video

    set_workspace(req.workspace)
    yield {"type": "tool_call", "name": "upscale_video",
           "args": {"kind": req.kind, "scene_id": req.scene_id, "project_id": req.project_id,
                    "width": req.width, "height": req.height, "method": req.method}}
    try:
        out = await asyncio.to_thread(
            upscale_video, req.scene_id, req.project_id, req.kind, req.width, req.height, req.method,
        )
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "upscale_video",
               "content": f"转规格失败: {type(e).__name__}: {e}"}
        return
    clean, events = ai_service._extract_tool_markers(out)
    yield {"type": "tool_result", "name": "upscale_video", "content": clean[:600]}
    for ev in events:
        yield ev


@router.post("/pipeline/upscale")
async def pipeline_upscale(req: UpscaleRequest):
    """一键转规格（4K/2K/1080p/自定义）：提交后台任务，立即返回 job_id（单飞队列）。"""
    from mirage.app.services.job_manager import job_manager
    job_id = job_manager.submit("upscale", lambda: _upscale_events(req))
    return {"job_id": job_id}


async def _flf2v_events(req: Flf2vRequest):
    """FLF2V 治本续段任务事件流：用有序关键帧做首尾帧无缝拼接，结果回写为该分镜成片。"""
    import asyncio
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import render_scene_flf2v, render_scene_flf2v_auto

    set_workspace(req.workspace)
    auto = bool(req.auto) and not (req.asset_ids and len(req.asset_ids) >= 2)
    yield {"type": "tool_call", "name": "render_scene_flf2v",
           "args": {"scene_id": req.scene_id, "auto": auto, "keyframes": len(req.asset_ids or [])}}
    try:
        if auto:
            out = await asyncio.to_thread(
                render_scene_flf2v_auto, req.scene_id, req.source_video, req.num_keyframes,
                req.frames, req.motion_prompt, req.width, req.height,
            )
        else:
            out = await asyncio.to_thread(
                render_scene_flf2v, req.scene_id, req.asset_ids, req.motion_prompt,
                req.width, req.height, req.frames,
            )
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "render_scene_flf2v",
               "content": f"FLF2V 失败: {type(e).__name__}: {e}"}
        return
    clean, events = ai_service._extract_tool_markers(out)
    yield {"type": "tool_result", "name": "render_scene_flf2v", "content": clean[:600]}
    for ev in events:
        yield ev


@router.post("/pipeline/flf2v_render")
async def pipeline_flf2v_render(req: Flf2vRequest):
    """FLF2V 共享关键帧·治本续段:提交后台任务,立即返回 job_id(单飞队列)。"""
    from mirage.app.services.job_manager import job_manager
    job_id = job_manager.submit("flf2v", lambda: _flf2v_events(req))
    return {"job_id": job_id}


async def _faceswap_events(req: "FaceSwapRequest"):
    """一键换脸任务事件流：把源脸换到成片里的人物上，产物落独立新文件(原片保留)。"""
    import asyncio
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import faceswap_scene_video

    set_workspace(req.workspace)
    yield {"type": "tool_call", "name": "faceswap_scene_video",
           "args": {"kind": req.kind, "scene_id": req.scene_id, "project_id": req.project_id}}
    try:
        out = await asyncio.to_thread(
            faceswap_scene_video, req.scene_id, req.face_path, req.project_id, req.kind,
        )
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "faceswap_scene_video",
               "content": f"换脸失败: {type(e).__name__}: {e}"}
        return
    clean, events = ai_service._extract_tool_markers(out)
    yield {"type": "tool_result", "name": "faceswap_scene_video", "content": clean[:600]}
    for ev in events:
        yield ev


@router.post("/pipeline/faceswap")
async def pipeline_faceswap(
    scene_id: str = Form(default=""),
    kind: str = Form(default="scene"),
    project_id: str = Form(default=""),
    workspace: str = Form(default=""),
    session_id: str = Form(default=""),
    file: UploadFile = File(...),
):
    """视频一键换脸：上传一张源脸 → 换到该成片里(产物独立新文件)。先存脸图，再提交后台任务，返回 job_id。

    合规红线：仅用于你有权使用的脸（原创/AI 生成/本人授权）；换可识别真人=deepfake，平台 ToS 与法律禁止。
    """
    import os as _os
    import pathlib
    from uuid import uuid4
    from mirage.app.pipeline.runtime import set_workspace, video_dir
    from mirage.app.pipeline.store import get_store
    from mirage.app.services.job_manager import job_manager
    suffix = pathlib.Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail=f"不支持的图片类型 {suffix}（支持 png/jpg/jpeg/webp）")
    set_workspace(workspace or None)
    if kind != "episode" and not get_store().get_scene(scene_id):
        raise HTTPException(status_code=404, detail=f"分镜不存在: {scene_id}")
    face_name = f"face_{uuid4().hex[:8]}{suffix}"
    face_path = _os.path.join(video_dir(), face_name)
    with open(face_path, "wb") as f:
        f.write(await file.read())
    req = FaceSwapRequest(
        kind=kind, scene_id=scene_id, project_id=project_id,
        workspace=(workspace or None), session_id=(session_id or None), face_path=face_path)
    meta = {"session_id": req.session_id, "scene_id": scene_id,
            "project_id": project_id or _scene_project_id(scene_id, req.workspace)}
    return {"job_id": job_manager.submit("faceswap", lambda: _faceswap_events(req), meta=meta)}


@router.get("/pipeline/jobs/{job_id}/events")
async def pipeline_job_events(job_id: str, since: int = 0) -> StreamingResponse:
    """SSE：回放并实时跟随某个 GPU 任务的事件，直到完成。

    断线重连：客户端记录已收事件数 N，重连传 ?since=N，不重不漏。
    任务在后台 worker 里独立运行，浏览器断开也不影响其完成与落库。
    """
    from mirage.app.services.job_manager import job_manager
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return StreamingResponse(_events_to_sse(job.stream(since)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/pipeline/jobs/{job_id}")
async def pipeline_job_status(job_id: str):
    """查询任务状态快照（轮询兜底用）。"""
    from mirage.app.services.job_manager import job_manager
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
    from mirage.app.pipeline.providers import video_provider_registry
    return {
        "default": video_provider_registry.default_name,
        "providers": video_provider_registry.list_providers(),
    }


@router.get("/image/providers")
async def list_image_providers():
    """列出已注册的出图模型及各自参数 schema（前端可据此构建出图模型选择/参数卡）。

    新增出图模型（在 pipeline/image_providers 注册）后自动出现，无需改前端。
    """
    from mirage.app.pipeline.image_providers import image_provider_registry
    return {
        "default": image_provider_registry.default_name,
        "providers": image_provider_registry.list_providers(),
    }


@router.post("/pipeline/select")
async def pipeline_select(req: SelectRequest):
    """点击候选图=选图：推进分镜到 PENDING_VIDEO_GEN。"""
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import select_candidate as _sel_tool
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
    from mirage.app.pipeline.runtime import candidates_dir
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
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store
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
    from mirage.app.pipeline.runtime import set_workspace, video_dir
    from mirage.app.pipeline.store import get_store
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
            "subtitle": s.get("subtitle") or "",
            "lipsync": bool(s.get("lipsync")),
            "voice": s.get("voice") or "",
            "image_prompt": s.get("image_prompt") or "",
            "motion_prompt": s.get("motion_prompt") or "",
            "candidates": cands,
            "selected": any(c["selected"] for c in cands),
            # url 带 mtime 版本号：追加/重出后文件变了但路径不变，靠 &v= 让浏览器不吃旧缓存。
            # 以 DB 的 video_path 为准：删成片清空 video_path 后立刻不显示（即便文件被浏览器锁住一时没删掉）。
            "video": ({"url": f"/api/file?path={_quote(vlocal)}&v={int(os.path.getmtime(vlocal))}",
                       "name": os.path.basename(vlocal)}
                      if (s.get("video_path") and os.path.exists(vlocal)) else None),
        })
    episode = os.path.join(vdir, f"episode_{project_id}.mp4")
    characters = store.list_characters(project_id) if hasattr(store, "list_characters") else []
    loras = store.list_lora_trainings(project_id) if hasattr(store, "list_lora_trainings") else []
    return {
        "project_id": project_id, "title": st["project"].get("title") or "",
        "scenes": scenes,
        "characters": characters,
        "lora_trainings": loras,
        "style": (store.get_project_style(project_id) if hasattr(store, "get_project_style") else {}),
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
    # 两档开关：None=按默认(WAN_LIGHTNING) / True=极速档(Lightning 4步打样) / False=精修档(满档)
    lightning: bool | None = None
    # 只渲指定分镜(精修重渲"选中的"用)；空=按默认 todo。即便已 COMPLETED 也会重渲。
    scene_ids: list[str] | None = None
    # 出图参数（面板可选）
    n: int = 0                # 每镜候选张数；0=默认
    width: int = 0
    height: int = 0
    # 出图「更多参数」（专业档；默认值=不覆盖）
    img_steps: int = 0
    img_guidance: float = -1.0
    img_seed: int = -1
    img_offload: str = ""
    image_model: str = ""


async def _batch_generate_events(req: BatchRequest):
    """批量出图：对所有"还没候选图"的分镜逐个跑 FLUX（用分镜自带 image_prompt + 默认参数）。"""
    import asyncio
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store
    from mirage.app.pipeline.pipeline_tools import generate_candidates as _gen_tool

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
        out = None
        try:
            async for it in _run_with_logs(lambda sid=s["id"]: _gen_tool.func(
                    scene_id=sid, n=req.n, width=req.width, height=req.height,
                    steps=req.img_steps, guidance=req.img_guidance,
                    seed=req.img_seed, offload=req.img_offload, model=req.image_model)):
                if "_log" in it:
                    yield {"type": "log", "line": it["_log"]}
                else:
                    out = it["_result"]
        except Exception as e:  # noqa: BLE001
            yield {"type": "tool_result", "name": "batch_generate",
                   "content": f"#{s['scene_number']} 出图失败: {type(e).__name__}: {e}"}
            continue
        _clean, events = ai_service._extract_tool_markers(out or "")
        for ev in events:
            yield ev   # image 事件带 scene_id，前端按分镜归位
        yield {"type": "scene_ready", "scene_id": s["id"]}
    yield {"type": "tool_result", "name": "batch_generate", "content": "批量出图完成，请逐个分镜点选一张候选图。"}


async def _batch_finish_events(req: BatchRequest):
    """批量出片 + 合成：对所有已选图的分镜出片，再合成整集。"""
    import asyncio
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store, SceneState
    from mirage.app.pipeline.pipeline_tools import do_render_scene_video, assemble_episode as _asm_tool

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
    # 「更多参数」打底，常用项（段数/分辨率/档位/选中镜）覆盖在上
    params: dict = dict(req.video_params or {})
    if req.segments and req.segments > 1:
        params["segments"] = req.segments
    if req.size:
        params["size"] = req.size
    if req.lightning is not None:                  # 两档:True=极速(Lightning 4步打样)/False=精修(满档)
        params["lightning"] = "1" if req.lightning else "0"
    if req.scene_ids:                              # 精修重渲"选中的":只渲这些镜(含已 COMPLETED；do_render 内部 force 重渲)
        _ids = set(req.scene_ids)
        todo = [s for s in scenes if s["id"] in _ids and s.get("selected_asset_id")]
    for i, s in enumerate(todo, 1):
        yield {"type": "batch_progress", "phase": "render",
               "scene_id": s["id"], "index": i, "total": len(todo),
               "label": f"出片 {i}/{len(todo)}：#{s['scene_number']} {s.get('title') or ''}"}
        out = None
        try:
            async for it in _run_with_logs(lambda sid=s["id"]: do_render_scene_video(
                    sid, "", req.model, dict(params))):
                if "_log" in it:
                    yield {"type": "log", "line": it["_log"]}
                else:
                    out = it["_result"]
        except Exception as e:  # noqa: BLE001
            yield {"type": "tool_result", "name": "batch_finish",
                   "content": f"#{s['scene_number']} 出片失败: {type(e).__name__}: {e}"}
            continue
        _clean, events = ai_service._extract_tool_markers(out or "")
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
    subtitle: str | None = None        # 屏幕字幕（独立于旁白）
    lipsync: bool | None = None        # 对口型(S2V)开关；None=不改
    title: str | None = None           # 分镜标题；None=不改
    scene_number: int | None = None    # 镜号；None=不改
    voice: str | None = None           # 这一镜 TTS 音色(角色圣经)；None=不改


@router.post("/pipeline/scene_prompts")
async def pipeline_scene_prompts(req: ScenePromptsRequest):
    """更新分镜提示词/旁白：AI 生成的提示词在面板上可见、可改，改完再出图/出片。"""
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store
    set_workspace(req.workspace)
    store = get_store()
    if not store.get_scene(req.scene_id):
        raise HTTPException(status_code=404, detail=f"分镜不存在: {req.scene_id}")
    s = store.update_scene_prompts(
        req.scene_id, image_prompt=req.image_prompt,
        motion_prompt=req.motion_prompt, narration=req.narration, subtitle=req.subtitle,
        title=req.title, scene_number=req.scene_number)
    if req.lipsync is not None:
        s = store.set_scene_lipsync(req.scene_id, req.lipsync)
    if req.voice is not None:
        s = store.set_scene_voice(req.scene_id, req.voice)
    return {"scene_id": s["id"], "image_prompt": s.get("image_prompt") or "",
            "motion_prompt": s.get("motion_prompt") or "", "narration": s.get("narration") or "",
            "subtitle": s.get("subtitle") or "", "lipsync": bool(s.get("lipsync")),
            "title": s.get("title") or "", "scene_number": s.get("scene_number"),
            "voice": s.get("voice") or ""}


# ── 剧集（项目）管理 + 每集风格 + 分镜 增/删（面板自助，不绕 agent）──
class ProjectCreateRequest(BaseModel):
    workspace: str | None = None
    title: str = "新剧集"


class ProjectEditRequest(BaseModel):
    workspace: str | None = None
    project_id: str
    title: str | None = None


class ProjectStyleRequest(BaseModel):
    workspace: str | None = None
    project_id: str
    # 全 None=只读返回；任一非 None=写入该字段
    style_prompt: str | None = None     # 通用风格词（拼到每镜 image_prompt 后）
    trigger_word: str | None = None     # 角色触发词（项目级，覆盖工作目录）
    flux_lora: str | None = None        # LoRA 路径；"none"=不加载
    negative_prompt: str | None = None
    default_size: str | None = None     # 默认出图尺寸，如 768x1024


class SceneAddRequest(BaseModel):
    workspace: str | None = None
    project_id: str
    scene_number: int | None = None     # 缺省=接在最后
    title: str = ""
    narration: str = ""
    image_prompt: str = ""
    motion_prompt: str = ""
    subtitle: str = ""
    lipsync: bool = False


class SceneDeleteRequest(BaseModel):
    workspace: str | None = None
    scene_id: str


def _ws_store(workspace):
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store
    set_workspace(workspace)
    return get_store()


@router.post("/pipeline/project_create")
async def pipeline_project_create(req: ProjectCreateRequest):
    """面板「新建剧集」：不绕 agent 直接建项目。返回 project_id。"""
    store = _ws_store(req.workspace)
    p = store.create_project(req.title or "新剧集")
    return {"project_id": p["id"], "title": p["title"]}


@router.post("/pipeline/project_rename")
async def pipeline_project_rename(req: ProjectEditRequest):
    store = _ws_store(req.workspace)
    if not store.get_project(req.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    p = store.rename_project(req.project_id, req.title or "")
    return {"project_id": p["id"], "title": p["title"]}


@router.post("/pipeline/project_delete")
async def pipeline_project_delete(req: ProjectEditRequest):
    """删除整个剧集（含全部分镜/候选，级联）。"""
    store = _ws_store(req.workspace)
    ok = store.delete_project(req.project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"deleted": True, "project_id": req.project_id}


@router.post("/pipeline/project_style")
async def pipeline_project_style(req: ProjectStyleRequest):
    """读/写剧集级风格（每集一种风格）。全字段 None=只读；否则写入非 None 字段。"""
    store = _ws_store(req.workspace)
    if not store.get_project(req.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    fields = {k: getattr(req, k) for k in
              ("style_prompt", "trigger_word", "flux_lora", "negative_prompt", "default_size")}
    if any(v is not None for v in fields.values()):
        style = store.update_project_style(req.project_id, **fields)
    else:
        style = store.get_project_style(req.project_id)
    return {"project_id": req.project_id, "style": style}


@router.get("/pipeline/loras")
async def pipeline_loras(workspace: str = ""):
    """列出 ComfyUI 实际可用的 LoRA 文件 + 当前工作目录(对话/全局)的出图配置。
    面板据此把「LoRA」做成下拉真实文件，免得手填出一个不存在的名字(出图会被 ComfyUI 打回、整批失败)。"""
    from mirage.app.pipeline.runtime import set_workspace, model_config
    from mirage.app.pipeline import comfy_http as ch
    if workspace:
        set_workspace(workspace)
    try:
        avail = ch.available_loras(ch.base_url())
    except Exception:  # noqa: BLE001
        avail = None
    return {"loras": sorted(avail) if avail else [], "model": model_config()}


@router.post("/pipeline/scene_add")
async def pipeline_scene_add(req: SceneAddRequest):
    """面板「新增分镜」：不绕 agent 直接加一镜。镜号缺省=接最后。"""
    store = _ws_store(req.workspace)
    if not store.get_project(req.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    n = req.scene_number
    if not n or n <= 0:
        existing = store.list_scenes(req.project_id)
        n = (max((s["scene_number"] for s in existing), default=0) + 1)
    s = store.add_scene(req.project_id, n, narration=req.narration,
                        image_prompt=req.image_prompt, motion_prompt=req.motion_prompt,
                        title=req.title, subtitle=req.subtitle)
    if req.lipsync:
        s = store.set_scene_lipsync(s["id"], True)
    return {"scene_id": s["id"], "scene_number": s["scene_number"], "title": s.get("title") or ""}


@router.post("/pipeline/scene_delete")
async def pipeline_scene_delete(req: SceneDeleteRequest):
    store = _ws_store(req.workspace)
    ok = store.delete_scene(req.scene_id)
    if not ok:
        raise HTTPException(status_code=404, detail="分镜不存在")
    return {"deleted": True, "scene_id": req.scene_id}


class AutoStoryboardRequest(BaseModel):
    workspace: str | None = None
    project_id: str
    novel_text: str
    scenes: int = 8           # 想拆几镜
    replace: bool = False     # true=先清空现有分镜再拆；false=接在现有后面
    # 前端「导演/分镜模型」(Settings 的 supervisor 配置)；空=走 .env STORYBOARD_*/默认。让 UI 选 grok 真生效。
    agent_configs: dict[str, AgentLLMConfig] | None = None


@router.post("/pipeline/auto_storyboard")
async def pipeline_auto_storyboard(req: AutoStoryboardRequest):
    """小说 → 自动拆分镜：LLM 当导演一次拆成 N 镜并入库（带本集统一风格 + 角色圣经）。"""
    from mirage.app.pipeline.storyboard import breakdown_storyboard
    store = _ws_store(req.workspace)
    if not store.get_project(req.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    style = (store.get_project_style(req.project_id) or {}).get("style_prompt") or ""
    chars = store.list_characters(req.project_id) if hasattr(store, "list_characters") else []
    n = max(1, min(int(req.scenes or 8), 40))     # 上限保护，避免一次拆太多
    sb_cfg = (req.agent_configs or {}).get("supervisor")   # 前端导演模型(空=回退 .env)
    scenes = await breakdown_storyboard(req.novel_text or "", n, style=style,
                                        characters=chars, llm_config=sb_cfg)
    if req.replace:
        for s in store.list_scenes(req.project_id):
            store.delete_scene(s["id"])
    base = 0 if req.replace else max((s["scene_number"] for s in store.list_scenes(req.project_id)), default=0)
    # 顺手把小说原文留在项目里（可重拆/存档）
    if req.novel_text and hasattr(store, "set_project_novel"):
        try:
            store.set_project_novel(req.project_id, req.novel_text)
        except Exception:  # noqa: BLE001
            pass
    created = []
    voice_of = {c.get("name"): c.get("voice") for c in chars} if chars else {}
    for i, sc in enumerate(scenes, 1):
        row = store.add_scene(req.project_id, base + i, narration=sc["narration"],
                              image_prompt=sc["image_prompt"], motion_prompt=sc["motion_prompt"],
                              title=sc["title"], subtitle=sc["subtitle"])
        if sc.get("lipsync"):
            store.set_scene_lipsync(row["id"], True)
        v = voice_of.get(sc.get("character"))
        if v and hasattr(store, "set_scene_voice"):
            store.set_scene_voice(row["id"], v)
        created.append({"scene_id": row["id"], "scene_number": row["scene_number"], "title": row.get("title") or ""})
    return {"project_id": req.project_id, "created": created, "count": len(created)}


class AutoFillRequest(BaseModel):
    workspace: str | None = None
    project_id: str
    novel_text: str
    scenes: int = 8
    replace: bool = False         # true=替换现有角色/风格/分镜（LoRA 任务不删，保住已传图）
    # 前端「导演/分镜模型」；空=走 .env STORYBOARD_*/默认。作用于 角色/风格/分镜 全部 AI 分析步骤。
    agent_configs: dict[str, AgentLLMConfig] | None = None


@router.post("/pipeline/auto_fill")
async def pipeline_auto_fill(req: AutoFillRequest):
    """一键 AI 分析小说 → 自动填 角色(+按名建空 LoRA) / 本集风格 / 分镜。各步失败走保底不中断。"""
    from mirage.app.pipeline.novel_analyze import extract_characters, generate_style
    from mirage.app.pipeline.storyboard import breakdown_storyboard
    store = _ws_store(req.workspace)
    pid = req.project_id
    if not store.get_project(pid):
        raise HTTPException(status_code=404, detail="项目不存在")
    novel = req.novel_text or ""
    sb_cfg = (req.agent_configs or {}).get("supervisor")   # 前端导演模型(空=回退 .env)；角色/风格/分镜共用

    # 1) 角色（replace 时先清空旧角色）——用前端配的模型，避免全局 LLM key 空时静默抽不出角色
    chars = await extract_characters(novel, llm_config=sb_cfg)
    if req.replace:
        for c in store.list_characters(pid):
            store.delete_character(c["id"])
    existing_lora = {t.get("name") for t in store.list_lora_trainings(pid)}
    char_rows, lora_created = [], 0
    for c in chars:
        row = store.add_character(pid, c["name"], c.get("appearance", ""), c.get("voice", ""))
        char_rows.append(row)
        if c["name"] not in existing_lora:   # 每角色建空 LoRA（按名去重，不删旧的）
            try:
                store.add_lora_training(pid, c["name"], "", row.get("id", "") or "")
                existing_lora.add(c["name"]); lora_created += 1
            except Exception:  # noqa: BLE001
                pass

    # 2) 风格（喂入模板库里存过的偏好风格，让 AI 贴近你的口味）
    import json as _json
    style_refs = []
    for t in store.list_templates("style"):
        try:
            style_refs.append((_json.loads(t.get("content") or "{}") or {}).get("style_prompt") or "")
        except Exception:  # noqa: BLE001
            pass
    style = await generate_style(novel, style_refs=[s for s in style_refs if s], llm_config=sb_cfg)
    try:
        store.update_project_style(pid, **style)
    except Exception:  # noqa: BLE001
        pass

    # 3) 分镜（带新角色 + 新风格；逻辑同 auto_storyboard）
    chars_now = store.list_characters(pid)
    n = max(1, min(int(req.scenes or 8), 40))
    scenes = await breakdown_storyboard(novel, n, style=style.get("style_prompt", ""),
                                        characters=chars_now, llm_config=sb_cfg)
    if req.replace:
        for s in store.list_scenes(pid):
            store.delete_scene(s["id"])
    base = 0 if req.replace else max((s["scene_number"] for s in store.list_scenes(pid)), default=0)
    if novel and hasattr(store, "set_project_novel"):
        try:
            store.set_project_novel(pid, novel)
        except Exception:  # noqa: BLE001
            pass
    voice_of = {c.get("name"): c.get("voice") for c in chars_now}
    created = []
    for i, sc in enumerate(scenes, 1):
        rrow = store.add_scene(pid, base + i, narration=sc["narration"],
                               image_prompt=sc["image_prompt"], motion_prompt=sc["motion_prompt"],
                               title=sc["title"], subtitle=sc["subtitle"])
        if sc.get("lipsync"):
            store.set_scene_lipsync(rrow["id"], True)
        v = voice_of.get(sc.get("character"))
        if v and hasattr(store, "set_scene_voice"):
            store.set_scene_voice(rrow["id"], v)
        created.append({"scene_id": rrow["id"], "scene_number": rrow["scene_number"]})

    return {"project_id": pid, "characters": len(char_rows), "lora_created": lora_created,
            "style": style, "scenes_count": len(created)}


class TemplateRequest(BaseModel):
    workspace: str | None = None
    action: str = "list"          # list / add / delete
    kind: str | None = None       # style / motion / prompt（list 可按 kind 过滤；add 必填）
    name: str | None = None
    content: str | None = None
    template_id: str | None = None


@router.post("/pipeline/templates")
async def pipeline_templates(req: TemplateRequest):
    """可复用模板库（per-workspace）：风格/运镜/提示词存取，跨剧集复用。"""
    store = _ws_store(req.workspace)
    act = (req.action or "list").lower()
    if act == "add" and req.kind:
        store.add_template(req.kind, (req.name or "未命名")[:40], req.content or "")
    elif act == "delete" and req.template_id:
        store.delete_template(req.template_id)
    return {"templates": store.list_templates(req.kind or "")}


class CharacterRequest(BaseModel):
    workspace: str | None = None
    project_id: str
    action: str = "list"          # list / add / update / delete
    char_id: str | None = None
    name: str | None = None
    appearance: str | None = None
    voice: str | None = None      # edge-tts 音色名，如 zh-CN-YunxiNeural
    ref_image_path: str | None = None   # 参考脸图路径(PuLID 单脸自举/展示)
    trained_lora_id: str | None = None  # 关联已训 LoRA(lora_trainings.id)


@router.post("/pipeline/characters")
async def pipeline_characters(req: CharacterRequest):
    """角色/声音圣经的增删改查（每剧：名字 + 外貌 + 固定 TTS 音色）。返回最新角色列表。"""
    store = _ws_store(req.workspace)
    if not store.get_project(req.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    act = (req.action or "list").lower()
    if act == "add":
        store.add_character(req.project_id, req.name or "", req.appearance or "", req.voice or "")
    elif act == "update" and req.char_id:
        store.update_character(req.char_id, name=req.name, appearance=req.appearance, voice=req.voice,
                               ref_image_path=req.ref_image_path, trained_lora_id=req.trained_lora_id)
    elif act == "delete" and req.char_id:
        store.delete_character(req.char_id)
    return {"project_id": req.project_id, "characters": store.list_characters(req.project_id)}


# ── 人物 LoRA 训练（界面框架 + 门控；实际训练等 Colab 训练后端接入）──
def _lora_dir(tid: str) -> str:
    from mirage.app.pipeline.runtime import agent_dir
    d = os.path.join(agent_dir(), "lora_train", tid)
    os.makedirs(d, exist_ok=True)
    return d


class LoraCreateRequest(BaseModel):
    workspace: str | None = None
    project_id: str
    name: str = "新角色LoRA"
    trigger_word: str = ""
    char_id: str | None = None


@router.post("/pipeline/lora_create")
async def pipeline_lora_create(req: LoraCreateRequest):
    """新建一个人物 LoRA 训练任务（之后往里传参考图、再开训）。"""
    store = _ws_store(req.workspace)
    if not store.get_project(req.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    t = store.add_lora_training(req.project_id, req.name or "新角色LoRA",
                                req.trigger_word or "", req.char_id or "")
    _lora_dir(t["id"])
    return {"training": t}


@router.post("/pipeline/lora_upload_image")
async def pipeline_lora_upload_image(training_id: str = Form(...), workspace: str = Form(default=""),
                                     file: UploadFile = File(...)):
    """往某 LoRA 训练任务里传一张参考图（同一人物多角度，建议 10-20 张）。"""
    import pathlib
    from uuid import uuid4
    suffix = pathlib.Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail=f"不支持的图片类型 {suffix}（png/jpg/webp）")
    store = _ws_store(workspace or None)
    if not store.get_lora_training(training_id):
        raise HTTPException(status_code=404, detail="训练任务不存在")
    d = _lora_dir(training_id)
    name = f"{uuid4().hex[:8]}{suffix}"
    with open(os.path.join(d, name), "wb") as f:
        f.write(await file.read())
    cnt = len([x for x in os.listdir(d) if x.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])
    store.update_lora_training(training_id, image_count=cnt)
    from urllib.parse import quote as _quote
    return {"training_id": training_id, "image_count": cnt,
            "url": f"/api/file?path={_quote(os.path.join(d, name))}"}


@router.post("/pipeline/lora_upload_ref")
async def pipeline_lora_upload_ref(training_id: str = Form(...), workspace: str = Form(default=""),
                                   file: UploadFile = File(...)):
    """PuLID 单脸自举：上传 1 张参考脸图（存 _ref/，不计入训练图数；自举时锁这张脸的 ID 批量出同人图）。"""
    import pathlib
    suffix = pathlib.Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail=f"不支持的图片类型 {suffix}（png/jpg/webp）")
    store = _ws_store(workspace or None)
    if not store.get_lora_training(training_id):
        raise HTTPException(status_code=404, detail="训练任务不存在")
    d = os.path.join(_lora_dir(training_id), "_ref")
    os.makedirs(d, exist_ok=True)
    for old in os.listdir(d):                       # 只留一张参考脸
        try:
            os.remove(os.path.join(d, old))
        except Exception:  # noqa: BLE001
            pass
    path = os.path.join(d, f"face{suffix}")
    with open(path, "wb") as f:
        f.write(await file.read())
    from urllib.parse import quote as _quote
    return {"training_id": training_id, "ref": f"/api/file?path={_quote(path)}"}


class LoraActionRequest(BaseModel):
    workspace: str | None = None
    project_id: str
    training_id: str | None = None
    action: str = "list"          # list / train / delete / update / bootstrap
    name: str | None = None       # update 用：改名
    trigger_word: str | None = None  # update 用：改触发词
    # bootstrap 用：免上传自训。mode=text(零图)/pulid(单脸)；count=造几张；appearance=外貌(空则取绑定角色)；
    mode: str | None = None
    count: int | None = None
    appearance: str | None = None
    auto_train: bool = True       # 造完即训(一键免上传自训)


@router.post("/pipeline/lora_trainings")
async def pipeline_lora_trainings(req: LoraActionRequest):
    """LoRA 训练任务的列表 / 开训 / 删除。开训是门控的：训练后端(LORA_TRAIN_ENDPOINT)没接入时只暂存。"""
    store = _ws_store(req.workspace)
    if not store.get_project(req.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    act = (req.action or "list").lower()
    if act == "delete" and req.training_id:
        store.delete_lora_training(req.training_id)
        # 连磁盘参考图一起清，别残留（之前只删了 DB 行 → 像"没删干净"）
        import shutil
        from mirage.app.pipeline.runtime import agent_dir
        shutil.rmtree(os.path.join(agent_dir(), "lora_train", req.training_id), ignore_errors=True)
    elif act == "update" and req.training_id:
        store.update_lora_training(req.training_id, name=req.name, trigger_word=req.trigger_word)
    elif act == "train" and req.training_id:
        t = store.get_lora_training(req.training_id)
        if not t:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        from mirage.app.pipeline import lora_train
        ddir = _lora_dir(req.training_id)
        imgs = lora_train.count_images(ddir)        # 以磁盘为准(上传/自举都落这)
        store.update_lora_training(req.training_id, image_count=imgs)
        if imgs < 5:
            store.update_lora_training(
                req.training_id, status="DRAFT",
                message="参考图太少：至少 5 张。可手动上传，或用『自动造训练集』免上传生成一套。")
        else:
            # 本地 ai-toolkit 子进程(默认)或远程派发(LORA_TRAIN_ENDPOINT 非空)，执行器内部判定
            lora_train.start_training(store, req.training_id, ddir)
    elif act == "bootstrap" and req.training_id:
        # 免上传自训：系统自己造训练集(text=零图 / pulid=单脸)，造完可自动开训
        t = store.get_lora_training(req.training_id)
        if not t:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        from mirage.app.pipeline import lora_bootstrap
        ddir = _lora_dir(req.training_id)
        appearance = req.appearance or ""
        if not appearance and t.get("char_id"):
            appearance = (store.get_character(t["char_id"]) or {}).get("appearance") or ""
        lora_bootstrap.start_bootstrap(store, req.training_id, ddir, mode=(req.mode or "text"),
                                       appearance=appearance, count=(req.count or 0),
                                       auto_train=bool(req.auto_train))
    return {"project_id": req.project_id, "trainings": store.list_lora_trainings(req.project_id)}


class SuggestSegmentPromptsRequest(BaseModel):
    scene_id: str
    workspace: str | None = None
    segments: int = 2
    intent: str = ""  # 用户中文意图（可空），AI 据此 + 画面拆成 N 段递进运镜


@router.post("/pipeline/suggest_segment_prompts")
async def pipeline_suggest_segment_prompts(req: SuggestSegmentPromptsRequest):
    """AI 据画面 + 一句中文意图（可空），把动作拆成 N 段递进的英文运镜提示词（尾帧接续用）。"""
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store
    from mirage.app.pipeline.prompt_gen import suggest_segment_prompts
    set_workspace(req.workspace)
    scene = get_store().get_scene(req.scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail=f"分镜不存在: {req.scene_id}")
    _cap = settings.MAX_CONTINUATION_SEGMENTS      # 段数不写死：0=不限
    n = max(1, int(req.segments or 1))
    if _cap and _cap > 0:
        n = min(n, _cap)
    prompts = await suggest_segment_prompts(
        scene.get("image_prompt") or "", req.intent or "", n)
    return {"scene_id": req.scene_id, "prompts": prompts}


class SuggestContinuationRequest(BaseModel):
    scene_id: str
    workspace: str | None = None
    lang: str = "zh"   # 推荐语言：zh=中文（Wan 原生支持）/ en=英文


@router.post("/pipeline/suggest_continuation")
async def pipeline_suggest_continuation(req: SuggestContinuationRequest):
    """据「现有成片的末帧 + 上下文」推荐下一段运镜提示词（配了视觉模型则真看末帧图）。防抽卡。"""
    from mirage.app.pipeline.runtime import set_workspace, video_dir
    from mirage.app.pipeline.store import get_store
    from mirage.app.pipeline.prompt_gen import suggest_continuation_prompt
    from mirage.app.pipeline.assembler import extract_last_frame
    set_workspace(req.workspace)
    scene = get_store().get_scene(req.scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail=f"分镜不存在: {req.scene_id}")
    final_local = os.path.join(video_dir(), f"{scene['scene_number']:02d}_{req.scene_id}.mp4")
    if not os.path.exists(final_local):
        raise HTTPException(status_code=400, detail="这个分镜还没有视频，无法据尾帧推荐。请先出一段。")
    frame = os.path.join(video_dir(), f"{scene['scene_number']:02d}_{req.scene_id}_suggest.png")
    try:
        extract_last_frame(final_local, frame)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"取末帧失败: {e}")
    res = await suggest_continuation_prompt(
        scene, [scene.get("motion_prompt") or ""], frame, req.lang or "zh")
    return {"scene_id": req.scene_id, **res}


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
    from mirage.app.pipeline.runtime import set_workspace, candidates_dir
    from mirage.app.pipeline.store import get_store, SceneState

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
    """删本地文件。Windows 上文件被浏览器 <video> 占用会抛 PermissionError → 退避重试几次；
    实在删不掉也不抛（DB 的 video_path 已清空，面板不会再显示，文件下次重出时覆盖）。"""
    if not path or not os.path.isfile(path):
        return
    import time as _t
    for i in range(4):
        try:
            os.remove(path)
            return
        except PermissionError:           # 被占用（播放中）→ 等一下再删
            _t.sleep(0.4 * (i + 1))
        except OSError:
            return


class DeleteCandidateRequest(BaseModel):
    asset_id: str
    workspace: str | None = None


@router.post("/pipeline/delete_candidate")
async def pipeline_delete_candidate(req: DeleteCandidateRequest):
    """删除一张候选图（DB + 本地文件）。删的是选中图则分镜回退到待选图。"""
    from mirage.app.pipeline.runtime import set_workspace, candidates_dir
    from mirage.app.pipeline.store import get_store
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
    """删除某分镜的成片（本地 mp4 + 分段 + 续段快照 + DB），回到「待出片」，可重新出片。"""
    import glob as _glob
    from mirage.app.pipeline.runtime import set_workspace, video_dir
    from mirage.app.pipeline.store import get_store
    set_workspace(req.workspace)
    store = get_store()
    scene = store.get_scene(req.scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="分镜不存在")
    base = os.path.join(video_dir(), f"{scene['scene_number']:02d}_{req.scene_id}")
    _rm_local(base + ".mp4")
    # 连分段/续段快照/末帧图一起清，别留垃圾
    for p in _glob.glob(base + "_seg*.mp4") + _glob.glob(base + ".undo*.mp4") \
            + _glob.glob(base + "*.png") + _glob.glob(base + ".tmp.mp4"):
        _rm_local(p)
    store.clear_scene_video(req.scene_id)
    return {"ok": True}


@router.post("/pipeline/scene_undo_append")
async def pipeline_scene_undo_append(req: SceneRequest):
    """撤销「上一段」续接：成片回退到最近一次「再续一段」之前（可多次回退）。"""
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store
    from mirage.app.pipeline.pipeline_tools import undo_last_append_segment
    set_workspace(req.workspace)
    if not get_store().get_scene(req.scene_id):
        raise HTTPException(status_code=404, detail="分镜不存在")
    msg = undo_last_append_segment(req.scene_id)
    return {"ok": not msg.startswith(("没有", "回退失败")), "message": msg}


class EpisodeRequest(BaseModel):
    project_id: str
    workspace: str | None = None


@router.post("/pipeline/delete_episode")
async def pipeline_delete_episode(req: EpisodeRequest):
    """删除整集成片文件（不动各分镜，可重新合成）。删除是尽力而为，路径异常也不报错。"""
    from mirage.app.pipeline.runtime import set_workspace, video_dir
    try:
        set_workspace(req.workspace)
        _rm_local(os.path.join(video_dir(), f"episode_{req.project_id}.mp4"))
    except OSError:
        pass
    return {"ok": True}


async def _run_with_logs(thread_fn):
    """在线程跑阻塞的 GPU 工作，同时把远程命令日志实时 yield 成 {type:'log'} 事件。

    用法：
        async for it in _run_with_logs(lambda: blocking()):
            if '_log' in it: yield {'type':'log','line': it['_log']}
            else: out = it['_result']     # 线程抛异常则在此处 raise
    """
    import asyncio
    import queue as _q
    from mirage.app.pipeline.log_bus import set_sink, reset_sink

    q: _q.Queue = _q.Queue(maxsize=4000)
    token = set_sink(q)
    try:
        task = asyncio.create_task(asyncio.to_thread(thread_fn))
        while True:
            try:
                while True:
                    yield {"_log": q.get_nowait()}
            except _q.Empty:
                pass
            if task.done():
                break
            await asyncio.sleep(0.25)
        try:
            while True:
                yield {"_log": q.get_nowait()}
        except _q.Empty:
            pass
        yield {"_result": task.result()}   # 线程内异常在此 raise → 由 job 落 error 终态
    finally:
        reset_sink(token)


async def _scene_generate_events(req: "SceneGenRequest"):
    """单个分镜出图（面板上点某镜的「出图」）。"""
    import asyncio
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import generate_candidates as _gen_tool
    set_workspace(req.workspace)
    yield {"type": "batch_progress", "phase": "generate", "scene_id": req.scene_id,
           "label": "出图中…"}
    out = None
    try:
        async for it in _run_with_logs(lambda: _gen_tool.func(
                scene_id=req.scene_id, n=req.n, width=req.width, height=req.height,
                steps=req.img_steps, guidance=req.img_guidance,
                seed=req.img_seed, offload=req.img_offload, model=req.image_model)):
            if "_log" in it:
                yield {"type": "log", "line": it["_log"]}
            else:
                out = it["_result"]
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "generate_candidates",
               "content": f"出图失败: {type(e).__name__}: {e}"}
        return
    _clean, events = ai_service._extract_tool_markers(out or "")
    for ev in events:
        yield ev
    yield {"type": "scene_ready", "scene_id": req.scene_id}


async def _scene_render_events(req: "SceneRenderRequest"):
    """单个分镜出片（面板上点某镜的「出视频」）。"""
    import asyncio
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import do_render_scene_video
    set_workspace(req.workspace)
    params: dict = dict(req.video_params or {})
    if req.segments and req.segments > 1:
        params["segments"] = req.segments
    if req.size:
        params["size"] = req.size
    seg_prompts = [p for p in (req.motion_prompts or []) if isinstance(p, str)]
    if seg_prompts:
        params["motion_prompts"] = seg_prompts
    if req.lipsync:
        params["lipsync"] = True
    yield {"type": "batch_progress", "phase": "render", "scene_id": req.scene_id,
           "label": "对口型出片中…" if req.lipsync else "出片中…"}
    out = None
    try:
        async for it in _run_with_logs(lambda: do_render_scene_video(
                req.scene_id, "", req.model, params)):
            if "_log" in it:
                yield {"type": "log", "line": it["_log"]}
            else:
                out = it["_result"]
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "render_scene_video",
               "content": f"出片失败: {type(e).__name__}: {e}"}
        return
    _clean, events = ai_service._extract_tool_markers(out or "")
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
    image_model: str = ""


class SceneRenderRequest(BaseModel):
    scene_id: str
    workspace: str | None = None
    session_id: str | None = None
    model: str = ""
    segments: int = 1
    size: str = ""
    video_params: dict = {}
    motion_prompts: list[str] = []  # 每段独立运镜提示词（AI 生成/手改），缺则全段用统一 prompt
    lipsync: bool = False           # 对口型(S2V)：人物开口说话的镜头，旁白→TTS→口型同步


class SceneAppendRequest(BaseModel):
    scene_id: str
    workspace: str | None = None
    session_id: str | None = None
    model: str = ""
    motion_prompt: str = ""          # 新增段的运镜提示词（留空用分镜自带的）
    count: int = 1                   # 追加多少段（不写死上限）
    size: str = ""
    video_params: dict = {}
    motion_prompts: list[str] = []   # 可选：逐段不同提示词


def _scene_project_id(scene_id: str, workspace: str | None) -> str | None:
    """查某分镜归属的项目 ID（给任务带上，供刷新后按项目重连）。"""
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store
    try:
        set_workspace(workspace)
        sc = get_store().get_scene(scene_id)
        return sc["project_id"] if sc else None
    except Exception:
        return None


@router.post("/pipeline/scene_generate")
async def pipeline_scene_generate(req: SceneGenRequest):
    """单镜出图：后台任务，返回 job_id。"""
    from mirage.app.services.job_manager import job_manager
    meta = {"session_id": req.session_id, "scene_id": req.scene_id,
            "project_id": _scene_project_id(req.scene_id, req.workspace)}
    return {"job_id": job_manager.submit(
        "generate", lambda: _scene_generate_events(req), meta=meta)}


@router.post("/pipeline/scene_render")
async def pipeline_scene_render(req: SceneRenderRequest):
    """单镜出片：后台任务，返回 job_id。"""
    from mirage.app.services.job_manager import job_manager
    meta = {"session_id": req.session_id, "scene_id": req.scene_id,
            "project_id": _scene_project_id(req.scene_id, req.workspace)}
    return {"job_id": job_manager.submit(
        "render", lambda: _scene_render_events(req), meta=meta)}


async def _scene_append_events(req: "SceneAppendRequest"):
    """在分镜已生成的成片末尾追加 N 段（看效果再加长）。流式同出片。"""
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import append_scene_segment
    set_workspace(req.workspace)
    params: dict = dict(req.video_params or {})
    if req.size:
        params["size"] = req.size
    seg_prompts = [p for p in (req.motion_prompts or []) if isinstance(p, str)]
    if seg_prompts:
        params["motion_prompts"] = seg_prompts
    yield {"type": "batch_progress", "phase": "render", "scene_id": req.scene_id,
           "label": "追加视频段中…"}
    out = None
    try:
        async for it in _run_with_logs(lambda: append_scene_segment(
                req.scene_id, req.motion_prompt, req.model, params, req.count)):
            if "_log" in it:
                yield {"type": "log", "line": it["_log"]}
            else:
                out = it["_result"]
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "append_scene_video",
               "content": f"追加失败: {type(e).__name__}: {e}"}
        return
    _clean, events = ai_service._extract_tool_markers(out or "")
    for ev in events:
        yield ev
    yield {"type": "scene_ready", "scene_id": req.scene_id}


@router.post("/pipeline/scene_append")
async def pipeline_scene_append(req: SceneAppendRequest):
    """单镜「再续一段」：后台任务，返回 job_id。"""
    from mirage.app.services.job_manager import job_manager
    meta = {"session_id": req.session_id, "scene_id": req.scene_id,
            "project_id": _scene_project_id(req.scene_id, req.workspace)}
    return {"job_id": job_manager.submit(
        "render", lambda: _scene_append_events(req), meta=meta)}


class SceneUploadContinueRequest(BaseModel):
    scene_id: str
    workspace: str | None = None
    session_id: str | None = None
    model: str = ""
    motion_prompt: str = ""          # AI 续写段的运镜提示词（留空用分镜自带）
    size: str = ""
    count: int = 1                   # 上传后再 AI 续写多少段（0=只拼接、不续写）
    uploaded_path: str = ""          # 端点先把上传视频存到本地，再带路径提交任务


async def _scene_upload_continue_events(req: "SceneUploadContinueRequest"):
    """拼接上传视频到成片末尾 + 从其尾帧 AI 续写。流式同「再续一段」。"""
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.pipeline_tools import append_uploaded_video
    set_workspace(req.workspace)
    params: dict = {}
    if req.size:
        params["size"] = req.size
    yield {"type": "batch_progress", "phase": "render", "scene_id": req.scene_id,
           "label": "拼接上传视频" + ("+ AI 续写" if (req.count or 0) >= 1 else "") + "中…"}
    out = None
    try:
        async for it in _run_with_logs(lambda: append_uploaded_video(
                req.scene_id, req.uploaded_path, req.motion_prompt, req.model, params, req.count)):
            if "_log" in it:
                yield {"type": "log", "line": it["_log"]}
            else:
                out = it["_result"]
    except Exception as e:  # noqa: BLE001
        yield {"type": "tool_result", "name": "upload_continue_video",
               "content": f"上传续接失败: {type(e).__name__}: {e}"}
        return
    _clean, events = ai_service._extract_tool_markers(out or "")
    for ev in events:
        yield ev
    yield {"type": "scene_ready", "scene_id": req.scene_id}


@router.post("/pipeline/upload_continue_video")
async def pipeline_upload_continue_video(
    scene_id: str = Form(...),
    workspace: str = Form(default=""),
    session_id: str = Form(default=""),
    model: str = Form(default=""),
    motion_prompt: str = Form(default=""),
    size: str = Form(default=""),
    count: int = Form(default=1),
    file: UploadFile = File(...),
):
    """上传一段视频 → 拼到该镜成片末尾 → 从其尾帧 AI 续写。先存文件，再提交后台任务，返回 job_id。"""
    import os as _os
    import pathlib
    from uuid import uuid4
    from mirage.app.pipeline.runtime import set_workspace, video_dir
    from mirage.app.pipeline.store import get_store
    from mirage.app.services.job_manager import job_manager
    suffix = pathlib.Path(file.filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}:
        raise HTTPException(status_code=400, detail=f"不支持的视频类型 {suffix}（支持 mp4/mov/webm/mkv）")
    set_workspace(workspace or None)
    if not get_store().get_scene(scene_id):
        raise HTTPException(status_code=404, detail=f"分镜不存在: {scene_id}")
    up_name = f"upload_{uuid4().hex[:8]}{suffix}"
    up_path = _os.path.join(video_dir(), up_name)
    with open(up_path, "wb") as f:
        f.write(await file.read())
    req = SceneUploadContinueRequest(
        scene_id=scene_id, workspace=(workspace or None), session_id=(session_id or None),
        model=model, motion_prompt=motion_prompt, size=size, count=count, uploaded_path=up_path)
    meta = {"session_id": req.session_id, "scene_id": scene_id,
            "project_id": _scene_project_id(scene_id, req.workspace)}
    return {"job_id": job_manager.submit(
        "render", lambda: _scene_upload_continue_events(req), meta=meta)}


@router.get("/pipeline/jobs")
async def pipeline_active_jobs(project_id: str | None = None, session_id: str | None = None):
    """列出在跑/排队的任务，供刷新后面板重连（显示进度 + 停止按钮）。"""
    from mirage.app.services.job_manager import job_manager
    return {"jobs": job_manager.list_active(project_id, session_id)}


@router.post("/pipeline/batch_generate")
async def pipeline_batch_generate(req: BatchRequest):
    """一键全部出图：后台单飞任务，返回 job_id。"""
    from mirage.app.services.job_manager import job_manager
    return {"job_id": job_manager.submit("batch_generate", lambda: _batch_generate_events(req), meta={"session_id": req.session_id, "project_id": req.project_id})}


@router.post("/pipeline/batch_finish")
async def pipeline_batch_finish(req: BatchRequest):
    """一键全部出片并合成整集：后台单飞任务，返回 job_id。"""
    from mirage.app.services.job_manager import job_manager
    return {"job_id": job_manager.submit("batch_finish", lambda: _batch_finish_events(req), meta={"session_id": req.session_id, "project_id": req.project_id})}
