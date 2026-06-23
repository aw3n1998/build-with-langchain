"""
re-export shim —— 视频 Provider 实体已整包迁到 comfy_core/providers/（解耦核心，单一真源）。

注册逻辑现位于 comfy_core/providers/__init__.py：导入 `comfy_core.providers` 即触发用
`comfy_core.config.settings` 的内置 provider 注册（Wan2.2 / LTX / ComfyUI 透明顶替 / LTX2 /
Sulphur2 / S2V / T2V / Stand-In，全部门控不变）。本 shim 只做两件事：

1. 触发并复用 comfy_core 的注册表（导入它即注册）；把 `video_provider_registry` 与
   `VideoProvider` 以历史路径 `mirage.app.pipeline.providers` 暴露给后端（~78 处调用点不改）。
2. 把每个 provider 子模块别名进 sys.modules，使后端历史的**直接子模块导入**
   （如 `from mirage.app.pipeline.providers.comfyui_t2v import ComfyUIT2VProvider`、
   `...providers.base import VideoProvider`、`.comfyui/.comfyui_ltx/.comfyui_s2v/.sulphur2/
   .standin/.wan22/.ltx`）透明解析到 comfy_core 下的同名实体（同一对象、同一注册表）。

新代码请直接 `from comfy_core.providers import video_provider_registry`。
"""
import sys

# 导入即注册（comfy_core/providers/__init__.py 用 comfy_core.config.settings 完成全部注册）。
from comfy_core.providers import VideoProvider, video_provider_registry  # noqa: F401

# 把 comfy_core 下的 provider 子模块以历史 mirage 路径别名进 sys.modules，
# 让 `from mirage.app.pipeline.providers.<sub> import ...` 解析到同一实体模块对象。
# 显式枚举内置子模块（与 comfy_core/providers/ 下文件一一对应），避免误吸 __init__ 自身。
for _sub in (
    "base",
    "wan22",
    "ltx",
    "comfyui",
    "comfyui_ltx",
    "comfyui_s2v",
    "comfyui_t2v",
    "sulphur2",
    "standin",
):
    try:
        _mod = __import__(f"comfy_core.providers.{_sub}", fromlist=["_"])
    except ImportError:
        # 某 provider 可选依赖缺失时跳过（与历史「按需 import 才报错」行为一致，不影响其余）。
        continue
    sys.modules[f"{__name__}.{_sub}"] = _mod
    # 同时把子模块挂为本包属性，支持 `import mirage.app.pipeline.providers.<sub>` 后的属性访问。
    setattr(sys.modules[__name__], _sub, _mod)

del sys, _sub
try:
    del _mod
except NameError:
    pass

__all__ = ["VideoProvider", "video_provider_registry"]
