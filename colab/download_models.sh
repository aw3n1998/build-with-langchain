#!/usr/bin/env bash
# Colab 单机：下载出片全套模型到 ComfyUI/models/，幂等(已存在跳过)+ 下完即时扁平化(去掉 split_files/HighNoise 等子目录)。
# FLUX.1-dev / ae 是 gated：先 `hf auth login`(或设 HF_TOKEN 环境变量)。huggingface-cli 已废弃。
set -e
M=/content/ComfyUI/models
mkdir -p "$M"/{unet,clip,vae,audio_encoders,loras,pulid,diffusion_models,text_encoders}

# 跳过闸只认扁平路径 $3/$base；hf 会按 repo 子目录(HighNoise/、split_files/..)存，
# 故下完立刻把文件挪到 $3/$base。即时扁平 = 中途被回收/打断时已下的也已就位，下次必 [skip]。
get() {  # repo  repo内路径  目标models子目录
  local base; base=$(basename "$2")
  if [ -s "$3/$base" ]; then echo "[skip] $base"; return; fi
  echo "[get ] $base"
  hf download "$1" "$2" --local-dir "$3" >/dev/null   # huggingface-cli 已废弃，用 hf
  if [ ! -s "$3/$base" ]; then                         # hf 存进了子目录 → 就地挪平
    local got; got=$(find "$3" -type f -name "$base" 2>/dev/null | head -1)
    [ -n "$got" ] && mv -f "$got" "$3/$base"
  fi
  find "$3" -mindepth 1 -type d -empty -delete 2>/dev/null || true
}

# ── 出图底模：Chroma1-HD(开放无审查 FLUX 系，A100 友好，~17GB；已替代 flux1-dev)──
get lodestones/Chroma1-HD Chroma1-HD.safetensors "$M/unet"
# flux1-dev 底模已弃用(换 Chroma)；要回退取消下一行注释即可：
# get black-forest-labs/FLUX.1-dev flux1-dev.safetensors "$M/unet"
# Chroma 复用 FLUX 的 VAE(ae，gated 需 HF token) 与 T5；clip_l 仅旧 flux 模板用，Chroma 不需要(留下无害)
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

# ── 兜底校验：get() 已逐个即时扁平；这里再扫一遍，发现仍埋在子目录的(如旧会话遗留)补挪并报警 ──
stray=$(find "$M" -mindepth 2 -type f \( -name '*.safetensors' -o -name '*.gguf' \) 2>/dev/null || true)
if [ -n "$stray" ]; then
  echo "[warn] 仍有模型在子目录，补一次扁平化："
  echo "$stray" | while read -r f; do
    rel=${f#"$M"/}; top="$M/${rel%%/*}"; base=$(basename "$f")
    [ "$f" != "$top/$base" ] && { echo "  mv  $rel  ->  ${rel%%/*}/$base"; mv -f "$f" "$top/$base"; }
  done
  find "$M" -mindepth 1 -type d -empty -delete 2>/dev/null || true
fi
echo "[download] 模型就绪 + 已扁平化"
ls -lh "$M"/unet "$M"/clip "$M"/vae "$M"/audio_encoders 2>/dev/null
