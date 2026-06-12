# -*- coding: utf-8 -*-
"""
Part E 单测：ComfyUI 后处理层 maybe_postprocess。

断言三态：
  1) 未配 workflow → no-op（note=off），原片不动；
  2) 配了 workflow + mock 端点 → 上传/提交/下载/就地替换，applied=True，文件被换成增强版；
  3) ComfyUI 报错 → 失败安全：保留原片，applied=False、note 以 "failed" 开头。
真机联调待 COMFYUI_BASE_URL + 放大/补帧 workflow。

运行：python tests/test_postprocess.py
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


class FakeOK:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def post(self, url, files=None, data=None, json=None, timeout=None):
        if url.endswith("/upload/image"):
            return _Resp(payload={"name": "film.mp4", "subfolder": "", "type": "input"})
        if url.endswith("/prompt"):
            return _Resp(payload={"prompt_id": "PP1", "node_errors": {}})
        return _Resp(status=404, payload={})

    def get(self, url, params=None, timeout=None):
        if "/history/PP1" in url:
            return _Resp(payload={"PP1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"4": {"gifs": [
                    {"filename": "agentlab_post_00001.mp4", "subfolder": "", "type": "output"}]}},
            }})
        if "/view" in url:
            return _Resp(content=b"ENHANCED")
        if "/queue" in url:
            return _Resp(payload={"queue_running": [], "queue_pending": []})
        return _Resp(status=404, payload={})


class FakeFail(FakeOK):
    def post(self, url, files=None, data=None, json=None, timeout=None):
        if url.endswith("/upload/image"):
            return _Resp(payload={"name": "film.mp4"})
        if url.endswith("/prompt"):
            return _Resp(status=500)          # ComfyUI 拒绝 → GpuRunError → 失败安全
        return _Resp(status=404, payload={})


def _mk_video(tmp, content=b"ORIGINAL"):
    p = os.path.join(tmp, "film.mp4")
    with open(p, "wb") as f:
        f.write(content)
    return p


def main() -> int:
    import agent_lab.app.pipeline.postprocess as pp
    from agent_lab.app.core.config import settings

    tmp = tempfile.mkdtemp(prefix="post_test_")
    # 一份带占位符的临时后处理 workflow
    wf = os.path.join(tmp, "post.json")
    with open(wf, "w", encoding="utf-8") as f:
        json.dump({"1": {"class_type": "VHS_LoadVideo", "inputs": {"video": "%VIDEO%"}},
                   "4": {"class_type": "VHS_VideoCombine",
                         "inputs": {"images": ["1", 0], "frame_rate": "%FPS%"}}}, f)

    # 1) 未配 workflow → no-op
    settings.COMFYUI_WORKFLOW_POST = ""
    v = _mk_video(tmp)
    r = pp.maybe_postprocess(v)
    assert r == {"applied": False, "note": "off"}, f"未配应 no-op，实际 {r}"
    assert open(v, "rb").read() == b"ORIGINAL", "未配时不应动原片"
    print("[post] 未配 workflow → no-op OK")

    # 2) 配 workflow + mock 端点 → 替换为增强版
    settings.COMFYUI_WORKFLOW_POST = wf
    settings.COMFYUI_BASE_URL = "http://fake:8188"
    pp.httpx.Client = FakeOK
    v2 = _mk_video(tmp)
    r2 = pp.maybe_postprocess(v2, fps=16)
    assert r2["applied"] is True and r2["note"] == "ok", f"应成功，实际 {r2}"
    assert open(v2, "rb").read() == b"ENHANCED", "成片应被替换为后处理增强版"
    print("[post] 配端点 → 上传/提交/下载/替换 OK")

    # 3) ComfyUI 报错 → 失败安全，保留原片
    pp.httpx.Client = FakeFail
    v3 = _mk_video(tmp)
    r3 = pp.maybe_postprocess(v3)
    assert r3["applied"] is False and r3["note"].startswith("failed"), f"应失败安全，实际 {r3}"
    assert open(v3, "rb").read() == b"ORIGINAL", "后处理失败必须保留原片"
    assert not os.path.exists(v3 + ".post.mp4"), "失败应清理半成品"
    print("[post] ComfyUI 报错 → 保留原片（失败安全）OK")

    print("\n=== 后处理层(Part E) 单测通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
