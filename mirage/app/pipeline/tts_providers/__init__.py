"""TTS 引擎 Provider 包。导入即把可用引擎注册到 tts_registry。

新增/换引擎 = 在本包加一个 provider 文件 + 在这里 register 一行 + 配 .env 门控，
合成器/流水线零改动(都走 synth_tts 路由)。

对外只暴露 synth_tts(text, out_path, voice) —— assembler._tts/_tts_dialogue 调它，
按 voice 形态(裸字符串=edge 预置音 / dict=克隆引擎)路由到对应 provider，失败自动回退 edge-tts。
"""

from __future__ import annotations

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline.tts_providers.base import TTSProvider, tts_registry

logger = get_logger("pipeline.tts")

# ★edge-tts 已弃用（基础合成音没用）。默认/保底引擎 = CosyVoice2（自托管克隆，自带 LibriVox 爬来的成熟女声当默认音色）。
# 配了 COSYVOICE2_BASE_URL 才注册（没起 8193 server 时整条配音链无声，需起 server）。
_def = (settings.TTS_PROVIDER_DEFAULT or "cosyvoice2").strip()
if settings.COSYVOICE2_BASE_URL:
    try:
        from mirage.app.pipeline.tts_providers.cosyvoice2 import CosyVoice2Provider
        tts_registry.register(CosyVoice2Provider(), default=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("[tts] CosyVoice2 注册失败: %s", e)

# IndexTTS2 自托管克隆（可选，情感控制更细）：配了 INDEXTTS2_ENABLED + 端点才注册。
if settings.INDEXTTS2_ENABLED and settings.INDEXTTS2_BASE_URL:
    try:
        from mirage.app.pipeline.tts_providers.indextts2 import IndexTTS2Provider
        tts_registry.register(IndexTTS2Provider(), default=(not settings.COSYVOICE2_BASE_URL))
    except Exception as e:  # noqa: BLE001
        logger.warning("[tts] IndexTTS2 注册失败: %s", e)

# 没有任何配音引擎注册 → 成片会无声。大声告警（否则用户看到"成功"却没人声）。
if not tts_registry.default_name:
    logger.warning("[tts] ⚠ 没有可用配音引擎（COSYVOICE2_BASE_URL / INDEXTTS2 都没配）→ 成片将【无配音】！"
                   "请配 CosyVoice2 端点（COSYVOICE2_BASE_URL）。")


def _normalize(voice) -> dict:
    """把 voice(str|dict) 归一成 {engine, voice, ref_audio, voice_id, emotion}。
    裸字符串 = edge-tts 音色 id；dict 缺 engine 时按是否带 ref_audio/voice_id 猜克隆引擎，否则 edge-tts。"""
    if isinstance(voice, dict):
        d = {k: (v or "") for k, v in voice.items()}
        eng = (d.get("engine") or "").strip()
        if not eng or eng == "edge-tts":   # edge 已弃用：旧 spec/裸 dict 一律落到默认引擎
            eng = tts_registry.default_name or "cosyvoice2"
        d["engine"] = eng
        return d
    # 裸字符串(老 edge 音色 id 已无意义) → 默认引擎(CosyVoice2)，用其默认音色。
    return {"engine": tts_registry.default_name or "cosyvoice2", "voice": (voice or "")}


def synth_tts(text: str, out_path: str, voice="") -> bool:
    """统一配音入口：按 voice 路由到对应 TTS 引擎；引擎失败自动回退 edge-tts。

    Args:
        voice: edge-tts 音色 id(str) 或克隆 spec(dict {engine,ref_audio,voice_id,emotion,voice})。
    Returns: True=出音；False=连 edge-tts 也失败(调用方退化无声)。
    """
    if not (text or "").strip():
        return False
    spec = _normalize(voice)
    engine = spec.pop("engine", "") or (tts_registry.default_name or "cosyvoice2")
    prov = tts_registry.get(engine)
    ok = False
    if prov is not None:
        try:
            ok = prov.synth(text, out_path, **spec)
        except Exception as e:  # noqa: BLE001
            logger.warning("[tts] 引擎 %s 异常(回退默认引擎): %s", engine, e)
    # 回退到默认引擎(CosyVoice2)。edge-tts 已弃用,不再兜底。
    _fb = tts_registry.default_name
    if not ok and _fb and engine != _fb and tts_registry.has(_fb):
        logger.info("[tts] %s 未出音 → 回退默认引擎 %s", engine, _fb)
        try:
            ok = tts_registry.get(_fb).synth(text, out_path, voice=spec.get("voice", ""),
                                             ref_audio=spec.get("ref_audio", ""),
                                             voice_id=spec.get("voice_id", ""),
                                             emotion=spec.get("emotion", ""))
        except Exception:  # noqa: BLE001
            ok = False
    return ok


__all__ = ["TTSProvider", "tts_registry", "synth_tts"]
