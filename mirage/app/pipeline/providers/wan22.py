"""
Wan2.2-I2V-A14B 视频 Provider（SSH 路径；5B 已彻底弃用）。

A14B 双专家、原生最强出片。A100-40G 用 --offload_model True 交换高/低噪专家以放下
（80G 可去掉 offload 更快）。
  generate.py --task i2v-A14B --size 704*1280 --frame_num 81 --sample_steps 30
  --offload_model True --convert_model_dtype
  （注：Colab 实际走 ComfyUI 的 A14B GGUF 模板；本 SSH 路径为可选后端。
   env 前缀在 GpuClient.run 里统一注入：OpenSSL legacy / CUDA 碎片化 / nvjitlink 路径）
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
    display_name = "Wan2.2-I2V-A14B"
    capabilities = {"i2v"}

    def param_schema(self) -> list[dict]:
        # 字段与 ComfyUI provider 对齐(frames/fps/steps/negative/seed)，保证 SSH/ComfyUI 两条后端
        # 参数卡完全一致——避免「Colab 4 个、本地 2 个」的混乱。generate() 内部把 frames→--frame_num、
        # steps→--sample_steps 映射回 SSH 脚本参数(并兼容旧键 frame_num/sample_steps)。
        return [
            {
                "key": "size", "label": "分辨率(宽*高)", "type": "select",
                "default": settings.WAN_SIZE,
                "help": "成片宽×高。竖屏适合手机；越大越清晰也越慢。",
                "options": [
                    {"value": "480*832", "label": "480×832 竖屏快出"},
                    {"value": "720*1280", "label": "720×1280 竖屏高清"},
                    {"value": "832*480", "label": "832×480 横屏快出"},
                    {"value": "1280*720", "label": "1280×720 横屏高清"},
                ],
            },
            {"key": "frames", "label": "帧数", "type": "number", "default": settings.WAN_FRAME_NUM,
             "help": "总帧数。时长≈帧数÷帧率。A14B 常用 81（≈5 秒）。"},
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.COMFYUI_FPS,
             "help": "每秒帧数。Wan 系常用 16。"},
            {"key": "steps", "label": "采样步数", "type": "number", "default": settings.WAN_SAMPLE_STEPS,
             "advanced": True, "help": "去噪步数。越大越精细越慢，一般 20-30。"},
            {"key": "negative", "label": "负向提示词", "type": "text",
             "default": "lowres, blurry, deformed, extra limbs, watermark, text",
             "advanced": True, "help": "不想要的内容（避免畸形/水印等）。"},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1,
             "advanced": True, "help": "随机种子。-1 每次不同；固定可复现。"},
        ]

    def generate(self, gpu: "GpuClient", *, image_path: str, prompt: str,
                 out_remote: str, params: dict) -> None:
        py = settings.GPU_PYTHON
        repo = settings.GPU_WAN_REPO
        ckpt = settings.GPU_WAN_CKPT
        size = params.get("size") or settings.WAN_SIZE
        # 统一字段 frames/steps → SSH 脚本的 --frame_num/--sample_steps(兼容旧键)
        frame_num = int(params.get("frames") or params.get("frame_num") or settings.WAN_FRAME_NUM)
        sample_steps = int(params.get("steps") or params.get("sample_steps") or settings.WAN_SAMPLE_STEPS)

        cmd = (
            f"cd {shlex.quote(repo)} && {shlex.quote(py)} generate.py "
            f"--task i2v-A14B --size {shlex.quote(size)} "
            f"--ckpt_dir {shlex.quote(ckpt)} "
            # A14B 双专家：A100-40G 用 offload 交换高/低噪专家以放下；80G 可去掉 offload 提速
            f"--offload_model True --convert_model_dtype "
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
