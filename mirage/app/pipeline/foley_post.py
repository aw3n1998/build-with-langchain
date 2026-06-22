"""音效生成后处理（引擎无关，不做 VideoProvider）。

Foley 模型契约 video(+可选 text prompt)→audio，与 VideoProvider.generate(image,prompt)→video 不符，
所以做成「出片后处理」：把已渲染好的成片喂给视频→音频模型，生成【与画面同步】的环境/动作音效
（如篮球真触地那一帧才响），再叠在已有人声之下。门控休眠：没配 FOLEY_ENGINE / server 没起 → 自动
跳过（保留原片+原音轨），链路零回归。对齐 [[lipsync_post]] 的可插拔范式；引擎部署见 colab/foley_server.py(端口 8194)。
"""
from __future__ import annotations

import os

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("pipeline.foley_post")


def _base_url() -> str:
    return (settings.FOLEY_BASE_URL or "").strip().rstrip("/")


def _engine_ready() -> bool:
    """音效引擎是否就绪：配了 FOLEY_ENGINE=mmaudio 且 server 健康。否则 False=跳过、不改片。"""
    if (settings.FOLEY_ENGINE or "").strip().lower() not in ("mmaudio", "foley"):
        return False
    if not (settings.FOLEY_ENABLED and _base_url()):
        return False
    try:
        import httpx
        r = httpx.get(f"{_base_url()}/v1/health", timeout=5)
        return r.status_code == 200 and (r.json() or {}).get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def generate_sfx(video_path: str, out_wav: str, prompt: str = "") -> dict:
    """给一段视频生成【与画面同步】的音效 wav。引擎未就绪/失败 → {"applied": False, "note": ...}（调用方保留原片）。

    prompt 可选：引导音效类型（如 "basketball dribble, sneaker squeak, crowd ambient"）；空=模型自行从画面推断。
    """
    if not _engine_ready():
        return {"applied": False, "note": "音效引擎未配置/未就绪，跳过(保留原片+原音轨)"}
    if not (video_path and os.path.exists(video_path)):
        return {"applied": False, "note": f"音效输入视频不存在: {video_path}"}
    # 生成前先卸 ComfyUI 显存：Foley 模型与出片抢同一张卡，先 POST /free 腾显存（下次出片自动重载）。
    try:
        _cb = (settings.COMFYUI_BASE_URL or "").strip().rstrip("/")
        if _cb:
            import httpx as _hx
            _hx.post(f"{_cb}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
    except Exception:  # noqa: BLE001
        pass
    try:
        import httpx
        # 片长传给 Foley（mirage 已知，省得 server 再探一遍）；模型按片长生成等长音频。
        try:
            from mirage.app.pipeline.assembler import _duration
            _dur = float(_duration(video_path))
        except Exception:  # noqa: BLE001
            _dur = 0.0
        payload = {"video": video_path, "output": out_wav, "prompt": prompt or "",
                   "duration": _dur,
                   "num_steps": int(settings.FOLEY_STEPS or 25),
                   "cfg_strength": float(settings.FOLEY_GUIDANCE or 4.5)}
        r = httpx.post(f"{_base_url()}/v1/foley", json=payload, timeout=1800)
        data = r.json() if r.status_code == 200 else {}
        outp = (data or {}).get("output_path") or out_wav
        if (data or {}).get("status") == "succeed" and os.path.exists(outp) and os.path.getsize(outp) > 1000:
            return {"applied": True, "output": outp}
        return {"applied": False, "note": f"音效生成失败: {(data or {}).get('error') or r.text[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"applied": False, "note": f"音效异常: {type(e).__name__}: {e}"}


def apply_sfx(clips: list, scenes: list) -> dict:
    """合成整集时自动配音效：对【标了 sfx 的镜】用 Foley 模型按画面生成同步音效，挂到 clip['sfx']
    （assembler._assemble_in 会把它压在人声/旁白之下，逐镜混音）。与 [[apply_lipsync]] 同范式：
    引擎未就绪 / 没标 sfx / 失败 → 该镜跳过，整体 no-op、零回归。"""
    if not _engine_ready():
        return {"sfx": 0, "skipped": len(clips or []), "note": "音效引擎未配置，全部跳过"}
    done = skipped = 0
    for clip, scene in zip(clips or [], scenes or []):
        try:
            if not bool(scene.get("sfx")):
                skipped += 1
                continue
            src = clip.get("path") or ""
            if not (src and os.path.exists(src)):
                skipped += 1
                continue
            wav = os.path.splitext(src)[0] + "_sfx.wav"
            prompt = (scene.get("motion_prompt") or scene.get("image_prompt") or "").strip()
            r = generate_sfx(src, wav, prompt)
            if r.get("applied"):
                clip["sfx"] = r.get("output") or wav
                done += 1
            else:
                logger.info("[sfx] 跳过 %s: %s", os.path.basename(src), r.get("note"))
                skipped += 1
        except Exception as e:  # noqa: BLE001
            logger.info("[sfx] 异常跳过: %s", e)
            skipped += 1
    return {"sfx": done, "skipped": skipped}
