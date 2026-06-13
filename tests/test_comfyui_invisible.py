# -*- coding: utf-8 -*-
"""
「ComfyUI 对用户完全隐形」单测。

核心断言（在带 env 的全新解释器里，模拟真实启动）：
  配了 COMFYUI_BASE_URL 后，ComfyUI **顶替**公开模型名的执行后端，而不是新增条目：
    - 出片：用户可见模型仍是 wan2.2 / ltx；其中 wan2.2 的 transport 变成 http（走 ComfyUI）；
    - 任何对用户可见的 name / display_name 里**都不出现 "comfyui" / "ComfyUI"**；
    - 默认仍解析到 wan2.2（用户无感）。
  出图默认不被顶替（COMFYUI_IMAGE_AS 空）→ flux 仍是 ssh；显式设 flux 才透明走 ComfyUI。

运行：python tests/test_comfyui_invisible.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 在子进程里拉起注册表并把「用户可见信息」打成 JSON 回传
_PROBE = r"""
import json
from mirage.app.pipeline.providers import video_provider_registry as V
from mirage.app.pipeline.image_providers import image_provider_registry as I
def dump(reg):
    return {"default": reg.default_name,
            "providers": [{"name": p.name, "display": p.display_name,
                           "transport": getattr(p, "transport", "ssh")} for p in
                          [reg.get(x["name"]) for x in reg.list_providers()]]}
print("JSON_START")
print(json.dumps({"video": dump(V), "image": dump(I)}, ensure_ascii=False))
"""


def _run(env_extra: dict) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = _ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"      # 让子进程的日志也按 utf-8 输出，避免 Windows GBK 解码炸
    env.update(env_extra)
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=_ROOT, env=env,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if "JSON_START" not in out.stdout:
        raise RuntimeError(f"子进程没输出 JSON:\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr[-1500:]}")
    return json.loads(out.stdout.split("JSON_START", 1)[1].strip())


def _no_comfy_visible(reg: dict, where: str) -> None:
    blob = json.dumps(reg, ensure_ascii=False).lower()
    assert "comfyui" not in blob, f"{where} 的用户可见信息里泄漏了 ComfyUI: {reg}"


def main() -> int:
    # 场景 1（auto，默认）：配端点 → “默认出片模型”透明顶替成 ComfyUI 后端，名字不变
    d = _run({"COMFYUI_BASE_URL": "http://endpoint:8188", "COMFYUI_VIDEO_AS": "auto"})
    v, im = d["video"], d["image"]
    vnames = {p["name"] for p in v["providers"]}
    assert "comfyui" not in vnames, f"出片不该出现 comfyui 条目: {vnames}"
    # 默认模型（本仓 .env 为 ltx；不写死，从结果取）现在 transport=http，但公开名不变
    dft = v["default"]
    assert dft and dft != "comfyui", f"默认应是公开模型名，实际 {dft}"
    dprov = next(p for p in v["providers"] if p["name"] == dft)
    assert dprov["transport"] == "http", f"auto 下默认出片模型 {dft} 应透明走 ComfyUI(http)，实际 {dprov}"
    _no_comfy_visible(v, "出片")
    print(f"[invisible] 出片(auto)：默认模型 '{dft}' 透明顶替为 ComfyUI，无 ComfyUI 字样 OK ->", vnames)

    # 出图：默认不被顶替 → flux 仍是 ssh
    flux = next(p for p in im["providers"] if p["name"] == "flux")
    assert flux["transport"] == "ssh", f"默认出图应仍走 FLUX-SSH，实际 {flux}"
    assert "comfyui-img" not in {p["name"] for p in im["providers"]}, "出图不该出现 comfyui-img 条目"
    _no_comfy_visible(im, "出图")
    print("[invisible] 出图：默认仍 FLUX-SSH，无 ComfyUI 字样 OK")

    # 场景 2：显式只顶替 wan2.2（不管默认是谁）→ wan2.2=http，公开名仍是 wan2.2
    d2 = _run({"COMFYUI_BASE_URL": "http://endpoint:8188", "COMFYUI_VIDEO_AS": "wan2.2"})
    wan = next(p for p in d2["video"]["providers"] if p["name"] == "wan2.2")
    assert wan["transport"] == "http", f"显式顶替 wan2.2 应走 ComfyUI，实际 {wan}"
    assert "comfyui" not in {p["name"] for p in d2["video"]["providers"]}
    _no_comfy_visible(d2["video"], "出片(显式)")
    print("[invisible] 出片(显式 wan2.2)：wan2.2 透明走 ComfyUI，无 ComfyUI 字样 OK")

    # 场景 3：显式让出图也透明走 ComfyUI（flux）
    d3 = _run({"COMFYUI_BASE_URL": "http://endpoint:8188", "COMFYUI_IMAGE_AS": "flux"})
    flux3 = next(p for p in d3["image"]["providers"] if p["name"] == "flux")
    assert flux3["transport"] == "http", f"设 COMFYUI_IMAGE_AS=flux 后出图应透明走 ComfyUI，实际 {flux3}"
    _no_comfy_visible(d3["image"], "出图(顶替)")
    print("[invisible] 出图：显式顶替后 flux 走 ComfyUI 仍无 ComfyUI 字样 OK")

    # 场景 4：没配端点 → 一切照旧（ssh），更不会有 ComfyUI
    d4 = _run({"COMFYUI_BASE_URL": ""})
    assert all(p["transport"] == "ssh" for p in d4["video"]["providers"]), "无端点出片应全 SSH"
    _no_comfy_visible(d4["video"], "出片(无端点)")
    _no_comfy_visible(d4["image"], "出图(无端点)")
    print("[invisible] 无端点：全 SSH、零 ComfyUI OK")

    print("\n=== ComfyUI 对用户完全隐形 单测通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
