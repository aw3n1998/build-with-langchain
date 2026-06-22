"""CosyVoice2 包装 server —— load-once HTTP TTS（克隆 + 情感），用来替代 edge-tts 当默认/保底引擎。

契约与 colab/indextts2_server.py 完全一致（后端 tts_providers/cosyvoice2.py 照打）：
  POST /v1/tts  {text, ref_audio(同机本地路径=克隆音色), voice_id(音色库,可选), emotion, output(同机输出wav)}
                -> {"status":"succeed","output_path": output}
  GET  /v1/health -> {"status":"ok","loaded":bool,"sr":int,"port":int}

CosyVoice2-0.5B 不带内置预置音 → 没传 ref_audio 时用 COSYVOICE_DEFAULT_REF 当默认音色。
★参考音必须与目标语言同语种：中文输出务必用【中文母语】参考音，否则 cross_lingual 会把参考音的
英文音素/口音迁到中文文本上 → 中文里混英文（这正是之前用英文 LibriVox 参考音的根因）。
克隆默认走 inference_cross_lingual（不需转写文本）；若设了 COSYVOICE_DEFAULT_REF_TEXT（默认音的转写）
则默认音走 inference_zero_shot（给中文锚点，更纯）；情感用 inference_instruct2（指令一律中文，避免英文指令串进语音）。
"""

import os
import sys
import threading
import traceback

REPO = os.environ.get("COSYVOICE_REPO", "/ephemeral/cosyvoice2/CosyVoice")
MODEL_DIR = os.environ.get("COSYVOICE_MODEL_DIR", "/ephemeral/cosyvoice2/CosyVoice2-0.5B")
PORT = int(os.environ.get("COSYVOICE_PORT", "8193"))
FP16 = os.environ.get("COSYVOICE_FP16", "1").strip() not in ("", "0", "false", "False")
DEFAULT_REF = os.environ.get("COSYVOICE_DEFAULT_REF", "")            # 没传 ref_audio 时的默认音色 wav（中文输出须为中文母语音）
DEFAULT_REF_TEXT = os.environ.get("COSYVOICE_DEFAULT_REF_TEXT", "").strip()  # 设了=DEFAULT_REF 走 zero_shot（该音转写文本当中文锚点，更纯中文）
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

# 单标签情感 → instruct2 自然语言指令。★指令一律中文：英文指令会被 instruct2 串进中文语音里。
# 英文情感 key 也映射到中文指令（上游标签常是英文如 happy/angry），lower() 先匹配也只会拿到中文。
_EMO_INSTR = {
    "happy": "用高兴愉快的语气说这句话", "高兴": "用高兴愉快的语气说这句话", "开心": "用开心的语气说这句话",
    "angry": "用愤怒的语气说这句话", "愤怒": "用愤怒的语气说这句话", "生气": "用愤怒的语气说这句话",
    "sad": "用悲伤的语气说这句话", "悲伤": "用悲伤的语气说这句话", "难过": "用悲伤的语气说这句话",
    "afraid": "用害怕颤抖的语气说这句话", "害怕": "用害怕颤抖的语气说这句话",
    "surprised": "用惊讶的语气说这句话", "惊讶": "用惊讶的语气说这句话",
    "calm": "用平静沉稳的语气说这句话", "平静": "用平静沉稳的语气说这句话", "冷静": "用平静沉稳的语气说这句话",
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
            elif DEFAULT_REF_TEXT and ref == DEFAULT_REF:
                # 默认音有转写 → zero_shot：给中文锚点，比 cross_lingual 更不易串语种。
                gen = _cosy.inference_zero_shot(req.text, DEFAULT_REF_TEXT, ref, stream=False)
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
