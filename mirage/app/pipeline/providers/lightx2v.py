"""lightx2v 文生视频 Provider —— 不走 ComfyUI，直接调 lightx2v(ModelTC/LightX2V)推理引擎。

lightx2v 是你那套 4 步蒸馏 LoRA 的娘家,专做 Wan 快速推理(t2v/i2v;★不支持 s2v/音频驱动对口型),自带 FastAPI HTTP server。
本 provider 把 Mirage 的 t2v 出片指向 lightx2v server(POST 建任务 → 轮询 → 取回成片),
**纯 t2v 工作流可彻底不用 ComfyUI**(t2v 不出图/不选图/不锁脸,ComfyUI 那套本就用不到)。

设计(照 comfyui_t2v 的旁路):隐藏 provider + capability=t2v + transport=http,由「出片模式=t2v」+
settings.T2V_PROVIDER='lightx2v-t2v' 路由。角色 LoRA + 蒸馏 LoRA 走 lightx2v 的 lora_configs。

★脚手架/待真机核对(同 s2v/ltx 脚手架惯例):lightx2v 的 HTTP API 字段(target_shape/帧数键、
产物返回方式、MoE 高低噪 LoRA 的具体配法)以你 Colab 上起的 lightx2v 版本实际为准——首跑前用
仓库自带 scripts/server/post.py 核对一次请求/响应形状,再按需校准下面 _PAYLOAD/_extract_output。
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

logger = get_logger("pipeline.providers.lightx2v")

_TERMINAL_OK = {"succeed", "success", "succeeded", "completed", "done", "finished"}
_TERMINAL_BAD = {"failed", "error", "cancelled", "canceled"}


def _base() -> str:
    b = (settings.LIGHTX2V_BASE_URL or "").rstrip("/")
    if not b:
        raise GpuConfigError("未配置 lightx2v 端点：请在 .env 设 LIGHTX2V_BASE_URL(如 http://127.0.0.1:8189)并先起 lightx2v server。")
    return b


def _lora_configs(params: dict | None = None) -> list[dict]:
    """组装 lightx2v lora_configs:角色 LoRA + 蒸馏 LoRA(★用 lora_configs 时蒸馏 LoRA 必须显式列,否则丢加速)。

    Wan2.2 双专家:`name` 是路由键,**只能是 "high_noise_model"/"low_noise_model"**(精确大小写),
    高/低噪各一条;同 name 多条会**叠加**(蒸馏加速 LoRA + 人物 LoRA 各 4 条)。缺 name 会被 server KeyError。

    ★LoRA 必须挂在「起 server 的 config」里才生效——per-request 传 lora 会被 server 忽略,且改 LoRA 要重启
    server(见部署笔记本 §5「挂 LoRA」)。本函数同时供部署侧据 .env 生成 server config 的 lora_configs。
    """
    params = params or {}
    out: list[dict] = []
    triples = [   # (name 路由键, path, strength)
        ("high_noise_model", params.get("wan_t2v_lora_high") or settings.WAN_T2V_LORA_HIGH, settings.WAN_T2V_LORA_STR_HIGH),
        ("low_noise_model",  params.get("wan_t2v_lora_low") or settings.WAN_T2V_LORA_LOW,  settings.WAN_T2V_LORA_STR_LOW),
        ("high_noise_model", settings.LIGHTX2V_DISTILL_LORA_HIGH, 1.0),
        ("low_noise_model",  settings.LIGHTX2V_DISTILL_LORA_LOW, 1.0),
    ]
    for name, path, strength in triples:
        p = (path or "").strip()
        if p:
            out.append({"name": name, "path": p, "strength": float(strength)})
    return out


def server_lora_configs() -> list[dict]:
    """部署侧(笔记本 §5)据 .env 的 WAN_T2V_LORA_* + LIGHTX2V_DISTILL_LORA_* 生成 server 启动 config 的
    lora_configs(带正确 name)。挂在起 server 的 config json 里 → LoRA 才真正生效(per-request 传会被忽略)。"""
    return _lora_configs({})


def _extract_output(client: httpx.Client, base: str, task_id: str, status: dict, out_remote: str) -> None:
    """把成片取回本地 out_remote。

    ★真机确认(2026-06-18 RTX PRO 6000):lightx2v server 把片存到同机本地
      <install>/lightx2v/server_cache/outputs/{task_id}.mp4(文件名=task_id)。
    优先用 status 里给的路径/URL(部分版本会给);没有就按这个约定 + LIGHTX2V_OUTPUT_DIR + glob 兜底拷回。
    """
    import shutil
    import glob as _glob
    # 1) status 直接给路径/URL(部分版本)
    cand = (status.get("output_path") or status.get("save_path") or status.get("video_path")
            or status.get("save_video_path") or status.get("result") or status.get("output"))
    if isinstance(cand, dict):
        cand = (cand.get("video_path") or cand.get("output_path")
                or cand.get("save_video_path") or cand.get("url"))
    if isinstance(cand, str) and cand:
        if cand.startswith("http"):                       # URL → 下载
            r = client.get(cand, timeout=300); r.raise_for_status()
            with open(out_remote, "wb") as f:
                f.write(r.content)
            return
        if os.path.exists(cand):                          # 同机本地路径 → 拷回工作目录
            shutil.copy(cand, out_remote)
            return
    # 2) 同机本地约定:server_cache/outputs/{task_id}.mp4(真机确认)→ 直接拷
    locals_: list[str] = []
    if (settings.LIGHTX2V_OUTPUT_DIR or "").strip():
        locals_.append(os.path.join(settings.LIGHTX2V_OUTPUT_DIR.strip(), f"{task_id}.mp4"))
    locals_.append(f"/content/LightX2V/lightx2v/server_cache/outputs/{task_id}.mp4")
    locals_ += _glob.glob(f"/content/LightX2V/**/server_cache/outputs/{task_id}.mp4", recursive=True)
    for p in locals_:
        if p and os.path.exists(p):
            shutil.copy(p, out_remote)
            return
    raise GpuRunError(
        f"lightx2v 任务完成但没取到成片(task={task_id})。片应在 <install>/lightx2v/server_cache/outputs/{task_id}.mp4;"
        f"install 路径不同时在 .env 设 LIGHTX2V_OUTPUT_DIR 指向 outputs 目录。status keys={list(status.keys())}")


class Lightx2vT2VProvider(VideoProvider):
    name = "lightx2v-t2v"
    display_name = "文生视频(lightx2v)"
    capabilities = {"t2v"}
    transport = "http"
    hidden = True   # 不进用户下拉;由「出片模式=t2v」+ T2V_PROVIDER 路由

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
            {"key": "steps", "label": "采样步数", "type": "number", "default": settings.WAN_LIGHTNING_STEPS, "advanced": True},
            {"key": "fps", "label": "帧率", "type": "number", "default": settings.COMFYUI_FPS, "advanced": True},
            {"key": "seed", "label": "seed(-1随机)", "type": "number", "default": -1, "advanced": True},
        ]

    def generate(self, gpu, *, image_path: str, prompt: str, out_remote: str, params: dict) -> None:
        """t2v:image_path 忽略(无首帧),POST 建任务 → 轮询 → 取回成片到 out_remote。"""
        params = params or {}
        base = _base()
        width, height = parse_size(params.get("size"), settings.COMFYUI_SIZE)
        seed = int(params.get("seed", -1))
        if seed < 0:
            seed = int(time.time_ns() % 2_000_000_000)
        payload = {
            "prompt": prompt or "",
            "negative_prompt": str(params.get("negative") or settings.WAN_VIDEO_NEGATIVE),
            "image_path": "",                                    # t2v 无首帧
            "target_shape": [int(height), int(width)],           # ★[H,W] 待核对(lightx2v 文档示例如此)
            "num_frames": int(params.get("frames") or settings.COMFYUI_FRAMES),
            "fps": int(params.get("fps") or settings.COMFYUI_FPS),
            "infer_steps": int(params.get("steps") or settings.WAN_LIGHTNING_STEPS),
            "seed": seed,
        }
        if settings.LIGHTX2V_MODEL_T2V:
            payload["model_path"] = settings.LIGHTX2V_MODEL_T2V
        # ★LoRA 的权威挂载点是「起 server 的 config」(见 server_lora_configs() + 笔记本 §5);
        #   per-request 这条多数 server 版本会忽略,这里仍带上(well-formed,带 name)做前向兼容,无害。
        loras = _lora_configs(params)
        if loras:
            payload["lora_configs"] = loras
        t0 = time.time()
        with httpx.Client() as client:
            r = client.post(f"{base}/v1/tasks/", json=payload, timeout=120)
            if r.status_code >= 400:
                raise GpuRunError(f"lightx2v 拒绝任务(HTTP {r.status_code}): {r.text[:600]}")
            task_id = (r.json() or {}).get("task_id") or (r.json() or {}).get("id")
            if not task_id:
                raise GpuRunError(f"lightx2v 未返回 task_id: {r.text[:400]}")
            log_bus.emit("[lightx2v] 已提交 t2v 任务，等待出片…")
            deadline = time.time() + max(120, int(settings.COMFYUI_TIMEOUT))
            last_beat = 0.0
            while time.time() < deadline:
                s = client.get(f"{base}/v1/tasks/{task_id}/status", timeout=30)
                status = s.json() if s.status_code < 400 else {}
                st = str(status.get("status") or status.get("state") or "").lower()
                if st in _TERMINAL_OK:
                    _extract_output(client, base, task_id, status, out_remote)
                    logger.info("[lightx2v] t2v 出片完成 %.0fs → %s", time.time() - t0, out_remote)
                    return
                if st in _TERMINAL_BAD:
                    raise GpuRunError(f"lightx2v 任务失败: {str(status)[:600]}")
                now = time.time()
                if now - last_beat >= 3:
                    last_beat = now
                    log_bus.emit(f"[lightx2v] {st or '运行中'}… 已等 {int(now - t0)}s")
                time.sleep(2)
            raise GpuRunError(f"lightx2v 超时(>{settings.COMFYUI_TIMEOUT}s),task={task_id}")
