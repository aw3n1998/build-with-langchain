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

  每条消息以 \n\n 结尾，前端用 EventSource API 接收。

面试问答：
Q: 为什么用 SSE 不用 WebSocket？
A: AI 回复是单向流（服务端 → 客户端），SSE 够用且更简单：
   - 基于 HTTP，无需握手协议，防火墙友好
   - 原生支持断线重连（EventSource 自动重试）
   - WebSocket 是双向通信，适合聊天室/协同编辑等场景
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

class ChatRequest(BaseModel):
    session_id: str = Field(
        default_factory=lambda: f"sid-{str(uuid.uuid4())[:8]}",
        description="会话 ID，同一个 session_id 共享对话历史",
    )
    content: str = Field(..., min_length=1, description="用户消息")


class IngestResponse(BaseModel):
    success: bool
    message: str
    session_id: str | None = None


class StatusResponse(BaseModel):
    rag_connected: bool
    chunk_count: int
    model: str


# ── 工具函数 ────────────────────────────────────────────────────

async def sse_generator(session_id: str, content: str) -> AsyncGenerator[str, None]:
    """
    把 ai_service.astream_chat() 的 chunk 转成 SSE 格式。

    SSE 协议规定：每条消息格式为 "data: <内容>\n\n"
    前端 EventSource 收到后自动触发 onmessage 事件。
    """
    try:
        async for chunk in ai_service.astream_chat(session_id, content):
            payload = json.dumps({"type": "chunk", "content": chunk}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

        # 发送结束信号，前端据此关闭 EventSource 连接
        yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"

    except Exception as e:
        logger.exception("[SSE] session=%s 异常", session_id)
        error_payload = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
        yield f"data: {error_payload}\n\n"


# ── 路由 ────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """
    与 AI Agent 对话（SSE 流式）。

    前端调用示例（JavaScript）：
        const es = new EventSource('/api/chat');
        // 注：EventSource 只支持 GET，POST 需用 fetch + ReadableStream

        // 推荐方式：fetch + ReadableStream
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: 'sid-001', content: '你好'})
        });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            const text = decoder.decode(value);
            // 解析 SSE 格式: "data: {...}\n\n"
            for (const line of text.split('\n')) {
                if (line.startsWith('data: ')) {
                    const msg = JSON.parse(line.slice(6));
                    if (msg.type === 'chunk') display(msg.content);
                }
            }
        }
    """
    logger.info("[Chat] session=%s  msg=%s", request.session_id, request.content[:40])
    return StreamingResponse(
        sse_generator(request.session_id, request.content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 关闭 Nginx 缓冲，保证流实时到达
        },
    )


@router.post("/rag/ingest/file", response_model=IngestResponse)
async def ingest_file(
    file: UploadFile = File(..., description="要导入的文档（.txt / .pdf / .docx）"),
    project_id: str = Form(default="default", description="项目 ID，多租户隔离用"),
):
    """
    上传文档并导入知识库。

    curl 调用示例：
        curl -X POST http://localhost:8000/api/rag/ingest/file \\
          -F "file=@施工验收规范.txt" \\
          -F "project_id=proj_001"
    """
    # 把上传文件写到临时目录
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
    """
    直接导入纯文本到知识库（不需要上传文件）。

    curl 调用示例：
        curl -X POST http://localhost:8000/api/rag/ingest/text \\
          -d "content=防水层施工须进行蓄水试验，蓄水时间不少于24小时" \\
          -d "source_name=施工规范" \\
          -d "project_id=proj_001"
    """
    pipeline = ai_service._rag_pipeline
    result = pipeline.ingest_text(content, source_name=source_name, project_id=project_id)
    return IngestResponse(success=result.startswith("✅"), message=result)


@router.get("/rag/status", response_model=StatusResponse)
async def rag_status():
    """
    查询 RAG 知识库状态。

    返回：
      - rag_connected: Milvus 是否已连接
      - chunk_count: 当前知识库中的 chunk 数量
      - model: 当前使用的 LLM 模型名称
    """
    from agent_lab.app.core.config import settings
    pipeline = ai_service._rag_pipeline
    return StatusResponse(
        rag_connected=pipeline.is_connected if pipeline else False,
        chunk_count=pipeline.chunk_count if pipeline else 0,
        model=settings.MODEL_NAME,
    )


@router.get("/health")
async def health():
    """健康检查，给 Docker / K8S 探针用。"""
    return {"status": "ok"}
