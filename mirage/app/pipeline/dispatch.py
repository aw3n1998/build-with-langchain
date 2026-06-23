"""拉取式派发（增量3）：DISPATCH_MODE=worker 且 kind 在 WORKER_KINDS 时，把出片任务【入队】给 GPU
worker 拉取出片，后端不在本机跑 ComfyUI。local 模式完全不经过这里（零回归）。

设计要点（配合 worker_routes/worker_ws）：
- 后端【只入队 + 等结果】，绝不连 GPU（GPU 不对外、主动权在 worker）。
- payload 自包含 {prompt, params, image_path}——worker 端 runner 直接喂同一个 ComfyUIT2VProvider 出片，零分叉。
- worker /complete 是 DB+文件权威：把成片落到从 task 行推导的【同一个】规范文件名(scene_number+scene_id)，
  并 set_scene_video + COMPLETED。所以这里只需轮询到 done，返回与 local 完全一致的 VIDFILE 标记给上层。
"""
from __future__ import annotations

import time

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("pipeline.dispatch")


def should_use_worker(kind: str) -> bool:
    if (settings.DISPATCH_MODE or "local").strip().lower() != "worker":
        return False
    kinds = [k.strip() for k in (settings.WORKER_KINDS or "").split(",") if k.strip()]
    return kind in kinds


_ONLINE_SECS = 45   # 与 worker_routes 一致：last_seen 在此秒内算在线

def _any_worker_can_run(store, provider: str) -> bool:
    """有没有在线 worker 能领这个 provider 的任务(通配 worker 或显式声明了它)。provider 空=通配任务总能领。"""
    if not provider:
        return True
    now = time.time()
    for w in store.list_workers():
        if (now - float(w.get("last_seen") or 0)) >= _ONLINE_SECS:
            continue   # 离线跳过
        models = [m.strip() for m in (w.get("models") or "").split(",") if m.strip()]
        if not models or provider in models:   # 通配(没声明) or 声明了这个 provider
            return True
    return False


def render_t2v_on_worker(scene_id: str, scene: dict, prompt: str, params: dict,
                         image_path: str, final_local: str) -> str:
    """把一镜 t2v 入队给 worker，同步轮询等出完。返回与 local 一致的 VIDFILE 标记（worker 已落盘 final_local）。"""
    from mirage.app.pipeline.store import get_store, SceneState
    from mirage.app.pipeline import log_bus
    store = get_store()
    try:
        store.set_scene_state(scene_id, SceneState.PENDING_VIDEO_GEN, force=True)
    except Exception:  # noqa: BLE001
        pass
    # provider=本任务要哪个出片模型(默认 comfyui-t2v)。落进 payload 让 worker runner 按名跑，
    # 同时落进 task.provider 让 claim_one 只把活派给「能跑这个模型」的 worker（模型感知路由）。
    provider = (settings.T2V_PROVIDER or "comfyui-t2v")
    payload = {"prompt": prompt, "params": params or {}, "image_path": image_path or "",
               "scene_number": scene.get("scene_number", 0), "kind": "render_t2v",
               "provider": provider}
    tid = store.enqueue_task("render_t2v", payload, scene_id=scene_id,
                             project_id=scene.get("project_id", ""), provider=provider)
    try:   # 路由性预警：没在线 worker 能跑这个 provider → 任务会一直排队，提前喊一声别让用户干等
        if not _any_worker_can_run(store, provider):
            log_bus.emit(f"⚠️ 当前没有在线 GPU worker 能跑「{provider}」——任务 {tid} 会一直排队。"
                         f"请在对应 GPU 的 worker 设 WORKER_MODELS 含「{provider}」(或留空=通配)，见算力面板。")
    except Exception:  # noqa: BLE001
        pass
    try:   # 叫醒已连 worker 立刻 claim（best-effort；漏了有 worker POLL 兜底）
        from mirage.app.api import worker_ws
        worker_ws.hub.nudge(["render_t2v"])
    except Exception:  # noqa: BLE001
        pass
    log_bus.emit(f"[worker] 已入队 {tid}，等 GPU worker 领取出片…（算力面板可看进度）")
    deadline = time.time() + int(settings.WORKER_LEASE_SECS) * max(1, int(settings.WORKER_MAX_ATTEMPTS)) + 180
    last = ""
    while time.time() < deadline:
        time.sleep(3)
        task = store.get_task(tid)
        if not task:
            return f"文生视频(worker)出片失败：任务 {tid} 丢失。"
        st = task.get("state")
        if st == "done":
            log_bus.emit(f"[worker] 出片完成 {scene_id}")
            return (f"文生视频(worker 出片)完成，分镜 {scene_id} 标记 COMPLETED。\n"
                    f"VIDFILE::{scene_id}::{final_local}")
        if st == "failed":
            return f"文生视频(worker)出片失败：{task.get('error') or '未知'}（可重出或看算力面板）"
        if st == "cancelled":   # 用户在算力面板点了取消 → 别再死等，立刻收尾
            log_bus.emit(f"[worker] 任务已取消 {scene_id}")
            return f"文生视频(worker)已取消（任务 {tid}）。"
        if st != last:
            log_bus.emit(f"[worker] 出片中…（{st}）")
            last = st
    return "文生视频(worker)出片超时——worker 可能离线，去「算力」面板看；可重出。"
