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
from mirage.app.pipeline.gpu_client import GpuConfigError, GpuRunError, parse_size  # noqa: F401 (re-export 供测试/外部引用)
from mirage.app.pipeline.providers.base import VideoProvider

logger = get_logger("pipeline.providers.comfyui")


class ComfyUIProvider(VideoProvider):
    # 默认元信息仅用于独立测试；正式注册时由 providers/__init__ 顶替成公开模型名
    # （如 name="wan2.2", display_name="Wan2.2-I2V-A14B"），用户因此看不到「ComfyUI」字样。
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
            {"key": "lightning", "label": "极速档(Lightning)", "type": "select",
             # 关态用非空哨兵 "0"(而非 "")：do_render 合并参数时会丢弃空串，空串会让「关」失效——
             # WAN_LIGHTNING=true 时就逐镜关不掉极速档。"0" 不在 generate() 的真值集合里→判为关。
             "default": "1" if settings.WAN_LIGHTNING else "0",
             "help": "开=4步蒸馏极速(~1-2分/镜，画质≈A14B 略降)；关=A14B 满档 30 步精修(更清更慢)。逐镜可切。",
             "options": [{"value": "0", "label": "关·精修(A14B 满档)"},
                         {"value": "1", "label": "开·极速(Lightning 4步)"}]},
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
             "default": "",   # 留空=回落到 settings.WAN_VIDEO_NEGATIVE(Wan 官方长串);非空才覆盖
             "advanced": True, "help": "不想要的内容。留空=用 Wan 官方视频负向词(压静止/过曝/畸形/morphing)。"},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1,
             "advanced": True, "help": "随机种子。-1 每次不同；固定可复现，便于微调对比。"},
        ]

    def generate(self, gpu, *, image_path: str, prompt: str, out_remote: str, params: dict) -> None:
        """http 分支调用：image_path 为本地参考图，out_remote 为本地输出 mp4 路径。gpu 忽略。"""
        base = ch.base_url()
        width, height = parse_size(params.get("size"), settings.COMFYUI_SIZE)
        seed = int(params.get("seed", -1))
        if seed < 0:
            seed = int(time.time_ns() % 2_000_000_000)
        mapping = {
            "%PROMPT%": prompt or "",
            # 负向词没传就用 Wan 官方长串(压静止/过曝/morphing/畸形)——出图通用负向不适合视频。
            "%NEG_PROMPT%": str(params.get("negative") or settings.WAN_VIDEO_NEGATIVE),
            "%WIDTH%": width, "%HEIGHT%": height,
            "%FRAMES%": int(params.get("frames") or settings.COMFYUI_FRAMES),
            "%FPS%": int(params.get("fps") or settings.COMFYUI_FPS),
            "%STEPS%": int(params.get("steps") or settings.COMFYUI_STEPS),
            # 双专家切换步=总步数一半(high 0→boundary, low boundary→end);随 steps 自动折半
            "%BOUNDARY%": int(params.get("steps") or settings.COMFYUI_STEPS) // 2,
            "%SHIFT%": float(params.get("shift") or settings.WAN_SHIFT),   # ModelSamplingSD3 必需
            "%SEED%": seed,
        }
        # 极速档:lightning=true(面板「极速档」开关/更多参数)或 settings.WAN_LIGHTNING → 4步蒸馏 LoRA 模板;否则 A14B 满档精修
        _lv = params.get("lightning", settings.WAN_LIGHTNING)
        lightning = _lv if isinstance(_lv, bool) else str(_lv).strip().lower() in (
            "1", "true", "yes", "on", "lightning", "极速")
        if lightning:
            mapping["%LIGHT_HI_LORA%"] = settings.WAN_LIGHTNING_LORA_HIGH
            mapping["%LIGHT_LO_LORA%"] = settings.WAN_LIGHTNING_LORA_LOW
            mapping["%LIGHT_HI_STR%"] = float(settings.WAN_LIGHTNING_STR_HIGH)   # 运动弱就调 1.5
            mapping["%LIGHT_LO_STR%"] = float(settings.WAN_LIGHTNING_STR_LOW)
            # 极速档专属步数/切换步/shift：覆盖满档默认（别拿 COMFYUI_STEPS=30 去跑 4 步蒸馏）。
            # 步数来自 WAN_LIGHTNING_STEPS(默认6)、夹在 2..12；切换步取一半；shift 用蒸馏档的 ~8。
            _lsteps = max(2, min(int(settings.WAN_LIGHTNING_STEPS or 6), 12))
            mapping["%STEPS%"] = _lsteps
            mapping["%BOUNDARY%"] = max(1, _lsteps // 2)
            mapping["%SHIFT%"] = float(params.get("shift") or settings.WAN_LIGHTNING_SHIFT)
            # 极速档模板按 GPU 精度自适应：无原生 fp8 的卡(A100/V100，cell-1 探测为 fp16)→ 用 bf16 极速档模板，
            # 避免在 sm_80 上跑模拟 fp8(纯亏)。仅当仍是 fp8 默认模板时自动切；用户显式改过则尊重其选择。
            _light_tmpl = settings.COMFYUI_WORKFLOW_I2V_LIGHTNING
            if (settings.I2V_PRECISION or "").lower() in ("fp16", "bf16") \
                    and _light_tmpl.endswith("i2v_fp8_lightning_template.json"):
                _light_tmpl = "comfyui_workflows/i2v_bf16_lightning_template.json"
            template = ch.load_workflow(_light_tmpl,
                                        "i2v_fp8_lightning_template.json", "i2v-lightning")
        else:
            template = ch.load_workflow(settings.COMFYUI_WORKFLOW_I2V, "i2v_gguf_template.json", "i2v")
        # 角色 LoRA(i2v 原生训的 wan_i2v_lora_*,用于尾帧续接锁脸):仅当 i2v 模板含 %CHAR_HI_LORA% 占位时注入,
        # 否则跳过(不破坏现有模板)。★要生效,i2v 模板需仿 t2v(comfyui_t2v.py 的 69/70 角色 LoRA 节点)加占位符+节点。
        import json as _json
        if "%CHAR_HI_LORA%" in _json.dumps(template):
            _chi = (params.get("wan_i2v_lora_high") or settings.WAN_I2V_LORA_HIGH or "").strip()
            _clo = (params.get("wan_i2v_lora_low") or settings.WAN_I2V_LORA_LOW or "").strip()
            if _chi:
                mapping["%CHAR_HI_LORA%"] = _chi
                mapping["%CHAR_HI_STR%"] = float(params.get("wan_i2v_lora_str_high") or settings.WAN_I2V_LORA_STR_HIGH)
                mapping["%CHAR_LO_LORA%"] = _clo or _chi
                mapping["%CHAR_LO_STR%"] = float(params.get("wan_i2v_lora_str_low") or settings.WAN_I2V_LORA_STR_LOW)
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
