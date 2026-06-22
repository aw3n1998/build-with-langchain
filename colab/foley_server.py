"""MMAudio 包装 server —— load-once 视频→音频 Foley HTTP（生成与画面同步的环境/动作音效）。

契约（后端 mirage/app/pipeline/foley_post.py 照打）：
  POST /v1/foley  {video(同机路径), output(同机输出wav), prompt(可选: SFX类型引导文本),
                   duration(秒,可选,0=自动探测), num_steps, cfg_strength}
                  -> {"status":"succeed","output_path": output}
  GET  /v1/health -> {"status":"ok","loaded":bool,"sr":int,"port":int}

原理：模型「看」视频帧（clip+sync 特征）条件生成音频，所以声音天然与画面同步——
篮球真触地那一帧才响、扣篮砸筐那刻才炸，不是乱铺。生成只出【音轨 wav】，叠回人声/合成由
mirage 的 assembler.mix_sfx_under_voice 做（音效压在人声之下）。
输出用 soundfile 写 wav，避开 torch2.11 的 torchaudio.save→torchcodec 依赖（与 cosyvoice2_server 同坑同解）。
"""

import os
import sys
import threading
import traceback

REPO = os.environ.get("MMAUDIO_REPO", "/ephemeral/mmaudio/MMAudio")
VARIANT = os.environ.get("MMAUDIO_VARIANT", "large_44k_v2")   # 44.1kHz 大模型，质量最好
PORT = int(os.environ.get("MMAUDIO_PORT", "8194"))
DTYPE = os.environ.get("MMAUDIO_DTYPE", "bf16").strip().lower()
DEFAULT_NEG = os.environ.get("MMAUDIO_NEG", "")               # 负向提示（如 "music, speech" 去掉人声/配乐）
DUR_CAP = float(os.environ.get("MMAUDIO_DUR_CAP", "30"))      # 单次最长秒数（保护显存/质量）

sys.path.insert(0, REPO)
if os.path.isdir(REPO):
    os.chdir(REPO)

import torch  # noqa: E402
# 纯推理：关 autograd，避开 torch2.11 下 MMAudio 的 inference_mode 张量被 autograd 保存 backward 的 RuntimeError。
# ★注意 grad 模式是【线程局部】的——这行只对主线程生效，真正的请求在 uvicorn 工作线程跑，
#   所以必须在 foley() 处理函数里再包一层 with torch.no_grad()（见下），否则照样报错。
torch.set_grad_enabled(False)
import soundfile as sf  # noqa: E402
from mmaudio.eval_utils import (all_model_cfg, generate, load_video,  # noqa: E402
                                setup_eval_logging)
from mmaudio.model.flow_matching import FlowMatching  # noqa: E402
from mmaudio.model.networks import MMAudio, get_my_mmaudio  # noqa: E402
from mmaudio.model.utils.features_utils import FeaturesUtils  # noqa: E402

_device = "cuda"
_dtype = torch.bfloat16 if DTYPE in ("bf16", "bfloat16") else torch.float32

print(f"[mmaudio-server] 加载 {VARIANT} dtype={_dtype} …", flush=True)
setup_eval_logging()
_cfg = all_model_cfg[VARIANT]
_cfg.download_if_needed()           # 首启自动下权重(~几G)到 weights/ ext_weights/
seq_cfg = _cfg.seq_cfg

_net: MMAudio = get_my_mmaudio(_cfg.model_name).to(_device, _dtype).eval()
_net.load_weights(torch.load(_cfg.model_path, map_location=_device, weights_only=True))

# 44k 模型不走 bigvgan(那是 16k 的)；用 getattr 兼容两类 ckpt。
_feat = FeaturesUtils(
    tod_vae_ckpt=_cfg.vae_path,
    synchformer_ckpt=_cfg.synchformer_ckpt,
    enable_conditions=True,
    mode=_cfg.mode,
    bigvgan_vocoder_ckpt=getattr(_cfg, "bigvgan_16k_path", None),
    need_vae_encoder=False,
).to(_device, _dtype).eval()

SR = seq_cfg.sampling_rate
_lock = threading.Lock()
print(f"[mmaudio-server] ✅ 就绪 sr={SR} variant={VARIANT} port={PORT}", flush=True)

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402
import uvicorn  # noqa: E402

app = FastAPI()


class FoleyReq(BaseModel):
    video: str = ""
    output: str = "/tmp/foley_out.wav"
    prompt: str = ""
    duration: float = 0.0
    num_steps: int = 25
    cfg_strength: float = 4.5


def _probe_duration(path: str) -> float:
    """无 duration 时用 ffmpeg 探片长。"""
    try:
        import subprocess
        import re
        err = subprocess.run(["ffmpeg", "-i", path], capture_output=True, text=True).stderr
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err or "")
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:  # noqa: BLE001
        pass
    return 0.0


@app.get("/v1/health")
def health():
    return {"status": "ok", "loaded": _net is not None, "sr": SR, "port": PORT}


@app.post("/v1/foley")
def foley(req: FoleyReq):
    if not (req.video and os.path.exists(req.video)):
        return {"status": "failed", "error": f"视频不存在: {req.video}"}
    try:
        # ★no_grad 必须在请求线程内：grad 模式线程局部，模块级 set_grad_enabled 不覆盖 uvicorn 工作线程。
        with _lock, torch.no_grad():
            dur = float(req.duration or 0) or _probe_duration(req.video) or 8.0
            dur = max(1.0, min(dur, DUR_CAP))
            # load_all_frames=False：只取 clip/sync 特征帧，不留整段原帧（省显存；不走 make_video）。
            video_info = load_video(req.video, dur, load_all_frames=False)
            clip_frames = video_info.clip_frames.unsqueeze(0)
            sync_frames = video_info.sync_frames.unsqueeze(0)
            seq_cfg.duration = video_info.duration_sec
            _net.update_seq_lengths(seq_cfg.latent_seq_len, seq_cfg.clip_seq_len, seq_cfg.sync_seq_len)
            fm = FlowMatching(min_sigma=0, inference_mode="euler", num_steps=int(req.num_steps or 25))
            rng = torch.Generator(device=_device)
            rng.manual_seed(42)
            audios = generate(clip_frames, sync_frames, [req.prompt or ""],
                              negative_text=[DEFAULT_NEG],
                              feature_utils=_feat, net=_net, fm=fm, rng=rng,
                              cfg_strength=float(req.cfg_strength or 4.5))
            audio = audios.float().cpu()[0]
            arr = audio.numpy()
            if arr.ndim == 2:                 # (channels, samples) -> (samples, channels)
                arr = arr.T
            os.makedirs(os.path.dirname(req.output) or ".", exist_ok=True)
            sf.write(req.output, arr, SR)
        if not (os.path.exists(req.output) and os.path.getsize(req.output) > 1000):
            return {"status": "failed", "error": f"未生成有效音频: {req.output}"}
        return {"status": "succeed", "output_path": req.output}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
