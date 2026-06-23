"""
re-export shim —— 实体已迁到 comfy_core/log_bus.py（解耦核心，单一真源）。

历史导入路径 `mirage.app.pipeline.log_bus`（含 `import log_bus`、
`from ...log_bus import set_sink, reset_sink` 等）保持不变，透明转发到 comfy_core.log_bus。
新代码请直接 `from comfy_core import log_bus`。
"""
from comfy_core import log_bus as _impl
from comfy_core.log_bus import *  # noqa: F401,F403

# 把实体模块全部公开属性（set_sink/reset_sink/emit 及内部 _sink 之外的公开名）并入本命名空间。
globals().update({k: getattr(_impl, k) for k in dir(_impl) if not k.startswith("_")})
