"""
NSFW Master FLUX 出图 Provider —— 复用 FLUX-SSH 链路，但把远程脚本的 --base 指向
可配置的无审查底模（settings.GPU_FLUX_NSFW_BASE）。

与默认 FLUX 的唯一区别：底模检查点不同（A100 推荐 lodestones/Chroma；或 FLUX-dev 系
无审查合并以兼容现有人物 LoRA）。不做任何内容过滤；人物 LoRA 照常叠加
（params.flux_lora 优先，未设回退 GPU_FLUX_NSFW_LORA）。

仅当 GPU_FLUX_NSFW_BASE 配置了才在 image_provider_registry 注册（见本包 __init__.py），
没配就不出现在前端「出图模型」下拉，避免用户选了却没底模而报错。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mirage.app.core.config import settings
from mirage.app.pipeline.image_providers.flux_ssh import FluxSshImageProvider

if TYPE_CHECKING:
    from mirage.app.pipeline.gpu_client import GpuClient


class NsfwFluxImageProvider(FluxSshImageProvider):
    name = "nsfw-flux"
    display_name = "NSFW Master FLUX"
    # 元信息 / param_schema（n/steps/guidance/width/height/seed/offload）继承默认 FLUX。

    def generate(self, gpu: "GpuClient", *, prompt: str, out_dir: str, params: dict) -> list[str]:
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
            lora=(params.get("flux_lora") or settings.GPU_FLUX_NSFW_LORA or None),
            base=(settings.GPU_FLUX_NSFW_BASE or None),   # ← 唯一关键：换无审查底模
        )
