"""
Wan2.2-TI2V-5B 视频 Provider —— 把原先写死在 gpu_client.generate_video 的命令搬到这里。

已验证可跑通的省显存配置（单卡 24G）：
  generate.py --task ti2v-5B --size 704*1280 --frame_num 25 --sample_steps 25
  --offload_model True --convert_model_dtype --t5_cpu
  （env 前缀在 GpuClient.run 里统一注入：OpenSSL legacy / CUDA 碎片化 / nvjitlink 路径）
"""

from __future__ import annotations

import shlex
import time
from typing import TYPE_CHECKING

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline.gpu_client import GpuRunError
from mirage.app.pipeline.providers.base import VideoProvider

if TYPE_CHECKING:
    from mirage.app.pipeline.gpu_client import GpuClient

logger = get_logger("pipeline.providers.wan22")


class Wan22Provider(VideoProvider):
    name = "wan2.2"
    display_name = "Wan2.2-TI2V-5B"
    capabilities = {"i2v"}

    def param_schema(self) -> list[dict]:
        return [
            {
                "key": "size", "label": "分辨率", "type": "select",
                "default": settings.WAN_SIZE,
                "help": "成片画面尺寸。竖屏适合手机短视频，横屏适合横版播放。",
                "options": [
                    {"value": "704*1280", "label": "704×1280 竖屏"},
                    {"value": "1280*704", "label": "1280×704 横屏"},
                    {"value": "960*960", "label": "960×960 方形"},
                ],
            },
            {"key": "frame_num", "label": "帧数(≤25稳)", "type": "number",
             "default": settings.WAN_FRAME_NUM,
             "help": "总帧数，决定视频长度（约 帧数÷24 秒）。越多越长越吃显存，24G 显卡建议不超过 25 帧。"},
            {"key": "sample_steps", "label": "采样步数", "type": "number",
             "default": settings.WAN_SAMPLE_STEPS, "advanced": True,
             "help": "去噪迭代次数。越大画质/稳定性略好但越慢，一般 20-30。"},
        ]

    def generate(self, gpu: "GpuClient", *, image_path: str, prompt: str,
                 out_remote: str, params: dict) -> None:
        py = settings.GPU_PYTHON
        repo = settings.GPU_WAN_REPO
        ckpt = settings.GPU_WAN_CKPT
        size = params.get("size") or settings.WAN_SIZE
        frame_num = int(params.get("frame_num") or settings.WAN_FRAME_NUM)
        sample_steps = int(params.get("sample_steps") or settings.WAN_SAMPLE_STEPS)

        cmd = (
            f"cd {shlex.quote(repo)} && {shlex.quote(py)} generate.py "
            f"--task ti2v-5B --size {shlex.quote(size)} "
            f"--ckpt_dir {shlex.quote(ckpt)} "
            f"--offload_model True --convert_model_dtype --t5_cpu "
            f"--frame_num {frame_num} --sample_steps {sample_steps} "
            f"--image {shlex.quote(image_path)} "
            f"--prompt {shlex.quote(prompt)} "
            f"--save_file {shlex.quote(out_remote)}"
        )
        t0 = time.time()
        res = gpu.run(cmd, timeout=3600)
        logger.info("[wan2.2] 耗时 %.0fs, exit=%s", time.time() - t0, res.exit_code)
        if not res.ok:
            raise GpuRunError(f"Wan2.2 图生视频失败 (exit {res.exit_code}):\n{res.stderr[-2000:]}")
