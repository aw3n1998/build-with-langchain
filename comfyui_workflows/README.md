# ComfyUI workflow 模板（全链路：出图 / 出片 / 后处理）

本目录放 ComfyUI workflow 模板（API 格式 JSON）。AgentLab 把**整条视频流水线**都可选接到
ComfyUI：出图（t2i）、出片（i2v）、合成后的后处理（放大/补帧）。各自读对应模板，把占位符
替换成真实值后，通过 ComfyUI 的 `POST /prompt` 提交。三层都可独立启用，互不影响。

> **ComfyUI 对用户完全隐形。** 它**不是**面板里一个叫「ComfyUI」的可选模型——而是**透明顶替**
> 你现有公开模型名（Wan2.2 / LTX / FLUX）的执行后端：用户面板里选的还是同一个模型名，配了端点后
> 它悄悄走 ComfyUI，下拉/实时日志/文案里**不出现「ComfyUI」字样**。

| 环节 | 模板（本目录默认） | 启用开关 | 行为 |
|---|---|---|---|
| 出图 t2i | `t2i_template.json` | `COMFYUI_IMAGE_AS`（默认空=关） | 顶替出图模型（如 flux）的后端；用户仍看到 FLUX |
| 出片 i2v | `i2v_template.json` | `COMFYUI_VIDEO_AS`（默认 `auto`=跟随默认出片模型） | 顶替出片模型（本仓默认 ltx）的后端；用户仍看到原模型名 |
| 后处理 | `post_upscale_template.json`（示例） | `COMFYUI_WORKFLOW_POST` 指向文件才开 | 成片合成后自动跑一道；失败保留原片 |

> 三个开关都以 `COMFYUI_BASE_URL` 非空为前提。**出片默认 auto**（配端点就透明升级你的默认出片
> 模型）；**出图默认关**（FLUX-SSH 本就够用，想接再把 `COMFYUI_IMAGE_AS` 设为 `auto`/`flux`）；
> **后处理默认关**，必须显式把 `COMFYUI_WORKFLOW_POST` 指向存在的 workflow 才执行。

---

## 出片 i2v（`i2v_template.json`）

配了端点后，被顶替的出片模型（默认你的默认模型）出片时会读这个 JSON，把占位符替换后提交。

## 怎么启用

1. 在任意机器（GPU 或本地）跑起 ComfyUI（带 `--listen` 暴露 HTTP）。
2. 在项目 `.env` 配置：
   ```
   COMFYUI_BASE_URL=http://你的机器:8188
   # COMFYUI_VIDEO_AS=auto                 # 默认即 auto：透明顶替你的默认出片模型（本仓是 ltx）
   #                  =wan2.2 / ltx         # 或指定只顶替某个模型；=""（空）则出片不走 ComfyUI
   # COMFYUI_WORKFLOW_I2V=                  # 可选：指向你自己的 workflow（留空用本目录的 i2v_template.json）
   ```
3. **面板照旧出视频**——你选的还是原来的模型名（如 LTX），它已透明走 ComfyUI。换机器只改 `COMFYUI_BASE_URL`，不绑死某台。

## 换成你自己的 workflow（重要）

`i2v_template.json` 只是一个**示例**（原生 Wan2.2 i2v + Video Helper Suite 输出 mp4），
里面的模型文件名/节点**很可能和你的 ComfyUI 安装对不上**。正确做法：

1. 在 ComfyUI 网页里搭好一个**能正常出片的 i2v workflow**（选你装好的模型/节点）。
2. 设置 → 勾选 **Enable Dev mode Options** → 工作流右上 **Save (API Format)** 导出 JSON。
3. 把导出的 JSON 覆盖本文件（或另存并用 `COMFYUI_WORKFLOW_I2V` 指过去）。
4. 把下面这些**占位符**填到对应节点的输入里（Provider 会按字符串精确替换）：

| 占位符 | 填到哪 | 类型 |
|---|---|---|
| `%IMAGE%` | LoadImage 节点的 `image` | 字符串（Provider 上传后回填文件名） |
| `%PROMPT%` | 正向 CLIPTextEncode 的 `text` | 字符串 |
| `%NEG_PROMPT%` | 负向 CLIPTextEncode 的 `text` | 字符串 |
| `%WIDTH%` / `%HEIGHT%` | i2v/EmptyLatent 的宽高 | 数字 |
| `%FRAMES%` | i2v 的帧数(length) | 数字 |
| `%FPS%` | 视频合成节点的 frame_rate | 数字 |
| `%STEPS%` | KSampler 的 steps | 数字 |
| `%SEED%` | KSampler 的 seed | 数字 |

> 规则：整个值就是一个占位符（如 `"%FRAMES%"`）会被替换成**数字**；
> 含占位符的更长字符串（如 `"agentlab_%SEED%"`）做子串替换、结果仍是字符串。

## 产物如何取回

Provider 出片后轮询 `GET /history/{prompt_id}`，从 outputs 里找视频文件
（支持 `gifs`/`videos`/`images`/`files` 任意键，优先 `.mp4/.webm/...`），
再 `GET /view` 下载到本地。所以你的 workflow 末端要有一个**会保存视频**的节点
（如 Video Helper Suite 的 `VHS_VideoCombine`，或 ComfyUI 原生的视频保存节点）。

---

## 出图 t2i（`t2i_template.json`）

出图默认仍走 FLUX-SSH（够用）。想让出图也透明走 ComfyUI（白嫖 GGUF Flux 省显存 / 更好采样器 /
LoRA 叠加），在 `.env` 设 `COMFYUI_IMAGE_AS=auto`（顶替默认出图模型）或 `=flux`（只顶替 flux）。
**用户面板照旧选 FLUX**，看不到「ComfyUI」字样。N 张候选 = 循环提交 N 次、每次 `seed+1`。

`t2i_template.json` 现在是**原生 Flux-dev 工作流**（与你出图用的 FLUX 一致）：
UNETLoader(`flux1-dev`)→DualCLIPLoader(`t5xxl`+`clip_l`)→CLIPTextEncode→FluxGuidance→
EmptySD3LatentImage→KSampler(cfg=1)→VAEDecode→SaveImage。里面的模型文件名是 ComfyUI 的 Flux
**标准命名**，你装好 Flux 后多半就对得上；对不上就改成你的文件名（或用 `COMFYUI_WORKFLOW_T2I`
指向你导出的 API 格式 workflow），保留以下占位符：

| 占位符 | 填到哪 | 类型 |
|---|---|---|
| `%PROMPT%` | 正向 CLIPTextEncode 的 `text` | 字符串 |
| `%NEG_PROMPT%` | 负向 CLIPTextEncode 的 `text`（Flux cfg=1 时基本不生效，可留空） | 字符串 |
| `%WIDTH%` / `%HEIGHT%` | EmptySD3LatentImage 的宽高 | 数字 |
| `%STEPS%` | KSampler 的 steps | 数字 |
| `%SEED%` | KSampler 的 seed | 数字 |

> Flux 的 guidance 在 `FluxGuidance` 节点里（模板写死 3.5，想调直接改该节点）。Flux-dev 是
> guidance 蒸馏模型，KSampler 的 cfg 固定 1.0、负向几乎不起作用，这是正常的。

末端要有 `SaveImage`（或会保存图片的节点）；Provider 从 outputs 的 `images` 里取回图片。
相关默认：`COMFYUI_T2I_SIZE` / `COMFYUI_T2I_STEPS` / `COMFYUI_T2I_N`。

---

## 后处理：放大 / 补帧（`post_upscale_template.json`，默认关）

成片合成（含字幕/旁白）后，若 `.env` 设了 `COMFYUI_WORKFLOW_POST=指向一份workflow`，
AgentLab 会把成片上传到 ComfyUI 再过一道（如 RealESRGAN 放大、RIFE 补帧），下载回来**就地替换**成片。
**失败安全**：后处理任何报错只记日志并保留原片，绝不让已合成的成片丢失。

`post_upscale_template.json` 是个**示例**（Video Helper Suite 读视频 → `ImageUpscaleWithModel` 放大 →
`VHS_VideoCombine` 重新合成），节点/模型名按你的安装替换。占位符：

| 占位符 | 填到哪 | 类型 |
|---|---|---|
| `%VIDEO%` | VHS_LoadVideo 的 `video`（Provider 上传后回填文件名） | 字符串 |
| `%FPS%` | VHS_VideoCombine 的 `frame_rate`（补帧目标帧率） | 数字 |
| `%SEED%` | 如有采样节点的 seed | 数字 |

末端要有会保存视频的节点；Provider 从 outputs 里取回 `.mp4` 等视频产物。

---

## 一处占位符通用规则

整个值就是一个占位符（如 `"%FRAMES%"`）→ 替换成**数字/字符串本体**（数字字段不会被写成字符串）；
含占位符的更长字符串（如 `"agentlab_%SEED%"`）→ 子串替换、结果仍是字符串。三类模板同一规则。
