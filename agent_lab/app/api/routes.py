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
) -> AsyncGenerator[str, None]:
    """把 ai_service.astream_chat() 的事件流转成 SSE 格式。"""
    gen = ai_service.astream_chat(session_id, content, agent=agent, agent_configs=agent_configs)
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
        
        sessions = {}
        async for c in checkpointer.alist(None):
            thread_id = c.config.get("configurable", {}).get("thread_id", "")
            if not thread_id or not thread_id.startswith("supervisor:"):
                continue
            session_id = thread_id.split(":", 1)[1]
            
            # 仅取每个 session_id 的最新 checkpoint 状态
            if session_id in sessions:
                continue
                
            channel_values = c.checkpoint.get("channel_values", {})
            messages = channel_values.get("messages", [])
            if not messages:
                continue
                
            first_user_msg = next((m.content for m in messages if m.type == "human"), "")
            title = first_user_msg[:40] if first_user_msg else "新会话"
            
            sessions[session_id] = {
                "session_id": session_id,
                "title": title,
                "updated_at": c.checkpoint.get("ts"),
                "message_count": len(messages)
            }
            
        sorted_sessions = sorted(sessions.values(), key=lambda x: x["updated_at"], reverse=True)
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
        
        thread_id = f"supervisor:{session_id}"
        config = {"configurable": {"thread_id": thread_id}}
        
        c = await checkpointer.aget(config)
        if not c:
            return {"messages": []}
            
        channel_values = c.get("channel_values", {})
        messages = channel_values.get("messages", [])
        
        formatted_messages = []
        for msg in messages:
            if msg.type == "system":
                continue
            role = "user" if msg.type == "human" else "assistant"
            formatted_messages.append({
                "id": getattr(msg, "id", None) or str(uuid.uuid4())[:8],
                "role": role,
                "content": msg.content,
                "streaming": False,
                "agentLabel": getattr(msg, "response_metadata", {}).get("agent", "supervisor")
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
        
        # 删除 supervisor 图的 thread
        thread_id = f"supervisor:{session_id}"
        await checkpointer.adelete_thread(thread_id)
        
        # 同时删除子 agent 的 thread（如果有的话）
        for ag in ["code", "file", "batch", "general", "shell"]:
            sub_thread_id = f"{ag}:{session_id}"
            await checkpointer.adelete_thread(sub_thread_id)
            
        return {"success": True}
    except Exception as e:
        logger.exception(f"Failed to delete session {session_id}")
        raise HTTPException(status_code=500, detail=str(e))
