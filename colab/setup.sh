#!/usr/bin/env bash
# Colab 单机：装 ComfyUI + 出片/出图/对口型所需自定义节点。幂等(已存在则 git pull)。
# Wan2.2 的 WanImageToVideo / WanSoundImageToVideo / AudioEncoder* 近版 ComfyUI 核心自带，无需 WanVideoWrapper。
set -e
cd /content
# ComfyUI 钉版本(关键):主线(v0.4+/v0.8+)依赖 comfy_kitchen,要 torch≥2.4(torch.library.custom_op)，
# 在 Colab 原装 torch 上 import 直接崩。v0.3.75(2025-11-26)已含 Wan2.2 i2v/s2v 原生节点 +
# fp8/GGUF/Lightning 全支持，且其 quant_ops 不用 custom_op、不依赖 comfy_kitchen → 用原装 torch 即可跑。
# 要升级新 ComfyUI:先确保 torch≥2.4，再 export COMFY_REF=master(或某新 tag) 覆盖本默认。
COMFY_REF="${COMFY_REF:-v0.3.75}"
_cur="$( [ -f ComfyUI/main.py ] && (cd ComfyUI && git describe --tags --always 2>/dev/null) || echo none )"
if [ "$_cur" != "$COMFY_REF" ]; then
  echo "[setup] ComfyUI → 钉定 $COMFY_REF (当前: $_cur)"
  rm -rf ComfyUI
  git clone --depth 1 --branch "$COMFY_REF" https://github.com/comfyanonymous/ComfyUI
fi
pip -q install -r ComfyUI/requirements.txt

cd ComfyUI/custom_nodes
clone_or_pull() { d=$(basename "$1"); if [ -d "$d" ]; then (cd "$d" && git pull -q || true); else git clone --depth 1 -q "$1"; fi; }
clone_or_pull https://github.com/city96/ComfyUI-GGUF              # UnetLoaderGGUF(A14B 双专家 GGUF)
clone_or_pull https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite  # VHS_VideoCombine(出片合成)
# 以下仅 LoRA 数据集自举(PuLID)用；纯出片主线可不装：
clone_or_pull https://github.com/lldacing/ComfyUI_PuLID_Flux_ll

# ── (可选) LTX-Video 2.3：与 Wan2.2 并列的「快/音视频一体」出片档。默认关(export SETUP_LTX=1 开)。──
# ★前提：LTX 2.3 需 ComfyUI v0.16+（强制 torch≥2.4）；本脚本默认 COMFY_REF=v0.3.75 跑不了 LTX。
#   用 LTX 要先：确保 torch≥2.4 → `export COMFY_REF=v0.16.1`(或更高) 重跑本 setup → `export SETUP_LTX=1`。
#   基础 i2v 在 v0.16+ 核心自带；这个包是官方增强节点(IC-LoRA/超分/对口型)，按需装。
if [ "${SETUP_LTX:-0}" = "1" ]; then
  echo "[setup] 装 LTX-Video 2.3 官方增强节点 ComfyUI-LTXVideo"
  clone_or_pull https://github.com/Lightricks/ComfyUI-LTXVideo || echo "[setup] LTX 节点拉取失败(不影响 Wan)"
  [ -f ComfyUI-LTXVideo/requirements.txt ] && pip -q install -r ComfyUI-LTXVideo/requirements.txt || true
fi

for r in ComfyUI-GGUF ComfyUI-VideoHelperSuite ComfyUI_PuLID_Flux_ll; do
  [ -f "$r/requirements.txt" ] && pip -q install -r "$r/requirements.txt" || true
done
pip -q install facexlib onnxruntime-gpu insightface facenet_pytorch || true   # PuLID 依赖(可选;facenet_pytorch 给 lldacing 版的 MTCNN)

# ── SageAttention：出片提速 ~2×(实测把 Wan2.2-A14B 720p 从 58→22 s/step)。装上 cell5 才会带 --use-sage-attention ──
# 优先 v2 现场编译(Colab 自带 nvcc,约几分钟);失败退纯 Triton 的 1.0.6(免编译、稍慢但稳);都失败也不影响出片。
cd /content
pip -q install -U triton || true
pip -q install sageattention==2.2.0 --no-build-isolation \
  || pip -q install sageattention==1.0.6 \
  || echo "[setup] SageAttention 未装上(出片仍可用,只是少了那 ~2x 注意力提速)"
python -c "import sageattention" 2>/dev/null && echo "[setup] SageAttention OK" || echo "[setup] 无 SageAttention(将走普通注意力)"

echo "[setup] ComfyUI + 节点就绪"
