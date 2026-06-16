"""
ComfyUI 文生图 Provider（t2i）—— 把出图也接到 ComfyUI 的 HTTP API。

为什么：出图和出片一样能白嫖 ComfyUI 生态（GGUF Flux 省显存、更好采样器、LoRA 叠加、内置放大）。
与 FluxSshImageProvider 的区别：transport="http"，不走 SSH——本 Provider 直接 HTTP 提交 t2i workflow、
轮询、把候选图下载到**本地** out_dir，返回本地路径（generate_candidates 的 http 分支据此免去 SSH 下载）。

多候选实现：循环 N 次、每次 seed+i 提交一张（ComfyUI 会缓存模型，循环很快），逐张下载。
不硬编码 workflow：读 settings.COMFYUI_WORKFLOW_T2I（或仓库自带 comfyui_workflows/t2i_template.json），
占位符 %PROMPT%/%NEG_PROMPT%/%WIDTH%/%HEIGHT%/%STEPS%/%SEED% 填值后提交。
端点未配置（COMFYUI_BASE_URL 空）时本 Provider 根本不会被注册（见 image_providers/__init__.py）。
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline import comfy_http as ch
from mirage.app.pipeline import log_bus
from mirage.app.pipeline.gpu_client import GpuConfigError, GpuRunError, parse_size  # noqa: F401 (re-export)
from mirage.app.pipeline.image_providers.base import ImageProvider

if TYPE_CHECKING:
    from mirage.app.pipeline.gpu_client import GpuClient

logger = get_logger("pipeline.image_providers.comfyui_image")


def _strip_lora_node(graph: dict) -> dict:
    """没配 LoRA 时删掉 LoraLoader(节点"13")，把对它的引用回退到它自己的上游：
    [13,0]→节点13.inputs.model（底模 MODEL），[13,1]→节点13.inputs.clip（CLIP 来源）。
    通用：flux 模板 clip 来自 DualCLIP[11,0]、checkpoint 模板 clip 来自 [10,1]，都能正确回退。"""
    node = graph.get("13", {})
    inp = node.get("inputs", {}) if isinstance(node, dict) else {}
    model_ref = inp.get("model", ["10", 0])
    clip_ref = inp.get("clip", ["11", 0])
    g = {k: v for k, v in graph.items() if k != "13"}

    def fix(x):
        if isinstance(x, list) and len(x) == 2 and x[0] == "13":
            return list(model_ref) if x[1] == 0 else list(clip_ref)
        if isinstance(x, dict):
            return {k: fix(v) for k, v in x.items()}
        if isinstance(x, list):
            return [fix(v) for v in x]
        return x

    return fix(g)


class ComfyUIImageProvider(ImageProvider):
    # 默认元信息仅用于独立测试；正式注册时由 image_providers/__init__ 顶替成公开模型名
    # （如 name="flux", display_name="FLUX (SSH)"），用户因此看不到「ComfyUI」字样。
    name = "comfyui-img"
    display_name = "ComfyUI (文生图)"
    capabilities = {"t2i"}
    transport = "http"
    # 本 Provider 服务的都是 FLUX 系 checkpoint(DAC_Fluxed / Chroma / flux-dev)——文本编码器纯英文，读不懂中文。
    # 标 "en" → 工具层出图前把含中文的 image_prompt 自动翻英文(受 IMAGE_PROMPT_AUTOTRANSLATE 总开关)。
    # ★漏标会退回基类默认 "any" → 跳过翻译 → 中文直喂 FLUX 出乱图(女人/食物/玩具那种)★。
    prompt_lang = "en"

    def __init__(self, name: str | None = None, display_name: str | None = None) -> None:
        if name:
            self.name = name
        if display_name:
            self.display_name = display_name

    def param_schema(self) -> list[dict]:
        return [
            {"key": "n", "label": "张数", "type": "number", "default": settings.COMFYUI_T2I_N,
             "help": "一次出几张候选图（每张换一个 seed）。越多挑选余地越大也越慢。"},
            {
                "key": "size", "label": "分辨率(宽*高)", "type": "select",
                "default": settings.COMFYUI_T2I_SIZE,
                "help": "出图宽×高。需与你的 workflow/模型匹配。",
                "options": [
                    {"value": "768*1024", "label": "768×1024 竖屏人物"},
                    {"value": "832*1216", "label": "832×1216 竖屏高"},
                    {"value": "1024*1024", "label": "1024×1024 方形"},
                    {"value": "1216*832", "label": "1216×832 横屏"},
                ],
            },
            {"key": "steps", "label": "采样步数", "type": "number", "default": settings.COMFYUI_T2I_STEPS,
             "help": "去噪步数。越大越精细越慢。Flux-dev 常用 28。"},
            {"key": "negative", "label": "负向提示词", "type": "text",
             "default": "lowres, blurry, deformed, extra fingers, watermark, text",
             "advanced": True, "help": "不想要的内容（Flux 等无 CFG 模型可留空）。"},
            {"key": "seed", "label": "起始 seed(-1随机)", "type": "number", "default": -1,
             "advanced": True, "help": "随机种子起点。-1 每次不同；固定可复现。N 张依次 seed、seed+1…"},
        ]

    def generate(self, gpu: "GpuClient", *, prompt: str, out_dir: str, params: dict) -> list[str]:
        """HTTP 提交 t2i workflow，循环出 N 张，下载到本地 out_dir，返回本地路径列表。"""
        base = ch.base_url()
        width, height = parse_size(params.get("size"), settings.COMFYUI_T2I_SIZE)
        n = int(params.get("n") or settings.COMFYUI_T2I_N)
        n = max(1, min(n, 12))
        steps = int(params.get("steps") or settings.COMFYUI_T2I_STEPS)
        negative = str(params.get("negative") or "")
        seed0 = int(params.get("seed", -1))
        if seed0 < 0:
            seed0 = int(time.time_ns() % 2_000_000_000)

        template = ch.load_workflow(settings.COMFYUI_WORKFLOW_T2I, "t2i_template.json", "t2i")
        os.makedirs(out_dir, exist_ok=True)
        t0 = time.time()
        client_id = f"mirage-img-{os.getpid()}-{int(t0)}"
        local_paths: list[str] = []
        with httpx.Client() as client:
            # 人物 LoRA：项目/工作目录配了 flux_lora 才注入 %LORA%（只取文件名，匹配 ComfyUI/models/loras/）。
            # 没配则删掉模板里的 LoraLoader 节点（空 %LORA% 会被 ComfyUI 当成找不到的 lora 直接报错）。
            lora = (params.get("flux_lora") or "").strip()
            use_lora = bool(lora) and lora.lower() != "none"
            # 核实 LoRA 真实存在：配了个 ComfyUI 里没有的文件名会让整批出图被校验打回(整批失败)。
            # 能查到列表且不在其中 → 降级为「不加 LoRA」继续出图 + 告警；查不到列表则不拦(保持原行为)。
            if use_lora:
                avail = ch.available_loras(base)
                if avail is not None and os.path.basename(lora) not in avail:
                    log_bus.emit(f"[出图] ⚠ LoRA「{os.path.basename(lora)}」在 ComfyUI 不存在，"
                                 f"本次按【不加 LoRA】出图（去「角色 & LoRA」训练它，或核对文件名）。")
                    use_lora = False
            for i in range(n):
                seed = (seed0 + i) % 2_000_000_000
                mapping = {
                    "%PROMPT%": prompt or "",
                    "%NEG_PROMPT%": negative,
                    "%WIDTH%": width, "%HEIGHT%": height,
                    "%STEPS%": steps, "%SEED%": seed,
                    # 出图底模可配：%UNET%=UNET-only 模板用(flux t2i)；%CKPT%=全合一 checkpoint 模板用(CivitAI 如 Fluxed Up)
                    "%UNET%": settings.COMFYUI_FLUX_UNET or "flux1-dev.safetensors",
                    "%CKPT%": settings.COMFYUI_FLUX_CKPT or "",
                }
                if use_lora:
                    mapping["%LORA%"] = os.path.basename(lora)
                graph = ch.fill_template(template, mapping)
                if not use_lora:
                    graph = _strip_lora_node(graph)
                prompt_id = ch.submit(client, base, graph, client_id)
                log_bus.emit(f"[出图] 第 {i + 1}/{n} 张已提交（seed={seed}），等待出图…")
                outputs = ch.wait(client, base, prompt_id, label="出图")
                items = ch.collect_outputs(outputs)
                imgs = [c for c in items
                        if str(c.get("filename", "")).lower().endswith(ch.IMAGE_EXTS)] or items
                if not imgs:
                    raise GpuRunError(f"ComfyUI 第 {i + 1} 张完成但没找到图片产物")
                pick = imgs[0]
                ext = os.path.splitext(pick["filename"])[1] or ".png"
                lp = os.path.join(out_dir, f"comfyui_{seed}{ext}")
                ch.download_view(client, base, pick, lp)
                local_paths.append(lp)
        logger.info("[comfyui-img] 出 %d 张候选 %.0fs → %s", len(local_paths), time.time() - t0, out_dir)
        return local_paths
