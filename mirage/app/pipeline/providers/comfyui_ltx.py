"""
LTX-Video 2.3 出片 Provider（图生视频 i2v）—— 通过 ComfyUI 的 HTTP API 提交 workflow。

与 Wan2.2 并列：用户在模型下拉里手选「LTX-Video 2.3」即走本 provider。参数卡完全由本类
param_schema() 驱动，字段是 **LTX 专属**（档位 dev/distilled、帧数须 8n+1、尺寸须 32 倍数、
guidance、是否保留原生音轨），不含 Wan 专属的 lightning/shift/boundary——参数严格对应模型。

定位（与 Wan2.2 互补）：
  LTX  = 快、音视频一体、分辨率高、走量/试错便宜；提示词遵循较松、运动控制不如 Wan 精细。
  Wan  = 运动真实感、电影级运镜控制、NSFW 社区生态成熟；慢，但质感上限更高。
常见用法：先用 LTX 极速打样锁提示词/节奏，再切 Wan 精修关键镜。

⚠️ 运行前提：LTX 2.3 需 ComfyUI v0.16+（强制 torch≥2.4）。本仓默认把 ComfyUI 钉在 v0.3.75
   （为躲 torch≥2.4 崩溃），两者**不能同实例共存**。要么升级 ComfyUI/torch 再用本 provider，
   要么单开一个 v0.16+ 的 ComfyUI 端点专给 LTX（provider 抽象支持多端点）。见 comfyui_workflows/README.md。

⚠️ workflow 模板：comfyui_workflows/ltx_i2v_template.json 是按 LTX 2.3 文档写的**脚手架**，
   节点名为 medium-confidence。首次真跑前，请用 ComfyUI v0.16+ 自带的官方 LTX i2v 模板（导出 API 格式）
   替换它，保留 %IMAGE%/%PROMPT%/%WIDTH%/... 占位符即可。模板路径由 settings.COMFYUI_WORKFLOW_LTX
   配置（可手改/可插拔），不动一行 Python。
"""

from __future__ import annotations

import os
import time

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline import comfy_http as ch
from mirage.app.pipeline import log_bus
from mirage.app.pipeline.gpu_client import GpuRunError, coerce_num, parse_size  # noqa: F401
from mirage.app.pipeline.providers.base import VideoProvider

logger = get_logger("pipeline.providers.comfyui_ltx")


class ComfyUILtxProvider(VideoProvider):
    name = "ltx2"
    display_name = "LTX-Video 2.3 (i2v)"
    capabilities = {"i2v"}
    transport = "http"   # 标记：do_render_scene_video 据此走纯本地分支（不碰 SSH）

    def param_schema(self) -> list[dict]:
        return [
            {"key": "mode", "label": "档位", "type": "select",
             "default": "distilled" if settings.LTX2_DISTILLED else "dev",
             "help": "dev=全量精修(质量上限更高)；distilled=8步蒸馏极速(走量/试错，类比 Wan 的极速档)。逐镜可切。",
             "options": [{"value": "dev", "label": "精修·全量(dev)"},
                         {"value": "distilled", "label": "极速·8步蒸馏(distilled)"}]},
            {"key": "size", "label": "分辨率(宽*高,须32倍数)", "type": "select",
             "default": settings.LTX2_SIZE,
             "help": "LTX 2.3 可到 1080p。竖屏适合手机；越大越清晰也越慢。宽高须为 32 的倍数。",
             "options": [
                 {"value": "704*1280", "label": "704×1280 竖屏(~720p)"},
                 {"value": "768*1344", "label": "768×1344 竖屏"},
                 {"value": "1088*1920", "label": "1088×1920 竖屏 1080p"},
                 {"value": "1280*704", "label": "1280×704 横屏"},
                 {"value": "1920*1088", "label": "1920×1088 横屏 1080p"},
                 {"value": "768*768", "label": "768×768 方形"},
             ]},
            {"key": "frames", "label": "帧数(须8n+1)", "type": "number", "default": settings.LTX2_FRAMES,
             "help": "总帧数，须为 8 的倍数+1(如 121≈5s@24fps)。时长≈帧数÷帧率。LTX 原生支持更长片段。"},
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.LTX2_FPS,
             "help": "每秒帧数。LTX 常用 24；调大更流畅但同帧数下更短。"},
            {"key": "steps", "label": "采样步数", "type": "number", "default": settings.LTX2_STEPS,
             "advanced": True, "help": "dev 档 30 左右；distilled 蒸馏档约 8。越大越精细越慢。"},
            {"key": "guidance", "label": "guidance", "type": "number", "default": settings.LTX2_GUIDANCE,
             "advanced": True, "help": "提示词引导强度。越大越贴提示词但可能僵硬，LTX 常用 3 左右。"},
            {"key": "audio", "label": "音频", "type": "select",
             "default": "1" if settings.LTX2_KEEP_AUDIO else "",
             "advanced": True,
             "help": "LTX 能一遍出音视频。默认『静音』把配音交给角色声音圣经 TTS(音色统一)；保留=用 LTX 原生音轨。",
             "options": [{"value": "", "label": "静音(交 TTS 配音，推荐)"},
                         {"value": "1", "label": "保留 LTX 原生音轨"}]},
            {"key": "negative", "label": "负向提示词", "type": "text",
             "default": "blurry, distorted, low quality, watermark, text",
             "advanced": True, "help": "不想要的内容（避免畸形/水印等）。"},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1,
             "advanced": True, "help": "随机种子。-1 每次不同；固定可复现，便于微调对比。"},
        ]

    def generate(self, gpu, *, image_path: str, prompt: str, out_remote: str, params: dict) -> None:
        """http 分支调用：image_path 为本地参考图，out_remote 为本地输出 mp4 路径。gpu 忽略。"""
        # 走 LTX 专属端点(双实例)；没配就回落到全局 COMFYUI_BASE_URL(单实例，与 Wan 共用)。
        base = ch.base_url(settings.COMFYUI_LTX_BASE_URL)
        # 分辨率/数值参数走共享 helper：格式/类型错在本地给友好提示，不裸 ValueError 冒泡。
        width, height = parse_size(params.get("size"), settings.LTX2_SIZE)
        try:
            seed = int(params.get("seed", -1))
        except (TypeError, ValueError):
            seed = -1
        if seed < 0:
            seed = int(time.time_ns() % 2_000_000_000)
        # 档位：distilled 没显式给步数就压到 8 步（蒸馏档的甜点）。只取本 provider 认识的键，
        # 多余键(如前端残留的 wan lightning)一律忽略，不报错。
        mode = str(params.get("mode") or ("distilled" if settings.LTX2_DISTILLED else "dev")).strip().lower()
        steps = coerce_num(params.get("steps"), settings.LTX2_STEPS, label="采样步数")
        if mode == "distilled" and not params.get("steps"):
            steps = 8
        keep_audio = params.get("audio", "1" if settings.LTX2_KEEP_AUDIO else "")
        keep_audio = keep_audio if isinstance(keep_audio, bool) else str(keep_audio).strip().lower() in (
            "1", "true", "yes", "on")
        mapping = {
            "%PROMPT%": prompt or "",
            "%NEG_PROMPT%": str(params.get("negative") or "blurry, distorted, low quality, watermark, text"),
            "%WIDTH%": width, "%HEIGHT%": height,
            "%FRAMES%": coerce_num(params.get("frames"), settings.LTX2_FRAMES, label="帧数"),
            "%FPS%": coerce_num(params.get("fps"), settings.LTX2_FPS, label="帧率"),
            "%STEPS%": steps,
            "%GUIDANCE%": coerce_num(params.get("guidance"), settings.LTX2_GUIDANCE, label="guidance", cast=float),
            "%SEED%": seed,
            "%MODE%": mode,
            "%KEEP_AUDIO%": "1" if keep_audio else "0",
        }
        template = ch.load_workflow(settings.COMFYUI_WORKFLOW_LTX, "ltx_i2v_template.json", "ltx-i2v")
        t0 = time.time()
        client_id = f"mirage-ltx-{os.getpid()}-{int(t0)}"
        with httpx.Client() as client:
            mapping["%IMAGE%"] = ch.upload_image(client, base, image_path)
            graph = ch.fill_template(template, mapping)
            prompt_id = ch.submit(client, base, graph, client_id)
            log_bus.emit("[出片·LTX] 已提交渲染任务，等待出片…")
            outputs = ch.wait(client, base, prompt_id, label="出片·LTX")
            items = ch.collect_outputs(outputs)
            if not items:
                raise GpuRunError("ComfyUI(LTX) 完成但没找到产物文件")
            # 优先选视频扩展名；都不是就取最后一个
            pick = next((c for c in items
                         if str(c.get("filename", "")).lower().endswith(ch.VIDEO_EXTS)),
                        items[-1])
            ch.download_view(client, base, pick, out_remote)
        logger.info("[comfyui-ltx] 出片完成 %.0fs → %s", time.time() - t0, out_remote)
