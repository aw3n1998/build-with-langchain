"""lightx2v 图生视频(i2v) Provider —— 用于「尾帧续接」：镜 N 用 镜 N-1 的尾帧当首帧续生成。

为什么要它：纯 t2v 每镜独立、无记忆，跨镜只有脸(LoRA)能锁,服装/场景/光线锁不住(详见 memory svi-long-video /
char-consistency-options)。要真·续接(镜 N 接 镜 N-1 的画面),唯一办法是 i2v 把上一镜尾帧当首帧续生成 →
服装/场景/光线/动作全部接续。本 provider 把首帧(本机 PNG 绝对路径)填进 lightx2v i2v 的 image_path 字段。

轮流跑(单卡 96G 装不下 t2v+i2v 两 server 同时):i2v server 与 t2v server 用不同端口、但同一时刻只起一个
(Colab §i2v续接 格起 i2v 前先杀 t2v 腾显存)。i2v 底模放 Drive(本地盘塞不下两套底模)。

API(2026-06-19 核查 ModelTC/LightX2V 源码确认):
  - 起服务: python -m lightx2v.server --model_cls wan2.2_moe --task i2v --config_json configs/wan22/wan_moe_i2v.json
  - 建任务: POST /v1/tasks/(兼容) ,首帧字段名 = image_path(收本机绝对路径/URL/base64);取片同 t2v。
  - i2v 默认 40 步 + CFG(慢);4 步蒸馏只有 nvfp4 版,这里走默认 bf16(可挂角色 LoRA 保脸)。
"""

from __future__ import annotations

import os
import time

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline import log_bus
from mirage.app.pipeline.gpu_client import GpuConfigError, GpuRunError, parse_size  # noqa: F401
from mirage.app.pipeline.providers.base import VideoProvider
# 复用 t2v provider 已写好的取片/帧对齐/状态判定(避免重复)
from mirage.app.pipeline.providers.lightx2v import _align_4np1, _extract_output, _TERMINAL_OK, _TERMINAL_BAD

logger = get_logger("pipeline.providers.lightx2v_i2v")


def _base() -> str:
    b = (settings.LIGHTX2V_I2V_BASE_URL or "").rstrip("/")
    if not b:
        raise GpuConfigError(
            "未配置 lightx2v i2v 端点：请在 Colab 跑「§i2v续接」格起 i2v server，它会把 LIGHTX2V_I2V_BASE_URL 写进 .env(默认 http://127.0.0.1:8190)。")
    return b


class Lightx2vI2VProvider(VideoProvider):
    name = "lightx2v-i2v"
    display_name = "图生视频·续接(lightx2v i2v)"
    capabilities = {"i2v"}
    transport = "http"
    hidden = True   # 不进用户下拉;由「续接出片」按需路由

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
            {"key": "steps", "label": "采样步数(i2v 默认 40,慢)", "type": "number", "default": settings.LIGHTX2V_I2V_STEPS, "advanced": True},
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.COMFYUI_FPS, "advanced": True},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1, "advanced": True},
        ]

    def generate(self, gpu, *, image_path: str, prompt: str, out_remote: str, params: dict) -> None:
        """image_path = 首帧(上一镜尾帧)本机绝对路径,必填;POST i2v 建任务 → 轮询 → 取回成片到 out_remote。"""
        params = params or {}
        ip = (image_path or "").strip()
        if not ip or not os.path.exists(ip):
            raise GpuConfigError(f"i2v 续接需要首帧(上一镜尾帧),但没拿到有效图: {ip or '(空)'}")
        base = _base()
        width, height = parse_size(params.get("size"), settings.COMFYUI_SIZE)
        seed = int(params.get("seed", -1))
        if seed < 0:
            seed = int(time.time_ns() % 2_000_000_000)
        num_frames = _align_4np1(int(params.get("frames") or settings.COMFYUI_FRAMES))
        fps = int(params.get("fps") or settings.COMFYUI_FPS)
        steps = int(params.get("steps") or settings.LIGHTX2V_I2V_STEPS)
        payload = {
            "prompt": prompt or "",
            "negative_prompt": str(params.get("negative") or settings.WAN_VIDEO_NEGATIVE),
            "image_path": ip,                              # ★首帧(本机绝对路径)——i2v 核查确认字段名
            "target_shape": [int(height), int(width)],
            "num_frames": num_frames,
            "target_video_length": num_frames,
            "video_length": num_frames,
            "fps": fps,
            "infer_steps": steps,
            "seed": seed,
        }
        if settings.LIGHTX2V_MODEL_I2V:
            payload["model_path"] = settings.LIGHTX2V_MODEL_I2V
        t0 = time.time()
        logger.info("[lightx2v-i2v] 续接: 首帧=%s steps=%d frames=%d size=%dx%d", os.path.basename(ip), steps, num_frames, width, height)
        log_bus.emit(f"[i2v续接] 从上一镜尾帧续生成…(i2v {steps} 步,较慢)")
        try:
            with httpx.Client() as client:
                r = client.post(f"{base}/v1/tasks/", json=payload, timeout=120)
                if r.status_code >= 400:
                    raise GpuRunError(f"lightx2v i2v 拒绝任务(HTTP {r.status_code}): {r.text[:600]}")
                task_id = (r.json() or {}).get("task_id") or (r.json() or {}).get("id")
                if not task_id:
                    raise GpuRunError(f"lightx2v i2v 未返回 task_id: {r.text[:400]}")
                deadline = time.time() + max(120, int(settings.COMFYUI_TIMEOUT))
                last_beat = 0.0
                while time.time() < deadline:
                    s = client.get(f"{base}/v1/tasks/{task_id}/status", timeout=30)
                    status = s.json() if s.status_code < 400 else {}
                    st = str(status.get("status") or status.get("state") or "").lower()
                    if st in _TERMINAL_OK:
                        _extract_output(client, base, task_id, status, out_remote)
                        logger.info("[lightx2v-i2v] 续接出片完成 %.0fs → %s", time.time() - t0, out_remote)
                        return
                    if st in _TERMINAL_BAD:
                        raise GpuRunError(f"lightx2v i2v 任务失败: {str(status)[:600]}")
                    now = time.time()
                    if now - last_beat >= 3:
                        last_beat = now
                        log_bus.emit(f"[i2v续接] {st or '运行中'}… 已等 {int(now - t0)}s")
                    time.sleep(2)
                raise GpuRunError(f"lightx2v i2v 超时(>{settings.COMFYUI_TIMEOUT}s),task={task_id}")
        except httpx.HTTPError as e:
            raise GpuRunError(f"lightx2v i2v HTTP 异常: {type(e).__name__}: {e}") from e
