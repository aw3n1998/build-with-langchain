"""
FLUX 出图 Provider（SSH 传输）—— 包住现有「远程 FLUX 多候选出图」链路。

这是默认出图模型，行为与重构前的 generate_candidates 完全一致：
  调 GpuClient.generate_candidates（跑已验证的 remote_scripts/flux_candidates.py），
  返回服务器上生成图的远程路径，工具层负责逐张下载回工作目录。

flux 专属的 LoRA 由工具层从工作目录配置读出后放进 params["flux_lora"]，
本 Provider 不直接依赖 runtime/model_config，保持纯净（只认 gpu + params + settings）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_lab.app.core.config import settings
from agent_lab.app.pipeline.image_providers.base import ImageProvider

if TYPE_CHECKING:
    from agent_lab.app.pipeline.gpu_client import GpuClient


class FluxSshImageProvider(ImageProvider):
    name = "flux"
    display_name = "FLUX (SSH)"
    capabilities = {"t2i"}
    transport = "ssh"
    prompt_lang = "en"   # FLUX-dev 只懂英文：工具层会把中文 image_prompt 自动翻成英文再下发

    def param_schema(self) -> list[dict]:
        return [
            {"key": "n", "label": "张数", "type": "number", "default": settings.FLUX_N,
             "help": "一次出几张候选图（多种子）。越多挑选余地越大也越慢。"},
            {"key": "steps", "label": "采样步数", "type": "number", "default": settings.FLUX_STEPS,
             "help": "去噪步数。越大越精细越慢。FLUX-dev 常用 28。"},
            {"key": "guidance", "label": "提示词贴合度", "type": "number", "default": settings.FLUX_GUIDANCE,
             "help": "guidance。越大越贴提示词但可能僵硬；FLUX 常用 3.5。"},
            {"key": "width", "label": "宽", "type": "number", "default": settings.FLUX_WIDTH,
             "help": "出图宽度（像素）。竖屏人物常用 768。"},
            {"key": "height", "label": "高", "type": "number", "default": settings.FLUX_HEIGHT,
             "help": "出图高度（像素）。竖屏人物常用 1024。"},
            {"key": "seed", "label": "起始 seed(-1随机)", "type": "number", "default": -1,
             "advanced": True, "help": "随机种子起点。-1 每次不同；固定可复现。"},
            {"key": "offload", "label": "显存策略", "type": "select", "default": settings.FLUX_OFFLOAD,
             "advanced": True, "help": "model=快(压线24G)；sequential=慢但最稳。",
             "options": [
                 {"value": "model", "label": "model（快）"},
                 {"value": "sequential", "label": "sequential（稳）"},
             ]},
        ]

    def generate(self, gpu: "GpuClient", *, prompt: str, out_dir: str, params: dict) -> list[str]:
        """跑远程 FLUX 多候选出图，返回远程路径列表（工具层负责下载）。"""
        guidance = params.get("guidance", -1.0)
        try:
            guidance = float(guidance)
        except (TypeError, ValueError):
            guidance = -1.0
        return gpu.generate_candidates(
            prompt, out_dir,
            n=(params.get("n") or None),
            steps=(params.get("steps") or None),
            guidance=(None if guidance < 0 else guidance),
            width=(params.get("width") or None),
            height=(params.get("height") or None),
            seed=int(params.get("seed", -1)),
            offload=(params.get("offload") or None),
            lora=(params.get("flux_lora") or None),
        )
