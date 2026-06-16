#!/usr/bin/env bash
# Colab 单机：下载出片全套模型到 ComfyUI/models/，幂等(已存在跳过)+ 下完即时扁平化(去掉 split_files/HighNoise 等子目录)。
# FLUX.1-dev / ae 是 gated：先 `hf auth login`(或设 HF_TOKEN 环境变量)。huggingface-cli 已废弃。
set -e
M=/content/ComfyUI/models
mkdir -p "$M"/{unet,checkpoints,clip,vae,audio_encoders,loras,pulid,insightface,diffusion_models,text_encoders,upscale_models,facerestore_models}

# 跳过闸只认扁平路径 $3/$base；hf 会按 repo 子目录(HighNoise/、split_files/..)存，
# 故下完立刻把文件挪到 $3/$base。即时扁平 = 中途被回收/打断时已下的也已就位，下次必 [skip]。
get() {  # repo  repo内路径  目标models子目录
  local base; base=$(basename "$2")
  if [ -s "$3/$base" ]; then echo "[skip] $base"; return; fi
  echo "[get ] $base"
  hf download "$1" "$2" --local-dir "$3" >/dev/null   # huggingface-cli 已废弃，用 hf
  if [ ! -s "$3/$base" ]; then                         # hf 存进了子目录 → 就地挪平
    # ★必须 find -L：models/<sub> 多是软链到 Drive，不加 -L 的 find 不会进软链目录，
    #   split_files/ 永远扁不平 → ComfyUI 列成 split_files/.. → 工作流名对不上 → 出片假跑超时。
    local got; got=$(find -L "$3" -type f -name "$base" 2>/dev/null | head -1)
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
# UNET-only 底模(默认;含 CivitAI 多数"checkpoint"其实是 UNET-only)需单独的 ae/t5xxl/clip_l。
# ae 用 FLUX.1-schnell(Apache,非 gated,与 dev 同一 VAE)→ 全程免 HF_TOKEN。t5xxl/clip_l 也公开。
# 真·全合一 checkpoint(自带 CLIP+VAE)才设 FLUX_BASE_KIND=checkpoint 跳过这三个。
if [ "$FLUX_BASE_KIND" != "checkpoint" ]; then
  get black-forest-labs/FLUX.1-schnell ae.safetensors    "$M/vae"       # 非 gated,免 HF_TOKEN
  get comfyanonymous/flux_text_encoders t5xxl_fp16.safetensors "$M/clip"
  get comfyanonymous/flux_text_encoders clip_l.safetensors     "$M/clip"
fi

# ── Wan2.2-I2V-A14B 双专家 —— 精度档由 I2V_PRECISION 决定(笔记本第1格按 GPU 自动设)──
#    fp16=A100 原生满精度(各~28G,走 i2v_bf16_template.json);
#    fp8 =H100/Ada 原生FP8(各~14G,又快又省,走 i2v_fp8_template.json)。默认 fp16。
I2V_PRECISION="${I2V_PRECISION:-fp16}"
if [ "$I2V_PRECISION" = "fp8" ]; then
  echo "[download] i2v 档 = fp8_scaled(原生FP8 卡;文本编码器用下方 fp8 umt5)"
  get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors "$M/unet"
  get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors  "$M/unet"
else
  echo "[download] i2v 档 = fp16 原生满精度"
  get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp16.safetensors "$M/unet"
  get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp16.safetensors  "$M/unet"
  get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/text_encoders/umt5_xxl_fp16.safetensors "$M/clip"
fi
# <24G 卡才用 GGUF Q5_K_M(各~10.8G,逐步反量化、慢);指回 i2v_gguf_template.json：
# get QuantStack/Wan2.2-I2V-A14B-GGUF HighNoise/Wan2.2-I2V-A14B-HighNoise-Q5_K_M.gguf "$M/unet"
# get QuantStack/Wan2.2-I2V-A14B-GGUF LowNoise/Wan2.2-I2V-A14B-LowNoise-Q5_K_M.gguf   "$M/unet"
# umt5 fp8(S2V 对口型必用;也是 i2v fp8 回退档的文本编码器)——保留下载。
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors "$M/clip"

# ── (可选) LTX-Video 2.3 权重：与 Wan2.2 并列的「快/音视频一体」档。默认不下(22B+Gemma 很大)。需要才 export DOWNLOAD_LTX=1。──
# ★前提同 setup：LTX 2.3 要 ComfyUI v0.16+。下方文件名/仓库以官方 Lightricks/LTX-2.3 + v0.16+ 官方模板实际为准；
#   每条都做成非致命(|| echo)：万一文件名随版本变了也绝不中断 Wan/FLUX 的下载。下完按 ltx_i2v_template.json 核对。
if [ "${DOWNLOAD_LTX:-0}" = "1" ]; then
  echo "[download] LTX-Video 2.3（dev fp8；可选蒸馏档；Gemma3 文本编码器）—— 文件名以官方模板为准"
  get Lightricks/LTX-2.3 ltx-2.3-22b-dev-fp8.safetensors "$M/checkpoints" || echo "[download] ⚠️ LTX dev-fp8 没下到(核对 Lightricks/LTX-2.3 实际文件名)"
  get Lightricks/LTX-2.3 ltx-2.3-22b-distilled.safetensors "$M/checkpoints" || echo "[download] (跳过)LTX 蒸馏档为可选"
  echo "[download] ⚠️ LTX 文本编码器是 Gemma 3 12B(非 umt5)：请按 ComfyUI v0.16+ 官方 LTX 模板里的确切文件名/仓库，把它下到 $M/text_encoders(本脚本不臆测仓库名，免下错)"
fi
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/vae/wan2.2_vae.safetensors "$M/vae"

# ── Wan2.2-S2V 对口型(可选；不做对口型可注释掉这3行)──
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_s2v_14B_fp8_scaled.safetensors "$M/unet"
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/vae/wan_2.1_vae.safetensors "$M/vae"
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors "$M/audio_encoders"

# ── PuLID-Flux 单脸自举(免上传训 LoRA：1 张脸→批量同人图)。EVA-CLIP / insightface antelopev2
#    由 ComfyUI_PuLID_Flux_ll 节点首跑自动拉，这里只下 pulid_flux 权重(~1.1G，幂等)。不做单脸自举可注释。──
PW="$M/pulid/pulid_flux_v0.9.1.safetensors"
if [ -s "$PW" ]; then echo "[skip] pulid_flux_v0.9.1.safetensors"; else
  echo "[get ] pulid_flux_v0.9.1.safetensors"
  wget -q -O "$PW" https://huggingface.co/guozinan/PuLID/resolve/main/pulid_flux_v0.9.1.safetensors || echo "[warn] PuLID 权重下载失败(单脸自举才需要，可忽略)"
fi

# ── Wan2.2-Lightning 4步加速 LoRA(极速档用;i2v 高/低噪各一个,放 loras/)。各 ~0.7G。不用极速档可注释这两行。──
get lightx2v/Wan2.2-Distill-Loras wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors "$M/loras"
get lightx2v/Wan2.2-Distill-Loras wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors  "$M/loras"

# ── 画质增强:RealESRGAN_x2 视频放大模型(COMFYUI_WORKFLOW_POST=post_upscale 才用;~64MB)。不放大可注释。──
get ai-forever/Real-ESRGAN RealESRGAN_x2.pth "$M/upscale_models"

# ── (可选) 视频换脸 ReActor 模型。默认不下;需要才 export DOWNLOAD_FACESWAP=1。──
# inswapper_128.onnx→insightface/(~530MB,核心换脸);GFPGANv1.4.pth→facerestore_models/(可选修脸);
# 人脸检测包 buffalo_l 由 insightface 首跑自动下到 /root/.insightface(cell5 已软链 Drive 持久化)。
if [ "${DOWNLOAD_FACESWAP:-0}" = "1" ]; then
  mkdir -p "$M/facerestore_models"
  if [ -s "$M/insightface/inswapper_128.onnx" ]; then echo "[skip] inswapper_128.onnx"; else
    echo "[get ] inswapper_128.onnx"
    wget -q -O "$M/insightface/inswapper_128.onnx" \
      https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/inswapper_128.onnx \
      || echo "[warn] inswapper_128.onnx 下载失败(换脸才需要)"
  fi
  if [ -s "$M/facerestore_models/GFPGANv1.4.pth" ]; then echo "[skip] GFPGANv1.4.pth"; else
    echo "[get ] GFPGANv1.4.pth"
    wget -q -O "$M/facerestore_models/GFPGANv1.4.pth" \
      https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/facerestore_models/GFPGANv1.4.pth \
      || echo "[warn] GFPGAN 下载失败(修脸可选;.env 设 FACESWAP_RESTORE_MODEL=none 也能跑)"
  fi
fi

# ── 兜底校验：get() 已逐个即时扁平；这里再扫一遍，发现仍埋在子目录的(如旧会话遗留)补挪并报警 ──
# ★find -L：models/<sub> 是软链到 Drive，不加 -L 扫不进软链 → 漏掉 split_files/ 里的文件（本次大坑根因）。
stray=$(find -L "$M" -mindepth 2 -type f \( -name '*.safetensors' -o -name '*.gguf' \) 2>/dev/null || true)
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
