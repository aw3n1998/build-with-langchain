"""worker 配置 —— 全部从环境变量解析成一个不可变 Config（无 I/O、无线程）。"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass


def _truthy(v: str) -> bool:
    return str(v).strip().lower() not in ("0", "false", "no", "off", "")


@dataclass(frozen=True)
class Config:
    backend: str          # 后端根 http(s)://host[:port]
    api: str              # backend + /api
    token: str            # WORKER_TOKEN（后端设了才校验）
    worker_id: str        # 默认 hostname-pid
    types: tuple          # 领哪些任务类型
    comfy: str            # 本机 ComfyUI 根
    gpu_name: str         # 仪表盘显示名覆盖（空=nvidia-smi 探测）
    poll_sec: float       # 无 WS 唤醒时的 claim 轮询间隔
    lease_sec: int        # 任务租约（秒）
    hb_sec: float         # HTTP 状态/心跳间隔（last_seen 在线窗靠它）
    ws_enabled: bool      # 开 WS 实时状态（缺 websockets 库会自动降级 HTTP-only）
    ws_reconnect_sec: float

    @property
    def http_headers(self) -> dict:
        return {"X-Worker-Token": self.token}

    @property
    def ws_url(self) -> str:
        b = self.backend.replace("https://", "wss://").replace("http://", "ws://")
        return b + "/api/worker/ws"

    @classmethod
    def from_env(cls) -> "Config":
        backend = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
        return cls(
            backend=backend,
            api=backend + "/api",
            token=os.environ.get("WORKER_TOKEN", ""),
            worker_id=os.environ.get("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}",
            types=tuple(t.strip() for t in os.environ.get("WORKER_TYPES", "render_t2v").split(",") if t.strip()),
            comfy=os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/"),
            gpu_name=os.environ.get("GPU_NAME", ""),
            poll_sec=float(os.environ.get("POLL_SEC", 3)),
            lease_sec=int(os.environ.get("LEASE_SEC", 1200)),
            hb_sec=float(os.environ.get("HEARTBEAT_SEC", 20)),
            ws_enabled=_truthy(os.environ.get("WS_ENABLED", "1")),
            ws_reconnect_sec=float(os.environ.get("WS_RECONNECT_SEC", 5)),
        )
