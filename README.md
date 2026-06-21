# 蜃景 Mirage —— 中文小说 → AI 短剧视频工作台

> 把一段中文小说，自动变成一集竖屏 AI 短剧：**拆分镜 → 文生视频(t2v) → 配音/字幕 → 合成整集**，全程网页工作台一条龙。
>
> 技术栈：Python · FastAPI · LangGraph · React + Vite · ComfyUI · Wan2.2(T2V/I2V) · Pydantic V2 · SQLite

> **当前路线 = ComfyUI 出片（Wan2.2-T2V 文生视频 + Wan2.2-I2V 尾帧续接），开 SageAttention 提速。** 人物一致靠自训的 **Wan 角色 LoRA**（t2v 锁脸 / i2v 续接锁脸，两套底模各训各的）。
> FLUX 出图 / 选图 / PuLID 锁脸 / S2V 对口型 / ReActor 换脸同在 ComfyUI 生态（端点门控、按需启用）。lightx2v 引擎已弃用、相关代码已移除。

---

## 它是什么

Mirage 是一个面向**竖屏短剧量产**的全栈 Web Agent。你把小说/剧情文本丢进去，它像导演一样：

```
小说文本
  │  ① LLM 导演拆分镜（每镜：画面提示词 / 运镜 / 旁白或台词 / 字幕 / 出场角色）
  ▼
分镜表（角色圣经：每个角色固定外貌 + 固定音色 + 角色 LoRA，出片/配音自动注入）
  │  ② 每镜 Wan2.2-T2V-A14B 文生视频（ComfyUI 后端；文本直接出片，无需出图/选图）
  ▼
分镜成片
  │  ③ 配音(TTS) + 字幕 + 拼接 + （可选）转 4K / BGM
  ▼
整集竖屏 mp4
```

GPU 重活（出片）走 **ComfyUI 的 HTTP API**（Wan2.2-A14B 双专家，开 SageAttention 提速），后端只做编排，端点未配置时自动休眠——本机零 GPU 也能跑完编排、改提示词、排分镜。
人物一致性来自**自训 Wan 角色 LoRA**（t2v 没有首帧，身份全靠 LoRA 锁定；i2v 续接锁脸用 i2v 原生 LoRA）。

---

## 核心能力

**创作流水线**
- **小说 → 自动拆分镜**：LLM 当导演，一次拆成整套分镜，固化了项目踩过的坑（人物写明确年龄、景别有节奏、台词控制在一口气说完、跨镜角色一致）。
- **角色 / 声音圣经**：每剧每个角色一份固定外貌 + 固定音色 + 角色 LoRA，出片复用外貌/触发词、配音复用音色，保证跨镜是同一个人。
- **文生视频出片**：Wan2.2-T2V-A14B 双专家，走 **ComfyUI** HTTP（lightning 4 步蒸馏极速档 + 满档精修两步走）。分镜文本直接出竖屏短片。
- **人物 LoRA 自训**：Colab 里用 ai-toolkit 训 Wan-T2V 高/低噪双 LoRA（`char_lora_high/low_noise.safetensors`），t2v 出片自动注入触发词 + 挂 LoRA 锁人物（t2v 没首帧，人物一致全靠它）。
- **配音 / 字幕**：每镜旁白或台词转 TTS（角色音色）、自动叠字幕，拼接成整集。
- **i2v 尾帧续接 / 出图选图 / PuLID / 对口型 / 换脸**：Wan2.2-I2V 续接 + FLUX 出图 + S2V + ReActor 同走 ComfyUI HTTP，配 `COMFYUI_BASE_URL` 启用。

**后处理 / 增强（可插拔，端点门控）**
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
│  转规格 / 换脸 按钮 · Settings(导演模型 + 后端地址) · 小助手问答             │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ HTTP / SSE / WebSocket
┌──────────────────────────────────▼────────────────────────────────────────┐
│                        FastAPI 后端 (mirage/main_api.py :8000)              │
│  /api/pipeline/*  拆分镜·出图·出片·选图·转规格·换脸·上传续接 (后台 job)       │
│  /api/v1/*        公开 API(APIKey)        /api/chat  视频 Agent 问答         │
│                                                                            │
│  pipeline/  storyboard·novel_analyze·prompt_gen·assembler·postprocess·     │
│             faceswap·lora_train  +  store(SQLite, per-workspace)            │
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
git clone <你的仓库地址>
cd <项目目录>

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

### B. Colab 一条龙（推荐，自带 GPU，ComfyUI 出片）

打开 **`colab_deploy.ipynb`** → 运行时选 GPU（Blackwell / Hopper / Ada / A100-80G）→ 菜单 **代码执行程序 → 全部运行 (Run all)**：

1. **§1** 自动探测显卡设精度档 + SageAttention 开关（非原生 fp8 卡如 A100 开 sage；Blackwell 因 Wan 全局 sage 噪声 bug 默认关，可 `MIRAGE_USE_SAGE=1` 强开）。
2. **§3** 装 ComfyUI + 自定义节点（含 SageAttention，`colab/setup.sh`）；模型权重持久化在 Drive、回收不重下。
3. **§5** 起 ComfyUI（GPU 探测结果决定 `--use-sage-attention` / `--highvram`）；后端写 `.env`（`COMFYUI_BASE_URL`）→ 起后端 → 公网地址。
4. 训角色 LoRA：前端「角色 & LoRA」选**训练目标 t2v / i2v** 上传同脸图开训；产物自动应用到项目，ComfyUI 出片按文件名加载。
5. 出片：t2v 文生（默认）/ i2v 尾帧续接（一镜到底）/ 强锁脸 Stand-In / 换脸 ReActor，均走 ComfyUI。

> 旧的 `colab_lightx2v_t2v.ipynb`（lightx2v 引擎）已弃用——lightx2v 后端代码已从仓库移除，改用 ComfyUI。

---

## GPU 后端（休眠退路）：为什么自托管 ComfyUI

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
<项目根>/
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
│           ├── assembler.py / postprocess.py / faceswap.py
│           ├── lora_train.py / lora_bootstrap.py                   # 人物 LoRA 自训
│           └── store.py / runtime.py                               # SQLite 状态 / 工作目录
├── comfyui_workflows/  t2i(flux/chroma/checkpoint) · pulid_t2i · i2v(bf16/fp8/fp8_lightning/gguf)
│                       · s2v · ltx_i2v · post_upscale · faceswap_video  (API 格式模板)
├── colab/  setup.sh · download_models.sh · persist.py
├── colab_deploy.ipynb · colab_deploy_blank.ipynb                   # Colab 一条龙 / 空白可填
├── colab_lightx2v_t2v.ipynb                                        # ★主：纯 t2v + lightx2v 部署(无 ComfyUI)
├── lightx2v_t2v_部署状态.md                                          # ★部署交接：已完成 / 待办 / 排错
├── frontend/  (React + Vite：纯 t2v 工作台 / 出片 / 设置)
├── scripts/  seed_ashborn_ep1.py …                                 # 示例剧集灌入
├── .env.example · .env.colab · requirements.txt · Dockerfile
└── docs/                                                           # 本地文档（不随发布）
```

---

## 成熟度

- **t2v 主线（当前路线）**：前后端链路已打通——拆分镜 → 逐镜文生视频(lightx2v) → 配音/字幕 → 合成整集；Colab 部署坑已固化进 `colab_lightx2v_t2v.ipynb`。**真机出片仍在收尾**：lightx2v server 起得来、权重加载成功，出片有一个 `'NoneType' object is not callable` 待真机抓真帧定位（§5 已自动插桩），裸片通过后再挂角色 LoRA（§5d）。进度见 `lightx2v_t2v_部署状态.md`。
- **i2v 退路（已跑通过、默认休眠）**：拆分镜 → FLUX 出图（选图）→ Wan2.2-I2V 出片 → 配音/字幕 → 合成整集，曾在 ComfyUI 实机全自动出整集。代码与模板保留、端点门控，配 `COMFYUI_BASE_URL` 即启用。
- **可插拔、待按 ComfyUI 真机核对模板**：S2V 对口型、一键转规格、视频换脸、LTX——均默认关 / 端点门控，节点名以各自 `comfyui_workflows/*.json` 模板为准，首跑前请按官方导出的 API 格式核对。

## 合规

- 出片仅用于**原创、虚构、成年**角色；遵守所在平台与当地法律。
- **视频换脸只用于你有权使用的脸**（原创 / AI 生成 / 本人授权）。把视频里的人换成可识别的真人 = deepfake，ReelShort / DramaBox 等平台 ToS 与多地法律禁止——本功能定位是给原创角色保持同一张脸跨镜一致，不是伪造真人。
- 密钥只走 `.env` / Colab Secrets，**绝不写进代码或提交**。
