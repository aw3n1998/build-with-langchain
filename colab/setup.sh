#!/usr/bin/env bash
# Colab 单机：装 ComfyUI + 出片/出图/对口型所需自定义节点。幂等(已存在则 git pull)。
# Wan2.2 的 WanImageToVideo / WanSoundImageToVideo / AudioEncoder* 近版 ComfyUI 核心自带，无需 WanVideoWrapper。
set -e
cd /content
# 自愈：只有 ComfyUI/main.py 在才算装好；否则(空壳/残缺)清掉重 clone
[ -f ComfyUI/main.py ] || { rm -rf ComfyUI; git clone --depth 1 https://github.com/comfyanonymous/ComfyUI; }
pip -q install -r ComfyUI/requirements.txt

cd ComfyUI/custom_nodes
clone_or_pull() { d=$(basename "$1"); if [ -d "$d" ]; then (cd "$d" && git pull -q || true); else git clone --depth 1 -q "$1"; fi; }
clone_or_pull https://github.com/city96/ComfyUI-GGUF              # UnetLoaderGGUF(A14B 双专家 GGUF)
clone_or_pull https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite  # VHS_VideoCombine(出片合成)
# 以下仅 LoRA 数据集自举(PuLID)用；纯出片主线可不装：
clone_or_pull https://github.com/lldacing/ComfyUI_PuLID_Flux_ll

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
