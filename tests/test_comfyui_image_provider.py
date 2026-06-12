# -*- coding: utf-8 -*-
"""
Part D 单测：ComfyUIImageProvider 用 mock httpx 跑通 N 张循环出图。

断言：每张一次 /prompt 提交 + 一次 /view 下载；seed 逐张递增；workflow 占位符正确替换
（数字保持 int）；产物落到本地 out_dir；未配端点抛 GpuConfigError。真机联调待 COMFYUI_BASE_URL。

运行：python tests/test_comfyui_image_provider.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Resp:
    def __init__(self, *, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    calls = []
    graphs = []
    n_submit = 0

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, files=None, data=None, json=None, timeout=None):
        FakeClient.calls.append(("POST", url))
        if url.endswith("/prompt"):
            FakeClient.n_submit += 1
            FakeClient.graphs.append(json["prompt"])
            return _Resp(payload={"prompt_id": f"PID{FakeClient.n_submit}", "node_errors": {}})
        return _Resp(status=404, payload={})

    def get(self, url, params=None, timeout=None):
        FakeClient.calls.append(("GET", url))
        if "/history/" in url:
            pid = url.rsplit("/", 1)[1]
            return _Resp(payload={pid: {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"9": {"images": [
                    {"filename": f"agentlab_t2i_{pid}.png", "subfolder": "", "type": "output"}]}},
            }})
        if "/view" in url:
            return _Resp(content=b"PNGDATA")
        if "/queue" in url:
            return _Resp(payload={"queue_running": [], "queue_pending": []})
        return _Resp(status=404, payload={})


def main() -> int:
    import agent_lab.app.pipeline.image_providers.comfyui_image as cu_img
    from agent_lab.app.core.config import settings

    settings.COMFYUI_BASE_URL = "http://fake-comfyui:8188"
    cu_img.httpx.Client = FakeClient
    FakeClient.calls = []
    FakeClient.graphs = []
    FakeClient.n_submit = 0

    prov = cu_img.ComfyUIImageProvider()
    assert prov.transport == "http" and prov.name == "comfyui-img"

    tmp = tempfile.mkdtemp(prefix="comfy_img_")
    paths = prov.generate(None, prompt="a girl, cinematic light", out_dir=tmp,
                          params={"n": 3, "size": "768*1024", "steps": 28,
                                  "seed": 1000, "negative": "blurry, text"})

    # 1) N=3：3 次提交、3 张本地产物
    assert len(paths) == 3, f"应出 3 张，实际 {len(paths)}"
    assert FakeClient.n_submit == 3, f"应提交 3 次，实际 {FakeClient.n_submit}"
    n_view = sum(1 for (_, u) in FakeClient.calls if "/view" in u)
    assert n_view == 3, f"应下载 3 次，实际 {n_view}"
    for p in paths:
        assert os.path.exists(p) and open(p, "rb").read() == b"PNGDATA", f"产物未落地: {p}"
    print("[comfy-img] N=3 循环出图 + 本地落地 OK ->", [os.path.basename(p) for p in paths])

    # 2) seed 逐张递增 1000/1001/1002，且占位符替换正确（数字保持 int）
    seeds = [g["3"]["inputs"]["seed"] for g in FakeClient.graphs]
    assert seeds == [1000, 1001, 1002], f"seed 应逐张 +1，实际 {seeds}"
    g0 = FakeClient.graphs[0]
    assert g0["6"]["inputs"]["text"] == "a girl, cinematic light", "正向提示词未替换"
    assert g0["7"]["inputs"]["text"] == "blurry, text", "负向提示词未替换"
    assert g0["5"]["inputs"]["width"] == 768 and isinstance(g0["5"]["inputs"]["width"], int), "宽未替换为 int"
    assert g0["5"]["inputs"]["height"] == 1024, "高未替换"
    assert g0["3"]["inputs"]["steps"] == 28 and isinstance(g0["3"]["inputs"]["steps"], int), "步数未替换为 int"
    assert "%" not in json.dumps(g0), f"workflow 仍有未替换占位符: {json.dumps(g0)[:300]}"
    print("[comfy-img] seed 递增 + 占位符替换 OK ->", seeds)

    # 3) 未配端点 → GpuConfigError
    settings.COMFYUI_BASE_URL = ""
    try:
        prov.generate(None, prompt="x", out_dir=tmp, params={"n": 1})
        print("[comfy-img] 期望抛 GpuConfigError 但没抛"); return 1
    except cu_img.GpuConfigError:
        print("[comfy-img] 未配端点正确报错 OK")

    print("\n=== ComfyUIImageProvider(Part D) 单测通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
