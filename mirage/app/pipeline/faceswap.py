"""ComfyUI 视频换脸 —— 把一张源脸贴到已有成片里的人物上（ReActor 等，后处理）。

合规红线：仅用于你有权使用的脸（原创 / AI 生成 / 本人授权）。把视频里的人换成
可识别的真人=deepfake，ReelShort/DramaBox 等平台 ToS 与多地法律禁止——本功能定位是
"给原创/虚构角色保持同一张脸跨镜一致"，不是伪造真人。

设计同 postprocess（保持一致、可插拔）：
  - 默认关闭：FACESWAP_ENABLED 且配了 COMFYUI_BASE_URL 且模板存在才工作；否则休眠。
  - 失败安全：任何报错只记日志并**保留原片**，绝不破坏已合成好的成片。
  - 产物落**独立新文件**（不覆盖原片，可对比/回退）。
  - 端点 / 换脸模型 / 修复模型 / 检测模型全可配（settings.FACESWAP_*）。
节点名与入参以 comfyui_workflows/faceswap_video_template.json 为准（脚手架·首跑真机核对）。
"""

from __future__ import annotations

import os
import time

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline import comfy_http as ch
from mirage.app.pipeline import log_bus

logger = get_logger("pipeline.faceswap")


def _workflow_path() -> str:
    return (settings.COMFYUI_WORKFLOW_FACESWAP
            or "comfyui_workflows/faceswap_video_template.json").strip()


def faceswap_enabled() -> bool:
    """是否可用（决定 provider/前端按钮是否亮）：开关 + 端点 + 模板都齐才算。"""
    wf = _workflow_path()
    return bool(settings.FACESWAP_ENABLED and settings.COMFYUI_BASE_URL
                and wf and os.path.exists(wf))


def faceswap_video(in_path: str, face_path: str, out_path: str, *, fps: int = 0) -> dict:
    """把 face_path 的脸换到 in_path 视频里的人物上，产物落 out_path（不动原片）。

    返回 {"applied": bool, "note": str, "out": str}。未启用/缺端点/任何失败 → applied=False 且保留原片。
    """
    if not (in_path and os.path.exists(in_path)):
        return {"applied": False, "note": "源视频不存在"}
    if not (face_path and os.path.exists(face_path)):
        return {"applied": False, "note": "源脸图片不存在"}
    wf = _workflow_path()
    if not os.path.exists(wf):
        return {"applied": False, "note": f"换脸 workflow 模板不存在: {wf}"}
    try:
        base = ch.base_url()
    except Exception as e:  # noqa: BLE001
        return {"applied": False, "note": f"ComfyUI 端点未配置: {e}"}

    tmp = out_path + ".swap.tmp.mp4"
    try:
        template = ch.load_workflow(wf, "faceswap_video_template.json", "faceswap")
        t0 = time.time()
        with httpx.Client() as client:
            vid = ch.upload_media(client, base, in_path, "video/mp4")   # 目标视频
            face = ch.upload_image(client, base, face_path)             # 源脸
            mapping = {
                "%VIDEO%": vid,
                "%FACE_IMAGE%": face,
                "%FPS%": int(fps or settings.COMFYUI_FPS),
                "%SEED%": int(time.time_ns() % 2_000_000_000),
                "%SWAP_MODEL%": settings.FACESWAP_SWAP_MODEL,
                "%FACE_RESTORE_MODEL%": settings.FACESWAP_RESTORE_MODEL,
                "%FACE_RESTORE_VISIBILITY%": float(settings.FACESWAP_RESTORE_VISIBILITY),
                "%DET_MODEL%": settings.FACESWAP_DET_MODEL,
            }
            graph = ch.fill_template(template, mapping)
            pid = ch.submit(client, base, graph, f"mirage-swap-{os.getpid()}-{int(t0)}")
            log_bus.emit("[换脸] 逐帧换脸中（ReActor）…")
            outs = ch.collect_outputs(ch.wait(client, base, pid, label="换脸"))
            vids = [c for c in outs
                    if str(c.get("filename", "")).lower().endswith(ch.VIDEO_EXTS)] or outs
            if not vids:
                raise RuntimeError("换脸完成但没找到视频产物")
            ch.download_view(client, base, vids[0], tmp)
        # 原子替换到 out_path（同目录同盘）
        os.replace(tmp, out_path)
        logger.info("[faceswap] %s + 源脸 → %s (%.0fs)",
                    os.path.basename(in_path), out_path, time.time() - t0)
        return {"applied": True, "note": "ok", "out": out_path}
    except Exception as e:  # noqa: BLE001 - 失败安全：保留原片
        logger.warning("[faceswap] 换脸失败，保留原片: %s", e)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return {"applied": False, "note": f"failed: {e}"}
