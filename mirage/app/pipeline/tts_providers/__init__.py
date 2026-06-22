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
from mirage.app.pipeline.tts_providers.edge_tts_provider import EdgeTTSProvider

logger = get_logger("pipeline.tts")

# edge-tts 永远注册(保底/回退)。默认引擎由 TTS_PROVIDER_DEFAULT 决定(缺省 edge-tts)。
_def = (settings.TTS_PROVIDER_DEFAULT or "edge-tts").strip()
tts_registry.register(EdgeTTSProvider(), default=(_def in ("", "edge-tts")))

# IndexTTS2 自托管克隆:配了 INDEXTTS2_ENABLED + 端点才注册(没起 server 时整条链自动只用 edge-tts，不报错)。
if settings.INDEXTTS2_ENABLED and settings.INDEXTTS2_BASE_URL:
    try:
        from mirage.app.pipeline.tts_providers.indextts2 import IndexTTS2Provider
        tts_registry.register(IndexTTS2Provider(), default=(_def == "indextts2"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[tts] IndexTTS2 注册失败(回退 edge-tts): %s", e)


def _normalize(voice) -> dict:
    """把 voice(str|dict) 归一成 {engine, voice, ref_audio, voice_id, emotion}。
    裸字符串 = edge-tts 音色 id；dict 缺 engine 时按是否带 ref_audio/voice_id 猜克隆引擎，否则 edge-tts。"""
    if isinstance(voice, dict):
        d = {k: (v or "") for k, v in voice.items()}
        eng = (d.get("engine") or "").strip()
        if not eng:
            eng = tts_registry.default_name if (d.get("ref_audio") or d.get("voice_id")) else "edge-tts"
        d["engine"] = eng
        return d
    return {"engine": "edge-tts", "voice": (voice or "")}


def synth_tts(text: str, out_path: str, voice="") -> bool:
    """统一配音入口：按 voice 路由到对应 TTS 引擎；引擎失败自动回退 edge-tts。

    Args:
        voice: edge-tts 音色 id(str) 或克隆 spec(dict {engine,ref_audio,voice_id,emotion,voice})。
    Returns: True=出音；False=连 edge-tts 也失败(调用方退化无声)。
    """
    if not (text or "").strip():
        return False
    spec = _normalize(voice)
    engine = spec.pop("engine", "") or "edge-tts"
    prov = tts_registry.get(engine)
    ok = False
    if prov is not None:
        try:
            ok = prov.synth(text, out_path, **spec)
        except Exception as e:  # noqa: BLE001
            logger.warning("[tts] 引擎 %s 异常(回退 edge-tts): %s", engine, e)
    if not ok and engine != "edge-tts" and tts_registry.has("edge-tts"):
        logger.info("[tts] %s 未出音 → 回退 edge-tts", engine)
        try:
            ok = tts_registry.get("edge-tts").synth(text, out_path, voice=spec.get("voice", ""))
        except Exception:  # noqa: BLE001
            ok = False
    return ok


__all__ = ["TTSProvider", "tts_registry", "synth_tts"]
