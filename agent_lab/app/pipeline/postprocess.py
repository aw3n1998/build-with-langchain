"""
ComfyUI 后处理层（放大 / 补帧）—— 成片合成后可选再过一道 ComfyUI workflow，提升清晰度/流畅度。

设计原则：
  - 默认关闭：仅当 settings.COMFYUI_WORKFLOW_POST 指向一份**存在的** workflow 才执行；空=不做。
  - 失败安全：后处理任何报错只记日志并**保留原片**，绝不破坏已经合成好的成片。
    （成片在调用本函数前就已落地，后处理只是「锦上添花」，失败不应让整条流水线失败。）
  - 端点可配置：走 settings.COMFYUI_BASE_URL，与出图/出片同一个 ComfyUI。

后处理 workflow 占位符：
  %VIDEO%  上传后的视频文件名（喂给 VHS LoadVideo 之类）
  %FPS%    目标帧率（补帧时用）
  %SEED%   随机种子（一般后处理用不到，留着备用）
真机联调待用户提供 COMFYUI_BASE_URL + 一份放大/补帧 workflow（见 comfyui_workflows/README.md）。
"""

from __future__ import annotations

import os
import time

import httpx

from agent_lab.app.core.config import settings
from agent_lab.app.core.logger import get_logger
from agent_lab.app.pipeline import comfy_http as ch
from agent_lab.app.pipeline import log_bus

logger = get_logger("pipeline.postprocess")


def postprocess_enabled() -> bool:
    """是否配置了后处理 workflow（决定 maybe_postprocess 走不走）。"""
    return bool((settings.COMFYUI_WORKFLOW_POST or "").strip())


def maybe_postprocess(video_path: str, *, fps: int = 0) -> dict:
    """对成片做可选 ComfyUI 后处理（就地替换）。返回 {"applied": bool, "note": str}。

    未启用 / 端点缺失 / 任何失败 → 保留原片，applied=False。只有真正出了增强片才 applied=True。
    """
    if not postprocess_enabled():
        return {"applied": False, "note": "off"}
    wf = (settings.COMFYUI_WORKFLOW_POST or "").strip()
    if not os.path.exists(wf):
        logger.warning("[postprocess] COMFYUI_WORKFLOW_POST 指向的文件不存在: %s（跳过后处理）", wf)
        return {"applied": False, "note": "workflow-missing"}
    try:
        base = ch.base_url()
    except Exception as e:  # noqa: BLE001
        logger.warning("[postprocess] ComfyUI 端点未配置，跳过后处理: %s", e)
        return {"applied": False, "note": "no-endpoint"}

    tmp_out = video_path + ".post.mp4"
    try:
        template = ch.load_workflow(wf, "", "post")
        t0 = time.time()
        client_id = f"agentlab-post-{os.getpid()}-{int(t0)}"
        with httpx.Client() as client:
            vid_name = ch.upload_media(client, base, video_path, "video/mp4")
            mapping = {
                "%VIDEO%": vid_name,
                "%FPS%": int(fps or settings.COMFYUI_FPS),
                "%SEED%": int(time.time_ns() % 2_000_000_000),
            }
            graph = ch.fill_template(template, mapping)
            pid = ch.submit(client, base, graph, client_id)
            log_bus.emit("[画质增强] 正在增强成片（放大/补帧），请稍候…")
            outputs = ch.wait(client, base, pid, label="画质增强")
            items = ch.collect_outputs(outputs)
            vids = [c for c in items
                    if str(c.get("filename", "")).lower().endswith(ch.VIDEO_EXTS)] or items
            if not vids:
                raise RuntimeError("后处理完成但没找到视频产物")
            ch.download_view(client, base, vids[0], tmp_out)
        # 就地替换原片（临时目录可能跨盘，用 move 不用 replace）
        import shutil
        if os.path.exists(video_path):
            os.remove(video_path)
        shutil.move(tmp_out, video_path)
        logger.info("[postprocess] 后处理完成 %.0fs → %s", time.time() - t0, video_path)
        return {"applied": True, "note": "ok"}
    except Exception as e:  # noqa: BLE001 - 失败安全：保留原片
        logger.warning("[postprocess] 后处理失败，保留原片: %s", e)
        if os.path.exists(tmp_out):
            try:
                os.remove(tmp_out)
            except OSError:
                pass
        return {"applied": False, "note": f"failed: {e}"}
