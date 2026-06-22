"""CosyVoice2 包装 server —— load-once HTTP TTS（克隆 + 情感），用来替代 edge-tts 当默认/保底引擎。

契约与 colab/indextts2_server.py 完全一致（后端 tts_providers/cosyvoice2.py 照打）：
  POST /v1/tts  {text, ref_audio(同机本地路径=克隆音色), voice_id(音色库,可选), emotion, output(同机输出wav)}
                -> {"status":"succeed","output_path": output}
  GET  /v1/health -> {"status":"ok","loaded":bool,"sr":int,"port":int}

CosyVoice2-0.5B 不带内置预置音 → 没传 ref_audio 时用 COSYVOICE_DEFAULT_REF（爬来的成熟女声）当默认音色。
克隆用 inference_cross_lingual（不需转写文本，适合爬来的无字幕音）；情感用 inference_instruct2（自然语言指令）。
"""

import os
import sys
import threading
import traceback

REPO = os.environ.get("COSYVOICE_REPO", "/ephemeral/cosyvoice2/CosyVoice")
MODEL_DIR = os.environ.get("COSYVOICE_MODEL_DIR", "/ephemeral/cosyvoice2/CosyVoice2-0.5B")
PORT = int(os.environ.get("COSYVOICE_PORT", "8193"))
FP16 = os.environ.get("COSYVOICE_FP16", "1").strip() not in ("", "0", "false", "False")
DEFAULT_REF = os.environ.get("COSYVOICE_DEFAULT_REF", "")            # 没传 ref_audio 时的默认音色 wav
VOICES_DIR = os.environ.get("COSYVOICE_VOICES_DIR", os.path.join(REPO, "voices"))

# CosyVoice 用包内相对资源 + Matcha-TTS 子模块 → sys.path + chdir 让其稳定可用。
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "third_party/Matcha-TTS"))
if os.path.isdir(REPO):
    os.chdir(REPO)

import torch  # noqa: E402
import torchaudio  # noqa: E402
from cosyvoice.cli.cosyvoice import CosyVoice2  # noqa: E402
from cosyvoice.utils.file_utils import load_wav  # noqa: E402

# 单标签情感 → instruct2 自然语言指令（中英同义）。识别不到=不加指令、走 cross_lingual 纯克隆。
_EMO_INSTR = {
    "happy": "Speak in a happy, cheerful tone.", "高兴": "用高兴的语气说这句话", "开心": "用开心的语气说这句话",
    "angry": "Speak in an angry, furious tone.", "愤怒": "用愤怒的语气说这句话", "生气": "用愤怒的语气说这句话",
    "sad": "Speak in a sad, sorrowful tone.", "悲伤": "用悲伤的语气说这句话", "难过": "用悲伤的语气说这句话",
    "afraid": "Speak in a fearful, trembling tone.", "害怕": "用害怕颤抖的语气说这句话",
    "surprised": "Speak in a surprised tone.", "惊讶": "用惊讶的语气说这句话",
    "calm": "Speak in a calm, composed tone.", "平静": "用平静沉稳的语气说这句话", "冷静": "用平静沉稳的语气说这句话",
}

print(f"[cosyvoice2-server] 加载模型… {MODEL_DIR} fp16={FP16}", flush=True)
_cosy = CosyVoice2(MODEL_DIR, load_jit=False, load_trt=False, load_vllm=False, fp16=FP16)
SR = _cosy.sample_rate     # 24000
_lock = threading.Lock()   # 单卡串行
print(f"[cosyvoice2-server] ✅ 就绪 SR={SR} default_ref={DEFAULT_REF!r} port={PORT}", flush=True)

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402
import uvicorn  # noqa: E402

app = FastAPI()


class TTSReq(BaseModel):
    text: str = ""
    ref_audio: str = ""
    voice_id: str = ""
    emotion: str = ""
    output: str = "/tmp/cosy_out.wav"


def _resolve_ref(ref_audio: str, voice_id: str) -> str:
    p = (ref_audio or "").strip()
    if p and os.path.exists(p):
        return p
    vid = (voice_id or "").strip()
    if vid:
        for cand in (os.path.join(VOICES_DIR, vid), os.path.join(VOICES_DIR, vid + ".wav"),
                     os.path.join(VOICES_DIR, vid + ".mp3")):
            if os.path.exists(cand):
                return cand
    return DEFAULT_REF if (DEFAULT_REF and os.path.exists(DEFAULT_REF)) else ""


@app.get("/v1/health")
def health():
    return {"status": "ok", "loaded": _cosy is not None, "sr": SR, "port": PORT}


@app.post("/v1/tts")
def tts(req: TTSReq):
    if not (req.text or "").strip():
        return {"status": "failed", "error": "text 为空"}
    ref = _resolve_ref(req.ref_audio, req.voice_id)
    if not ref:
        return {"status": "failed", "error": f"无参考音(ref_audio={req.ref_audio!r} voice_id={req.voice_id!r} 且无 DEFAULT_REF)"}
    try:
        with _lock:
            os.makedirs(os.path.dirname(req.output) or ".", exist_ok=True)
            emo = (req.emotion or "").strip()
            instr = _EMO_INSTR.get(emo.lower()) or _EMO_INSTR.get(emo)
            # CosyVoice2 最新 API 收【路径】(prompt_wav)，内部自己 load_wav(已 patch 成 soundfile 读，避开 torchcodec)。
            if instr:
                gen = _cosy.inference_instruct2(req.text, instr, ref, stream=False)
            else:
                gen = _cosy.inference_cross_lingual(req.text, ref, stream=False)
            chunks = [j["tts_speech"] for j in gen]
            if not chunks:
                return {"status": "failed", "error": "没生成音频块"}
            audio = torch.cat(chunks, dim=1)
            import soundfile as _sf      # 用 soundfile 写,避开 torchaudio.save 的 torchcodec 依赖
            _sf.write(req.output, audio.squeeze(0).detach().cpu().numpy(), SR)
        if not (os.path.exists(req.output) and os.path.getsize(req.output) > 1000):
            return {"status": "failed", "error": f"未生成有效 wav: {req.output}"}
        return {"status": "succeed", "output_path": req.output}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
