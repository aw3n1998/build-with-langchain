"""
LTX-Video 视频 Provider（图生视频，i2v）—— 解耦后的「第二个视频模型」样板。

部署步骤（在 GPU 服务器上，连上 GPU 后做一次）：
  1. pip install "diffusers>=0.32" transformers accelerate imageio imageio-ffmpeg sentencepiece
  2. 下载权重（任选其一，填到 .env 的 GPU_LTX_MODEL）：
       - Lightricks/LTX-Video           （13B 高质量，显存需求高）
       - Lightricks/LTX-Video-0.9.7-dev 等较小/快变体
  3. 本框架首次出片时会自动把 remote_scripts/ltx_i2v.py 上传到服务器（幂等），无需手动部署脚本。
  4. .env 配置：GPU_LTX_MODEL=Lightricks/LTX-Video（或本地权重目录）。

参数 schema 即「出视频参数卡」上 LTX 专属的可调项；和 Wan2.2 的字段不同，
前端参数卡完全由 schema 驱动，所以这里加的字段会自动出现在卡片上。
"""

from __future__ import annotations

import os
import shlex
import time
from typing import TYPE_CHECKING

from comfy_core.config import settings
from comfy_core.logger import get_logger
from comfy_core.gpu_client import GpuConfigError, GpuRunError, coerce_num, parse_size
from comfy_core.providers.base import VideoProvider

if TYPE_CHECKING:
    from comfy_core.gpu_client import GpuClient

logger = get_logger("pipeline.providers.ltx")

# 本机随仓库携带的 LTX 推理脚本（首次出片自动上传，幂等）
_LOCAL_LTX_SOURCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "remote_scripts", "ltx_i2v.py",
)


class LtxProvider(VideoProvider):
    name = "ltx"
    display_name = "LTX-Video (i2v)"
    capabilities = {"i2v", "t2v"}

    def param_schema(self) -> list[dict]:
        return [
            {
                "key": "size", "label": "分辨率(宽*高,需为32倍数)", "type": "select",
                "default": settings.LTX_SIZE,
                "help": "成片宽×高，需为 32 的倍数。竖屏适合手机，横屏适合横版，越大越清晰也越慢。",
                "options": [
                    {"value": "480*832", "label": "480×832 竖屏·快(省显存,推荐)"},
                    {"value": "704*1280", "label": "704×1280 竖屏·高清(吃满卡,需独占)"},
                    {"value": "832*480", "label": "832×480 宽屏快出"},
                    {"value": "768*768", "label": "768×768 方形"},
                    {"value": "1280*704", "label": "1280×704 横屏"},
                ],
            },
            # LTX 要求帧数为 8 的倍数 +1（如 121 / 161），卡片下拉给安全值
            {
                "key": "num_frames", "label": "帧数(8n+1)", "type": "select",
                "default": settings.LTX_NUM_FRAMES,
                "help": "总帧数（需为 8 的倍数加 1）。和帧率一起决定时长：时长≈帧数÷帧率。",
                "options": [
                    {"value": 89, "label": "89 (~3.7s)"},
                    {"value": 121, "label": "121 (~5s)"},
                    {"value": 161, "label": "161 (~6.7s)"},
                    {"value": 201, "label": "201 (~8.4s)"},
                    {"value": 257, "label": "257 (~10.7s)"},
                ],
            },
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.LTX_FPS,
             "advanced": True,
             "help": "每秒播放多少帧。和帧数一起决定时长，常用 24；调大画面更流畅但同帧数下时长变短。"},
            {"key": "steps", "label": "采样步数", "type": "number", "default": settings.LTX_STEPS,
             "advanced": True,
             "help": "去噪迭代次数。越大画质越精细但越慢，LTX 常用 30-40。"},
            {"key": "guidance", "label": "guidance", "type": "number", "default": settings.LTX_GUIDANCE,
             "advanced": True,
             "help": "提示词引导强度。越大越贴合提示词但可能僵硬，LTX 常用 3 左右。"},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1,
             "advanced": True,
             "help": "随机种子。-1 每次都不一样；固定为同一数值可复现同一结果，便于微调对比。"},
        ]

    def _ensure_script(self, gpu: "GpuClient") -> str:
        remote_script = settings.GPU_LTX_SCRIPT
        if os.path.exists(_LOCAL_LTX_SOURCE):
            gpu.upload(_LOCAL_LTX_SOURCE, remote_script)
        elif not gpu.exists(remote_script):
            raise GpuConfigError(
                f"本地缺 LTX 脚本 {_LOCAL_LTX_SOURCE}，服务器也没有 {remote_script}。"
            )
        return remote_script

    def generate(self, gpu: "GpuClient", *, image_path: str, prompt: str,
                 out_remote: str, params: dict) -> None:
        if not settings.GPU_LTX_MODEL:
            raise GpuConfigError("未配置 LTX 模型，请在 .env 设置 GPU_LTX_MODEL（HF id 或本地权重目录）。")
        script = self._ensure_script(gpu)
        py = settings.GPU_PYTHON
        # 分辨率 + 数值参数都走共享 helper：格式/类型错在本地给友好提示，不再裸 ValueError 冒泡成 500。
        width, height = parse_size(params.get("size"), settings.LTX_SIZE, example="480*832")
        num_frames = coerce_num(params.get("num_frames"), settings.LTX_NUM_FRAMES, label="帧数")
        fps = coerce_num(params.get("fps"), settings.LTX_FPS, label="帧率")
        steps = coerce_num(params.get("steps"), settings.LTX_STEPS, label="采样步数")
        guidance = coerce_num(params.get("guidance"), settings.LTX_GUIDANCE, label="guidance", cast=float)
        try:
            seed = int(params.get("seed", -1))
        except (TypeError, ValueError):
            seed = -1   # seed 非法就回退随机（-1），不打断出片

        t5_arg = ""
        if settings.GPU_LTX_T5_DIR:
            t5_arg = f"--text_encoder {shlex.quote(settings.GPU_LTX_T5_DIR)} "
        cmd = (
            f"{shlex.quote(py)} {shlex.quote(script)} "
            f"--model {shlex.quote(settings.GPU_LTX_MODEL)} "
            f"{t5_arg}"
            f"--image {shlex.quote(image_path)} "
            f"--prompt {shlex.quote(prompt)} "
            f"--out {shlex.quote(out_remote)} "
            f"--width {width} --height {height} --num_frames {num_frames} "
            f"--fps {fps} --steps {steps} --guidance {guidance} --seed {seed}"
        )
        t0 = time.time()
        res = gpu.run(cmd, timeout=3600)
        logger.info("[ltx] 耗时 %.0fs, exit=%s", time.time() - t0, res.exit_code)
        ok = res.ok and any(l.startswith("SAVED::") for l in res.stdout.splitlines())
        if not ok:
            raise GpuRunError(f"LTX 图生视频失败 (exit {res.exit_code}):\n{res.stderr[-2000:]}")
