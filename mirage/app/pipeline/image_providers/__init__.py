"""
出图模型 Provider 包。导入即把内置出图模型注册到 image_provider_registry。

新增一个出图模型 = 在本包加一个 provider 文件 + 在这里 register 一行，
工具层 / 路由 / 前端参数卡都不用改（参数卡由 provider.param_schema() 驱动）。
"""

from mirage.app.core.config import settings
from mirage.app.pipeline.image_providers.base import (
    ImageProvider,
    image_provider_registry,
)
from mirage.app.pipeline.image_providers.flux_ssh import FluxSshImageProvider

# 注册内置出图模型。默认由 .env 的 IMAGE_PROVIDER_DEFAULT 决定（缺省 flux）。
# 单一底模即可（含 NSFW）：把 .env 的 GPU_FLUX_BASE 指向你选的检查点（如 lodestones/Chroma）。
image_provider_registry.register(FluxSshImageProvider())
# ComfyUI 文生图：对用户完全隐形。不新增条目，而是**顶替** COMFYUI_IMAGE_AS 指定的公开模型名
# （默认空=出图仍走 FLUX-SSH；设 "flux" 才让出图透明走 ComfyUI）。用户看不到「ComfyUI」字样。
if settings.COMFYUI_BASE_URL and settings.COMFYUI_IMAGE_AS:
    _ias = settings.COMFYUI_IMAGE_AS
    if _ias == "auto":   # 跟随默认出图模型
        _ias = settings.IMAGE_PROVIDER_DEFAULT or image_provider_registry.default_name
    if _ias:
        import os as _os
        # 显示名跟随实际底模（COMFYUI_FLUX_UNET，如 Chroma1-HD），别再写死「FLUX」误导
        _unet = _os.path.splitext(_os.path.basename(settings.COMFYUI_FLUX_UNET or ""))[0]
        _idisp = (f"出图 · {_unet}" if _unet
                  else (image_provider_registry.get(_ias).display_name if image_provider_registry.has(_ias) else _ias))
        from mirage.app.pipeline.image_providers.comfyui_image import ComfyUIImageProvider
        image_provider_registry.register(ComfyUIImageProvider(name=_ias, display_name=_idisp))  # 同名覆盖 SSH 版（ComfyUI/Chroma 出图，参数=n/尺寸/步数/负向/seed，无 FLUX 的 guidance/显存策略）
if settings.IMAGE_PROVIDER_DEFAULT and image_provider_registry.has(settings.IMAGE_PROVIDER_DEFAULT):
    image_provider_registry.set_default(settings.IMAGE_PROVIDER_DEFAULT)

__all__ = ["ImageProvider", "image_provider_registry"]
