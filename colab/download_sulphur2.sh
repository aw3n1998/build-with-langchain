#!/usr/bin/env bash
# Sulphur 2（LTX-2.3 无审查 fine-tune）单机部署：下模型 + 装 ComfyUI 自定义节点。
# ★Sulphur/LTX-2.3 需 ComfyUI v0.16+（torch≥2.4），与 Wan 钉的 v0.3.75 不能共存——本仓是 Sulphur 专用 fork，
#   其 ComfyUI 直接装 v0.16+。装完把后端 .env 配 SULPHUR2_BASE_URL 指向这个 ComfyUI 即可。
# 幂等：已存在跳过。文件名/仓库都用 env 可覆盖（HF 上具体量化名/VAE/文本编码器名以 Sulphur 官方为准，先核对再跑）。
set -e
COMFY="${COMFYUI_DIR:-/content/ComfyUI}"
M="$COMFY/models"
mkdir -p "$M"/{unet,vae,text_encoders,loras,checkpoints}

get() {  # repo  repo内路径  目标models子目录   —— hf 下载 + 扁平化 + 跳过已存在
  local base; base=$(basename "$2")
  if [ -s "$3/$base" ]; then echo "[skip] $base"; return; fi
  echo "[get ] $base  ←  $1/$2"
  hf download "$1" "$2" --local-dir "$3" >/dev/null
  if [ ! -s "$3/$base" ]; then
    local got; got=$(find -L "$3" -type f -name "$base" 2>/dev/null | head -1)
    [ -n "$got" ] && mv -f "$got" "$3/$base"
  fi
  find "$3" -mindepth 1 -type d -empty -delete 2>/dev/null || true
}

# ── 1) Sulphur 2 主模型（GGUF；5090 32G 用 Q8，显存小可换 Q5/Q4，名见 HF vantagewithai/Sulphur-2-Base-GGUF）──
SULPHUR_GGUF_REPO="${SULPHUR_GGUF_REPO:-vantagewithai/Sulphur-2-Base-GGUF}"
SULPHUR_GGUF_FILE="${SULPHUR_GGUF_FILE:-Sulphur-2-Base-Q8_0.gguf}"   # 与 sulphur_*_template.json 的 unet_name 对齐
get "$SULPHUR_GGUF_REPO" "$SULPHUR_GGUF_FILE" "$M/unet"
# 模板里 unet_name 默认是 sulphur-2-base-Q8_0.gguf；若实际名不同，改模板或在此 mv 对齐
[ -s "$M/unet/$SULPHUR_GGUF_FILE" ] && [ ! -s "$M/unet/sulphur-2-base-Q8_0.gguf" ] && \
  cp -f "$M/unet/$SULPHUR_GGUF_FILE" "$M/unet/sulphur-2-base-Q8_0.gguf" || true

# ── 2) LTX VAE（Sulphur 不带，须从 Lightricks LTX-Video 仓单独下；文件名以官方为准）──
LTX_VAE_REPO="${LTX_VAE_REPO:-Lightricks/LTX-Video}"
LTX_VAE_FILE="${LTX_VAE_FILE:-ltxv-2.3-vae.safetensors}"      # ★核对官方实际文件名；放 models/vae
get "$LTX_VAE_REPO" "$LTX_VAE_FILE" "$M/vae"
[ -s "$M/vae/$(basename "$LTX_VAE_FILE")" ] && [ ! -s "$M/vae/ltx_vae.safetensors" ] && \
  cp -f "$M/vae/$(basename "$LTX_VAE_FILE")" "$M/vae/ltx_vae.safetensors" || true

# ── 3) LTX-2 文本编码器（LTX-2 用 Gemma3；具体仓/文件以 Sulphur 官方工作流为准）──
LTX_TE_REPO="${LTX_TE_REPO:-Lightricks/LTX-Video}"
LTX_TE_FILE="${LTX_TE_FILE:-gemma_3_12B_it_fp4_mixed.safetensors}"  # ★核对；放 models/text_encoders
get "$LTX_TE_REPO" "$LTX_TE_FILE" "$M/text_encoders" || \
  echo "[warn] 文本编码器没下到：请按 Sulphur 官方工作流核对仓/文件名后手下到 $M/text_encoders"

# ── 4) ComfyUI 自定义节点（GGUF 加载 / LTX 节点 / 视频封装）──
CN="$COMFY/custom_nodes"; mkdir -p "$CN"
clone() { local d="$CN/$(basename "$1" .git)"; [ -d "$d" ] && echo "[skip node] $(basename "$d")" || { echo "[node] $(basename "$d")"; git clone --depth 1 "$1" "$d" >/dev/null 2>&1 || echo "[warn] clone 失败 $1"; }; }
clone https://github.com/city96/ComfyUI-GGUF.git
clone https://github.com/Lightricks/ComfyUI-LTXVideo.git
clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git

echo
echo "✅ Sulphur 2 模型/节点就绪（核对上面 [warn] 提示）。"
echo "   起 ComfyUI v0.16+ 后，后端 .env 配 SULPHUR2_BASE_URL=http://127.0.0.1:8188（或你的端口）。"
echo "   首次真跑前：从 Sulphur 官方下 t2v/i2v 工作流，导出 API 格式，替换 comfyui_workflows/sulphur_{t2v,i2v}_template.json（保留 %占位符%）。"
