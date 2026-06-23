"""出片执行层：纯计算。复用后端【同一个】t2v provider 跑本机 ComfyUI 出片。无 claim/上传/完成 逻辑。"""
from __future__ import annotations

import os
import sys


def render_t2v(cfg, task: dict, on_progress) -> str:
    """payload 自包含 {prompt, params, image_path}——直接喂后端同一个 ComfyUIT2VProvider（零分叉）。
    provider 读 settings.COMFYUI_BASE_URL=本机 ComfyUI(worker env 设)；out_remote=本地临时 mp4，返回其路径。"""
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())   # 让 import mirage.* 走仓库根
    from mirage.app.pipeline.providers.comfyui_t2v import ComfyUIT2VProvider  # noqa: E402

    payload = task.get("payload") or {}
    out = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"{task['id']}.mp4")
    on_progress("ComfyUI 出片中…")
    ComfyUIT2VProvider().generate(None, image_path=payload.get("image_path", ""),
                                  prompt=payload.get("prompt", ""), out_remote=out,
                                  params=payload.get("params") or {})
    if not (os.path.exists(out) and os.path.getsize(out) > 0):
        raise RuntimeError("ComfyUI 没产出视频")
    return out


# 任务类型 → 执行函数。新类型(i2v/续接/upscale)在这里加一个 handler 即可。
HANDLERS = {"render_t2v": render_t2v}
