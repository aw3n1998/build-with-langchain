# 蜃景 Mirage —— 中文小说 → AI 短剧视频工作台

> 把一段中文小说，自动变成一集竖屏 AI 短剧：**拆分镜 → 出图 → 图生视频 → 配音/字幕 → 合成整集**，全程网页工作台一条龙。
>
> 技术栈：Python · FastAPI · LangGraph · React + Vite · ComfyUI(HTTP) · Wan2.2 · FLUX · Pydantic V2 · SQLite

---

## 它是什么

Mirage 是一个面向**竖屏短剧量产**的全栈 Web Agent。你把小说/剧情文本丢进去，它像导演一样：

```
小说文本
  │  ① LLM 导演拆分镜（每镜：画面提示词 / 运镜 / 旁白或台词 / 字幕 / 是否对口型 / 出场角色）
  ▼
分镜表（角色圣经：每个角色固定外貌 + 固定音色，出图/配音自动注入）
  │  ② 每镜 FLUX 出图（多候选 → 选图）
  ▼
关键帧
  │  ③ Wan2.2-I2V-A14B 图生视频（七条运镜法则；可对口型 / 无缝续段）
  ▼
分镜成片
  │  ④ 配音(TTS) + 字幕 + 拼接 + （可选）转 4K / 换脸 / BGM
  ▼
整集竖屏 mp4
```

GPU 重活（出图 / 出片 / 对口型 / 超分 / 换脸）全部走 **ComfyUI 的 HTTP API**，后端只做编排，端点未配置时自动休眠——本机零 GPU 也能跑完编排、改提示词、排分镜。

---

## 核心能力

**创作流水线**
- **小说 → 自动拆分镜**：LLM 当导演，一次拆成整套分镜，固化了项目踩过的坑（人物写明确年龄、景别有节奏、台词控制在一口气说完、跨镜角色一致）。
- **角色 / 声音圣经**：每剧每个角色一份固定外貌 + 固定音色，出图复用外貌、配音复用音色，保证跨镜是同一个人。
- **出图**：FLUX（UNET-only 的 flux-dev / Chroma，或 CivitAI 全合一 checkpoint，NSFW 底模可配），每镜多候选 → 网页选图；PuLID 单脸自举；**人物 LoRA 自训**（ai-toolkit 子进程，免上传，造图即训）。
- **出片**：Wan2.2-I2V-A14B 双专家（fp8 / fp16 / GGUF 自适配显卡），**Lightning 极速档**打样 + 满档精修两步走。
- **对口型**：Wan2.2-S2V 语音驱动，开口说台词的镜头自动走它。

**后处理 / 增强（可插拔，端点门控）**
- **FLF2V 无缝续段**：共享关键帧首尾拼接，治本接缝抖动，支持零人工自动选帧。
- **一键转规格**：把低清成片转 4K / 2K / 1080P（AI 超分 RealESRGAN 或 ffmpeg，引擎可配）。
- **视频一键换脸**：ReActor 逐帧换脸，给原创角色保持同一张脸跨镜一致（⚠️ 见下「合规」）。
- **LTX-Video 2.3**（可选）：与 Wan2.2 并列的「快 / 音视频一体」出片档。

**工程**
- **LLM 解耦**：OpenAI 兼容，`.env` 一处切换 DeepSeek / OpenRouter(grok) / 其它；分镜可走专属模型；前端 Settings 也能选。
- **GPU Provider 抽象**：`wan2.2 / ltx2 / comfyui-s2v / flux` 注册即出现，参数 schema 自描述，传输 `http | ssh` 可插拔。
- **后台单飞任务**：出图/出片是后台 job（job_manager），SSE/WebSocket 推进度，断网/切会话不丢、可重连续看。
- **toC / API 口子**：`/api/v1` 公开 API + APIKey 鉴权 + 多租户 user_id 位 + usage/webhook 钩子。
- **Colab 一条龙**：Run all 出整集，模型/依赖全持久化 Drive，断线再 Run all 几分钟恢复。

---

## 架构

```
┌────────────────────────── 浏览器 (React + Vite) ──────────────────────────┐
│  剧集列表 · 工作台面板(剧本 / 角色&LoRA / 分镜 / 导出) · 选图 · 出片 ·       │
│  转规格 / 换脸 / FLF2V 按钮 · Settings(导演模型 + 后端地址) · 小助手问答     │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ HTTP / SSE / WebSocket
┌──────────────────────────────────▼────────────────────────────────────────┐
│                        FastAPI 后端 (mirage/main_api.py :8000)              │
│  /api/pipeline/*  拆分镜·出图·出片·选图·转规格·换脸·FLF2V·上传续接 (后台 job) │
│  /api/v1/*        公开 API(APIKey)        /api/chat  视频 Agent 问答         │
│                                                                            │
│  pipeline/  storyboard·novel_analyze·prompt_gen·assembler·postprocess·     │
│             flf2v·faceswap·lora_train  +  store(SQLite, per-workspace)      │
│  providers/ wan2.2 / ltx2 / comfyui-s2v   image_providers/ flux            │
│  comfy_http 上传图/视频 → 提交 workflow → 轮询 → 取产物                      │
└───────────┬─────────────────────────────────────────┬──────────────────────┘
            │ OpenAI 兼容 (.env)                        │ HTTP（端点门控，未配则休眠）
            ▼                                           ▼
   DeepSeek / OpenRouter(grok) / …            ComfyUI + GPU（自托管：Colab / 租的卡 + 隧道）
                                              FLUX 出图 · Wan2.2 出片 · S2V · 超分 · 换脸
```

> 仓库保留了多 Agent 框架骨架（supervisor / code / file / general / shell / batch），但产品默认运行在**视频专用模式**（`video_agent_only`），这些非视频 Agent 在前端被门控隐藏、不删除。

---

## 快速开始

### A. 本地（编排 + 网页，GPU 重活连到你的 ComfyUI）

```bash
git clone https://github.com/aw3n1998/build-with-langchain.git
cd build-with-langchain

# 1) Python 依赖
pip install -r requirements.txt

# 2) 配置：复制并填 .env
cp .env.example .env
#   - 分镜/聊天 LLM：OPENAI_API_KEY / OPENAI_API_BASE / MODEL_NAME
#     默认 DeepSeek；切 OpenRouter(grok) 改这三行即可；只想分镜用 grok 填 STORYBOARD_*
#   - GPU：COMFYUI_BASE_URL=http://你的ComfyUI:8188（空=出图/出片休眠，仅离线编排）

# 3) 后端（:8000，热重载）
python -m mirage.main_api          # Swagger: http://localhost:8000/docs

# 4) 前端（:5173，开发模式；/api 自动代理到 :8000）
cd frontend && npm install && npm run dev
#   生产：npm run build → 构建产物给后端单端口托管，直接访问 :8000
```

### B. Colab 一条龙（推荐，自带 GPU，出整集）

打开 **`colab_deploy.ipynb`** → 运行时选 GPU（H100 / RTX PRO 6000 Blackwell / A100-80G）→ 菜单 **代码执行程序 → 全部运行 (Run all)**：

1. 第 1 格自动探测显卡选精度档（原生 FP8 → fp8 快档；A100 → fp16 原生）。
2. 右侧 🔑 Secrets 加 `CIVITAI_TOKEN`（出图底模用）。
3. cell **1b/1c** 可选开关：`ENABLE_LTX`（LTX 出片档）、`ENABLE_FACESWAP`（视频换脸）改 `True` 再 Run all。
4. 末尾自动出整集 ASHBORN EP1，并打印 cloudflared 公网地址访问网页工作台。

断线/回收后再点一次 **Run all** 即可——模型 / ai-toolkit / pip 缓存全持久化在 Drive，不重下。
（空白可填版本见 `colab_deploy_blank.ipynb`，出图/出片模型默认全空、自己填。）

---

## GPU 后端：为什么自托管 ComfyUI

Mirage 需要**任意自定义节点 + 自带任意底模（含 NSFW checkpoint）+ 可编程 API + 自训 LoRA 落盘**，因此走**自托管 ComfyUI**（Colab / 租的 GPU + cloudflared 隧道），而非 ComfyUI 官方云（官方云只支持策展白名单节点 + 仅能上传 LoRA、不能换任意底模）。

- 模型预放 `ComfyUI/models/{unet,checkpoints,clip,vae,loras,...}`，自定义节点装进 `custom_nodes/`，`colab/setup.sh` + `download_models.sh` 幂等装好。
- 端点配置在 `COMFYUI_BASE_URL`（LTX 可用 `COMFYUI_LTX_BASE_URL` 走第二实例）。

**模型与精度（笔记本按显卡自动选）**

| 用途 | 模型 | 放置 |
|---|---|---|
| 出片 | Wan2.2-I2V-A14B 双专家（fp8_scaled / fp16 / GGUF Q5）+ Lightning 4 步 LoRA | `models/unet`,`models/loras` |
| 文本编码 | umt5-xxl（fp8 / fp16） | `models/clip` |
| VAE | `wan_2.1_vae`（A14B 必用） | `models/vae` |
| 出图 | FLUX-dev / Chroma / CivitAI 全合一 checkpoint（NSFW 可配） | `models/unet` 或 `models/checkpoints` |
| 对口型 | Wan2.2-S2V + wav2vec2 | `models/unet`,`models/audio_encoders` |
| 换脸 | inswapper_128 + GFPGAN（ReActor） | `models/insightface`,`models/facerestore_models` |

---

## 目录结构

```
build-with-langchain/
├── mirage/
│   ├── main_api.py                 # FastAPI 入口（:8000）
│   ├── main.py                     # CLI 入口
│   └── app/
│       ├── api/  routes.py · v1_public.py(公开API)
│       ├── core/ config.py(.env) · auth.py(APIKey) · logger.py
│       ├── agents/ video_agent.py(主) + supervisor/code/file/general/shell/batch(门控)
│       ├── services/ ai_service.py(LLM 工厂/解耦) · job_manager · usage · vision …
│       └── pipeline/
│           ├── storyboard.py / novel_analyze.py / prompt_gen.py   # 文本 → 分镜
│           ├── comfy_http.py                                       # ComfyUI HTTP 调用
│           ├── providers/      wan22 · ltx · comfyui · comfyui_s2v · comfyui_ltx
│           ├── image_providers/ comfyui_image · flux_ssh
│           ├── assembler.py / postprocess.py / flf2v.py / faceswap.py
│           ├── lora_train.py / lora_bootstrap.py                   # 人物 LoRA 自训
│           └── store.py / runtime.py                               # SQLite 状态 / 工作目录
├── comfyui_workflows/  t2i(flux/chroma/checkpoint) · pulid_t2i · i2v(bf16/fp8/fp8_lightning/gguf)
│                       · s2v · flf2v · ltx_i2v · post_upscale · faceswap_video  (API 格式模板)
├── colab/  setup.sh · download_models.sh · persist.py
├── colab_deploy.ipynb · colab_deploy_blank.ipynb                   # Colab 一条龙 / 空白可填
├── frontend/  (React + Vite：工作台面板 / 选图 / 出片 / 设置)
├── scripts/  seed_ashborn_ep1.py …                                 # 示例剧集灌入
├── .env.example · .env.colab · requirements.txt · Dockerfile
└── docs/                                                           # 本地文档（不随发布）
```

---

## 成熟度

- **已跑通（Colab 实机）**：拆分镜 → 出图（选图）→ Wan2.2 出片 → 配音/字幕 → 合成整集，全自动出整集。
- **可插拔、待按你的 ComfyUI 真机核对模板**：LTX-Video 2.3、FLF2V、S2V 对口型、一键转规格、视频换脸——均默认关 / 端点门控，节点名以各自 `comfyui_workflows/*.json` 模板为准，首跑前请按官方导出的 API 格式核对。

## 合规

- 出图/出片仅用于**原创、虚构、成年**角色；遵守所在平台与当地法律。
- **视频换脸只用于你有权使用的脸**（原创 / AI 生成 / 本人授权）。把视频里的人换成可识别的真人 = deepfake，ReelShort / DramaBox 等平台 ToS 与多地法律禁止——本功能定位是给原创角色保持同一张脸跨镜一致，不是伪造真人。
- 密钥只走 `.env` / Colab Secrets，**绝不写进代码或提交**。
