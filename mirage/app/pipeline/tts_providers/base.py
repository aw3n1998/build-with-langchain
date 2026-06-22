"""
TTS Provider 抽象 + 注册表 —— 把「具体用哪个 TTS 引擎配音」从合成器/流水线里解耦出来。

为什么要这层（同 video providers 的思路）：
  原先配音写死在 assembler._tts 里调 edge-tts。换/加引擎(IndexTTS2/CosyVoice2/GPT-SoVITS/ElevenLabs)
  要改合成器。抽出 Provider 后：
    - assembler._tts 退回成纯路由(text,out,voice -> bool)，不认识任何引擎；
    - 每个引擎 = 一个 TTSProvider 子类，自带 synth() 实现；
    - 新增/换引擎 = 写一个文件 + 在 __init__ register 一行 + 配一个 .env 门控，调用方零改动；
    - 引擎不可用/失败 → synth_tts 自动回退 edge-tts，再不行返回 False(调用方退化无声)。

voice 形态(向后兼容)：
  - 裸字符串 "zh-CN-YunxiNeural" → edge-tts 预置音色 id(老行为)；
  - dict {"engine":"indextts2","ref_audio":"/path/x.wav","voice_id":"","emotion":"happy","voice":""}
    → 克隆引擎(engine 决定路由,ref_audio/voice_id 给克隆音色,emotion 给情感)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from mirage.app.core.logger import get_logger

logger = get_logger("pipeline.tts")


class TTSProvider(ABC):
    """一个 TTS 引擎的适配器。子类只需声明 name + 实现 synth。"""

    name: str = ""               # 唯一标识(路由用),如 "edge-tts" / "indextts2"
    display_name: str = ""       # 人类可读名
    needs_ref_audio: bool = False  # True=克隆引擎(要参考音);False=预置音色 id(edge-tts)

    @abstractmethod
    def synth(self, text: str, out_path: str, *, voice: str = "", ref_audio: str = "",
              voice_id: str = "", emotion: str = "", **kw) -> bool:
        """把 text 合成音频写到 out_path。成功 True，失败 False(由 synth_tts 回退处理)。"""
        raise NotImplementedError

    def info(self) -> dict:
        return {"name": self.name, "display_name": self.display_name or self.name, "clone": self.needs_ref_audio}


class TTSRegistry:
    """TTS Provider 注册表(与 video_provider_registry 同款热插拔)。"""

    def __init__(self) -> None:
        self._providers: dict[str, TTSProvider] = {}
        self._default: Optional[str] = None

    def register(self, provider: TTSProvider, *, default: bool = False) -> None:
        if not provider.name:
            raise ValueError("TTSProvider.name 不能为空")
        self._providers[provider.name] = provider
        if default or self._default is None:
            self._default = provider.name
        logger.info("[tts] 注册 TTS 引擎 %s（default=%s）", provider.name, default)

    def get(self, name: str = "") -> Optional[TTSProvider]:
        if name and name in self._providers:
            return self._providers[name]
        if name:
            logger.warning("[tts] 未知 TTS 引擎 %s，回退默认 %s", name, self._default)
        return self._providers.get(self._default) if self._default else None

    def has(self, name: str) -> bool:
        return name in self._providers

    @property
    def default_name(self) -> str:
        return self._default or ""

    def list_providers(self) -> list[dict]:
        return [p.info() for p in self._providers.values()]


# 全局单例
tts_registry = TTSRegistry()
