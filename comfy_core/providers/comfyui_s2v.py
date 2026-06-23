"""
Wan2.2-S2V 对口型 Provider（语音驱动，speech-to-video）—— 图 + 音频 → 口型同步视频，走 ComfyUI。

与 i2v 的区别：S2V 的输入是「一张人物图 + 一段语音音频」，输出是人物嘴型跟音频对上的视频
（Wan2.2-S2V-14B：Wav2Vec 音频编码器对齐口型 + 文本引导全局运动）。用于「人物当镜头说话」的镜头。

设计：
  - 隐藏 Provider（hidden=True）：不进用户模型下拉。由每镜「对口型」开关自动路由（用户不碰模型名）。
  - transport="http"：走 ComfyUI，全程本地。端点门控同 COMFYUI_BASE_URL。
  - 音频从 params["audio_path"] 取（do_render 把该镜旁白 TTS 成本地音频后传进来）。
  - 不硬编码 workflow：读 COMFYUI_WORKFLOW_S2V（或仓库自带 s2v_template.json），
    占位符 %IMAGE%/%AUDIO%/%PROMPT%/%NEG_PROMPT%/%WIDTH%/%HEIGHT%/%STEPS%/%SEED%/%FPS%。
真机联调待用户在 4090 上部署 S2V（GGUF/FP8 量化版可塞进 24G）。
"""

from __future__ import annotations

import os
import time

import httpx

from comfy_core.config import settings
from comfy_core.logger import get_logger
from comfy_core import comfy_http as ch
from comfy_core import log_bus
from comfy_core.gpu_client import GpuConfigError, GpuRunError, parse_size  # noqa: F401 (re-export)
from comfy_core.providers.base import VideoProvider

logger = get_logger("pipeline.providers.comfyui_s2v")


class ComfyUIS2VProvider(VideoProvider):
    name = "comfyui-s2v"
    display_name = "对口型(Wan2.2-S2V)"
    capabilities = {"s2v"}
    transport = "http"
    hidden = True   # 不进用户下拉；由「对口型」开关自动路由

    def param_schema(self) -> list[dict]:
        return [
            {"key": "size", "label": "分辨率(宽*高)", "type": "select", "default": settings.COMFYUI_SIZE,
             "options": [
                 {"value": "480*832", "label": "480×832 竖屏"},
                 {"value": "720*1280", "label": "720×1280 竖屏高清"},
                 {"value": "832*480", "label": "832×480 横屏"},
                 {"value": "768*768", "label": "768×768 方形"},
             ]},
            {"key": "steps", "label": "采样步数", "type": "number", "default": settings.COMFYUI_STEPS, "advanced": True},
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.COMFYUI_FPS, "advanced": True},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1, "advanced": True},
        ]

    def generate(self, gpu, *, image_path: str, prompt: str, out_remote: str, params: dict) -> None:
        """http 分支：image_path 本地人物图，params['audio_path'] 本地语音，out_remote 本地输出 mp4。"""
        base = ch.base_url()
        audio_path = params.get("audio_path") or ""
        if not audio_path or not os.path.exists(audio_path):
            raise GpuRunError("对口型(S2V)缺少语音音频：这镜没有旁白/台词可配音。请先给这镜写一句台词。")
        width, height = parse_size(params.get("size"), settings.COMFYUI_SIZE)
        seed = int(params.get("seed", -1))
        if seed < 0:
            seed = int(time.time_ns() % 2_000_000_000)
        mapping = {
            "%PROMPT%": prompt or "",
            "%NEG_PROMPT%": str(params.get("negative") or ""),
            "%WIDTH%": width, "%HEIGHT%": height,
            "%FRAMES%": int(params.get("frames") or settings.COMFYUI_FRAMES),  # 视频长度(帧)
            "%STEPS%": int(params.get("steps") or settings.COMFYUI_STEPS),
            "%FPS%": int(params.get("fps") or settings.COMFYUI_FPS),
            "%SEED%": seed,
        }
        template = ch.load_workflow(settings.COMFYUI_WORKFLOW_S2V, "s2v_template.json", "s2v")
        t0 = time.time()
        client_id = f"mirage-s2v-{os.getpid()}-{int(t0)}"
        with httpx.Client() as client:
            mapping["%IMAGE%"] = ch.upload_media(client, base, image_path, "image/png")
            mapping["%AUDIO%"] = ch.upload_media(client, base, audio_path, "audio/mpeg")
            graph = ch.fill_template(template, mapping)
            prompt_id = ch.submit(client, base, graph, client_id)
            log_bus.emit("[对口型] 已提交语音驱动渲染，等待出片…")
            outputs = ch.wait(client, base, prompt_id, label="对口型")
            items = ch.collect_outputs(outputs)
            if not items:
                raise GpuRunError("S2V 完成但没找到产物文件")
            pick = next((c for c in items
                         if str(c.get("filename", "")).lower().endswith(ch.VIDEO_EXTS)), items[-1])
            ch.download_view(client, base, pick, out_remote)
        logger.info("[对口型] S2V 出片完成 %.0fs → %s", time.time() - t0, out_remote)
