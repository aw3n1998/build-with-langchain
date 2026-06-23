#!/usr/bin/env python3
"""
Mirage GPU worker —— 跑在 GPU 机器上的「领任务」程序（拉取式架构的 worker 端）。

它做的事：周期把自己的 GPU/状态 push 给后端 → 轮询后端 claim 出片任务 → 用【本机 ComfyUI】
出片 → 把成片上传回后端 → complete。后端永远不用够得着 GPU；要扩容就在更多 GPU 机器上各跑一个
本脚本（都连同一个 BACKEND_URL），原子领取保证不重复。★一台 ComfyUI 只跑一个 worker 进程（防 VRAM OOM）。

跑法（在仓库根目录，让它能 import mirage.app.pipeline.comfy_http）：
  BACKEND_URL=https://你的后端  WORKER_TOKEN=和后端一致的密钥 \
  COMFYUI_BASE_URL=http://127.0.0.1:8188  PYTHONPATH=. python colab/worker.py

环境变量：
  BACKEND_URL       后端根（如 http://127.0.0.1:8000）       必填
  WORKER_TOKEN      与后端 settings.WORKER_TOKEN 一致（后端设了才校验）
  WORKER_ID         worker 标识（默认 hostname-pid）
  WORKER_TYPES      领哪些任务类型，逗号分隔（默认 render_t2v）
  COMFYUI_BASE_URL  本机 ComfyUI（默认 http://127.0.0.1:8188）
  GPU_NAME          仪表盘显示名（默认 nvidia-smi 探测）
  POLL_SEC=3  LEASE_SEC=1200  HEARTBEAT_SEC=20

后端需 DISPATCH_MODE=worker 才会把出片任务入队给 worker；否则队列恒空、本脚本只会闲等。
"""
import hashlib
import os
import socket
import subprocess
import sys
import threading
import time

import httpx

API = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/") + "/api"
TOKEN = os.environ.get("WORKER_TOKEN", "")
WID = os.environ.get("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
TYPES = [t.strip() for t in os.environ.get("WORKER_TYPES", "render_t2v").split(",") if t.strip()]
COMFY = os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/")
GPU_OVERRIDE = os.environ.get("GPU_NAME", "")
POLL = float(os.environ.get("POLL_SEC", 3))
LEASE = int(os.environ.get("LEASE_SEC", 1200))
HB = float(os.environ.get("HEARTBEAT_SEC", 20))
HEAD = {"X-Worker-Token": TOKEN}

_state = {"state": "idle", "current_task": "", "progress": "", "done": 0, "fail": 0, "vram": ""}
_stop = threading.Event()


def _nvsmi(query: str) -> str:
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5)
        return (out.stdout or "").strip().splitlines()[0].strip()
    except Exception:
        return ""


def _gpu_name() -> str:
    return GPU_OVERRIDE or _nvsmi("name") or "GPU"


def _vram() -> str:
    raw = _nvsmi("memory.used,memory.total")
    if not raw:
        return ""
    try:
        u, t = [int(x) for x in raw.split(",")]
        return f"{u // 1024}/{t // 1024}GB" if t > 2000 else f"{u}/{t}MB"
    except Exception:
        return ""


def push_status(client: httpx.Client) -> None:
    try:
        _state["vram"] = _vram()
        client.post(f"{API}/worker/status", headers=HEAD, json={
            "worker_id": WID, "gpu": _gpu_name(), "hostname": socket.gethostname(),
            "state": _state["state"], "current_task": _state["current_task"],
            "progress": _state["progress"], "vram": _state["vram"], "types": ",".join(TYPES),
            "done_count": _state["done"], "fail_count": _state["fail"]})
    except Exception:
        pass


def status_loop() -> None:
    with httpx.Client(timeout=15) as client:
        while not _stop.is_set():
            push_status(client)
            _stop.wait(HB)


def render_t2v(task: dict, on_progress) -> str:
    """本机 ComfyUI 出 t2v 片，返回本地 mp4 路径。payload 自包含：template_path + mapping(占位符→值)。
    ★复用后端同一套 comfy_http（零分叉）；模板从同仓 comfyui_workflows/ 加载（worker 机也有仓库）。"""
    sys.path.insert(0, os.getcwd())
    from mirage.app.pipeline import comfy_http as ch  # noqa: E402

    payload = task.get("payload") or {}
    tpath = payload.get("template_path") or ""
    if not tpath:
        raise RuntimeError("payload 缺 template_path（后端 dispatch 未打包模板）")
    template = ch.load_workflow(tpath, os.path.basename(tpath), "t2v")
    graph = ch.fill_template(template, payload.get("mapping", {}))
    out = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"{task['id']}.mp4")
    vexts = getattr(ch, "VIDEO_EXTS", (".mp4", ".webm", ".mov"))
    with httpx.Client(timeout=None) as cc:
        pid = ch.submit(cc, COMFY, graph, f"mirage-worker-{task['id']}")
        on_progress("ComfyUI 出片中…")
        hist = ch.wait(cc, COMFY, pid, label="worker-t2v")
        outs = ch.collect_outputs(hist)
        vids = [o for o in outs if str(o.get("filename", "")).lower().endswith(vexts)] or outs
        if not vids:
            raise RuntimeError("ComfyUI 没产出视频")
        ch.download_view(cc, COMFY, vids[0], out)
    return out


HANDLERS = {"render_t2v": render_t2v}


def _heartbeat(client: httpx.Client, task_id: str, progress: str = "") -> bool:
    """续租。返回 False 表示 409（被重领/完成），worker 应中止本任务。"""
    try:
        r = client.post(f"{API}/worker/tasks/{task_id}/heartbeat", headers=HEAD,
                        json={"worker_id": WID, "lease_secs": LEASE, "progress": progress})
        return r.status_code != 409
    except Exception:
        return True


def run_task(client: httpx.Client, task: dict) -> None:
    tid = task["id"]
    ttype = task.get("type", "")
    _state.update(state="busy", current_task=tid, progress="开始")
    push_status(client)

    # 后台续租线程：长出片期间每 HB 秒续一次租约（否则 reclaim sweeper 会重派）。
    hb_stop = threading.Event()
    lost = threading.Event()

    def hb_loop():
        with httpx.Client(timeout=15) as c:
            while not hb_stop.wait(HB):
                if not _heartbeat(c, tid, _state.get("progress", "")):
                    lost.set()
                    return
    hbt = threading.Thread(target=hb_loop, daemon=True)
    hbt.start()

    handler = HANDLERS.get(ttype)
    try:
        if not handler:
            client.post(f"{API}/worker/tasks/{tid}/fail", headers=HEAD,
                        json={"worker_id": WID, "error": f"不支持的任务类型 {ttype}", "retryable": False})
            _state["fail"] += 1
            return
        out = handler(task, lambda p: _state.__setitem__("progress", p))
        # 上传成片（流式 content）+ 完成
        data = open(out, "rb").read()
        sha = hashlib.sha256(data).hexdigest()
        client.put(f"{API}/worker/tasks/{tid}/result", headers={**HEAD, "X-Total-Sha256": sha}, content=data)
        rc = client.post(f"{API}/worker/tasks/{tid}/complete", headers=HEAD,
                         json={"worker_id": WID, "sha256": sha})
        if rc.status_code == 200:
            _state["done"] += 1
            print(f"[worker] 完成 {tid}")
        else:
            print(f"[worker] complete 被拒({rc.status_code})：{rc.text[:120]}")
        try:
            os.remove(out)
        except OSError:
            pass
    except Exception as e:  # noqa: BLE001
        print(f"[worker] 任务 {tid} 失败：{e}")
        try:
            client.post(f"{API}/worker/tasks/{tid}/fail", headers=HEAD,
                        json={"worker_id": WID, "error": str(e)[:500], "retryable": True})
        except Exception:
            pass
        _state["fail"] += 1
    finally:
        hb_stop.set()
        _state.update(state="idle", current_task="", progress="")
        push_status(client)


def main() -> None:
    if not TOKEN:
        print("[worker] 警告：未设 WORKER_TOKEN（后端若设了 token 会全部 401）")
    with httpx.Client(timeout=15) as client:
        try:
            client.get(f"{API}/worker/ping", headers=HEAD).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print("连不上后端 worker 接口：", e)
            sys.exit(1)
        print(f"[worker] {WID} 上线 → {API} | GPU={_gpu_name()} | 领取 {TYPES} | ComfyUI {COMFY}")
        threading.Thread(target=status_loop, daemon=True).start()
        while not _stop.is_set():
            try:
                r = client.post(f"{API}/worker/claim", headers=HEAD,
                                json={"worker_id": WID, "types": TYPES, "lease_secs": LEASE})
                task = (r.json() or {}).get("task")
            except Exception as e:  # noqa: BLE001
                print("claim 出错：", e)
                time.sleep(POLL)
                continue
            if not task:
                time.sleep(POLL)
                continue
            print(f"[worker] 领到 {task['id']} ({task.get('type')})")
            run_task(client, task)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _stop.set()
        print("\n[worker] 退出")
