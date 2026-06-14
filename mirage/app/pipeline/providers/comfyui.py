"""
ComfyUI 出片 Provider（图生视频，i2v）—— 通过 ComfyUI 的 HTTP API 提交 workflow 出片。

为什么走 ComfyUI：
  自搓 SSH 脚本（裸调 diffusers/generate.py）缺少社区那套优化与调好的 workflow，易崩、慢、画质低。
  ComfyUI 生态已把 GGUF 量化（24G 跑 14B）、SageAttention 提速、FramePack/长视频、以及调到不崩的
  i2v workflow 都封装好了。本 Provider 把出片后端接到 ComfyUI，白嫖这些，面板/Agent/合成全不动。

与其它 Provider 不同点：
  - transport = "http"：不走 SSH/GpuClient。do_render_scene_video 检测到后会走「纯本地」分支，
    把本地参考图交给本 Provider，本 Provider 自己 HTTP 上传到 ComfyUI、提交、轮询、下载到本地 out。
  - 不绑死机器：端点由 settings.COMFYUI_BASE_URL 配置，换机器只改这一个地址。
  - 不硬编码 workflow：读 settings.COMFYUI_WORKFLOW_I2V（或仓库自带 comfyui_workflows/i2v_gguf_template.json，A14B 双专家），
    按占位符 %IMAGE%/%PROMPT%/%NEG_PROMPT%/%WIDTH%/%HEIGHT%/%FRAMES%/%FPS%/%STEPS%/%SEED% 填值后提交。

HTTP 调用（上传/提交/轮询/下载/填模板）统一走 pipeline/comfy_http.py 的共享 helper。
"""

from __future__ import annotations

import os
import time

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline import comfy_http as ch
from mirage.app.pipeline import log_bus
from mirage.app.pipeline.gpu_client import GpuConfigError, GpuRunError  # noqa: F401 (re-export 供测试/外部引用)
from mirage.app.pipeline.providers.base import VideoProvider

logger = get_logger("pipeline.providers.comfyui")


class ComfyUIProvider(VideoProvider):
    # 默认元信息仅用于独立测试；正式注册时由 providers/__init__ 顶替成公开模型名
    # （如 name="wan2.2", display_name="Wan2.2-TI2V-5B"），用户因此看不到「ComfyUI」字样。
    name = "comfyui"
    display_name = "ComfyUI (i2v)"
    capabilities = {"i2v"}
    transport = "http"   # 标记：do_render_scene_video 据此走纯本地分支（不碰 SSH）

    def __init__(self, name: str | None = None, display_name: str | None = None) -> None:
        if name:
            self.name = name
        if display_name:
            self.display_name = display_name

    def param_schema(self) -> list[dict]:
        return [
            {
                "key": "size", "label": "分辨率(宽*高)", "type": "select",
                "default": settings.COMFYUI_SIZE,
                "help": "成片宽×高。竖屏适合手机，越大越清晰也越慢。需与你的 workflow/模型匹配。",
                "options": [
                    {"value": "480*832", "label": "480×832 竖屏快出"},
                    {"value": "720*1280", "label": "720×1280 竖屏高清"},
                    {"value": "832*480", "label": "832×480 横屏快出"},
                    {"value": "1280*720", "label": "1280×720 横屏高清"},
                    {"value": "768*768", "label": "768×768 方形"},
                ],
            },
            {"key": "frames", "label": "帧数", "type": "number", "default": settings.COMFYUI_FRAMES,
             "help": "总帧数。和帧率一起决定时长：时长≈帧数÷帧率。Wan 系常用 81。"},
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.COMFYUI_FPS,
             "help": "每秒帧数。Wan 系常用 16；调大更流畅但同帧数下更短。"},
            {"key": "steps", "label": "采样步数", "type": "number", "default": settings.COMFYUI_STEPS,
             "advanced": True, "help": "去噪步数。越大越精细越慢。"},
            {"key": "negative", "label": "负向提示词", "type": "text",
             "default": "lowres, blurry, deformed, extra limbs, watermark, text",
             "advanced": True, "help": "不想要的内容（避免畸形/水印等）。"},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1,
             "advanced": True, "help": "随机种子。-1 每次不同；固定可复现，便于微调对比。"},
        ]

    def generate(self, gpu, *, image_path: str, prompt: str, out_remote: str, params: dict) -> None:
        """http 分支调用：image_path 为本地参考图，out_remote 为本地输出 mp4 路径。gpu 忽略。"""
        base = ch.base_url()
        size = str(params.get("size") or settings.COMFYUI_SIZE)
        try:
            width, height = (int(x) for x in size.replace("x", "*").split("*"))
        except ValueError:
            raise GpuRunError(f"分辨率格式应为 宽*高，收到: {size}")
        seed = int(params.get("seed", -1))
        if seed < 0:
            seed = int(time.time_ns() % 2_000_000_000)
        mapping = {
            "%PROMPT%": prompt or "",
            "%NEG_PROMPT%": str(params.get("negative") or ""),
            "%WIDTH%": width, "%HEIGHT%": height,
            "%FRAMES%": int(params.get("frames") or settings.COMFYUI_FRAMES),
            "%FPS%": int(params.get("fps") or settings.COMFYUI_FPS),
            "%STEPS%": int(params.get("steps") or settings.COMFYUI_STEPS),
            "%SEED%": seed,
        }
        template = ch.load_workflow(settings.COMFYUI_WORKFLOW_I2V, "i2v_gguf_template.json", "i2v")
        t0 = time.time()
        client_id = f"mirage-{os.getpid()}-{int(t0)}"
        with httpx.Client() as client:
            mapping["%IMAGE%"] = ch.upload_image(client, base, image_path)
            graph = ch.fill_template(template, mapping)
            prompt_id = ch.submit(client, base, graph, client_id)
            log_bus.emit("[出片] 已提交渲染任务，等待出片…")
            outputs = ch.wait(client, base, prompt_id, label="出片")
            items = ch.collect_outputs(outputs)
            if not items:
                raise GpuRunError("ComfyUI 完成但没找到产物文件")
            # 优先选视频扩展名；都不是就取最后一个
            pick = next((c for c in items
                         if str(c.get("filename", "")).lower().endswith(ch.VIDEO_EXTS)),
                        items[-1])
            ch.download_view(client, base, pick, out_remote)
        logger.info("[comfyui] 出片完成 %.0fs → %s", time.time() - t0, out_remote)
