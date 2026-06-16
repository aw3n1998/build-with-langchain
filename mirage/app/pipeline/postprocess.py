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

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline import comfy_http as ch
from mirage.app.pipeline import log_bus

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
        client_id = f"mirage-post-{os.getpid()}-{int(t0)}"
        with httpx.Client() as client:
            vid_name = ch.upload_media(client, base, video_path, "video/mp4")
            mapping = {
                "%VIDEO%": vid_name,
                "%FPS%": int(fps or settings.COMFYUI_FPS),
                "%SEED%": int(time.time_ns() % 2_000_000_000),
                "%UPSCALE_MODEL%": settings.UPSCALE_MODEL,   # 模板里超分模型可配(x2/x4)
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
        # 就地原子替换：tmp_out 与原片同目录同盘，os.replace 原子覆盖。
        # 不能"先 remove 原片再 move"——move 万一失败(占用/满盘)会两头落空、丢掉成片。
        os.replace(tmp_out, video_path)
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


# ───────────────────────── 一键转规格（按需放大到目标分辨率，如 4K）─────────────────────────
# 与上面的「自动后处理」不同：这里是用户对某个已生成的低清成片**点一下、转成目标规格**，
# 产物落**独立新文件**（不覆盖原片，可对比）。引擎可插拔（settings.UPSCALE_METHOD）。
import shutil as _shutil
import subprocess as _sp


def resolve_upscale_method() -> str:
    """auto → 配了 ComfyUI + 存在超分 workflow 就走 AI 超分，否则 ffmpeg；也可被强制为 comfyui/ffmpeg。"""
    m = (settings.UPSCALE_METHOD or "auto").strip().lower()
    if m in ("comfyui", "ffmpeg"):
        return m
    wf = (settings.COMFYUI_WORKFLOW_UPSCALE or settings.COMFYUI_WORKFLOW_POST
          or "comfyui_workflows/post_upscale_template.json").strip()
    return "comfyui" if (settings.COMFYUI_BASE_URL and wf and os.path.exists(wf)) else "ffmpeg"


def _ffmpeg_scale_pad(src: str, dst: str, width: int, height: int) -> bool:
    """ffmpeg 缩放到精确 width×height（保持比例 + 黑边补齐 + 偶数化），保留音轨。成功 True。"""
    if not _shutil.which("ffmpeg"):
        logger.warning("[upscale] 未找到 ffmpeg，无法缩放")
        return False
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "copy", dst]
    r = _sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not (os.path.exists(dst) and os.path.getsize(dst) > 0):
        # 音轨 copy 失败（如源无音轨/编码不兼容）→ 退一步重编码音轨
        cmd2 = cmd[:-3] + ["-an", dst]
        r = _sp.run(cmd2, capture_output=True, text=True)
        if r.returncode != 0 or not (os.path.exists(dst) and os.path.getsize(dst) > 0):
            logger.warning("[upscale] ffmpeg 缩放失败: %s", (r.stderr or "")[-400:])
            return False
    return True


def _comfyui_upscale(src: str) -> str | None:
    """用 ComfyUI 超分 workflow(RealESRGAN) 把视频整体放大，返回临时放大文件路径；不可用/失败 → None。"""
    wf = (settings.COMFYUI_WORKFLOW_UPSCALE or settings.COMFYUI_WORKFLOW_POST
          or "comfyui_workflows/post_upscale_template.json").strip()
    if not (wf and os.path.exists(wf)):
        return None
    try:
        base = ch.base_url()
    except Exception:  # noqa: BLE001
        return None
    tmp = src + ".ai.mp4"
    try:
        template = ch.load_workflow(wf, "post_upscale_template.json", "upscale")
        with httpx.Client() as client:
            vid = ch.upload_media(client, base, src, "video/mp4")
            mapping = {
                "%VIDEO%": vid,
                "%FPS%": int(settings.COMFYUI_FPS),
                "%SEED%": int(time.time_ns() % 2_000_000_000),
                "%UPSCALE_MODEL%": settings.UPSCALE_MODEL,
            }
            graph = ch.fill_template(template, mapping)
            pid = ch.submit(client, base, graph, f"mirage-up-{os.getpid()}-{int(time.time())}")
            log_bus.emit("[转规格] AI 超分中（RealESRGAN）…")
            outs = ch.collect_outputs(ch.wait(client, base, pid, label="转规格·超分"))
            vids = [c for c in outs
                    if str(c.get("filename", "")).lower().endswith(ch.VIDEO_EXTS)] or outs
            if not vids:
                return None
            ch.download_view(client, base, vids[0], tmp)
        return tmp if (os.path.exists(tmp) and os.path.getsize(tmp) > 0) else None
    except Exception as e:  # noqa: BLE001
        logger.warning("[upscale] AI 超分失败，退回 ffmpeg: %s", e)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return None


def upscale_to(in_path: str, out_path: str, *, width: int, height: int,
               method: str = "auto") -> dict:
    """把 in_path 放大/转到精确 width×height，产物落 out_path（不动原片）。

    method='comfyui'：先 AI 超分(RealESRGAN)补细节，再 ffmpeg 精确缩到目标规格（保证任意 4K/2K 都精确）。
    method='ffmpeg'：直接 ffmpeg 缩放（秒级、免 GPU、偏软）。method='auto' → resolve_upscale_method()。
    返回 {applied, note, out, method}。
    """
    if not (in_path and os.path.exists(in_path)):
        return {"applied": False, "note": "源视频不存在"}
    if int(width) <= 0 or int(height) <= 0:
        return {"applied": False, "note": "目标宽高无效"}
    m = method if method in ("comfyui", "ffmpeg") else resolve_upscale_method()
    src, ai_tmp = in_path, None
    if m == "comfyui":
        ai_tmp = _comfyui_upscale(in_path)
        if ai_tmp:
            src = ai_tmp           # AI 超分后再精确缩到目标规格
    ok = _ffmpeg_scale_pad(src, out_path, int(width), int(height))
    if ai_tmp and os.path.exists(ai_tmp):
        try:
            os.remove(ai_tmp)
        except OSError:
            pass
    if not ok:
        return {"applied": False, "note": "ffmpeg 缩放失败（检查是否已安装 ffmpeg）"}
    note = "AI超分+精确缩放" if (m == "comfyui" and src != in_path) else "ffmpeg 缩放"
    logger.info("[upscale] %s → %dx%d (%s) → %s", os.path.basename(in_path), width, height, note, out_path)
    return {"applied": True, "note": note, "out": out_path, "method": m}
