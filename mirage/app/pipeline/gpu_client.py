"""
re-export shim —— 实体已迁到 comfy_core/gpu_client.py（解耦核心，单一真源）。

历史导入路径 `mirage.app.pipeline.gpu_client`（后端 + image_providers 用到
GpuClient / GpuConfigError / GpuRunError / get_gpu_client / parse_size / coerce_num /
RemoteResult 等）保持不变，全部透明转发到 comfy_core.gpu_client。
新代码请直接 `from comfy_core.gpu_client import ...`。
"""
from comfy_core import gpu_client as _impl
from comfy_core.gpu_client import *  # noqa: F401,F403

# 同 comfy_http shim：把实体模块全部公开属性并入，确保 `from ...gpu_client import X`
# 对任意公开名（含 import * 可能漏掉的 RemoteResult/常量/单例 helper 等）都解析得到。
globals().update({k: getattr(_impl, k) for k in dir(_impl) if not k.startswith("_")})
