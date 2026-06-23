"""出片执行层：纯计算。复用后端 comfy_http 跑【本机】ComfyUI 出片。无 claim/上传/完成 逻辑。"""
from __future__ import annotations

import os
import sys

import httpx


def render_t2v(cfg, task: dict, on_progress) -> str:
    """payload 自包含：template_path + mapping(占位符→值)。返回本地 mp4 路径。
    ★复用后端同一套 comfy_http（零分叉）；模板从同仓 comfyui_workflows/ 加载（worker 机也有仓库）。"""
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())   # 让 import mirage.app.pipeline.comfy_http 走仓库根
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
        pid = ch.submit(cc, cfg.comfy, graph, f"mirage-worker-{task['id']}")
        on_progress("ComfyUI 出片中…")
        hist = ch.wait(cc, cfg.comfy, pid, label="worker-t2v")
        outs = ch.collect_outputs(hist)
        vids = [o for o in outs if str(o.get("filename", "")).lower().endswith(vexts)] or outs
        if not vids:
            raise RuntimeError("ComfyUI 没产出视频")
        ch.download_view(cc, cfg.comfy, vids[0], out)
    return out


# 任务类型 → 执行函数。新类型(i2v/续接/upscale)在这里加一个 handler 即可。
HANDLERS = {"render_t2v": render_t2v}
