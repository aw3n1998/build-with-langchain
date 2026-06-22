"""IndexTTS2 Provider —— 自托管克隆 + 情感 TTS（可插拔，不好用直接换别的 provider）。

架构(照 standin provider 旁路)：
  IndexTTS2 自带依赖，在 Colab 另起一个包装 server(colab/indextts2_server.py，load-once 常驻，端口 8191)。
  本 provider 只 POST「文本 + 角色参考音路径 + 情感」→ server 把 wav 写到同机共享盘 out_path → 返回状态。
  门控:INDEXTTS2_ENABLED + INDEXTTS2_BASE_URL（见 tts_providers/__init__.py）。失败由 synth_tts 回退 edge-tts。

换引擎(CosyVoice2/GPT-SoVITS/ElevenLabs…)只需仿本文件新增一个 provider + 在 __init__ 注册，调用方零改动。
"""

from __future__ import annotations

import os

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline.tts_providers.base import TTSProvider

logger = get_logger("pipeline.tts.indextts2")


class IndexTTS2Provider(TTSProvider):
    name = "indextts2"
    display_name = "IndexTTS2（自托管克隆·情感）"
    needs_ref_audio = True

    def __init__(self, base_url: str = "", default_emotion: str = "") -> None:
        self.base_url = (base_url or settings.INDEXTTS2_BASE_URL or "").rstrip("/")
        self.default_emotion = default_emotion or settings.INDEXTTS2_DEFAULT_EMOTION or ""

    def synth(self, text: str, out_path: str, *, voice: str = "", ref_audio: str = "",
              voice_id: str = "", emotion: str = "", **kw) -> bool:
        if not self.base_url:
            logger.warning("[tts.indextts2] 未配置 INDEXTTS2_BASE_URL，跳过(回退 edge-tts)")
            return False
        # 克隆音色来源:优先角色参考音(ref_audio)，否则 voice_id(server 端音色库)。两者皆空则没法克隆 → 让它回退。
        if not (ref_audio or voice_id):
            logger.warning("[tts.indextts2] 该角色没有参考音/voice_id，跳过克隆(回退 edge-tts)")
            return False
        payload = {
            "text": text or "",
            "ref_audio": ref_audio or "",          # 同机本地路径(server 直接读，同 standin 约定)
            "voice_id": voice_id or "",
            "emotion": (emotion or self.default_emotion or ""),
            "output": out_path,                    # ★同机共享盘:server 直接写到这里
        }
        try:
            with httpx.Client() as client:
                r = client.post(f"{self.base_url}/v1/tts", json=payload,
                                timeout=max(120, int(getattr(settings, "COMFYUI_TIMEOUT", 600) or 600)))
            if r.status_code >= 400:
                logger.warning("[tts.indextts2] server 拒绝(HTTP %s): %s", r.status_code, r.text[:300])
                return False
            data = r.json() if (r.headers.get("content-type", "").startswith("application/json")) else {}
            out = (data.get("output_path") or out_path) if isinstance(data, dict) else out_path
            if out != out_path and os.path.exists(out):
                import shutil
                shutil.copy(out, out_path)
            return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
        except httpx.HTTPError as e:  # 超时/连接错 → 返 False，由 synth_tts 回退 edge-tts(不卡链路)
            logger.warning("[tts.indextts2] HTTP 异常(回退 edge-tts): %s: %s", type(e).__name__, e)
            return False
