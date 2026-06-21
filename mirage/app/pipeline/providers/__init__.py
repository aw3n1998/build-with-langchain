"""
视频模型 Provider 包。导入即把内置模型注册到 video_provider_registry。

新增一个视频模型 = 在本包加一个 provider 文件 + 在这里 register 一行，
工具层 / 路由 / 前端参数卡都不用改（参数卡由 provider.param_schema() 驱动）。
"""

from mirage.app.core.config import settings
from mirage.app.pipeline.providers.base import (
    VideoProvider,
    video_provider_registry,
)
from mirage.app.pipeline.providers.wan22 import Wan22Provider
from mirage.app.pipeline.providers.ltx import LtxProvider

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
        from mirage.app.pipeline.providers.comfyui import ComfyUIProvider
        video_provider_registry.register(ComfyUIProvider(name=_as, display_name=_disp))  # 同名覆盖 SSH 版
# LTX-Video 2.3：ComfyUI HTTP 后端，**独立注册**(不走上面的透明顶替)——和 Wan2.2 并列出现在
# 用户模型下拉里、逐镜可手选。双门控：配了端点 + LTX2_ENABLED 才注册，避免没装/没下 LTX 时
# 下拉里冒出个选了跑不了的项。参数卡由它自己的 param_schema() 驱动(LTX 专属字段，与 Wan 不混)。
if settings.LTX2_ENABLED and (settings.COMFYUI_LTX_BASE_URL or settings.COMFYUI_BASE_URL):
    from mirage.app.pipeline.providers.comfyui_ltx import ComfyUILtxProvider
    video_provider_registry.register(ComfyUILtxProvider())
if settings.VIDEO_PROVIDER_DEFAULT and video_provider_registry.has(settings.VIDEO_PROVIDER_DEFAULT):
    video_provider_registry.set_default(settings.VIDEO_PROVIDER_DEFAULT)
# Wan2.2-S2V 对口型：隐藏 Provider，不进用户下拉，由「对口型」开关路由。配了端点才注册。
if settings.COMFYUI_BASE_URL:
    from mirage.app.pipeline.providers.comfyui_s2v import ComfyUIS2VProvider
    video_provider_registry.register(ComfyUIS2VProvider())
# Wan2.2-T2V 文生视频：隐藏 Provider，不进用户下拉，由「出片模式=t2v」路由。配了端点才注册。
if settings.COMFYUI_BASE_URL:
    from mirage.app.pipeline.providers.comfyui_t2v import ComfyUIT2VProvider
    video_provider_registry.register(ComfyUIT2VProvider())
# Stand-In 强锁脸文生视频后端(WeChatCV/Stand-In,另起包装 server,不走 lightx2v):配了 STANDIN_ENABLED + 端点才注册。
# 隐藏 Provider,由「出片模式=t2v + 强锁脸开关 + 该角色有参考脸」路由(见 pipeline_tools._do_render_t2v)。
if settings.STANDIN_ENABLED and settings.STANDIN_BASE_URL:
    from mirage.app.pipeline.providers.standin import StandInT2VProvider
    video_provider_registry.register(StandInT2VProvider())
__all__ = ["VideoProvider", "video_provider_registry"]
