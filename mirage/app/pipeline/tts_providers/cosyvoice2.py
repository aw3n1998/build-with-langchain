"""CosyVoice2 Provider —— 自托管克隆 + 情感 TTS。默认/保底引擎（替代 edge-tts）。

架构同 indextts2 旁路：CosyVoice2 在 /ephemeral 另起包装 server(colab/cosyvoice2_server.py，load-once，端口 8193)。
本 provider 只 POST「文本 + 参考音路径 + 情感」→ server 写 wav 到同机共享盘 → 返回状态。
门控：COSYVOICE2_BASE_URL（见 tts_providers/__init__.py）。CosyVoice2-0.5B 无内置预置音 →
没传 ref_audio 时由 server 端 COSYVOICE_DEFAULT_REF（爬来的成熟女声）兜底，所以可当「没参考音也能出声」的默认引擎。
"""

from __future__ import annotations

import os

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline.tts_providers.base import TTSProvider

logger = get_logger("pipeline.tts.cosyvoice2")


class CosyVoice2Provider(TTSProvider):
    name = "cosyvoice2"
    display_name = "CosyVoice2（自托管克隆·情感）"
    needs_ref_audio = False   # server 端有 DEFAULT_REF 兜底，不强制角色参考音

    def __init__(self, base_url: str = "") -> None:
        self.base_url = (base_url or settings.COSYVOICE2_BASE_URL or "").rstrip("/")

    def synth(self, text: str, out_path: str, *, voice: str = "", ref_audio: str = "",
              voice_id: str = "", emotion: str = "", **kw) -> bool:
        if not self.base_url:
            return False
        payload = {
            "text": text or "",
            "ref_audio": ref_audio or "",     # 同机本地路径(克隆音色);空则 server 用 DEFAULT_REF
            "voice_id": voice_id or "",
            "emotion": emotion or "",
            "output": out_path,               # ★同机共享盘:server 直接写到这里
        }
        try:
            with httpx.Client() as client:
                r = client.post(f"{self.base_url}/v1/tts", json=payload,
                                timeout=max(120, int(getattr(settings, "COMFYUI_TIMEOUT", 600) or 600)))
            if r.status_code >= 400:
                logger.warning("[tts.cosyvoice2] server 拒绝(HTTP %s): %s", r.status_code, r.text[:300])
                return False
            data = r.json() if (r.headers.get("content-type", "").startswith("application/json")) else {}
            out = (data.get("output_path") or out_path) if isinstance(data, dict) else out_path
            if out != out_path and os.path.exists(out):
                import shutil
                shutil.copy(out, out_path)
            return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
        except httpx.HTTPError as e:  # 超时/连接错 → False，由 synth_tts 回退（也回退到 cosyvoice2 自身或无声）
            logger.warning("[tts.cosyvoice2] HTTP 异常: %s: %s", type(e).__name__, e)
            return False
