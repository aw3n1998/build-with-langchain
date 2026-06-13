# -*- coding: utf-8 -*-
"""真机联调：蜃景 本机 → 远程 ComfyUI 跑一条真实 S2V 对口型片(造测试图+TTS→上传→出片→下载)。"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = os.path.join(os.path.dirname(__file__), "..", "bench_out")
os.makedirs(OUT, exist_ok=True)

# 1) 造一张测试人物图（粗糙脸即可，测的是链路不是画质）
img = os.path.join(OUT, "s2v_face.png")
try:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (512, 768), (55, 65, 85)); d = ImageDraw.Draw(im)
    d.ellipse([150, 170, 362, 430], fill=(214, 184, 165))
    d.ellipse([200, 260, 244, 304], fill=(35, 35, 35)); d.ellipse([268, 260, 312, 304], fill=(35, 35, 35))
    d.rectangle([228, 366, 284, 386], fill=(120, 60, 60))
    im.save(img); print("test image via PIL ->", img)
except Exception as e:
    print("PIL 不可用，写最小 png:", e)
    open(img, "wb").write(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000200000003000806000000"
        "b3a4f9b80000000d4944415478daedc101010000008090fe2f6e48400000"
        "0000000000000000c0b700010000018f5b8d2c0000000049454e44ae426082"))

# 2) TTS 生成测试音频
from mirage.app.pipeline.assembler import _tts
aud = os.path.join(OUT, "s2v_voice.mp3")
ok = _tts("你好，这是一段对口型测试。", aud, "zh-CN-YunxiNeural")
print("tts ok=", ok, "size=", os.path.getsize(aud) if os.path.exists(aud) else 0)
if not ok:
    print("TTS 失败，无法继续 S2V 测试"); sys.exit(1)

# 3) 跑 S2V（低参数求快；这是 14B，首次还要载模型，耐心几分钟）
from mirage.app.pipeline.providers.comfyui_s2v import ComfyUIS2VProvider
from mirage.app.core.config import settings
print("endpoint:", settings.COMFYUI_BASE_URL[:55])
prov = ComfyUIS2VProvider()
outp = os.path.join(OUT, "s2v_out.mp4")
if os.path.exists(outp):
    os.remove(outp)
t0 = time.time()
try:
    prov.generate(None, image_path=img,
                  prompt="a person speaking to camera, calm expression, slight natural head motion",
                  out_remote=outp,
                  params={"audio_path": aud, "size": "480*832", "frames": 49, "steps": 10, "fps": 16, "seed": 1})
    print(f"=== [OK] S2V 出片成功 {round(time.time()-t0)}s, 大小 {os.path.getsize(outp)} bytes -> {outp} ===")
except Exception as e:
    print(f"=== [FAIL] S2V 失败({round(time.time()-t0)}s): {type(e).__name__}: {e} ===")
    sys.exit(2)
