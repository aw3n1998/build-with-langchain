"""传输层：HTTP 权威通道(claim/心跳/上传/完成/失败) + WS 实时状态通道(可选、缺库自动降级)。

★HTTP 是权威：claim 拉取、结果 PUT、complete(DB权威)、租约心跳 全走 HTTP，语义不变。
★WS 只承载轻量实时 status/progress；缺 websockets 库或 WS_ENABLED=0 → 自动 no-op，agent 退回纯 HTTP。
"""
from __future__ import annotations

import asyncio
import json
import threading

import httpx

try:
    import websockets
except Exception:  # noqa: BLE001
    websockets = None


class HttpClient:
    """权威通道。语义与后端 worker_routes HTTP 端点一一对应。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self._c = httpx.Client(timeout=30, headers=cfg.http_headers)

    def ping(self):
        self._c.get(f"{self.cfg.api}/worker/ping").raise_for_status()

    def post_status(self, payload):
        try:
            self._c.post(f"{self.cfg.api}/worker/status", json=payload)
        except Exception:  # noqa: BLE001
            pass

    def claim(self):
        try:
            r = self._c.post(f"{self.cfg.api}/worker/claim", json={
                "worker_id": self.cfg.worker_id, "types": list(self.cfg.types), "lease_secs": self.cfg.lease_sec})
            return (r.json() or {}).get("task")
        except Exception:  # noqa: BLE001
            return None

    def heartbeat(self, task_id, progress=""):
        try:
            r = self._c.post(f"{self.cfg.api}/worker/tasks/{task_id}/heartbeat", json={
                "worker_id": self.cfg.worker_id, "lease_secs": self.cfg.lease_sec, "progress": progress})
            return r.status_code != 409   # 409=租约失效，worker 该中止
        except Exception:  # noqa: BLE001
            return True

    def put_result(self, task_id, data, sha):
        return self._c.put(f"{self.cfg.api}/worker/tasks/{task_id}/result",
                           headers={**self.cfg.http_headers, "X-Total-Sha256": sha}, content=data)

    def complete(self, task_id, sha):
        return self._c.post(f"{self.cfg.api}/worker/tasks/{task_id}/complete",
                            json={"worker_id": self.cfg.worker_id, "sha256": sha})

    def fail(self, task_id, err, retryable=True):
        try:
            self._c.post(f"{self.cfg.api}/worker/tasks/{task_id}/fail", json={
                "worker_id": self.cfg.worker_id, "error": str(err)[:500], "retryable": retryable})
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        try:
            self._c.close()
        except Exception:  # noqa: BLE001
            pass


class WsStatusClient:
    """实时状态/进度通道：worker 主动开一条 WS 连后端推 status/progress、收 claim-nudge。
    在独立线程跑自己的 asyncio loop；send() 线程安全。缺库/关闭 → available=False、全 no-op。"""

    def __init__(self, cfg, on_nudge=None):
        self.cfg = cfg
        self._on_nudge = on_nudge
        self._loop = None
        self._outq = None
        self._last_status = None
        self._stop = threading.Event()
        self._thread = None
        self.available = bool(cfg.ws_enabled and websockets is not None)
        self.connected = False

    def start(self):
        if not self.available:
            return
        self._thread = threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True)
        self._thread.start()

    def send(self, msg: dict):
        if msg.get("type") == "status":
            self._last_status = msg   # 重连后补发用
        loop, q = self._loop, self._outq
        if loop and q and self.connected:
            try:
                loop.call_soon_threadsafe(q.put_nowait, msg)
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        self._stop.set()

    async def _run(self):
        self._loop = asyncio.get_event_loop()
        self._outq = asyncio.Queue(maxsize=200)
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.cfg.ws_url) as ws:
                    await ws.send(json.dumps({"type": "auth", "worker_token": self.cfg.token, "worker_id": self.cfg.worker_id}))
                    await ws.recv()   # ack
                    self.connected = True
                    if self._last_status:   # ★重连后立刻补发当前完整状态，仪表盘不卡在旧值
                        try:
                            await ws.send(json.dumps(self._last_status))
                        except Exception:  # noqa: BLE001
                            pass
                    await asyncio.gather(self._send_loop(ws), self._recv_loop(ws))
            except Exception:  # noqa: BLE001 - 断开/连不上：退避后重连，绝不抛进 agent
                pass
            finally:
                self.connected = False
            if self._stop.is_set():
                break
            await asyncio.sleep(self.cfg.ws_reconnect_sec)

    async def _send_loop(self, ws):
        while not self._stop.is_set():
            await ws.send(json.dumps(await self._outq.get()))

    async def _recv_loop(self, ws):
        while not self._stop.is_set():
            m = json.loads(await ws.recv())
            t = (m or {}).get("type")
            if t == "claim-available" and self._on_nudge:
                self._on_nudge()
            elif t == "ping":
                try:
                    await ws.send(json.dumps({"type": "pong"}))
                except Exception:  # noqa: BLE001
                    pass
