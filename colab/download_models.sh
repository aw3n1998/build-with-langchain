#!/usr/bin/env bash
# Colab 单机：下载出片全套模型到 ComfyUI/models/，幂等(已存在跳过)+ 下载后扁平化(去掉 split_files/HighNoise 等子目录)。
# FLUX.1-dev / ae 是 gated：先 `huggingface-cli login`(或设 HF_TOKEN 环境变量)。
set -e
M=/content/ComfyUI/models
mkdir -p "$M"/{unet,clip,vae,audio_encoders,loras,pulid,diffusion_models,text_encoders}

get() {  # repo  repo内路径  目标models子目录
  local base; base=$(basename "$2")
  if [ -s "$3/$base" ]; then echo "[skip] $base"; return; fi
  echo "[get ] $base"
  hf download "$1" "$2" --local-dir "$3" >/dev/null   # huggingface-cli 已废弃，用 hf
}

# ── FLUX 出图(gated，需 HF token)──
get black-forest-labs/FLUX.1-dev flux1-dev.safetensors "$M/unet"
get black-forest-labs/FLUX.1-dev ae.safetensors        "$M/vae"
get comfyanonymous/flux_text_encoders t5xxl_fp16.safetensors "$M/clip"
get comfyanonymous/flux_text_encoders clip_l.safetensors     "$M/clip"

# ── Wan2.2-I2V-A14B 双专家 GGUF(Q5_K_M，各 ~10.8GB)──
get QuantStack/Wan2.2-I2V-A14B-GGUF HighNoise/Wan2.2-I2V-A14B-HighNoise-Q5_K_M.gguf "$M/unet"
get QuantStack/Wan2.2-I2V-A14B-GGUF LowNoise/Wan2.2-I2V-A14B-LowNoise-Q5_K_M.gguf   "$M/unet"
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors "$M/clip"
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/vae/wan2.2_vae.safetensors "$M/vae"

# ── Wan2.2-S2V 对口型(可选；不做对口型可注释掉这3行)──
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_s2v_14B_fp8_scaled.safetensors "$M/unet"
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/vae/wan_2.1_vae.safetensors "$M/vae"
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors "$M/audio_encoders"

# ── 扁平化：HF 会保留 repo 子目录(split_files/.. 、HighNoise/..)，挪到 models/<dir> 根，ComfyUI 才列得出 ──
find "$M" -mindepth 2 -type f \( -name '*.safetensors' -o -name '*.gguf' \) | while read -r f; do
  top=$(echo "$f" | sed -E "s#($M/[^/]+)/.*#\1#")
  base=$(basename "$f")
  [ "$f" != "$top/$base" ] && mv -f "$f" "$top/$base"
done
find "$M" -type d -empty -delete 2>/dev/null || true
echo "[download] 模型就绪 + 已扁平化"
ls -lh "$M"/unet "$M"/clip "$M"/vae "$M"/audio_encoders 2>/dev/null
