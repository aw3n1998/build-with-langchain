"""LatentSync 口型对齐 server —— 把 bytedance/LatentSync 包成 HTTP 服务，给后端 lipsync_post.py 调
（仿 colab/indextts2_server.py / standin_server.py 的契约）。

为什么用 CLI 包装而非 load-once：LatentSync 没有干净可导入的 run() 函数（要把 scripts/inference.py
main() 整段搬出来，且随上游重构易碎）。这里直接 subprocess 调它官方的 `python -m scripts.inference`
（=inference.sh 同一条命令、smoke test 验过的路径），最稳；代价是每请求重载模型(~2-3min)。
量大了再换 load-once（构建一次 LipsyncPipeline）。

契约(与 lipsync_post.py 对齐)：
  POST /v1/lipsync {video, audio, output, inference_steps, guidance_scale, seed} -> {status, output_path}
  GET  /v1/health -> {status:"ok", loaded, port}

env：LATENTSYNC_DIR(repo路径) / LATENTSYNC_UNET_CONFIG / LATENTSYNC_CKPT / LATENTSYNC_STEPS /
     LATENTSYNC_GUIDANCE / LATENTSYNC_PYTHON(venv python) / LATENTSYNC_PORT(默认8192)
"""

import os
import sys
import subprocess
import threading
import traceback

LATENTSYNC_DIR = os.environ.get("LATENTSYNC_DIR", "/ephemeral/latentsync/repo")
UNET_CONFIG = os.environ.get("LATENTSYNC_UNET_CONFIG", os.path.join(LATENTSYNC_DIR, "configs/unet/stage2_512.yaml"))
INFERENCE_CKPT = os.environ.get("LATENTSYNC_CKPT", os.path.join(LATENTSYNC_DIR, "checkpoints/latentsync_unet.pt"))
DEFAULT_STEPS = int(os.environ.get("LATENTSYNC_STEPS", "20"))
DEFAULT_GUIDANCE = float(os.environ.get("LATENTSYNC_GUIDANCE", "1.5"))
DEFAULT_SEED = int(os.environ.get("LATENTSYNC_SEED", "1247"))
PORT = int(os.environ.get("LATENTSYNC_PORT", "8192"))
PY = os.environ.get("LATENTSYNC_PYTHON", sys.executable)

_lock = threading.Lock()   # 单卡串行，防两请求抢 GPU

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402
import uvicorn  # noqa: E402

app = FastAPI()
print(f"[latentsync-server] 就绪(CLI 模式) dir={LATENTSYNC_DIR} ckpt={INFERENCE_CKPT} py={PY} port={PORT}", flush=True)


class LipsyncReq(BaseModel):
    video: str = ""
    audio: str = ""
    output: str = "/ephemeral/lipsync_io/out.mp4"
    inference_steps: int = DEFAULT_STEPS
    guidance_scale: float = DEFAULT_GUIDANCE
    seed: int = DEFAULT_SEED


@app.get("/v1/health")
def health():
    ok = os.path.exists(INFERENCE_CKPT) and os.path.exists(UNET_CONFIG)
    return {"status": "ok", "loaded": ok, "port": PORT}


@app.post("/v1/lipsync")
def lipsync(req: LipsyncReq):
    if not (req.video and os.path.exists(req.video)):
        return {"status": "failed", "error": f"video 不存在: {req.video}"}
    if not (req.audio and os.path.exists(req.audio)):
        return {"status": "failed", "error": f"audio 不存在: {req.audio}"}
    try:
        os.makedirs(os.path.dirname(req.output) or ".", exist_ok=True)
        cmd = [PY, "-m", "scripts.inference",
               "--unet_config_path", UNET_CONFIG,
               "--inference_ckpt_path", INFERENCE_CKPT,
               "--inference_steps", str(int(req.inference_steps)),
               "--guidance_scale", str(float(req.guidance_scale)),
               "--seed", str(int(req.seed)),
               "--video_path", req.video,
               "--audio_path", req.audio,
               "--video_out_path", req.output,
               "--enable_deepcache"]
        with _lock:
            p = subprocess.run(cmd, cwd=LATENTSYNC_DIR, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=1800)
        if not (os.path.exists(req.output) and os.path.getsize(req.output) > 1000):
            tail = (p.stderr or p.stdout or "")[-1000:]
            return {"status": "failed", "error": f"未生成有效 mp4。inference 输出尾部:\n{tail}"}
        return {"status": "succeed", "output_path": req.output}
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "lipsync 超时(>1800s)"}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
