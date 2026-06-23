"""
拉取式 GPU worker 的 WebSocket 实时层（状态/进度），与 worker_routes.py 的 HTTP 权威通道并存。

为什么：HTTP 4s 轮询不够实时。worker 是【只出站】的（GPU 不对外）→ 它【主动开一条 WS 连到后端】推
实时 status/progress；后端鉴权(WORKER_TOKEN)后走同一个 store.upsert_worker(仪表盘唯一真相源)，并
fan-out 广播给前端订阅的 /api/ws/workers。前端 WorkerPanel 实时更新、不再死等 4s。

★只承载轻量实时状态/进度。claim 拉取、结果上传(PUT)、complete(DB权威)、租约心跳全部仍走 HTTP 不变；
WS 断了一切照常走 HTTP + 4s 轮询兜底，零回归。
★worker socket 是双向的(收 auth/status/progress + 发 ack/claim-nudge/pong)——不能照抄只发的 /ws/jobs：
用 recv 主循环 + 每连接一个 outbound 队列的 sender 任务。
"""
from __future__ import annotations

import asyncio
import hmac
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("api.worker_ws")
router = APIRouter()
_ONLINE_SECS = 45


def _store():
    from mirage.app.pipeline.store import get_store
    return get_store()


def _token_ok(tok_in) -> bool:
    tok = (settings.WORKER_TOKEN or "").strip()
    if not tok:
        return True   # 开发态：空 token 放行（与 HTTP _check_token 一致）
    return hmac.compare_digest(str(tok_in or "").strip(), tok)


def _enrich(w: dict, now: float) -> dict:
    ls = float(w.get("last_seen") or 0)
    online = (now - ls) < _ONLINE_SECS
    w["online"] = online
    w["display_state"] = (w.get("state") or "idle") if online else "offline"
    w["last_seen_ago"] = round(now - ls, 1) if ls else None
    return w


class WorkerWSHub:
    """连接管理 + fan-out（仿 job_manager._subscribers 形状）。前端=只收的订阅队列；worker=可发可收。"""

    def __init__(self):
        self._frontends: set[asyncio.Queue] = set()
        self._workers: dict[str, asyncio.Queue] = {}

    async def subscribe_frontend(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._frontends.add(q)
        try:
            q.put_nowait(await self._snapshot())
        except asyncio.QueueFull:
            pass
        return q

    def unsubscribe_frontend(self, q):
        self._frontends.discard(q)

    def broadcast(self, msg: dict):
        for q in list(self._frontends):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass   # 丢这条、不丢订阅者（下次 status 会纠正）；满了也不让仪表盘变黑

    async def _snapshot(self) -> dict:
        now = time.time()
        rows = await asyncio.to_thread(lambda: _store().list_workers())
        queue = await asyncio.to_thread(lambda: _store().list_pending_tasks(50))
        return {"type": "workers_snapshot", "workers": [_enrich(w, now) for w in rows],
                "queue": queue, "dispatch_mode": settings.DISPATCH_MODE, "now": now}

    async def on_status(self, msg: dict):
        """worker 状态帧：走同一个 upsert_worker（仪表盘真相源 + 45s 在线窗一致）+ 广播完整行。"""
        wid = msg.get("worker_id") or ""
        await asyncio.to_thread(lambda: _store().upsert_worker(
            wid, gpu=msg.get("gpu", ""), hostname=msg.get("hostname", ""),
            state=msg.get("state", "idle"), current_task=msg.get("current_task", ""),
            progress=msg.get("progress", ""), vram=msg.get("vram", ""), types=msg.get("types", ""),
            done_count=int(msg.get("done_count", 0) or 0), fail_count=int(msg.get("fail_count", 0) or 0)))
        now = time.time()
        rows = await asyncio.to_thread(lambda: _store().list_workers())
        row = next((r for r in rows if r.get("id") == wid), None)
        if row:
            self.broadcast({"type": "worker_update", "worker": _enrich(row, now), "now": now})

    def on_progress(self, msg: dict):
        """进度帧：高频、不写库（避免覆盖其它字段 + churn），只广播；前端按 id 合并进度。"""
        wid = msg.get("worker_id") or ""
        self.broadcast({"type": "worker_update", "now": time.time(),
                        "worker": {"id": wid, "current_task": msg.get("current_task", ""),
                                   "progress": msg.get("progress", ""), "online": True}})

    def register_worker(self, wid, outq):
        self._workers[wid] = outq

    def unregister_worker(self, wid, outq):
        if self._workers.get(wid) is outq:
            self._workers.pop(wid, None)

    def nudge(self, types):
        """新任务入队时叫醒已连的 worker 立刻 claim（best-effort；漏了有 POLL 兜底）。增量3 dispatch 入队后调。"""
        for outq in list(self._workers.values()):
            try:
                outq.put_nowait({"type": "claim-available", "types": types})
            except asyncio.QueueFull:
                pass


hub = WorkerWSHub()


@router.websocket("/ws/workers")
async def ws_workers(websocket: WebSocket):
    """前端仪表盘订阅：连上即收 workers_snapshot，之后实时 worker_update。无需 token（只读监控，同 GET /workers）。"""
    await websocket.accept()
    q = await hub.subscribe_frontend()
    try:
        while True:
            await websocket.send_json(await q.get())
    except (WebSocketDisconnect, Exception):  # noqa: BLE001
        pass
    finally:
        hub.unsubscribe_frontend(q)


@router.websocket("/worker/ws")
async def worker_ws(websocket: WebSocket):
    """worker(GPU 机)主动连进来推实时状态/进度。双向：收 auth/status/progress、发 ack/claim-nudge/pong。"""
    await websocket.accept()
    try:
        auth = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except Exception:  # noqa: BLE001
        await websocket.close(code=4401)
        return
    if (auth or {}).get("type") != "auth" or not _token_ok((auth or {}).get("worker_token")):
        await websocket.close(code=4401)
        return
    wid = (auth or {}).get("worker_id") or "worker"
    outq: asyncio.Queue = asyncio.Queue(maxsize=100)
    hub.register_worker(wid, outq)
    await websocket.send_json({"type": "ack", "ok": True})

    async def sender():   # 后端→worker（claim-nudge/pong）独立发送任务，与 recv 主循环并发
        try:
            while True:
                await websocket.send_json(await outq.get())
        except Exception:  # noqa: BLE001
            pass
    send_task = asyncio.create_task(sender())
    try:
        while True:
            msg = await websocket.receive_json()
            mt = (msg or {}).get("type")
            if mt == "status":
                await hub.on_status(msg)
            elif mt == "progress":
                hub.on_progress(msg)
            elif mt == "ping":
                try:
                    outq.put_nowait({"type": "pong"})
                except asyncio.QueueFull:
                    pass
            # heartbeat/pong：WS 级保活，不写库（last_seen 由 HTTP status_loop 负责）
    except (WebSocketDisconnect, Exception):  # noqa: BLE001
        pass
    finally:
        send_task.cancel()
        hub.unregister_worker(wid, outq)
