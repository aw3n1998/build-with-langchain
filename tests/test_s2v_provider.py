# -*- coding: utf-8 -*-
"""
S2V(对口型)Provider 单测：mock httpx 验证 图+音频 都上传、workflow 占位替换、产物下载、缺音频报错。
真机联调待 4090 部署 Wan2.2-S2V。运行：python tests/test_s2v_provider.py
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
    "00000049454e44ae426082")


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
    graph = None

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def post(self, url, files=None, data=None, json=None, timeout=None):
        FakeClient.calls.append(("POST", url))
        if url.endswith("/upload/image"):
            fname = files["image"][0] if files else "x"   # 回显上传的文件名，便于区分 图/音频
            return _Resp(payload={"name": fname, "subfolder": "", "type": "input"})
        if url.endswith("/prompt"):
            FakeClient.graph = json["prompt"]
            return _Resp(payload={"prompt_id": "PID", "node_errors": {}})
        return _Resp(status=404, payload={})

    def get(self, url, params=None, timeout=None):
        FakeClient.calls.append(("GET", url))
        if "/history/PID" in url:
            return _Resp(payload={"PID": {"status": {"status_str": "success"},
                "outputs": {"57": {"gifs": [{"filename": "agentlab_s2v_0001.mp4",
                                             "subfolder": "", "type": "output"}]}}}})
        if "/view" in url: return _Resp(content=b"S2V-MP4")
        if "/queue" in url: return _Resp(payload={"queue_running": [], "queue_pending": []})
        return _Resp(status=404, payload={})


def main() -> int:
    import mirage.app.pipeline.providers.comfyui_s2v as s2v_mod
    from mirage.app.core.config import settings

    settings.COMFYUI_BASE_URL = "http://fake:8188"
    s2v_mod.httpx.Client = FakeClient
    FakeClient.calls = []; FakeClient.graph = None

    prov = s2v_mod.ComfyUIS2VProvider()
    assert prov.transport == "http" and prov.hidden is True and prov.name == "comfyui-s2v"

    tmp = tempfile.mkdtemp(prefix="s2v_")
    img = os.path.join(tmp, "ref.png"); open(img, "wb").write(_PNG)
    aud = os.path.join(tmp, "voice.mp3"); open(aud, "wb").write(b"ID3FAKEMP3")
    out = os.path.join(tmp, "lip.mp4")

    prov.generate(None, image_path=img, prompt="she speaks to camera, gentle smile",
                  out_remote=out, params={"audio_path": aud, "size": "480*832",
                                          "steps": 20, "fps": 16, "seed": 7})

    # 图 + 音频都上传（两次 /upload/image），再 /prompt，再 /view
    uploads = [u for (_, u) in FakeClient.calls if u.endswith("/upload/image")]
    assert len(uploads) == 2, f"应上传 图+音频 两次，实际 {len(uploads)}"
    assert any("/view" in u for (_, u) in FakeClient.calls), "未下载产物"
    g = FakeClient.graph
    assert g["52"]["inputs"]["image"] == "ref.png", "人物图未回填"
    assert g["50"]["inputs"]["audio"] == "voice.mp3", "语音音频未回填"
    assert g["6"]["inputs"]["text"] == "she speaks to camera, gentle smile", "提示词未替换"
    assert g["3"]["inputs"]["steps"] == 20 and isinstance(g["3"]["inputs"]["steps"], int), "步数非 int"
    assert "%" not in json.dumps(g), f"仍有未替换占位符: {json.dumps(g)[:200]}"
    assert open(out, "rb").read() == b"S2V-MP4", "产物未下载"
    print("[s2v] 图+音频上传 + 占位替换 + 下载 OK")

    # 缺音频 → 明确报错
    try:
        prov.generate(None, image_path=img, prompt="x", out_remote=out, params={})
        print("[s2v] 期望缺音频报错但没报"); return 1
    except s2v_mod.GpuRunError:
        print("[s2v] 缺音频正确报错 OK")

    print("\n=== S2V(对口型)Provider 单测通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
