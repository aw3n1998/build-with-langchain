"""
FLF2V 首尾帧·共享关键帧续段 —— 根治「单尾帧续段」的接缝抖动。

原理:不再「取单尾帧重新 i2v」,而是给一串**有序关键帧**,每对相邻关键帧用 ComfyUI 原生
WanFirstLastFrameToVideo(first-last-frame-to-video)生成中间运动;相邻段**共用同一张关键帧**
→ 交界是像素完全相同的真值锚点,零抖、免 xfade,且每段被两端约束、不累积漂移(治本)。

⚠️ workflow(comfyui_workflows/flf2v_template.json)是脚手架:其余结构沿用跑通的 i2v_bf16,
   仅 WanFirstLastFrameToVideo 节点的输入键为 medium-confidence,首跑前在 ComfyUI v0.16+ 用官方
   Wan2.2 FLF2V 模板 Save(API格式) 核对一次。端点门控同 COMFYUI_BASE_URL。
"""

from __future__ import annotations

import os
import shutil
import time

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline import comfy_http as ch
from mirage.app.pipeline import log_bus
from mirage.app.pipeline.gpu_client import GpuRunError

logger = get_logger("pipeline.flf2v")


def _segment(start_path: str, end_path: str, out_path: str, *, prompt: str, neg: str,
             width: int, height: int, frames: int, fps: int, steps: int, seed: int) -> bool:
    """对一对关键帧(start→end)跑 FLF2V,产物落 out_path。"""
    base = ch.base_url()
    wf = (settings.COMFYUI_WORKFLOW_FLF2V or "comfyui_workflows/flf2v_template.json").strip()
    template = ch.load_workflow(wf, "flf2v_template.json", "flf2v")
    if seed is None or int(seed) < 0:
        seed = int(time.time_ns() % 2_000_000_000)
    steps = int(steps or settings.COMFYUI_STEPS)
    with httpx.Client() as client:
        s = ch.upload_image(client, base, start_path)
        e = ch.upload_image(client, base, end_path)
        mapping = {
            "%START_IMAGE%": s, "%END_IMAGE%": e,
            "%PROMPT%": prompt or "",
            "%NEG_PROMPT%": str(neg or settings.WAN_VIDEO_NEGATIVE),
            "%WIDTH%": int(width), "%HEIGHT%": int(height),
            "%FRAMES%": int(frames or settings.COMFYUI_FRAMES),
            "%FPS%": int(fps or settings.COMFYUI_FPS),
            "%STEPS%": steps, "%BOUNDARY%": max(1, steps // 2),
            "%SHIFT%": float(settings.WAN_SHIFT), "%SEED%": int(seed),
        }
        graph = ch.fill_template(template, mapping)
        pid = ch.submit(client, base, graph, f"mirage-flf2v-{os.getpid()}-{int(time.time())}")
        outs = ch.collect_outputs(ch.wait(client, base, pid, label="FLF2V 段"))
        vids = [c for c in outs
                if str(c.get("filename", "")).lower().endswith(ch.VIDEO_EXTS)] or outs
        if not vids:
            raise GpuRunError("FLF2V 段完成但没找到视频产物")
        ch.download_view(client, base, vids[0], out_path)
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def stitch_keyframes(keyframe_paths, out_path: str, *, prompt: str = "", neg: str = "",
                     width: int = 0, height: int = 0, frames: int = 0, fps: int = 0,
                     steps: int = 0, seed: int = -1, drop_shared=None) -> dict:
    """有序关键帧 → 每对相邻帧 FLF2V → 无缝拼接到 out_path。返回 {applied, note, out, segments}。

    相邻段共用边界关键帧(seg_i 末帧 == seg_{i+1} 首帧,像素相同),所以拼接用硬切(crossfade=0)
    即无缝;drop_shared=True 时丢掉后续段重复的首帧避免 1 帧卡顿。
    """
    ks = [p for p in (keyframe_paths or []) if p and os.path.exists(p)]
    if len(ks) < 2:
        return {"applied": False, "note": "FLF2V 至少需要 2 张关键帧(有序、不同时刻)"}
    if drop_shared is None:
        drop_shared = bool(settings.FLF2V_DROP_SHARED_FRAME)
    fps = int(fps or settings.COMFYUI_FPS)
    work = out_path + ".segs"
    os.makedirs(work, exist_ok=True)
    segs = []
    try:
        for i in range(len(ks) - 1):
            seg = os.path.join(work, f"seg_{i:03d}.mp4")
            log_bus.emit(f"[FLF2V] 段 {i + 1}/{len(ks) - 1}:关键帧 {i + 1}→{i + 2} …")
            ok = _segment(ks[i], ks[i + 1], seg, prompt=prompt, neg=neg, width=int(width),
                          height=int(height), frames=int(frames), fps=fps, steps=int(steps), seed=int(seed))
            if not ok:
                return {"applied": False, "note": f"FLF2V 第 {i + 1} 段失败"}
            segs.append(seg)
        if len(segs) == 1:
            shutil.copy(segs[0], out_path)
        else:
            from mirage.app.pipeline.assembler import concat_videos
            # 相邻段共用边界关键帧(seg_i 末帧 == seg_{i+1} 首帧)→ dedup_boundary 去掉重复帧、硬拼即无缝,不用 xfade
            concat_videos(segs, out_path, dedup_boundary=bool(drop_shared), crossfade=0.0)
        ok = os.path.exists(out_path) and os.path.getsize(out_path) > 0
        return {"applied": ok, "note": "FLF2V 无缝拼接(共享关键帧)" if ok else "拼接失败",
                "out": out_path, "segments": len(segs)}
    finally:
        shutil.rmtree(work, ignore_errors=True)
