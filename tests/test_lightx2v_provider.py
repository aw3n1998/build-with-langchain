# -*- coding: utf-8 -*-
"""lightx2v t2v Provider 单测：mock httpx,锁死请求契约对齐 ModelTC/LightX2V 锁定版 schema.py。

防回归:provider 曾发一堆 server 不认的字段(target_shape/num_frames/video_length/fps/model_path),
被静默丢弃 → 出片基础不稳。本测把 payload 钉死在真实 TaskRequest 字段上,字段名再漂就红。
运行:python tests/test_lightx2v_provider.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Resp:
    def __init__(self, *, status=200, payload=None, content=b""):
        self.status_code = status; self._payload = payload; self.content = content
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self): return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    calls = []
    payload = None

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def post(self, url, json=None, timeout=None):
        FakeClient.calls.append(("POST", url))
        FakeClient.payload = json
        return _Resp(payload={"task_id": "TID"})

    def get(self, url, timeout=None):
        FakeClient.calls.append(("GET", url))
        if url.endswith("/status"):
            return _Resp(payload={"status": "completed"})   # 真实终态值=completed(TaskStatus)
        if url.endswith("/result"):
            return _Resp(content=b"LIGHTX2V-MP4")           # 官方流式取片端点
        return _Resp(status=404, payload={})


def main() -> int:
    import mirage.app.pipeline.providers.lightx2v as lx_mod
    from mirage.app.core.config import settings

    settings.LIGHTX2V_BASE_URL = "http://fake:8189"
    lx_mod.httpx.Client = FakeClient
    FakeClient.calls = []; FakeClient.payload = None

    prov = lx_mod.Lightx2vT2VProvider()
    assert prov.transport == "http" and prov.hidden is True and prov.name == "lightx2v-t2v"

    tmp = tempfile.mkdtemp(prefix="lx_")
    out = os.path.join(tmp, "clip.mp4")
    prov.generate(None, image_path="", prompt="a girl walking in neon city, cinematic",
                  out_remote=out, params={"size": "480*832", "frames": 144, "steps": 8, "fps": 16, "seed": 7})

    p = FakeClient.payload
    # 1) 字段名对齐真实 TaskRequest —— 该有的有
    for k in ("prompt", "negative_prompt", "image_path", "target_video_length",
              "target_fps", "aspect_ratio", "infer_steps", "seed"):
        assert k in p, f"payload 缺真实字段 {k}: {list(p.keys())}"
    # 2) server 不认的字段一个都别发(发了被静默丢→出片不稳的老坑)
    for k in ("target_shape", "num_frames", "video_length", "fps", "model_path"):
        assert k not in p, f"payload 仍带 server 不认的字段 {k}"
    # 3) 值正确:144→对齐 4n+1=145;竖屏→9:16;steps 透传
    assert p["target_video_length"] == 145, f"144 应对齐到 145,实际 {p['target_video_length']}"
    assert p["aspect_ratio"] == "9:16", f"480*832 竖屏应 9:16,实际 {p['aspect_ratio']}"
    assert p["infer_steps"] == 8 and p["target_fps"] == 16
    # 4) 提交走 video 子路由,取片走官方 /result 端点
    assert ("POST", "http://fake:8189/v1/tasks/video/") in FakeClient.calls, "未走 /v1/tasks/video/"
    assert any(u.endswith("/v1/tasks/TID/result") for (_, u) in FakeClient.calls), "未用 /result 流式取片"
    assert open(out, "rb").read() == b"LIGHTX2V-MP4", "产物未取回"
    print("[lightx2v] 契约对齐 + 帧对齐 + 宽高比 + /result 取片 OK")

    print("\n=== lightx2v t2v Provider 单测通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
