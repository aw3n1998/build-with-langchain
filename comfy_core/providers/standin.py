"""Stand-In 强锁脸文生视频 Provider —— 给一张参考脸，跨镜锁定同一身份（免训练）。

为什么要它（见 memory char-consistency-options）：
  Wan-T2V 角色 LoRA 是「软一致」(记气质/身材，运镜/转头时脸会朝通用脸漂)；Stand-In(WeChatCV/Stand-In)
  是「硬锁脸」——把一张参考脸作为**全程显式条件**注入 t2v 生成内部(153M 身份分支),跨镜稳定性更强,且免训练。

架构(贴合「架构可改、目标优先、别锁单一技术」的方针):
  Stand-In 不走 lightx2v——它自带 DiffSynth 引擎、纯 CLI、依赖版本与 lightx2v 冲突。所以在 Colab 上**另起**
  一个 Stand-In 包装 server(mirage/colab/standin_server.py,load-once 常驻,端口 8190,复用你已下的 Wan2.2
  权重 /content/wan_local 当 base_path,不重下底模)。本 provider 只负责 POST 一张参考脸+提示词 → 拿回成片。

设计(照 lightx2v provider 旁路):
  - 隐藏 provider(hidden=True),capability=t2v,transport=http。
  - 由 _do_render_t2v 在「params.lock_face=True 且该镜角色有参考脸(characters.ref_image_path)」时路由到它;
    否则仍走 lightx2v(快)。参考脸经 base 签名的 image_path 传入(i2v 用首帧、t2v 一般忽略,这里复用它当参考脸)。
  - Stand-In 默认 20 步无蒸馏(慢但细),不挂角色 LoRA(身份来自参考脸)。门控:STANDIN_ENABLED + STANDIN_BASE_URL。
"""

from __future__ import annotations

import os
import time

import httpx

from comfy_core.config import settings
from comfy_core.logger import get_logger
from comfy_core import log_bus
from comfy_core.gpu_client import GpuConfigError, GpuRunError, parse_size  # noqa: F401
from comfy_core.providers.base import VideoProvider

logger = get_logger("pipeline.providers.standin")


def _align_4np1(n: int) -> int:
    """帧数对齐到 Wan 要求的 4n+1（同 lightx2v；不对齐 DiffSynth 多半报错或回退）。"""
    n = max(5, int(n))
    return ((n - 1 + 2) // 4) * 4 + 1


def _base() -> str:
    b = (settings.STANDIN_BASE_URL or "").rstrip("/")
    if not b:
        raise GpuConfigError(
            "未配置 Stand-In 端点：请在 Colab 跑「§Stand-In」格起 server，它会把 STANDIN_BASE_URL 写进 .env(默认 http://127.0.0.1:8190)。")
    return b


class StandInT2VProvider(VideoProvider):
    name = "standin-t2v"
    display_name = "文生视频·强锁脸(Stand-In)"
    capabilities = {"t2v"}
    transport = "http"
    hidden = True   # 不进用户下拉;由「出片模式=t2v + 强锁脸开关 + 该角色有参考脸」路由

    def param_schema(self) -> list[dict]:
        return [
            {"key": "size", "label": "分辨率(宽*高)", "type": "select", "default": settings.COMFYUI_SIZE,
             "options": [
                 {"value": "480*832", "label": "480×832 竖屏"},
                 {"value": "720*1280", "label": "720×1280 竖屏高清"},
                 {"value": "832*480", "label": "832×480 横屏"},
             ]},
            {"key": "negative", "label": "负向词(留空=Wan 官方负向)", "type": "text", "default": "", "advanced": True},
            {"key": "frames", "label": "帧数(4n+1)", "type": "number", "default": settings.COMFYUI_FRAMES, "advanced": True},
            {"key": "steps", "label": "采样步数(锁脸无蒸馏,20 步起细)", "type": "number", "default": settings.STANDIN_STEPS, "advanced": True},
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.COMFYUI_FPS, "advanced": True},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1, "advanced": True},
        ]

    def generate(self, gpu, *, image_path: str, prompt: str, out_remote: str, params: dict) -> None:
        """image_path = 参考脸路径(必填,Stand-In 靠它锁脸);POST 包装 server 阻塞出片,成片直接写到 out_remote(同机共享盘)。"""
        params = params or {}
        ip = (image_path or "").strip()
        if not ip or not os.path.exists(ip):
            raise GpuConfigError(
                "Stand-In 强锁脸需要该角色的参考脸：请先在「角色 & LoRA」给这个角色上传一张清晰正脸(写入 characters.ref_image_path)。")
        base = _base()
        width, height = parse_size(params.get("size"), settings.COMFYUI_SIZE)
        seed = int(params.get("seed", -1))
        if seed < 0:
            seed = int(time.time_ns() % 2_000_000_000)
        num_frames = _align_4np1(int(params.get("frames") or settings.COMFYUI_FRAMES))
        fps = int(params.get("fps") or settings.COMFYUI_FPS)
        steps = int(params.get("steps") or settings.STANDIN_STEPS)
        payload = {
            "prompt": prompt or "",
            "negative_prompt": str(params.get("negative") or settings.WAN_VIDEO_NEGATIVE),
            "ip_image": ip,                       # 参考脸(同机本地路径;包装 server 直接读)
            "seed": seed,
            "num_inference_steps": steps,
            "num_frames": num_frames,
            "width": int(width),
            "height": int(height),
            "fps": fps,
            "quality": 9,
            "output": out_remote,                 # ★同机共享盘:server 直接 save_video 到这里,省一次拷贝
        }
        t0 = time.time()
        logger.info("[standin] 锁脸 t2v: steps=%d frames=%d size=%dx%d ref=%s", steps, num_frames, width, height, os.path.basename(ip))
        log_bus.emit(f"[Stand-In] 强锁脸出片中…(无蒸馏 {steps} 步,较慢,锁脸更稳)")
        try:
            with httpx.Client() as client:
                r = client.post(f"{base}/v1/standin", json=payload, timeout=max(300, int(settings.COMFYUI_TIMEOUT)))
                if r.status_code >= 400:
                    raise GpuRunError(f"Stand-In server 拒绝任务(HTTP {r.status_code}): {r.text[:600]}")
                data = r.json() or {}
                st = str(data.get("status") or "").lower()
                if st and st not in ("ok", "succeed", "success", "succeeded", "completed", "done"):
                    raise GpuRunError(f"Stand-In 出片失败: {str(data)[:600]}")
                out = (data.get("output_path") or out_remote)
                if out != out_remote and os.path.exists(out):
                    import shutil
                    shutil.copy(out, out_remote)
                if not os.path.exists(out_remote):
                    raise GpuRunError(f"Stand-In 报成功但没拿到成片(out={out_remote}); server 返回 {str(data)[:300]}")
        except httpx.HTTPError as e:   # 超时/连接错 → 转 GpuRunError(走重试 + FAILED 写回,别静默卡 PENDING)
            raise GpuRunError(f"Stand-In HTTP 异常: {type(e).__name__}: {e}") from e
        logger.info("[standin] 锁脸 t2v 出片完成 %.0fs → %s", time.time() - t0, out_remote)
