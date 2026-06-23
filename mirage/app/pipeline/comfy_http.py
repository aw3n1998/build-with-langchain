"""
re-export shim —— 实体已迁到 comfy_core/comfy_http.py（解耦核心，单一真源）。

历史导入路径 `mirage.app.pipeline.comfy_http`（含 `import comfy_http as ch`、
`from ...comfy_http import interrupt` 等约 ~78 处后端调用点 + image_providers）保持不变，
全部透明转发到 comfy_core.comfy_http。新代码请直接 `from comfy_core import comfy_http`。
"""
from comfy_core import comfy_http as _impl
from comfy_core.comfy_http import *  # noqa: F401,F403  （拉入全部 __all__/公开名）

# `import *` 默认跳过下划线开头名、且无 __all__ 时只取公开名；为保证后端用到的所有
# 模块级名字（函数/常量，如 base_url/interrupt/upload_image/submit/wait/collect_outputs/
# download_view/load_workflow/fill_template/WORKFLOWS_DIR/VIDEO_EXTS/... 乃至 logger）都能
# 经本 shim 解析，这里把实体模块的全部公开属性整体并入本模块命名空间。
globals().update({k: getattr(_impl, k) for k in dir(_impl) if not k.startswith("_")})
