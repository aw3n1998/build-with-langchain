"""
拉取式 GPU worker 的 HTTP 接口（DISPATCH_MODE=worker 时用）+ worker 在线状态注册。

GPU 机上的 worker（colab/worker.py）：周期 push 状态 → 轮询 claim 任务 → 本机出片 →
PUT 上传结果 → complete。另含仪表盘 GET /workers（多 worker 在线状态 + 队列）。

安全：写端点要 X-Worker-Token == settings.WORKER_TOKEN（常数时间比对）；TOKEN 为空=开发态放行
（与 AUTH_ENABLED 关=开放 同philosophy；生产设 WORKER_TOKEN 即强制）。
★complete 是 DB+文件权威：无论有没有活的 SSE Job，都落盘 + 推进 scene 态（评审要求，重启后端不丢成片）。
★落盘文件名从【可信 task 行】推导 + 断言在 video_dir() 内（防 worker payload 路径穿越）。
所有 store I/O 走 asyncio.to_thread（store 用 threading.Lock + 阻塞 sqlite，别堵事件循环）。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("api.worker")
router = APIRouter()

_ONLINE_SECS = 45   # last_seen 在此秒内算在线（worker 心跳/状态 push 间隔应 < 这个）


def _store():
    from mirage.app.pipeline.store import get_store
    return get_store()


def _video_dir() -> str:
    from mirage.app.pipeline.runtime import video_dir
    return os.path.abspath(video_dir())


def _check_token(tok_in: str) -> None:
    tok = (settings.WORKER_TOKEN or "").strip()
    if tok and not hmac.compare_digest((tok_in or "").strip(), tok):
        raise HTTPException(status_code=401, detail="worker token 无效")


def _canonical_output(task: dict) -> str:
    """从【可信 task 行】推导成片落盘绝对路径 + 断言在 video_dir() 内（防 worker payload 路径穿越）。"""
    vd = _video_dir()
    t = task.get("type", "")
    if t in ("render_t2v", "render_i2v", "continuation_one"):
        sid = task.get("scene_id") or ""
        scene = _store().get_scene(sid) if sid else None
        num = int((scene or {}).get("scene_number", 0) or 0)
        name = f"{num:02d}_{sid}.mp4"
    elif t == "assemble":
        name = f"episode_{task.get('project_id','')}.mp4"
    else:
        name = f"{task.get('id','out')}.mp4"
    safe = "".join(c for c in name if c.isalnum() or c in "_.-") or "out.mp4"
    full = os.path.abspath(os.path.join(vd, safe))
    if not (full == vd or full.startswith(vd + os.sep)):
        raise HTTPException(status_code=400, detail="非法输出路径")
    return full


# ──────────────── worker 状态注册 + 仪表盘 ────────────────
class WorkerStatusReq(BaseModel):
    worker_id: str
    gpu: str = ""
    hostname: str = ""
    state: str = "idle"          # idle|busy|error
    current_task: str = ""
    progress: str = ""
    vram: str = ""
    types: str = ""
    models: str = ""             # 本 GPU 能跑的视频模型 provider 名(逗号分隔);''=通配(legacy)
    done_count: int = 0
    fail_count: int = 0


@router.get("/worker/ping")
async def worker_ping(x_worker_token: str = Header(default="")):
    _check_token(x_worker_token)
    return {"now": time.time(), "ok": True}


@router.post("/worker/status")
async def worker_status(req: WorkerStatusReq, x_worker_token: str = Header(default="")):
    """worker 周期 push 自己的 GPU/状态/当前任务/显存 → 仪表盘可见。"""
    _check_token(x_worker_token)
    await asyncio.to_thread(lambda: _store().upsert_worker(
        req.worker_id, gpu=req.gpu, hostname=req.hostname, state=req.state,
        current_task=req.current_task, progress=req.progress, vram=req.vram,
        types=req.types, models=req.models, done_count=req.done_count, fail_count=req.fail_count))
    return {"ok": True}


@router.get("/workers")
async def list_workers():
    """仪表盘：所有 worker 在线状态（last_seen 过期算 offline）+ 当前队列。无需 worker token（只读监控）。"""
    rows = await asyncio.to_thread(lambda: _store().list_workers())
    now = time.time()
    out = []
    for w in rows:
        ls = float(w.get("last_seen") or 0)
        online = (now - ls) < _ONLINE_SECS
        w["online"] = online
        w["display_state"] = (w.get("state") or "idle") if online else "offline"
        w["last_seen_ago"] = round(now - ls, 1) if ls else None
        out.append(w)
    queue = await asyncio.to_thread(lambda: _store().list_pending_tasks(50))
    return {"workers": out, "queue": queue, "now": now, "dispatch_mode": settings.DISPATCH_MODE}


@router.get("/models")
async def list_runnable_models():
    """当前【在线】worker 能跑的视频模型 provider 名并集（供 UI 下拉只展示真能出片的模型）。
    在线判定与 /workers 一致（last_seen 在 _ONLINE_SECS 内）。models 为空的 worker 是通配，不贡献具体模型名。"""
    rows = await asyncio.to_thread(lambda: _store().list_workers())
    now = time.time()
    names: set[str] = set()
    for w in rows:
        if (now - float(w.get("last_seen") or 0)) >= _ONLINE_SECS:
            continue
        for m in (w.get("models") or "").split(","):
            m = m.strip()
            if m:
                names.add(m)
    return {"models": sorted(names), "now": now}


# ──────────────── 任务领取 / 心跳 / 结果 / 完成 / 失败 ────────────────
class ClaimReq(BaseModel):
    worker_id: str
    types: list = []
    lease_secs: int = 0
    models: list = []            # 本 GPU 能跑的视频模型 provider 名;空=通配(legacy,啥任务都领)


@router.post("/worker/claim")
async def worker_claim(req: ClaimReq, x_worker_token: str = Header(default="")):
    _check_token(x_worker_token)
    lease = int(req.lease_secs or settings.WORKER_LEASE_SECS)
    task = await asyncio.to_thread(lambda: _store().claim_one(
        req.worker_id, [str(x) for x in req.types], lease, models=[str(x) for x in req.models]))
    return {"task": task}


class HeartbeatReq(BaseModel):
    worker_id: str
    lease_secs: int = 0
    progress: str = ""


@router.post("/worker/tasks/{task_id}/heartbeat")
async def worker_heartbeat(task_id: str, req: HeartbeatReq, x_worker_token: str = Header(default="")):
    _check_token(x_worker_token)
    lease = int(req.lease_secs or settings.WORKER_LEASE_SECS)
    ok = await asyncio.to_thread(lambda: _store().heartbeat_task(task_id, req.worker_id, lease))
    if req.progress:
        await asyncio.to_thread(lambda: _store().upsert_worker(
            req.worker_id, state="busy", current_task=task_id, progress=req.progress[:200]))
    if not ok:
        raise HTTPException(status_code=409, detail="租约已失效（被重领/完成），worker 应自我中止")
    return {"ok": True}


@router.put("/worker/tasks/{task_id}/result")
async def worker_result(task_id: str, request: Request,
                        x_worker_token: str = Header(default=""),
                        x_total_sha256: str = Header(default="")):
    """流式接收 worker 上传的成片到 .uploads/{task_id}.part（边收边 sha256；可选校验）。"""
    _check_token(x_worker_token)
    updir = os.path.join(_video_dir(), ".uploads")
    os.makedirs(updir, exist_ok=True)
    part = os.path.join(updir, f"{task_id}.part")
    h = hashlib.sha256()
    total = 0
    with open(part, "wb") as f:
        async for chunk in request.stream():
            if chunk:
                f.write(chunk); h.update(chunk); total += len(chunk)
    sha = h.hexdigest()
    if x_total_sha256 and x_total_sha256.lower() != sha:
        try:
            os.remove(part)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="上传校验失败（sha256 不符）")
    return {"received_bytes": total, "sha256": sha}


class CompleteReq(BaseModel):
    worker_id: str
    sha256: str = ""
    duration_ms: int = 0


@router.post("/worker/tasks/{task_id}/complete")
async def worker_complete(task_id: str, req: CompleteReq, x_worker_token: str = Header(default="")):
    """★DB+文件权威：把 .part 重命名到从 task 行推导的权威文件名 → 标 task done + 推进 scene 态。
    无论有没有活的 SSE Job 都落库（评审要求：重启后端也不丢成片，前端靠重连查 scene 态恢复）。"""
    _check_token(x_worker_token)

    def _finish():
        st = _store()
        task = st.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        final = _canonical_output(task)
        part = os.path.join(_video_dir(), ".uploads", f"{task_id}.part")
        if os.path.exists(part):
            os.replace(part, final)
        elif not (os.path.exists(final) or task.get("state") == "done"):
            raise HTTPException(status_code=400, detail="未收到结果文件（先 PUT /result）")
        res = {"video_filename": os.path.basename(final), "sha256": req.sha256, "duration_ms": req.duration_ms}
        done = st.complete_task(task_id, req.worker_id, res)
        if done is None:
            raise HTTPException(status_code=409, detail="租约已失效（被重领），拒绝过期 worker 的完成")
        sid = task.get("scene_id") or ""
        if sid and task.get("type") in ("render_t2v", "render_i2v", "continuation_one"):
            try:
                st.set_scene_video(sid, final)
            except Exception as e:  # noqa: BLE001
                logger.warning("[worker] set_scene_video 失败 %s: %s", sid, e)
        st.upsert_worker(req.worker_id, state="idle", current_task="", progress="完成 " + os.path.basename(final))
        return {"ok": True, "video": "/api/file?path=" + final}

    return await asyncio.to_thread(_finish)


class FailReq(BaseModel):
    worker_id: str
    error: str = ""
    retryable: bool = True


@router.post("/worker/tasks/{task_id}/fail")
async def worker_fail(task_id: str, req: FailReq, x_worker_token: str = Header(default="")):
    _check_token(x_worker_token)

    def _do():
        st = _store()
        r = st.fail_task(task_id, req.worker_id, req.error, req.retryable)
        if r is None:
            raise HTTPException(status_code=409, detail="租约已失效")
        if r.get("state") == "failed":
            task = st.get_task(task_id) or {}
            sid = task.get("scene_id") or ""
            if sid:
                try:
                    from mirage.app.pipeline.store import SceneState
                    st.set_scene_state(sid, SceneState.FAILED, force=True)
                except Exception:  # noqa: BLE001
                    pass
        st.upsert_worker(req.worker_id, state="idle", current_task="", progress="失败: " + (req.error or "")[:80])
        return r

    r = await asyncio.to_thread(_do)
    return {"ok": True, "state": r.get("state")}


async def reclaim_sweeper_loop(interval: int = 30):
    """后台回收过期租约（worker 挂了/断网的任务回 pending 重派 或 failed）。DISPATCH_MODE=worker 才起。"""
    logger.info("[worker] reclaim sweeper 启动（每 %ds）", interval)
    while True:
        try:
            reclaimed = await asyncio.to_thread(lambda: _store().reclaim_expired())
            for t in reclaimed:
                if t.get("state") == "failed":
                    sid = t.get("scene_id") or ""
                    if sid:
                        try:
                            from mirage.app.pipeline.store import SceneState
                            await asyncio.to_thread(lambda: _store().set_scene_state(sid, SceneState.FAILED, force=True))
                        except Exception:  # noqa: BLE001
                            pass
            if reclaimed:
                logger.info("[worker] 回收过期任务 %d 个", len(reclaimed))
        except Exception as e:  # noqa: BLE001
            logger.warning("[worker] reclaim sweeper 异常: %s", e)
        await asyncio.sleep(interval)
