"""
可插拔视觉模型客户端 —— OpenAI 兼容的多模态 /chat/completions。

用途：把一张图（如视频末帧）+ 文本喂给会「看图」的模型，拿回文字（如推荐的续段运镜提示词）。
为什么可插拔：不绑死厂商。配 VISION_BASE_URL/MODEL/API_KEY 即可指向
  - 通义千问 Qwen-VL（DashScope OpenAI 兼容模式）
  - GPT-4o / 任意 OpenAI 兼容多模态服务
  - 本地 LLaVA / vLLM / LM Studio 等
留空则 vision_enabled()=False，调用方自动回退到纯文本推理（看不到图，但据上下文推断）。
"""

from __future__ import annotations

import base64
import os

import httpx

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("services.vision")


def vision_enabled() -> bool:
    """是否配置了可用的视觉模型（决定能不能「真看尾帧」）。"""
    return bool((settings.VISION_BASE_URL or "").strip()
                and (settings.VISION_MODEL or "").strip())


def _data_url(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lstrip(".").lower() or "png"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def suggest_from_image(image_path: str, system: str, user_text: str) -> str | None:
    """把一张图 + 文本喂给视觉模型，返回模型回复文本。

    未启用 / 图不存在 / 调用失败 → 返回 None（调用方据此回退到纯文本）。绝不抛异常打断流程。
    """
    if not vision_enabled() or not os.path.exists(image_path):
        return None
    base = settings.VISION_BASE_URL.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if settings.VISION_API_KEY:
        headers["Authorization"] = f"Bearer {settings.VISION_API_KEY}"
    body = {
        "model": settings.VISION_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": _data_url(image_path)}},
            ]},
        ],
        "max_tokens": 300,
        "temperature": 0.7,
    }
    try:
        r = httpx.post(f"{base}/chat/completions", json=body, headers=headers,
                       timeout=float(settings.VISION_TIMEOUT))
        r.raise_for_status()
        data = r.json()
        content = (data["choices"][0]["message"]["content"] or "").strip()
        return content or None
    except Exception as e:  # noqa: BLE001 - 视觉失败只回退，不打断
        logger.warning("[vision] 调用失败，回退纯文本推荐: %s", e)
        return None
