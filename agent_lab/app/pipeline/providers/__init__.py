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
if settings.VIDEO_PROVIDER_DEFAULT and video_provider_registry.has(settings.VIDEO_PROVIDER_DEFAULT):
    video_provider_registry.set_default(settings.VIDEO_PROVIDER_DEFAULT)

__all__ = ["VideoProvider", "video_provider_registry"]
