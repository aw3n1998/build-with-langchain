"""口型对齐后处理（引擎无关，不做 VideoProvider）。

LatentSync/Wav2Lip 的契约是 video+audio→video，与 VideoProvider.generate(image,prompt)→video 不符，
所以做成「出片后处理」：对正脸说话镜用已渲染好的片 + 配音重缝嘴，非正脸/旁白镜不动。
门控休眠：没配 LIPSYNC_ENGINE / server 没起 → 自动跳过缝嘴（保留原片+配音叠轨），链路无回归。
对齐 [[tts-lipsync-integration-plan]] 第③步；引擎部署见 colab/latentsync_server.py(端口 8192)。
"""
from __future__ import annotations

import os

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("pipeline.lipsync_post")


def _base_url() -> str:
    return (settings.LATENTSYNC_BASE_URL or "").strip().rstrip("/")


def _engine_ready() -> bool:
    """口型引擎是否就绪：配了 LIPSYNC_ENGINE=latentsync 且 LatentSync server 健康。否则 False=跳过缝嘴。"""
    if (settings.LIPSYNC_ENGINE or "").strip().lower() != "latentsync":
        return False
    if not (settings.LATENTSYNC_ENABLED and _base_url()):
        return False
    try:
        import httpx
        r = httpx.get(f"{_base_url()}/v1/health", timeout=5)
        return r.status_code == 200 and (r.json() or {}).get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def lipsync_video(video_path: str, audio_path: str, out_path: str) -> dict:
    """给一段视频按驱动音缝嘴。引擎未就绪/失败 → {"applied": False, "note": ...}（调用方保留原片）。"""
    if not _engine_ready():
        return {"applied": False, "note": "口型引擎未配置/未就绪，跳过缝嘴(保留原片+配音)"}
    if not (video_path and os.path.exists(video_path)):
        return {"applied": False, "note": f"缝嘴输入视频不存在: {video_path}"}
    if not (audio_path and os.path.exists(audio_path)):
        return {"applied": False, "note": f"缝嘴驱动音不存在: {audio_path}"}
    cap = float(settings.LIPSYNC_MAX_SECONDS or 0)
    if cap > 0:
        try:
            from mirage.app.pipeline.assembler import _duration
            if _duration(video_path) > cap:
                return {"applied": False, "note": f"片长超过 LIPSYNC_MAX_SECONDS={cap}s，跳过缝嘴"}
        except Exception:  # noqa: BLE001
            pass
    # 缝嘴前先卸 ComfyUI 显存：LatentSync(~20G) 与出片(~20G) 抢同一张卡，
    # 页面点缝嘴时 ComfyUI 模型还占着会 OOM → 先 POST /free 把它的模型卸了（下次出片自动重载）。
    try:
        _cb = (settings.COMFYUI_BASE_URL or "").strip().rstrip("/")
        if _cb:
            import httpx as _hx
            _hx.post(f"{_cb}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
    except Exception:  # noqa: BLE001
        pass
    try:
        import httpx
        payload = {"video": video_path, "audio": audio_path, "output": out_path,
                   "inference_steps": int(settings.LATENTSYNC_STEPS or 20),
                   "guidance_scale": float(settings.LATENTSYNC_GUIDANCE or 1.5)}
        r = httpx.post(f"{_base_url()}/v1/lipsync", json=payload, timeout=1800)
        data = r.json() if r.status_code == 200 else {}
        outp = (data or {}).get("output_path") or out_path
        if (data or {}).get("status") == "succeed" and os.path.exists(outp) and os.path.getsize(outp) > 1000:
            return {"applied": True, "output": outp}
        return {"applied": False, "note": f"缝嘴失败: {(data or {}).get('error') or r.text[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"applied": False, "note": f"缝嘴异常: {type(e).__name__}: {e}"}


def _is_talking_face(scene: dict) -> bool:
    """正脸说话镜判定：有对口型标记 + 有旁白(台词) + 不是多角色对话镜（与渲染期 S2V 谓词一致）。"""
    return bool(scene.get("lipsync")) and bool((scene.get("narration") or "").strip()) \
        and not (scene.get("dialogue") or "").strip()


def apply_lipsync(clips: list, scenes: list, *, voice_default: str = "") -> dict:
    """合成整集时缝嘴：对正脸说话镜用旁白配音重缝嘴 → 替换 clip['path']、置 keep_audio（_assemble_in 不再重配音）。
    旁白/对话/空镜不动（走原配音叠轨）。引擎未就绪=整体 no-op、零回归。"""
    if not _engine_ready():
        return {"synced": 0, "skipped": len(clips or []), "note": "口型引擎未配置，全部保留配音叠轨"}
    from mirage.app.pipeline.assembler import _tts
    synced = skipped = 0
    for clip, scene in zip(clips or [], scenes or []):
        try:
            if clip.get("keep_audio") or not _is_talking_face(scene):
                skipped += 1
                continue
            line = (scene.get("narration") or "").strip()
            voice = clip.get("voice") or voice_default
            base = os.path.splitext(clip["path"])[0]
            audio = base + "_lsvoice.mp3"
            if not _tts(line, audio, voice):
                skipped += 1
                continue
            out = base + "_lipsync.mp4"
            r = lipsync_video(clip["path"], audio, out)
            if r.get("applied"):
                clip["path"] = r.get("output") or out
                clip["keep_audio"] = True
                clip["narration"] = ""
                synced += 1
            else:
                logger.info("[lipsync] 跳过 %s: %s", clip.get("path"), r.get("note"))
                skipped += 1
        except Exception as e:  # noqa: BLE001
            logger.info("[lipsync] 异常跳过: %s", e)
            skipped += 1
    return {"synced": synced, "skipped": skipped, "engine": settings.LIPSYNC_ENGINE}
