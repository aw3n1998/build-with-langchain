#!/usr/bin/env bash
# Colab 单机：下载出片全套模型到 ComfyUI/models/，幂等(已存在跳过)+ 下完即时扁平化(去掉 split_files/HighNoise 等子目录)。
# FLUX.1-dev / ae 是 gated：先 `hf auth login`(或设 HF_TOKEN 环境变量)。huggingface-cli 已废弃。
set -e
M=/content/ComfyUI/models
mkdir -p "$M"/{unet,checkpoints,clip,vae,audio_encoders,loras,pulid,diffusion_models,text_encoders}

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

# ── 出图底模（可配：换底模只设这几个 env，不改代码）──
#   HF UNET-only:     export FLUX_BASE_REPO=org/name  FLUX_BASE_FILE=xxx.safetensors
#   CivitAI 全合一:    export FLUX_BASE_URL=https://civitai.com/api/download/models/<版本号>?token=<你的CivitaiKey>
#                      export FLUX_BASE_FILE=xxx.safetensors  FLUX_BASE_KIND=checkpoint
#   都不设 → 默认下 flux1-dev（UNET-only 兜底）。
FLUX_BASE_REPO="${FLUX_BASE_REPO:-black-forest-labs/FLUX.1-dev}"
FLUX_BASE_FILE="${FLUX_BASE_FILE:-flux1-dev.safetensors}"
FLUX_BASE_URL="${FLUX_BASE_URL:-}"
FLUX_BASE_KIND="${FLUX_BASE_KIND:-unet}"   # unet=UNET-only(flux 模板) | checkpoint=全合一(CivitAI 如 Fluxed Up)
BASE_DIR="$M/unet"; [ "$FLUX_BASE_KIND" = "checkpoint" ] && BASE_DIR="$M/checkpoints"
mkdir -p "$BASE_DIR"
if [ -s "$BASE_DIR/$FLUX_BASE_FILE" ]; then
  echo "[skip] $FLUX_BASE_FILE"
elif [ -n "$FLUX_BASE_URL" ]; then
  echo "[get url] $FLUX_BASE_FILE → $FLUX_BASE_KIND"
  wget -q -O "$BASE_DIR/$FLUX_BASE_FILE" "$FLUX_BASE_URL"
  # 直链失败常见:存成了 HTML 错误页(token/URL 错)。体积过小就报警。
  sz=$(stat -c%s "$BASE_DIR/$FLUX_BASE_FILE" 2>/dev/null || echo 0)
  [ "$sz" -lt 1000000 ] && echo "[warn] $FLUX_BASE_FILE 只有 ${sz}B,八成是 token/URL 错下成了错误页,请核对 FLUX_BASE_URL"
else
  get "$FLUX_BASE_REPO" "$FLUX_BASE_FILE" "$BASE_DIR"
fi
# FLUX 系底模共用的 VAE(ae，gated 需 HF token) + 文本编码器(t5xxl + clip_l，flux t2i 模板用 DualCLIP)
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
