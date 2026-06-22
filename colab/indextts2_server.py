"""IndexTTS2 包装 server —— 把 index-tts/index-tts(IndexTTS2)包成一个 load-once 的 HTTP 服务，
给后端 tts_providers/indextts2.py 调（仿 colab/standin_server.py 的结构）。

为什么要这层：IndexTTS2 加载一次约 5.9G 权重(gpt.pth 3.5G + s2mel.pth 1.2G + qwen 情感模型 + w2v-bert…)，
每次重载要几分钟，没法当生产用。本 server 启动时**只加载一次** IndexTTS2()，之后每个请求秒级进入推理。

由 Colab「§IndexTTS2」格启动(它会 clone index-tts、建 venv、下 IndexTeam/IndexTTS-2 权重、设好下面这些 env
再起本文件)。端口默认 8191(与 lightx2v 8189 / Stand-In 8190 错开)。

请求契约(与后端 tts_providers/indextts2.py 完全对齐):
  POST /v1/tts  body={text, ref_audio(同机本地路径=克隆音色), voice_id(server 端音色库,可选), emotion, output(同机输出 wav 路径)}
  → server 把 wav 写到 output → 返回 {"status":"succeed","output_path": output}
  GET  /v1/health → {"status":"ok","loaded":bool}

环境变量(由 §IndexTTS2 格传入):
  INDEXTTS2_DIR        index-tts 仓库路径(默认 /content/index-tts);用于 sys.path/chdir 让其相对资源(如 examples/)可用
  INDEXTTS2_CKPT       权重目录(默认 <DIR>/checkpoints;内含 config.yaml + gpt.pth + s2mel.pth + qwen…)
  INDEXTTS2_FP16       "1"=use_fp16=True(省显存,默认开);"0"=关
  INDEXTTS2_USE_CUDA_KERNEL  "1"=BigVGAN 走自定义 CUDA kernel(sm120/Blackwell 可能编译失败,默认 0=关,先跑通)
  INDEXTTS2_VOICES_DIR voice_id 音色库目录(默认 <DIR>/voices;voice_id="alice" → <dir>/alice.wav,找不到再试 examples/)
  INDEXTTS2_EMO_ALPHA  文字情感模式的强度系数(默认 0.6,官方建议值;数值情感向量不受此影响)
  INDEXTTS2_PORT       默认 8191
"""

import os
import sys
import threading
import traceback

INDEXTTS2_DIR = os.environ.get("INDEXTTS2_DIR", "/content/index-tts")
CKPT_DIR = os.environ.get("INDEXTTS2_CKPT", os.path.join(INDEXTTS2_DIR, "checkpoints"))
USE_FP16 = (os.environ.get("INDEXTTS2_FP16", "1").strip() not in ("", "0", "false", "False"))
USE_CUDA_KERNEL = (os.environ.get("INDEXTTS2_USE_CUDA_KERNEL", "0").strip() in ("1", "true", "True"))
VOICES_DIR = os.environ.get("INDEXTTS2_VOICES_DIR", os.path.join(INDEXTTS2_DIR, "voices"))
EMO_ALPHA = float(os.environ.get("INDEXTTS2_EMO_ALPHA", "0.6") or 0.6)
PORT = int(os.environ.get("INDEXTTS2_PORT", "8191"))

# emo_vector 8 维顺序(infer_v2.py 约定):happy, angry, sad, afraid, disgusted, melancholic, surprised, calm
# 高兴 / 愤怒 / 悲伤 / 害怕 / 厌恶 / 忧郁 / 惊讶 / 平静
_EMO_IDX = {
    "happy": 0, "joy": 0, "高兴": 0, "开心": 0, "喜悦": 0,
    "angry": 1, "anger": 1, "愤怒": 1, "生气": 1,
    "sad": 2, "sadness": 2, "悲伤": 2, "难过": 2, "伤心": 2,
    "afraid": 3, "fear": 3, "fearful": 3, "害怕": 3, "恐惧": 3,
    "disgusted": 4, "disgust": 4, "厌恶": 4, "恶心": 4,
    "melancholic": 5, "melancholy": 5, "忧郁": 5, "惆怅": 5,
    "surprised": 6, "surprise": 6, "惊讶": 6, "吃惊": 6,
    "calm": 7, "neutral": 7, "平静": 7, "中性": 7,
}


def _emo_to_vector(emotion: str):
    """把单标签 emotion(英文/中文同义词)→ 8 维 one-hot 情感向量。识别不了返回 None(走中性)。"""
    key = (emotion or "").strip().lower()
    if not key:
        return None
    idx = _EMO_IDX.get(key) or _EMO_IDX.get(emotion.strip())  # 原文兜底(中文不被 lower 影响)
    if idx is None:
        return None
    vec = [0.0] * 8
    vec[idx] = 1.0
    return vec


def _resolve_ref_audio(ref_audio: str, voice_id: str) -> str:
    """决定克隆参考音(spk_audio_prompt)：优先 ref_audio(同机本地路径),否则 voice_id → 音色库文件。"""
    p = (ref_audio or "").strip()
    if p and os.path.exists(p):
        return p
    vid = (voice_id or "").strip()
    if vid:
        for cand in (
            os.path.join(VOICES_DIR, vid),
            os.path.join(VOICES_DIR, vid + ".wav"),
            os.path.join(VOICES_DIR, vid + ".mp3"),
            os.path.join(INDEXTTS2_DIR, "examples", vid + ".wav"),
            os.path.join(INDEXTTS2_DIR, "examples", vid),
        ):
            if os.path.exists(cand):
                return cand
    return ""


# index-tts 用包内相对资源 + local_files_only 从 checkpoints 加载子模型 → chdir + sys.path 让其稳定可用。
sys.path.insert(0, INDEXTTS2_DIR)
if os.path.isdir(INDEXTTS2_DIR):
    os.chdir(INDEXTTS2_DIR)

from indextts.infer_v2 import IndexTTS2  # noqa: E402

_cfg = os.path.join(CKPT_DIR, "config.yaml")
print(f"[indextts2-server] 加载模型… ckpt={CKPT_DIR} fp16={USE_FP16} cuda_kernel={USE_CUDA_KERNEL}", flush=True)
if not os.path.exists(_cfg):
    print(f"[indextts2-server] ❌ 没找到 {_cfg}；先在 §IndexTTS2 格下好 IndexTeam/IndexTTS-2 到 {CKPT_DIR}", flush=True)
_tts = IndexTTS2(cfg_path=_cfg, model_dir=CKPT_DIR, use_fp16=USE_FP16, use_cuda_kernel=USE_CUDA_KERNEL)
_lock = threading.Lock()  # 单卡串行,防两请求抢 GPU
print(f"[indextts2-server] ✅ 就绪 voices={VOICES_DIR} emo_alpha={EMO_ALPHA} port={PORT}", flush=True)

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402
import uvicorn  # noqa: E402

app = FastAPI()


class TTSReq(BaseModel):
    text: str = ""
    ref_audio: str = ""          # 同机本地路径(克隆音色来源);server 直接读
    voice_id: str = ""           # server 端音色库 id(ref_audio 为空时用)
    emotion: str = ""            # 单标签情感(happy/angry/sad/… 或中文);空=中性
    output: str = "/content/indextts2_out.wav"   # ★同机共享盘:server 直接写到这里


@app.get("/v1/health")
def health():
    return {"status": "ok", "loaded": _tts is not None, "port": PORT}


@app.post("/v1/tts")
def tts(req: TTSReq):
    if not (req.text or "").strip():
        return {"status": "failed", "error": "text 为空"}
    spk = _resolve_ref_audio(req.ref_audio, req.voice_id)
    if not spk:
        return {"status": "failed",
                "error": f"克隆参考音不存在: ref_audio={req.ref_audio!r} voice_id={req.voice_id!r}"}
    try:
        emo_vec = _emo_to_vector(req.emotion)  # 识别到的情感 → 8 维 one-hot;识别不了=None=中性
        with _lock:   # 单卡串行
            os.makedirs(os.path.dirname(req.output) or ".", exist_ok=True)
            kw = dict(spk_audio_prompt=spk, text=req.text, output_path=req.output, verbose=False)
            if emo_vec is not None:
                kw["emo_vector"] = emo_vec
                kw["use_random"] = False
            _tts.infer(**kw)
        if not (os.path.exists(req.output) and os.path.getsize(req.output) > 1000):
            return {"status": "failed", "error": f"未生成有效 wav: {req.output}"}
        return {"status": "succeed", "output_path": req.output}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
