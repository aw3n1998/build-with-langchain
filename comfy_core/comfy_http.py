"""
ComfyUI HTTP API 共享 helper —— 上传/提交/轮询/下载 + workflow 占位符填充。

出图(t2i)、出片(i2v)、后处理三个 ComfyUI Provider 共用同一套 HTTP 调用，避免三处重复。
这些函数都是无状态的模块级函数：传入一个 httpx.Client + base url 即可。

约定的占位符（各 workflow 模板按需使用）：
  %IMAGE% %PROMPT% %NEG_PROMPT% %WIDTH% %HEIGHT% %FRAMES% %FPS% %STEPS% %SEED% %VIDEO% ...
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from comfy_core.config import settings
from comfy_core.logger import get_logger
from comfy_core import log_bus
from comfy_core.gpu_client import GpuConfigError, GpuRunError

logger = get_logger("pipeline.comfy_http")

# __file__: <repo>/comfy_core/comfy_http.py → 上溯 1 层到 <repo>（comfy_core 在仓库根）。
# 允许 .env 用 COMFYUI_WORKFLOWS_DIR 覆盖（worker 独立部署、仓库布局不同也能指对模板目录）。
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKFLOWS_DIR = os.environ.get("COMFYUI_WORKFLOWS_DIR") or os.path.join(_REPO_ROOT, "comfyui_workflows")

# 产物扩展名（从 history.outputs 里分辨视频/图片）
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".gif", ".webp")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def base_url(override: str = "") -> str:
    """读取并校验 ComfyUI 端点。

    override 非空 → 用它（供 LTX 等走独立实例：如另一端口/另一台的 v0.16+ ComfyUI）；
    否则回落到全局 COMFYUI_BASE_URL（单实例，Wan/LTX 共用）。两者都空抛 GpuConfigError。
    """
    base = (override or settings.COMFYUI_BASE_URL or "").rstrip("/")
    if not base:
        raise GpuConfigError(
            "未配置 ComfyUI 端点，请在 .env 设置 COMFYUI_BASE_URL（如 http://127.0.0.1:8188）。")
    return base


def interrupt(base: str = "") -> bool:
    """中断 ComfyUI 当前正在执行的 prompt + 卸显存。用于任务取消/超时清理——
    只停本地协程不够：ComfyUI 仍在 GPU 上跑那条 prompt（kill_inference 只杀 SSH 脚本，杀不到它）→
    POST /interrupt 停它、/free 卸模型释放 VRAM，防僵尸占卡堆积。端点没配/不可达 → 返回 False，不抛。"""
    try:
        b = (base or settings.COMFYUI_BASE_URL or "").rstrip("/")
        if not b:
            return False
        with httpx.Client(timeout=8) as c:
            c.post(f"{b}/interrupt")
            c.post(f"{b}/free", json={"unload_models": True, "free_memory": True})
        return True
    except Exception:  # noqa: BLE001
        return False


def available_loras(base: str) -> set[str] | None:
    """查 ComfyUI 实际可用的 LoRA 文件名集合（GET /object_info/LoraLoader）。
    取不到/解析失败返回 None —— 让调用方「无法核实就别拦」，避免把存在的 LoRA 误删/误判。"""
    try:
        r = httpx.get(f"{base}/object_info/LoraLoader", timeout=10)
        r.raise_for_status()
        names = r.json()["LoraLoader"]["input"]["required"]["lora_name"][0]
        return {str(n) for n in names} if isinstance(names, (list, tuple)) else None
    except Exception:  # noqa: BLE001
        return None


def load_workflow(path: str, default_name: str, kind: str) -> dict:
    """读 workflow 模板（API 格式 JSON）。path 为空则用仓库自带 comfyui_workflows/<default_name>。"""
    p = path or os.path.join(WORKFLOWS_DIR, default_name)
    if not os.path.exists(p):
        raise GpuConfigError(
            f"找不到 ComfyUI {kind} workflow 模板：{p}。"
            f"请在 .env 指向你导出的 API 格式 workflow（保留约定占位符）。")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def fill_template(obj: Any, mapping: dict) -> Any:
    """递归把 workflow 模板里的占位符替换成真实值。

    - 整个字符串恰为某占位符（如 "%FRAMES%"）→ 替换成对应的**类型化**值（int/str），
      这样数字字段不会被写成字符串导致 ComfyUI 报类型错。
    - 字符串里**含**占位符 → 子串替换（结果仍是字符串，如 filename_prefix）。
    """
    if isinstance(obj, dict):
        return {k: fill_template(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fill_template(v, mapping) for v in obj]
    if isinstance(obj, str):
        if obj in mapping:                       # 整串就是一个占位符 → 类型化值
            return mapping[obj]
        out = obj                                 # 含占位符 → 子串替换为字符串
        for token, val in mapping.items():
            if token in out:
                out = out.replace(token, str(val))
        return out
    return obj


def upload_image(client: httpx.Client, base: str, image_path: str) -> str:
    """把本地参考图传到 ComfyUI 的 input 区，返回 LoadImage 用的图名（含 subfolder）。"""
    if not os.path.exists(image_path):
        raise GpuRunError(f"ComfyUI：本地参考图不存在 {image_path}")
    fname = os.path.basename(image_path)
    with open(image_path, "rb") as f:
        files = {"image": (fname, f, "image/png")}
        data = {"overwrite": "true", "type": "input"}
        r = client.post(f"{base}/upload/image", files=files, data=data, timeout=120)
    r.raise_for_status()
    info = r.json()
    name = info.get("name") or fname
    sub = info.get("subfolder") or ""
    return f"{sub}/{name}" if sub else name


def upload_media(client: httpx.Client, base: str, path: str,
                 content_type: str = "application/octet-stream") -> str:
    """把本地任意媒体（视频/图片）传到 ComfyUI 的 input 区，返回节点用的文件名（含 subfolder）。

    ComfyUI 的 /upload/image 端点对视频同样有效（VHS LoadVideo 从 input 区按文件名读取）。
    """
    if not os.path.exists(path):
        raise GpuRunError(f"ComfyUI：本地文件不存在 {path}")
    fname = os.path.basename(path)
    with open(path, "rb") as f:
        files = {"image": (fname, f, content_type)}
        data = {"overwrite": "true", "type": "input"}
        r = client.post(f"{base}/upload/image", files=files, data=data, timeout=300)
    r.raise_for_status()
    info = r.json()
    name = info.get("name") or fname
    sub = info.get("subfolder") or ""
    return f"{sub}/{name}" if sub else name


def submit(client: httpx.Client, base: str, graph: dict, client_id: str) -> str:
    """提交填好占位符的 workflow，返回 prompt_id。校验失败抛 GpuRunError。"""
    r = client.post(f"{base}/prompt", json={"prompt": graph, "client_id": client_id}, timeout=120)
    if r.status_code >= 400:
        raise GpuRunError(f"ComfyUI 拒绝 workflow (HTTP {r.status_code}): {r.text[:800]}")
    body = r.json()
    if body.get("node_errors"):
        raise GpuRunError(f"ComfyUI workflow 校验失败: {json.dumps(body['node_errors'])[:800]}")
    pid = body.get("prompt_id")
    if not pid:
        raise GpuRunError(f"ComfyUI 未返回 prompt_id: {body}")
    return pid


def wait(client: httpx.Client, base: str, prompt_id: str, *, label: str = "comfyui") -> dict:
    """轮询直到该 prompt 出现在 history（完成）。返回它的 outputs。带心跳日志。"""
    deadline = time.time() + max(60, int(settings.COMFYUI_TIMEOUT))
    t0 = time.time()
    last_beat = 0.0
    while time.time() < deadline:
        h = client.get(f"{base}/history/{prompt_id}", timeout=30)
        if h.status_code < 400:
            data = h.json()
            if prompt_id in data:
                entry = data[prompt_id]
                status = (entry.get("status") or {})
                if status.get("status_str") == "error":
                    raise GpuRunError(f"ComfyUI 执行报错: {json.dumps(status)[:800]}")
                return entry.get("outputs") or {}
        now = time.time()
        if now - last_beat >= 3:                  # 心跳（复用实时日志框）
            last_beat = now
            pos = _queue_hint(client, base, prompt_id)
            log_bus.emit(f"[{label}] {pos} 已等待 {int(now - t0)}s")
        time.sleep(2)
    raise GpuRunError(f"ComfyUI 超时（>{settings.COMFYUI_TIMEOUT}s），prompt_id={prompt_id}")


def _queue_hint(client: httpx.Client, base: str, prompt_id: str) -> str:
    """看队列判断是「排队中」还是「生成中」（取不到就给个中性提示）。"""
    try:
        q = client.get(f"{base}/queue", timeout=10).json()
        for item in (q.get("queue_running") or []):
            if len(item) > 1 and item[1] == prompt_id:
                return "生成中…"
        if any(len(it) > 1 and it[1] == prompt_id for it in (q.get("queue_pending") or [])):
            return "排队中…"
    except Exception:  # noqa: BLE001
        pass
    return "生成中…"


def collect_outputs(outputs: dict) -> list[dict]:
    """从 history.outputs 收集所有产物文件 dict（gifs/videos/images/files）。"""
    items: list[dict] = []
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for key in ("gifs", "videos", "images", "files"):
            for it in (node_out.get(key) or []):
                if isinstance(it, dict) and it.get("filename"):
                    items.append(it)
    return items


def download_view(client: httpx.Client, base: str, item: dict, out_path: str) -> None:
    """GET /view 下载一个产物到本地 out_path。"""
    params = {"filename": item["filename"], "subfolder": item.get("subfolder", ""),
              "type": item.get("type", "output")}
    r = client.get(f"{base}/view", params=params, timeout=300)
    r.raise_for_status()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(r.content)
    if os.path.getsize(out_path) == 0:
        raise GpuRunError(f"ComfyUI 下载文件为 0 字节: {out_path}")
