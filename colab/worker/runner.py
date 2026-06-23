"""出片执行层：纯计算。复用后端【同一个】t2v provider 跑本机 ComfyUI 出片。无 claim/上传/完成 逻辑。"""
from __future__ import annotations

import os
import sys


def render_t2v(cfg, task: dict, on_progress) -> str:
    """payload 自包含 {prompt, params, image_path, provider}——按 provider 名跑对应的视频模型（零分叉、不写死 Wan）。
    provider 读 settings.COMFYUI_BASE_URL=本机 ComfyUI(worker env 设)；out_remote=本地临时 mp4，返回其路径。"""
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())   # 让 import mirage.* 走仓库根

    payload = task.get("payload") or {}
    pname = (payload.get("provider") or "comfyui-t2v")
    # 用注册表按名取 provider（import 这个包即注册所有内置 provider）；取不到回退 comfyui-t2v；
    # 注册表彻底没有(异常)再兜底直接 import ComfyUIT2VProvider，保证老任务一定能跑。
    try:
        from comfy_core.providers import video_provider_registry as R  # noqa: E402
        has = R.has(pname)
    except Exception:  # noqa: BLE001  注册表整体导入异常(极少)
        R, has = None, False
    if R is not None and has:
        prov = R.get(pname)
    elif R is not None:
        # ★注册表正常但本 worker 没注册「pname」(没装/没在本机 .env 开它，如 SULPHUR2_ENABLED)：
        #   绝不用默认 provider 替跑——那会出【错模型】的片。抛错让任务回队、重派给真能跑它的 worker。
        raise RuntimeError(
            f"本 worker 未注册视频 provider「{pname}」——拒绝用默认模型替跑(免出错模型)。"
            f"请在本机 .env 启用它(如 SULPHUR2_ENABLED+端点)，或别让本机领「{pname}」任务"
            f"(WORKER_MODELS 显式声明本机真能跑的模型、别留空通配)。")
    else:
        # 注册表整体异常才兜底直跑 comfyui-t2v，保证老任务不全挂。
        from comfy_core.providers.comfyui_t2v import ComfyUIT2VProvider  # noqa: E402
        prov = ComfyUIT2VProvider()

    out = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"{task['id']}.mp4")
    on_progress(f"{pname} 出片中…")
    prov.generate(None, image_path=payload.get("image_path", ""),
                  prompt=payload.get("prompt", ""), out_remote=out,
                  params=payload.get("params") or {})
    if not (os.path.exists(out) and os.path.getsize(out) > 0):
        raise RuntimeError(f"{pname} 没产出视频")
    return out


# 任务类型 → 执行函数。新类型(i2v/续接/upscale)在这里加一个 handler 即可。
HANDLERS = {"render_t2v": render_t2v}
