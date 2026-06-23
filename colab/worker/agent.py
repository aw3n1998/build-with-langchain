"""生命周期编排：ping→连 WS→状态线程(HTTP+WS)→claim 循环→分发出片→上传→完成。

HTTP 是权威通道(claim/上传/complete/租约心跳)；WS 给实时状态/进度(断了照常走 HTTP)。
claim 循环平时按 POLL 轮询，收到 WS 的 claim-available nudge 会被立刻叫醒。
"""
from __future__ import annotations

import hashlib
import os
import socket
import threading

from . import gpu
from .runner import HANDLERS
from .transport import HttpClient, WsStatusClient


class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.http = HttpClient(cfg)
        self._state = {"state": "idle", "current_task": "", "progress": "", "vram": "", "done": 0, "fail": 0}
        self._stop = threading.Event()
        self._wake = threading.Event()   # WS claim-available nudge 叫醒 claim 循环
        self.ws = WsStatusClient(cfg, on_nudge=self._wake.set)

    # ── 状态上报：HTTP(权威 last_seen/在线窗) + WS(实时) ──
    def _status_payload(self) -> dict:
        return {"worker_id": self.cfg.worker_id, "gpu": gpu.gpu_name(self.cfg), "hostname": socket.gethostname(),
                "state": self._state["state"], "current_task": self._state["current_task"],
                "progress": self._state["progress"], "vram": self._state["vram"], "types": ",".join(self.cfg.types),
                "done_count": self._state["done"], "fail_count": self._state["fail"]}

    def _push_status(self):
        self._state["vram"] = gpu.vram()
        p = self._status_payload()
        self.http.post_status(p)
        self.ws.send({"type": "status", **p})

    def _status_loop(self):
        while not self._stop.is_set():
            self._push_status()
            self._stop.wait(self.cfg.hb_sec)

    def _on_progress(self, p: str):
        self._state["progress"] = p
        self.ws.send({"type": "progress", "worker_id": self.cfg.worker_id,
                      "current_task": self._state["current_task"], "progress": p})

    def _run_task(self, task: dict):
        tid = task["id"]
        ttype = task.get("type", "")
        self._state.update(state="busy", current_task=tid, progress="开始")
        self._push_status()
        hb_stop = threading.Event()

        def hb_loop():   # 出片期间每 HB 秒续租（HTTP 权威），409→本任务作废
            while not hb_stop.wait(self.cfg.hb_sec):
                if not self.http.heartbeat(tid, self._state.get("progress", "")):
                    hb_stop.set()
        threading.Thread(target=hb_loop, daemon=True).start()

        handler = HANDLERS.get(ttype)
        try:
            if not handler:
                self.http.fail(tid, f"不支持的任务类型 {ttype}", retryable=False)
                self._state["fail"] += 1
                return
            out = handler(self.cfg, task, self._on_progress)
            data = open(out, "rb").read()
            sha = hashlib.sha256(data).hexdigest()
            self.http.put_result(tid, data, sha)
            rc = self.http.complete(tid, sha)
            if getattr(rc, "status_code", 0) == 200:
                self._state["done"] += 1
                print(f"[worker] 完成 {tid}")
            else:
                print(f"[worker] complete 被拒({getattr(rc, 'status_code', '?')})：{getattr(rc, 'text', '')[:120]}")
            try:
                os.remove(out)
            except OSError:
                pass
        except Exception as e:  # noqa: BLE001
            print(f"[worker] 任务 {tid} 失败：{e}")
            self.http.fail(tid, e, retryable=True)
            self._state["fail"] += 1
        finally:
            hb_stop.set()
            self._state.update(state="idle", current_task="", progress="")
            self._push_status()

    def run(self):
        try:
            self.http.ping()
        except Exception as e:  # noqa: BLE001
            print("连不上后端 worker 接口：", e)
            return
        print(f"[worker] {self.cfg.worker_id} 上线 → {self.cfg.api} | GPU={gpu.gpu_name(self.cfg)} | "
              f"领取 {list(self.cfg.types)} | ComfyUI {self.cfg.comfy} | "
              f"WS={'on' if self.ws.available else 'off(HTTP-only)'}")
        self.ws.start()
        threading.Thread(target=self._status_loop, daemon=True).start()
        while not self._stop.is_set():
            task = self.http.claim()
            if not task:
                self._wake.wait(self.cfg.poll_sec)
                self._wake.clear()
                continue
            print(f"[worker] 领到 {task['id']} ({task.get('type')})")
            self._run_task(task)

    def shutdown(self):
        self._stop.set()
        self.ws.stop()
        self.http.close()
