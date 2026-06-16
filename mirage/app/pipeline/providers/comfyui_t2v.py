"""Wan2.2-T2V 文生视频 Provider —— 文本直接 → 视频，走 ComfyUI（与 i2v 并存）。

与 i2v 的区别：t2v **不吃首帧图**，用 EmptyHunyuanLatentVideo 产空 latent，正负提示词直连采样器。
角色身份靠训好的 Wan-T2V 角色 LoRA（高/低噪各一）；没训就纯提示词驱动（身份不稳）。

设计（照搬已验证的 S2V 旁路）：
  - 隐藏 Provider（hidden=True）：不进用户模型下拉，由「出片模式=t2v」路由（见 pipeline_tools._do_render_t2v）。
  - transport="http"：走 ComfyUI，端点门控同 COMFYUI_BASE_URL。
  - generate() 收下 image_path 但忽略（t2v 无首帧），保持与 base 同签名，调用点无需为 t2v 改。
  - 模板：满档 t2v_fp8_template.json / 极速 t2v_fp8_lightning_template.json（params['lightning'] 或 .env）。
  - 角色 LoRA 占位符 %CHAR_HI/LO_LORA%/STR：从 params(wan_t2v_lora_*)→.env 取；为空则摘掉 LoRA 节点
    （传空 lora_name 会让 ComfyUI 校验失败）。
"""

from __future__ import annotations

import os
import time

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline import comfy_http as ch
from mirage.app.pipeline import log_bus
from mirage.app.pipeline.gpu_client import GpuConfigError, GpuRunError, parse_size  # noqa: F401 (re-export)
from mirage.app.pipeline.providers.base import VideoProvider

logger = get_logger("pipeline.providers.comfyui_t2v")


def _strip_lora_node(graph: dict, node_id: str) -> None:
    """从 workflow graph 摘掉一个 LoraLoaderModelOnly 节点，并把引用它的下游接回它的 model 上游。

    用于角色 LoRA 为空时：避免传空 lora_name 触发 ComfyUI node_errors。
    """
    node = graph.get(node_id)
    if not node:
        return
    upstream = (node.get("inputs") or {}).get("model")   # 如 ["37",0] 或 ["67",0]
    if upstream is None:
        return
    for n in graph.values():
        ins = n.get("inputs") if isinstance(n, dict) else None
        if not isinstance(ins, dict):
            continue
        for k, v in ins.items():
            if isinstance(v, list) and len(v) == 2 and v[0] == node_id:
                ins[k] = upstream
    graph.pop(node_id, None)


class ComfyUIT2VProvider(VideoProvider):
    name = "comfyui-t2v"
    display_name = "文生视频(Wan2.2-T2V)"
    capabilities = {"t2v"}
    transport = "http"
    hidden = True   # 不进用户下拉；由「出片模式=t2v」路由

    def param_schema(self) -> list[dict]:
        return [
            {"key": "size", "label": "分辨率(宽*高)", "type": "select", "default": settings.COMFYUI_SIZE,
             "options": [
                 {"value": "480*832", "label": "480×832 竖屏"},
                 {"value": "720*1280", "label": "720×1280 竖屏高清"},
                 {"value": "832*480", "label": "832×480 横屏"},
                 {"value": "768*768", "label": "768×768 方形"},
             ]},
            {"key": "negative", "label": "负向词(留空=Wan 官方负向)", "type": "text", "default": "", "advanced": True},
            {"key": "lightning", "label": "极速档(4-6步蒸馏)", "type": "bool", "default": bool(settings.WAN_LIGHTNING)},
            {"key": "frames", "label": "帧数(4n+1)", "type": "number", "default": settings.COMFYUI_FRAMES, "advanced": True},
            {"key": "steps", "label": "采样步数(满档)", "type": "number", "default": settings.COMFYUI_STEPS, "advanced": True},
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.COMFYUI_FPS, "advanced": True},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1, "advanced": True},
        ]

    def generate(self, gpu, *, image_path: str, prompt: str, out_remote: str, params: dict) -> None:
        """http 分支：image_path 忽略(t2v 无首帧)，out_remote 本地输出 mp4。"""
        base = ch.base_url()
        params = params or {}
        width, height = parse_size(params.get("size"), settings.COMFYUI_SIZE)
        seed = int(params.get("seed", -1))
        if seed < 0:
            seed = int(time.time_ns() % 2_000_000_000)
        # 极速档(蒸馏)还是满档：与 i2v 同款判定
        _lv = params.get("lightning", settings.WAN_LIGHTNING)
        lightning = _lv if isinstance(_lv, bool) else str(_lv).strip().lower() in (
            "1", "true", "yes", "on", "lightning", "极速")
        # 极速档缺 t2v 蒸馏 LoRA 文件名 → 4-6 步无蒸馏=噪声,自动改走满档(别拿空 lora_name 喂 ComfyUI)
        if lightning and not ((settings.WAN_T2V_LIGHTNING_LORA_HIGH or "").strip()
                              and (settings.WAN_T2V_LIGHTNING_LORA_LOW or "").strip()):
            log_bus.emit("[文生视频] 极速档缺 t2v 蒸馏 LoRA 文件名,本次改走满档。")
            lightning = False
        if lightning:
            steps = max(2, min(int(settings.WAN_LIGHTNING_STEPS or 6), 12))
            shift = float(params.get("shift") or settings.WAN_LIGHTNING_SHIFT)
            tmpl = settings.COMFYUI_WORKFLOW_T2V_LIGHTNING or "comfyui_workflows/t2v_fp8_lightning_template.json"
            tmpl_default, bf16_tmpl = "t2v_fp8_lightning_template.json", "comfyui_workflows/t2v_bf16_lightning_template.json"
        else:
            steps = int(params.get("steps") or settings.COMFYUI_STEPS)
            shift = float(params.get("shift") or settings.WAN_SHIFT)
            tmpl = settings.COMFYUI_WORKFLOW_T2V or "comfyui_workflows/t2v_fp8_template.json"
            tmpl_default, bf16_tmpl = "t2v_fp8_template.json", "comfyui_workflows/t2v_bf16_template.json"
        # 无原生 fp8 卡(A100/V100，cell-1 探测=fp16)→ 用 bf16 模板,避免 sm_80 跑模拟 fp8;仅当仍是 fp8 默认模板时切
        if (settings.T2V_PRECISION or "").lower() in ("fp16", "bf16") and tmpl.endswith(tmpl_default):
            tmpl = bf16_tmpl
        mapping = {
            "%PROMPT%": prompt or "",
            "%NEG_PROMPT%": str(params.get("negative") or settings.WAN_VIDEO_NEGATIVE),
            "%WIDTH%": width, "%HEIGHT%": height,
            "%FRAMES%": int(params.get("frames") or settings.COMFYUI_FRAMES),
            "%FPS%": int(params.get("fps") or settings.COMFYUI_FPS),
            "%STEPS%": steps,
            "%BOUNDARY%": max(1, steps // 2),   # 高噪 0→boundary，低噪 boundary→end
            "%SHIFT%": shift,
            "%SEED%": seed,
        }
        template = ch.load_workflow(tmpl, tmpl_default, "t2v")
        # 角色 LoRA：有就填，没有就摘节点(69/70)
        char_hi = (params.get("wan_t2v_lora_high") or settings.WAN_T2V_LORA_HIGH or "").strip()
        char_lo = (params.get("wan_t2v_lora_low") or settings.WAN_T2V_LORA_LOW or "").strip()
        if char_hi:
            mapping["%CHAR_HI_LORA%"] = char_hi
            mapping["%CHAR_HI_STR%"] = float(params.get("wan_t2v_lora_str_high") or settings.WAN_T2V_LORA_STR_HIGH)
            mapping["%CHAR_LO_LORA%"] = char_lo or char_hi
            mapping["%CHAR_LO_STR%"] = float(params.get("wan_t2v_lora_str_low") or settings.WAN_T2V_LORA_STR_LOW)
        else:
            _strip_lora_node(template, "69")
            _strip_lora_node(template, "70")
        if lightning:
            mapping["%LIGHT_HI_LORA%"] = settings.WAN_T2V_LIGHTNING_LORA_HIGH
            mapping["%LIGHT_LO_LORA%"] = settings.WAN_T2V_LIGHTNING_LORA_LOW
            mapping["%LIGHT_HI_STR%"] = 1.0   # t2v 蒸馏档基准 1.0(别照搬 i2v 的 1.5)
            mapping["%LIGHT_LO_STR%"] = 1.0
        graph = ch.fill_template(template, mapping)
        t0 = time.time()
        client_id = f"mirage-t2v-{os.getpid()}-{int(t0)}"
        with httpx.Client() as client:
            prompt_id = ch.submit(client, base, graph, client_id)
            log_bus.emit("[文生视频] 已提交 t2v 渲染，等待出片…")
            outputs = ch.wait(client, base, prompt_id, label="文生视频")
            items = ch.collect_outputs(outputs)
            if not items:
                raise GpuRunError("T2V 完成但没找到产物文件")
            pick = next((c for c in items
                         if str(c.get("filename", "")).lower().endswith(ch.VIDEO_EXTS)), items[-1])
            ch.download_view(client, base, pick, out_remote)
        logger.info("[文生视频] t2v 出片完成 %.0fs → %s", time.time() - t0, out_remote)
