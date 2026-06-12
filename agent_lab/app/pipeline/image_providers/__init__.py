"""
出图模型 Provider 包。导入即把内置出图模型注册到 image_provider_registry。

新增一个出图模型 = 在本包加一个 provider 文件 + 在这里 register 一行，
工具层 / 路由 / 前端参数卡都不用改（参数卡由 provider.param_schema() 驱动）。
"""

from agent_lab.app.core.config import settings
from agent_lab.app.pipeline.image_providers.base import (
    ImageProvider,
    image_provider_registry,
)
from agent_lab.app.pipeline.image_providers.flux_ssh import FluxSshImageProvider

# 注册内置出图模型。默认由 .env 的 IMAGE_PROVIDER_DEFAULT 决定（缺省 flux）。
image_provider_registry.register(FluxSshImageProvider())
# ComfyUI 文生图：对用户完全隐形。不新增条目，而是**顶替** COMFYUI_IMAGE_AS 指定的公开模型名
# （默认空=出图仍走 FLUX-SSH；设 "flux" 才让出图透明走 ComfyUI）。用户看不到「ComfyUI」字样。
if settings.COMFYUI_BASE_URL and settings.COMFYUI_IMAGE_AS:
    _ias = settings.COMFYUI_IMAGE_AS
    if _ias == "auto":   # 跟随默认出图模型
        _ias = settings.IMAGE_PROVIDER_DEFAULT or image_provider_registry.default_name
    if _ias:
        _idisp = image_provider_registry.get(_ias).display_name if image_provider_registry.has(_ias) else _ias
        from agent_lab.app.pipeline.image_providers.comfyui_image import ComfyUIImageProvider
        image_provider_registry.register(ComfyUIImageProvider(name=_ias, display_name=_idisp))  # 同名覆盖 SSH 版
if settings.IMAGE_PROVIDER_DEFAULT and image_provider_registry.has(settings.IMAGE_PROVIDER_DEFAULT):
    image_provider_registry.set_default(settings.IMAGE_PROVIDER_DEFAULT)

__all__ = ["ImageProvider", "image_provider_registry"]
