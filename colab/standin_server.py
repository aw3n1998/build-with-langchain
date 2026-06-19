"""Stand-In 强锁脸包装 server —— 把 WeChatCV/Stand-In 包成一个 load-once 的 HTTP 服务，给后端 standin-t2v provider 调。

为什么要这层：Stand-In 只有 CLI(infer.py)、每次跑都重载 14B 模型(几分钟),没法当生产用。本 server 在启动时
**只加载一次** pipe(load_wan_pipe + set_stand_in),之后每个请求秒级进入推理。复用你已下的 Wan2.2 权重当 base_path
(布局正好匹配:high_noise_model/ low_noise_model/ models_t5_umt5-xxl-enc-bf16.pth Wan2.1_VAE.pth google/),不重下底模。

由 Colab「§Stand-In」格启动(它会 clone Stand-In、建 venv、下适配器、设好下面这些 env 再起本文件)。端口默认 8190。

环境变量(由 §Stand-In 格传入):
  STANDIN_DIR      Stand-In 仓库路径(默认 /content/Stand-In);用于 sys.path/chdir 让其相对 import 生效
  STANDIN_BASE_PATH Wan2.2 权重目录(默认 /content/wan_local;就是你 §4 下的那套,免重下)
  STANDIN_WAN_VERSION 默认 2.2
  STANDIN_ADAPTER   Stand-In 适配器 .ckpt 显式路径(留空=在 <DIR>/checkpoints/Stand-In 里 glob wan2.2 的)
  STANDIN_ANTELOPE  antelopev2 根目录(默认 <DIR>/checkpoints/antelopev2;其下应有 models/antelopev2/)
  STANDIN_PORT      默认 8190
"""

import glob
import inspect
import os
import sys
import threading
import traceback

STANDIN_DIR = os.environ.get("STANDIN_DIR", "/content/Stand-In")
BASE_PATH = os.environ.get("STANDIN_BASE_PATH", "/content/wan_local")
WAN_VERSION = os.environ.get("STANDIN_WAN_VERSION", "2.2")
ANTELOPE = os.environ.get("STANDIN_ANTELOPE", os.path.join(STANDIN_DIR, "checkpoints/antelopev2"))
PORT = int(os.environ.get("STANDIN_PORT", "8190"))


def _find_adapter() -> str:
    p = (os.environ.get("STANDIN_ADAPTER") or "").strip()
    if p and os.path.exists(p):
        return p
    root = os.path.join(STANDIN_DIR, "checkpoints", "Stand-In")
    pats = ["**/*wan2.2*.ckpt", "**/*wan2_2*.ckpt", "**/*2.2*.ckpt", "**/*.ckpt",
            "**/*wan2.2*.safetensors", "**/*.safetensors"]
    for pat in pats:
        fs = sorted(glob.glob(os.path.join(root, pat), recursive=True))
        if fs:
            return fs[0]
    return ""


# Stand-In 用相对 import(from data.video import .. / from wan_loader import .. / from preprocessor import ..)→ 必须 chdir + sys.path
sys.path.insert(0, STANDIN_DIR)
os.chdir(STANDIN_DIR)

import torch  # noqa: E402
from data.video import save_video  # noqa: E402
from wan_loader import load_wan_pipe  # noqa: E402
from models.set_condition_branch import set_stand_in  # noqa: E402
from preprocessor import FaceProcessor  # noqa: E402

print(f"[standin-server] 加载模型… base={BASE_PATH} wan={WAN_VERSION}", flush=True)
ADAPTER = _find_adapter()
if not ADAPTER:
    print("[standin-server] ❌ 没找到 Stand-In 适配器 .ckpt(应在 checkpoints/Stand-In/);先在 §Stand-In 格下好 BowenXue/Stand-In", flush=True)
_face = FaceProcessor(antelopv2_path=ANTELOPE)
_pipe = load_wan_pipe(base_path=BASE_PATH, wan_version=WAN_VERSION, torch_dtype=torch.bfloat16)
set_stand_in(_pipe, model_path=ADAPTER, wan_version=WAN_VERSION)
# pipe.__call__ 接受哪些可选参数(num_frames/height/width 等),按签名过滤再传——不同 Stand-In/DiffSynth 版本签名不一,避免 TypeError
try:
    _params = inspect.signature(_pipe.__call__).parameters
    _accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _params.values())
    _accepted = set(_params)
except (TypeError, ValueError):
    _accepts_kwargs, _accepted = True, set()
_lock = threading.Lock()
print(f"[standin-server] ✅ 就绪 adapter={os.path.basename(ADAPTER) or '(无)'} antelope={ANTELOPE} port={PORT}", flush=True)

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402
import uvicorn  # noqa: E402

app = FastAPI()


class GenReq(BaseModel):
    prompt: str = ""
    negative_prompt: str = ""
    ip_image: str = ""
    seed: int = 0
    num_inference_steps: int = 20
    num_frames: int = 81
    width: int = 480
    height: int = 832
    fps: int = 16
    quality: int = 9
    output: str = "/content/standin_out.mp4"


@app.get("/v1/health")
def health():
    return {"status": "ok", "loaded": _pipe is not None, "adapter": os.path.basename(ADAPTER)}


@app.post("/v1/standin")
def standin(req: GenReq):
    if not req.ip_image or not os.path.exists(req.ip_image):
        return {"status": "failed", "error": f"参考脸不存在: {req.ip_image}"}
    try:
        with _lock:   # 单卡串行,防两请求抢 GPU
            ip = _face.process(req.ip_image)
            kw = dict(prompt=req.prompt, negative_prompt=req.negative_prompt, seed=int(req.seed),
                      ip_image=ip, num_inference_steps=int(req.num_inference_steps), tiled=False)
            for k, v in (("num_frames", int(req.num_frames)), ("height", int(req.height)), ("width", int(req.width))):
                if _accepts_kwargs or k in _accepted:   # 只传 pipe 认的可选项(否则报 TypeError)
                    kw[k] = v
            video = _pipe(**kw)
            os.makedirs(os.path.dirname(req.output) or ".", exist_ok=True)
            save_video(video, req.output, fps=int(req.fps), quality=int(req.quality))
        return {"status": "succeed", "output_path": req.output}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
