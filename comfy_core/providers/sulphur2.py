"""
Sulphur 2 出片 Provider（文生视频 t2v + 图生视频 i2v）—— 通过 ComfyUI HTTP API 提交 workflow。

Sulphur 2 = ~21B 的 **LTX-Video 2.3 无审查(uncensored) fine-tune**（NSFW 生产用），
ComfyUI 原生工作流 + GGUF 量化 + 蒸馏 LoRA，是 LTX-2.3 的 drop-in swap。本类与 comfyui_ltx.py
的 ComfyUILtxProvider 几乎同款（同走 LTX 采样/VAE），区别：① 同时支持 t2v+i2v（一镜按 image_path
有无自动分流到对应模板）；② 指向 Sulphur 的 checkpoint/模板/端点；③ 默认值用 Sulphur 推荐档。

★本仓(sulphur2 版)把默认视频后端从 Wan2.2 换成 Sulphur 2：
  settings.VIDEO_PROVIDER_DEFAULT="sulphur2"（i2v/续接走它）+ settings.T2V_PROVIDER="sulphur2"（t2v 走它）。
  其余全自动管线(拆镜/配音/对口型/MMAudio音效/合成) provider 无关，零改动复用。

⚠️ 运行前提：LTX 2.3/Sulphur 需 ComfyUI v0.16+（torch≥2.4）+ 节点 ComfyUI-GGUF / ComfyUI-LTXVideo
   / VideoHelperSuite。模型：Sulphur GGUF(unet) + ltx_vae.safetensors + LTX T5 文本编码器。
   下载见 colab/download_sulphur2.sh。端点 settings.SULPHUR2_BASE_URL（没配回落 COMFYUI_BASE_URL）。
⚠️ workflow 模板：comfyui_workflows/sulphur_{t2v,i2v}_template.json。首次真跑前请用 Sulphur 官方
   ComfyUI 工作流(导出 API 格式)替换，保留 %PROMPT%/%IMAGE%/%WIDTH%/... 占位符即可；不动一行 Python。
"""

from __future__ import annotations

import os
import time

import httpx

from comfy_core.config import settings
from comfy_core.logger import get_logger
from comfy_core import comfy_http as ch
from comfy_core import log_bus
from comfy_core.gpu_client import GpuRunError, coerce_num, parse_size  # noqa: F401
from comfy_core.providers.base import VideoProvider

logger = get_logger("pipeline.providers.sulphur2")


class Sulphur2Provider(VideoProvider):
    name = "sulphur2"
    display_name = "Sulphur 2 (LTX-2.3 无审查)"
    capabilities = {"i2v", "t2v"}     # 同一 provider 两用：有参考图=i2v / 无=t2v（按 image_path 分流）
    transport = "http"                # do_render_scene_video 据此走纯本地分支（不碰 SSH）

    def param_schema(self) -> list[dict]:
        return [
            {"key": "mode", "label": "档位", "type": "select",
             "default": "distilled" if settings.SULPHUR2_DISTILLED else "dev",
             "help": "dev=全量精修(质量上限更高)；distilled=蒸馏极速(走量/试错)。逐镜可切。",
             "options": [{"value": "dev", "label": "精修·全量(dev)"},
                         {"value": "distilled", "label": "极速·蒸馏(distilled)"}]},
            {"key": "size", "label": "分辨率(宽*高,须32倍数)", "type": "select",
             "default": settings.SULPHUR2_SIZE,
             "help": "LTX/Sulphur 可到 1080p。竖屏适合手机；越大越清晰也越慢。宽高须为 32 的倍数。",
             "options": [
                 {"value": "704*1280", "label": "704×1280 竖屏(~720p)"},
                 {"value": "768*1344", "label": "768×1344 竖屏"},
                 {"value": "1088*1920", "label": "1088×1920 竖屏 1080p"},
                 {"value": "1280*704", "label": "1280×704 横屏"},
                 {"value": "768*768", "label": "768×768 方形"},
             ]},
            {"key": "frames", "label": "帧数(须8n+1)", "type": "number", "default": settings.SULPHUR2_FRAMES,
             "help": "总帧数，须为 8 的倍数+1(如 121≈5s@24fps)。时长≈帧数÷帧率。"},
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.SULPHUR2_FPS,
             "help": "每秒帧数。LTX 常用 24。"},
            {"key": "steps", "label": "采样步数", "type": "number", "default": settings.SULPHUR2_STEPS,
             "advanced": True, "help": "dev 档 25-35；distilled 蒸馏档约 8。越大越精细越慢。"},
            {"key": "guidance", "label": "guidance(CFG)", "type": "number", "default": settings.SULPHUR2_GUIDANCE,
             "advanced": True, "help": "提示词引导强度。Sulphur/LTX 常用 3.5-5。"},
            {"key": "audio", "label": "音频", "type": "select",
             "default": "1" if settings.SULPHUR2_KEEP_AUDIO else "",
             "advanced": True,
             "help": "LTX/Sulphur 能一遍出音视频。默认『静音』把配音交给 TTS(音色统一)；保留=用原生音轨。",
             "options": [{"value": "", "label": "静音(交 TTS 配音，推荐)"},
                         {"value": "1", "label": "保留原生音轨"}]},
            {"key": "negative", "label": "负向提示词", "type": "text",
             "default": "blurry, distorted, low quality, watermark, text",
             "advanced": True, "help": "不想要的内容（避免畸形/水印等）。"},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1,
             "advanced": True, "help": "随机种子。-1 每次不同；固定可复现。"},
        ]

    def generate(self, gpu, *, image_path: str, prompt: str, out_remote: str, params: dict) -> None:
        """http 分支调用：image_path 非空=i2v(参考图)/空=t2v；out_remote 为本地输出 mp4 路径。gpu 忽略。"""
        base = ch.base_url(settings.SULPHUR2_BASE_URL)   # Sulphur 专属端点；没配回落全局 COMFYUI_BASE_URL
        is_i2v = bool(image_path) and os.path.exists(image_path)
        width, height = parse_size(params.get("size"), settings.SULPHUR2_SIZE)
        try:
            seed = int(params.get("seed", -1))
        except (TypeError, ValueError):
            seed = -1
        if seed < 0:
            seed = int(time.time_ns() % 2_000_000_000)
        mode = str(params.get("mode") or ("distilled" if settings.SULPHUR2_DISTILLED else "dev")).strip().lower()
        steps = coerce_num(params.get("steps"), settings.SULPHUR2_STEPS, label="采样步数")
        if mode == "distilled" and not params.get("steps"):
            steps = 8     # 蒸馏档甜点步数（未显式给步数才压）
        keep_audio = params.get("audio", "1" if settings.SULPHUR2_KEEP_AUDIO else "")
        keep_audio = keep_audio if isinstance(keep_audio, bool) else str(keep_audio).strip().lower() in (
            "1", "true", "yes", "on")
        mapping = {
            "%PROMPT%": prompt or "",
            "%NEG_PROMPT%": str(params.get("negative") or "blurry, distorted, low quality, watermark, text"),
            "%WIDTH%": width, "%HEIGHT%": height,
            "%FRAMES%": coerce_num(params.get("frames"), settings.SULPHUR2_FRAMES, label="帧数"),
            "%FPS%": coerce_num(params.get("fps"), settings.SULPHUR2_FPS, label="帧率"),
            "%STEPS%": steps,
            "%GUIDANCE%": coerce_num(params.get("guidance"), settings.SULPHUR2_GUIDANCE, label="guidance", cast=float),
            "%SEED%": seed,
            "%MODE%": mode,
            "%KEEP_AUDIO%": "1" if keep_audio else "0",
        }
        if is_i2v:
            template = ch.load_workflow(settings.COMFYUI_WORKFLOW_SULPHUR_I2V, "sulphur_i2v_template.json", "sulphur-i2v")
            label = "出片·Sulphur·i2v"
        else:
            template = ch.load_workflow(settings.COMFYUI_WORKFLOW_SULPHUR_T2V, "sulphur_t2v_template.json", "sulphur-t2v")
            label = "出片·Sulphur·t2v"
        t0 = time.time()
        client_id = f"sulphur2-{os.getpid()}-{int(t0)}"
        with httpx.Client() as client:
            if is_i2v:
                mapping["%IMAGE%"] = ch.upload_image(client, base, image_path)
            graph = ch.fill_template(template, mapping)
            # ★角色 LoRA 注入(可选，防御式)：训好的单 LoRA(项目级 char_lora)串到采样器前锁身份。
            #   约定节点 "8"=KSampler。取它【当前】的 model 来源，插一个 LoraLoaderModelOnly 串在中间，
            #   再把 KSampler 改吃 LoRA 输出；无 char_lora 则不动图。包 try/except，绝不破坏无 LoRA 路径。
            #   ★LoraLoaderModelOnly 是 ComfyUI 内置节点名；若你的 ComfyUI/LTX 套件节点名/采样器节点号不同，按实际改。
            # 只取文件名(先把 \ 归一成 /)，防 ../ 路径穿越——char_lora 本应是平铺在 loras/ 根的文件名，
            # 但它可能来自用户 video_params，必须当不可信处理(否则 ../../x 能让 ComfyUI 读宿主任意文件)。
            char_lora = (params.get("char_lora") or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
            try:
                char_lora_str = float(params.get("char_lora_str") or settings.SULPHUR_LORA_STRENGTH)
            except (TypeError, ValueError):
                char_lora_str = settings.SULPHUR_LORA_STRENGTH
            if char_lora:
                try:
                    # 取 KSampler(节点"8")【当前】的 model 来源，把 LoRA 串在它与 KSampler 之间——
                    # 不写死「LoRA 取自节点1」，官方工作流换图也稳(只要 8 是采样器)。
                    ks = graph.get("8") or {}
                    cur_model = (ks.get("inputs") or {}).get("model")
                    if cur_model is not None:
                        # 新节点 id 取【现有数字 id 最大值+1】，绝不撞官方模板已有节点(别写死 "20")。
                        new_id = str(max((int(k) for k in graph if str(k).isdigit()), default=0) + 1)
                        graph[new_id] = {
                            "class_type": "LoraLoaderModelOnly",
                            "inputs": {"model": cur_model, "lora_name": char_lora,
                                       "strength_model": char_lora_str},
                        }
                        graph["8"]["inputs"]["model"] = [new_id, 0]   # 采样器改吃挂了 LoRA 的模型
                        log_bus.emit(f"[{label}] 挂角色 LoRA: {char_lora} (强度 {char_lora_str})")
                except Exception:  # noqa: BLE001
                    logger.warning("[sulphur2] 角色 LoRA 注入失败，回退无 LoRA 出片: %s", char_lora)
            prompt_id = ch.submit(client, base, graph, client_id)
            log_bus.emit(f"[{label}] 已提交渲染任务，等待出片…")
            outputs = ch.wait(client, base, prompt_id, label=label)
            items = ch.collect_outputs(outputs)
            if not items:
                raise GpuRunError("ComfyUI(Sulphur 2) 完成但没找到产物文件")
            pick = next((c for c in items
                         if str(c.get("filename", "")).lower().endswith(ch.VIDEO_EXTS)),
                        items[-1])
            ch.download_view(client, base, pick, out_remote)
        logger.info("[sulphur2] 出片完成 %.0fs (%s) → %s", time.time() - t0,
                    "i2v" if is_i2v else "t2v", out_remote)
