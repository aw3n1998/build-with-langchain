"""edge-tts Provider —— 微软在线预置音色(默认引擎、保底)。

预置音色 id(如 zh-CN-YunxiNeural)，不克隆。需联网；断网/未装则 synth 返 False。
这是 voice 为裸字符串时的归宿，也是克隆引擎失败时的回退。
"""

from __future__ import annotations

import asyncio
import os

from mirage.app.core.logger import get_logger
from mirage.app.pipeline.tts_providers.base import TTSProvider

logger = get_logger("pipeline.tts.edge")

DEFAULT_EDGE_VOICE = "zh-CN-YunxiNeural"   # 沉稳男声；女声可用 zh-CN-XiaoxiaoNeural


class EdgeTTSProvider(TTSProvider):
    name = "edge-tts"
    display_name = "edge-tts（微软在线预置音）"
    needs_ref_audio = False

    def synth(self, text: str, out_path: str, *, voice: str = "", ref_audio: str = "",
              voice_id: str = "", emotion: str = "", **kw) -> bool:
        v = (voice or voice_id or "").strip() or DEFAULT_EDGE_VOICE   # edge 用音色 id；忽略 ref_audio/emotion
        try:
            import edge_tts

            async def gen():
                await edge_tts.Communicate(text, v).save(out_path)

            asyncio.run(gen())
            return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
        except Exception as e:  # noqa: BLE001
            logger.warning("[tts.edge] 失败（退化为无旁白）: %s", e)
            return False
