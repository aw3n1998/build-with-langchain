# -*- coding: utf-8 -*-
"""
Part B 单测：ComfyUIProvider 用 mock httpx 跑通 upload→prompt→history→view，
断言 workflow 占位符被正确替换（数字保持数字类型）、产物落到本地 out 路径。
真机联调（出真片）待用户提供 COMFYUI_BASE_URL，本测试不连网络。

运行：python tests/test_comfyui_provider.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63fcffff3f0300050201f7a8d5ad00"
    "00000049454e44ae426082"
)


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
    """记录调用序列 + 返回固定响应的假 httpx.Client。"""
    calls = []            # 类级别记录，测试结束后检查
    submitted_graph = None

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, files=None, data=None, json=None, timeout=None):
        FakeClient.calls.append(("POST", url))
        if url.endswith("/upload/image"):
            return _Resp(payload={"name": "uploaded_ref.png", "subfolder": "", "type": "input"})
        if url.endswith("/prompt"):
            FakeClient.submitted_graph = json["prompt"]   # 填好占位符后的图
            return _Resp(payload={"prompt_id": "PID123", "node_errors": {}})
        return _Resp(status=404, payload={})

    def get(self, url, params=None, timeout=None):
        FakeClient.calls.append(("GET", url))
        if "/history/PID123" in url:
            return _Resp(payload={"PID123": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"57": {"gifs": [
                    {"filename": "agentlab_i2v_00001.mp4", "subfolder": "", "type": "output"}]}},
            }})
        if "/queue" in url:
            return _Resp(payload={"queue_running": [], "queue_pending": []})
        if "/view" in url:
            return _Resp(content=b"FAKE-MP4-BYTES")
        return _Resp(status=404, payload={})


def main() -> int:
    import agent_lab.app.pipeline.providers.comfyui as cu
    from agent_lab.app.core.config import settings

    # 配端点 + 让 Provider 用假 httpx
    settings.COMFYUI_BASE_URL = "http://fake-comfyui:8188"
    cu.httpx.Client = FakeClient
    FakeClient.calls = []
    FakeClient.submitted_graph = None

    prov = cu.ComfyUIProvider()
    assert prov.transport == "http", "transport 应为 http（触发本地分支）"

    tmp = tempfile.mkdtemp(prefix="comfy_test_")
    img = os.path.join(tmp, "ref.png")
    with open(img, "wb") as f:
        f.write(_PNG)
    out = os.path.join(tmp, "seg1.mp4")

    prov.generate(None, image_path=img,
                  prompt="slow push-in on her face, subtle motion",
                  out_remote=out,
                  params={"size": "480*832", "frames": 81, "fps": 16, "steps": 20,
                          "seed": 12345, "negative": "blurry, deformed"})

    # 1) 调用序列：先 upload，再 prompt，最后 view 下载
    seq = [u for (_, u) in FakeClient.calls]
    assert any(u.endswith("/upload/image") for u in seq), "未调用 /upload/image"
    assert any(u.endswith("/prompt") for u in seq), "未提交 /prompt"
    assert any("/view" in u for u in seq), "未 GET /view 下载产物"
    # 顺序：upload 在 prompt 之前，view 在最后
    i_up = next(i for i, (_, u) in enumerate(FakeClient.calls) if u.endswith("/upload/image"))
    i_pr = next(i for i, (_, u) in enumerate(FakeClient.calls) if u.endswith("/prompt"))
    i_vw = next(i for i, (_, u) in enumerate(FakeClient.calls) if "/view" in u)
    assert i_up < i_pr < i_vw, f"调用顺序不对: {seq}"
    print("[comfy] 调用序列 OK ->", seq)

    # 2) 占位符替换：图名/提示词/数字（数字要保持 int 类型）
    g = FakeClient.submitted_graph
    assert g["52"]["inputs"]["image"] == "uploaded_ref.png", "未回填上传后的图名"
    assert g["6"]["inputs"]["text"] == "slow push-in on her face, subtle motion", "正向提示词未替换"
    assert g["7"]["inputs"]["text"] == "blurry, deformed", "负向提示词未替换"
    assert g["55"]["inputs"]["width"] == 480 and isinstance(g["55"]["inputs"]["width"], int), "宽未替换为 int"
    assert g["55"]["inputs"]["height"] == 832, "高未替换"
    assert g["55"]["inputs"]["length"] == 81 and isinstance(g["55"]["inputs"]["length"], int), "帧数未替换为 int"
    assert g["3"]["inputs"]["steps"] == 20 and isinstance(g["3"]["inputs"]["steps"], int), "步数未替换为 int"
    assert g["3"]["inputs"]["seed"] == 12345, "seed 未替换"
    assert g["57"]["inputs"]["frame_rate"] == 16, "帧率未替换"
    # 占位符不应有残留
    assert "%" not in json.dumps(g), f"workflow 仍有未替换占位符: {json.dumps(g)[:300]}"
    print("[comfy] 占位符替换 OK（数字保持 int 类型，无残留）")

    # 3) 产物落地
    assert os.path.exists(out) and open(out, "rb").read() == b"FAKE-MP4-BYTES", "产物未正确下载到本地"
    print("[comfy] 产物下载 OK ->", out)

    # 4) 没配端点时应明确报错（GpuConfigError）
    settings.COMFYUI_BASE_URL = ""
    try:
        prov.generate(None, image_path=img, prompt="x", out_remote=out, params={})
        print("[comfy] 期望抛 GpuConfigError 但没抛"); return 1
    except cu.GpuConfigError:
        print("[comfy] 未配端点正确报错 OK")

    print("\n=== ComfyUIProvider 单测通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
