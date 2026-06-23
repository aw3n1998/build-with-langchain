"""GPU 探测 —— 只调 nvidia-smi，无网络、无状态。仪表盘的 GPU 名/显存来自这里。"""
from __future__ import annotations

import subprocess


def _nvsmi(query: str) -> str:
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5)
        return (out.stdout or "").strip().splitlines()[0].strip()
    except Exception:
        return ""


def gpu_name(cfg) -> str:
    return cfg.gpu_name or _nvsmi("name") or "GPU"


def vram() -> str:
    raw = _nvsmi("memory.used,memory.total")
    if not raw:
        return ""
    try:
        u, t = [int(x) for x in raw.split(",")]
        return f"{u // 1024}/{t // 1024}GB" if t > 2000 else f"{u}/{t}MB"
    except Exception:
        return ""
