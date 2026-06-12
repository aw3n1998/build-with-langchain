# 在 Colab(A100)上跑 AgentLab 视频方案

一个 Colab notebook 同时拉起 **ComfyUI(GPU) + AgentLab 编排器 + 前端 UI**,把整条
「小说→分镜→FLUX 出图→Wan2.2 图生视频→(可选)Wan2.2-S2V 对口型→合成成片」流水线跑在 Colab 上。

打开 [`agentlab_video_colab.ipynb`](./agentlab_video_colab.ipynb) → 上传到 Google Colab → 运行时选 **A100** → 从上到下逐格运行。

---

## 架构(为什么这么接)

仓库出视频有两条后端路径:
- **SSH 路径**(`gpu_client.py`):直接 SSH 进 GPU 机跑脚本——为 AutoDL 4090 设计,Colab 不允许入站 SSH,不走这条。
- **ComfyUI HTTP 路径**(`comfy_http.py`):框架通过 HTTP 把 workflow 提交给任意机器上的 ComfyUI——**这就是 Colab 方案走的路**。

拓扑(全在一个 Colab 内,只暴露一个隧道):

```
你的浏览器 ──cloudflared──> 前端 Vite(5173) ──/api 代理──> AgentLab API(8000)
                                                              │  COMFYUI_BASE_URL
                                                              ▼
                                                        ComfyUI(8188, 本机 GPU)
                                                        ├─ t2i  FLUX.1-dev
                                                        ├─ i2v  Wan2.2-I2V-14B (GGUF)
                                                        └─ s2v  Wan2.2-S2V-14B + wav2vec2 + edge-tts
```

`COMFYUI_VIDEO_AS=auto` / `COMFYUI_IMAGE_AS=auto` 让用户面板里选的 FLUX / Wan2.2 **透明走 ComfyUI**,
UI 上不出现「ComfyUI」字样。对口型(S2V)由每镜「对口型」开关自动路由。

---

## 用到的模型 / 下载来源

| 环节 | 文件名(对齐 workflow 模板) | 目录 | HF 仓库 |
|---|---|---|---|
| 出图 FLUX | `flux1-dev.safetensors` | `models/diffusion_models` | `black-forest-labs/FLUX.1-dev` ⚠️gated |
| | `ae.safetensors` | `models/vae` | 同上 |
| | `t5xxl_fp16.safetensors` `clip_l.safetensors` | `models/clip` | `comfyanonymous/flux_text_encoders` |
| 出片 Wan2.2 i2v | `wan2.2-i2v-14B-Q4_K_M.gguf` | `models/unet` | `QuantStack/Wan2.2-I2V-A14B-GGUF`(LowNoise) |
| | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `models/clip` | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` |
| | `wan2.2_vae.safetensors` | `models/vae` | 同上 |
| 对口型 S2V | `wan2.2_s2v_14B_fp8_scaled.safetensors` | `models/diffusion_models` | 同上 |
| | `wan_2.1_vae.safetensors` | `models/vae` | 同上 |
| | `wav2vec2_large_english_fp16.safetensors` | `models/audio_encoders` | 同上 |

> **FLUX.1-dev 是 gated**:先去 https://huggingface.co/black-forest-labs/FLUX.1-dev 同意协议,
> 再在 notebook 第 0 格填 `HF_TOKEN`。总下载量约 **70GB**,建议开 Drive 缓存(断连免重下)。

LLM(deepseek-chat/gpt-4o)与配音 edge-tts 走云,不吃 GPU。

---

## 关于 Wan2.2-14B 与显存

Wan2.2-I2V-**A14B 是 MoE**(high-noise + low-noise 两专家,fp16 合计 ~54GB),A100 40GB 一次装不下两个。
本方案默认走 **GGUF 量化 + 单专家(LowNoise 精修)**,跑得稳、出错点少,适合先跑通。
若要**满血两专家**质量,见下。

### 升级:两专家(high/low noise)i2v

ComfyUI 官方 Wan2.2 14B 范式是 `两个 UnetLoaderGGUF + 两段 KSamplerAdvanced`(高噪专家跑前一半步、
低噪专家跑后一半步)。本仓的占位符填充器不会做算术,**步数边界要写死**,所以这条工作流需手工导出:

1. 第 4 格额外下 HighNoise GGUF:
   `QuantStack/Wan2.2-I2V-A14B-GGUF` 里 `HighNoise/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf`
   → 放 `models/unet/wan2.2-i2v-14B-HighNoise-Q4_K_M.gguf`。
2. 在 ComfyUI 网页里搭官方两专家 i2v 图(KSamplerAdvanced #1 高噪 `start=0,end=10,leftover_noise=enable`;
   #2 低噪 `start=10,end=10000`,steps 都设 20),把 `%IMAGE%/%PROMPT%/%NEG_PROMPT%/%WIDTH%/%HEIGHT%/%FRAMES%/%SEED%/%FPS%` 填进对应节点。
3. 设置→Enable Dev mode→Save(API Format)导出 JSON,存为 `comfyui_workflows/colab/i2v_2expert.json`。
4. 第 5 格把 `COMFYUI_WORKFLOW_I2V` 指过去,重跑写 .env + 重启 API。

> 边界写死的代价:之后改 `VIDEO_STEPS` 要同步改工作流里的 `end_at_step`。单专家版没这限制。

---

## 已知限制 / 诚实说明

- 搭这套的环境**没有 GPU,无法端到端实测**。逻辑、文件名、目录都按 ComfyUI 社区标准对齐,
  但上游仓库偶有改名/挪路径;若第 4 格某条 404 或 ComfyUI 报「节点/权重找不到」,按单元格提示去 HF 页面核对文件名即可。
- **免费版 T4(16GB)跑不动** Wan2.2-14B。必须 Colab Pro 的 A100(或自行换更小模型,如 LTX-Video)。
- Colab 临时环境会回收;出长片别关页面。模型已缓存到 Drive,重连第 4 格秒过。
- RAG(Milvus)在 Colab 不启用,自动降级,不影响视频。
