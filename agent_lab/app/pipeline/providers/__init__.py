"""
视频模型 Provider 包。导入即把内置模型注册到 video_provider_registry。

新增一个视频模型 = 在本包加一个 provider 文件 + 在这里 register 一行，
工具层 / 路由 / 前端参数卡都不用改（参数卡由 provider.param_schema() 驱动）。
"""

from agent_lab.app.core.config import settings
from agent_lab.app.pipeline.providers.base import (
    VideoProvider,
    video_provider_registry,
)
from agent_lab.app.pipeline.providers.wan22 import Wan22Provider
from agent_lab.app.pipeline.providers.ltx import LtxProvider

# 注册内置模型。默认模型由 .env 的 VIDEO_PROVIDER_DEFAULT 决定（缺省 wan2.2）。
video_provider_registry.register(Wan22Provider())
video_provider_registry.register(LtxProvider())
# ComfyUI 出片后端：对用户完全隐形。不新增「ComfyUI」条目，而是**顶替** COMFYUI_VIDEO_AS 指定的
# 公开模型名（默认 wan2.2）的执行后端——用户选到的还是 Wan2.2，配了端点后它透明地走 ComfyUI。
if settings.COMFYUI_BASE_URL and settings.COMFYUI_VIDEO_AS:
    _as = settings.COMFYUI_VIDEO_AS
    if _as == "auto":   # 跟随默认出片模型（用户用哪个，就透明把哪个换成 ComfyUI 后端）
        _as = settings.VIDEO_PROVIDER_DEFAULT or video_provider_registry.default_name
    if _as:
        _disp = video_provider_registry.get(_as).display_name if video_provider_registry.has(_as) else _as
        from agent_lab.app.pipeline.providers.comfyui import ComfyUIProvider
        video_provider_registry.register(ComfyUIProvider(name=_as, display_name=_disp))  # 同名覆盖 SSH 版
if settings.VIDEO_PROVIDER_DEFAULT and video_provider_registry.has(settings.VIDEO_PROVIDER_DEFAULT):
    video_provider_registry.set_default(settings.VIDEO_PROVIDER_DEFAULT)
# Wan2.2-S2V 对口型：隐藏 Provider，不进用户下拉，由「对口型」开关路由。配了端点才注册。
if settings.COMFYUI_BASE_URL:
    from agent_lab.app.pipeline.providers.comfyui_s2v import ComfyUIS2VProvider
    video_provider_registry.register(ComfyUIS2VProvider())

__all__ = ["VideoProvider", "video_provider_registry"]
