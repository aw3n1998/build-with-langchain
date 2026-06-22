from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from dotenv import load_dotenv
import os

class Settings(BaseSettings):
    # 项目元数据
    PROJECT_NAME: str = "AI Agent Build Lab"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # OpenAI / DeepSeek 配置 (优先从 .env 读取)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY") or ""   # 缺 key 不崩；LLM 调用时才报错(出图/出片不需 LLM)
    OPENAI_API_BASE: str = "https://api.deepseek.com/v1"
    MODEL_NAME: str = "deepseek-chat"
    EMBEDDING_MODEL_NAME: str = "text-embedding-3-small"
    # ── 分镜(storyboard)专属 LLM:可选覆盖,空=用上面通用默认。通用解耦,跟 DeepSeek 同一套 OpenAI 兼容口 ──
    #   想【全体 agent 都用 OpenRouter/grok】→ 直接把上面 OPENAI_API_BASE/KEY/MODEL 指向 OpenRouter(.env 有样例)。
    #   只想【分镜用 grok、聊天仍 DeepSeek】→ 填下面三个(未填的字段回退通用默认)。★ key 一律走 env/Secret,绝不入库。
    STORYBOARD_API_KEY: str = ""       # 空=用 OPENAI_API_KEY
    STORYBOARD_API_BASE: str = ""      # 如 https://openrouter.ai/api/v1;空=用 OPENAI_API_BASE
    STORYBOARD_MODEL: str = ""         # 如 x-ai/grok-4.20;空=用 MODEL_NAME
    # OpenRouter 可选归属头(base 含 openrouter 时自动带;非必填,用于排行/部分免费模型)
    OPENROUTER_REFERER: str = ""       # 如 https://你的站点 或留空
    OPENROUTER_TITLE: str = "Mirage"
    # 专用视频 Agent：聊天直达视频 Agent，不再过 supervisor 多路选择（功能专一）。false=恢复多 Agent 路由。
    VIDEO_AGENT_ONLY: bool = True
    # ── toC / 对外 API 预留口子（全部默认放行/不启用，不影响现有单用户面板）──
    # 对外公开 API(/api/v1)的 API-Key 白名单。空=不校验(默认放行，开发/单用户无感)；填了才要求 X-API-Key。
    PUBLIC_API_KEYS: str = ""           # 逗号分隔多个 key，如 "key1,key2"
    # 前端静态产物目录(yarn build 输出)。后端按需挂载，让单端口能 serve 整套 UI（生产/toC 用）。
    FRONTEND_DIST_DIR: str = "mirage/static"
    SERVE_FRONTEND: bool = True         # 目录存在才挂；缺了自动跳过，不报错
    WEBHOOK_TIMEOUT: int = 15           # 将来 webhook 回调超时(秒)，现仅占位

    # 网络高级配置
    SKIP_SSL_VERIFY: bool = True
    REQUEST_TIMEOUT: int = 60
    # LLM 输出/上下文长度上限（可被前端 per-request 覆盖）
    MAX_TOKENS: int = 4096
    # 上下文窗口（token）与压缩触发：用量超过 窗口×比例 时自动压缩旧消息
    CONTEXT_WINDOW: int = 65536          # deepseek-chat 约 64K
    COMPACT_RATIO: float = 0.75          # 达到窗口 75% 触发压缩

    # ── 小说转视频流水线 / 远程 GPU 配置 ──────────────────────────
    # 远程 GPU 服务器（跑 FLUX 出图 + Wan2.2 图生视频）。SSH 凭据走 .env，不入库。
    GPU_SSH_HOST: Optional[str] = None
    GPU_SSH_PORT: int = 22
    GPU_SSH_USER: str = "root"
    GPU_SSH_KEY_PATH: Optional[str] = None          # 私钥路径（优先于密码）
    GPU_SSH_PASSWORD: Optional[str] = None
    # 服务器端路径
    GPU_PYTHON: str = "/root/autodl-tmp/miniconda3/bin/python"
    GPU_WAN_REPO: str = "/root/autodl-tmp/Wan2.2"
    GPU_WAN_CKPT: str = "/root/autodl-tmp/models/Wan-AI/Wan2.2-I2V-A14B"   # A14B 双专家(5B 已彻底弃用)
    GPU_OUTPUT_DIR: str = "/root/autodl-tmp/pipeline_out"
    GPU_SCENES_DIR: str = "/root/autodl-tmp/cael_scenes"
    # FLUX 多候选出图（单次加载、多种子；本地源会自动上传，无需手动部署）
    GPU_FLUX_CANDIDATES_SCRIPT: str = "/root/autodl-tmp/flux_candidates.py"
    # 出图底模检查点。NSFW 直接把这个指向无审查模型即可（单一底模，无需另设 NSFW 选项）。
    # A100 推荐 lodestones/Chroma（开放无审查 FLUX 系，画质/自由度最佳）；注意 Chroma 架构异于
    # FLUX-dev，人物 LoRA 需按 Chroma 重训。要 FLUX-dev 人物 LoRA 直接生效则用 FLUX-dev 系无审查合并。
    GPU_FLUX_BASE: str = "/root/autodl-tmp/models/flux-dev"
    GPU_FLUX_LORA: str = "/root/autodl-tmp/output/cael_flux_lora_v1/cael_flux_lora_v1.safetensors"
    GPU_FLUX_OUT_ROOT: str = "/root/autodl-tmp/flux_candidates_out"
    FLUX_N: int = 4
    FLUX_STEPS: int = 28
    FLUX_GUIDANCE: float = 3.5
    FLUX_WIDTH: int = 768
    FLUX_HEIGHT: int = 1024
    FLUX_OFFLOAD: str = "model"                      # model=快(压线24G)；sequential=慢但最稳
    # 出图模型解耦：默认用哪个出图 Provider（注册名：flux / comfyui-img）
    IMAGE_PROVIDER_DEFAULT: str = "flux"
    # 人物 LoRA 训练：训练执行器。LORA_TRAIN_ENDPOINT 空=Colab 单机本地跑 ai-toolkit 子进程(默认)；
    # 填了远程训练服务地址才改走 POST 远程(SSH/独立 GPU 场景)。可插拔，不改代码切换。
    LORA_TRAIN_ENDPOINT: str = ""        # 远程训练服务接入点；空=本地 ai-toolkit 子进程
    LORA_TRAIN_STEPS: int = 3000         # 默认训练步数(Wan 双专家;脸保真社区建议 3000+，2000 易欠拟合「神似不形似」)
    # 人物 LoRA 训练底模 = Wan2.2-T2V-A14B diffusers(ai-toolkit 读；arch=wan22_14b 走 MoE 双专家)。
    # ★训练底模(diffusers)与 t2v 出片底模(lightx2v / ComfyUI fp8)是两套，各管训练/推理。
    # Colab 上 LW1 下到本地持久化目录后，把本项设成那个本地路径更省(免训练时重下 ~56G)。仅原创虚构成年角色，遵守合规前置。
    LORA_TRAIN_BASE: str = "ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16"
    # i2v 人物 LoRA 训练底模(diffusers;ai-toolkit arch=wan22_14b_i2v)。前端训练「模式=i2v」时用它,
    # 而非 t2v 的 LORA_TRAIN_BASE。t2v 训的 LoRA 套 i2v 错配(强度只能压 0.5、脸漂),i2v 出片要 i2v 原生 LoRA。
    LORA_TRAIN_I2V_BASE: str = "ai-toolkit/Wan2.2-I2V-A14B-Diffusers-bf16"
    # i2v 原生 LoRA 训练数据：必须喂【视频 clip】(num_frames>1)；纯静图(=1)对 i2v arch 条件张量为 None 必崩。
    LORA_TRAIN_I2V_FRAMES: int = 81       # i2v 每段抽帧数(须 4n+1：81 原生 / 41 / 33；显存紧可降)
    LORA_TRAIN_I2V_MIX_IMAGES: bool = True  # 混一个静图锚桶(dataset_dir/_imgs 干净正脸)做身份监督、治脸漂
    LORA_TRAIN_I2V_ANCHOR_REPEATS: int = 2  # 静图锚桶 num_repeats(身份监督权重；越大越偏静图身份)
    # 训练显存策略：auto(按显存自动：>48G 全 GPU 训、GPU 吃满更快；≤48G 把闲置专家挪 CPU 省显存) / true(强制省显存) / false(强制全 GPU)
    LORA_TRAIN_LOW_VRAM: str = "auto"
    # 本地训练执行器(照搬 notebook LW1/LW2 已验证的 ai-toolkit Wan 配方)。均可 .env 覆盖、不写死。
    AI_TOOLKIT_DIR: str = "/content/ai-toolkit"            # ai-toolkit 仓库目录(notebook L1 软链于此)
    COMFYUI_LORA_DIR: str = "/content/ComfyUI/models/loras"  # 训出 LoRA 拷到此(出片按文件名加载)
    LORA_TRAIN_RESOLUTION: int = 512     # 训练分辨率(短边；长边自动取 1.5x)
    LORA_TRAIN_NETWORK_DIM: int = 64     # LoRA rank(linear)；alpha 取一半。64 比 32 学人脸高频细节更足(从「神似」到「形似」)，14B 上显存代价小；显存吃紧可降回 32
    LORA_TRAIN_BATCH: int = 1            # batch_size(Wan 双专家训练吃显存，默认 1)
    # ── 训练提速旋钮(均 .env 可调；OOM 就调回更省显存的一档)──────────────────────────
    # 分辨率桶是否含 1024：含(默认)学脸高频细节更足；关=只 [512,768]、快~40% 但脸细节略降。
    LORA_TRAIN_HIRES: bool = True
    # 底模量化：auto(≥90G 大卡免量化、用 bf16 更快；其余含 A100-80G 保守开量化、稳不 OOM) / true / false。
    #   A100-80G 想再快可手动设 false(bf16 底模 ~56G 装得下；OOM 再回 true)。
    LORA_TRAIN_QUANTIZE: str = "auto"
    # 梯度检查点：auto/true=开(省显存,但反向重算激活、慢~25%)；false=关(快~25%,需显存余量,可能 OOM)。
    LORA_TRAIN_GRAD_CKPT: str = "auto"
    # 数据集自举(免上传自训)：每个角色自动生成多少张训练图、变体提示词(语言无关、可加可减、不写死)。
    LORA_BOOTSTRAP_COUNT: int = 16       # 自举默认生成张数(>=训练门槛 5)
    PULID_ENABLED: bool = True           # 单脸自举开关(需 ComfyUI 装 PuLID_Flux + 下配套模型)
    PULID_WEIGHT: float = 0.9            # PuLID 人脸特征注入权重
    PULID_MODEL: str = "pulid_flux_v0.9.1.safetensors"  # PuLID 权重(notebook L1 已下到 models/pulid)
    COMFYUI_WORKFLOW_PULID: str = ""     # PuLID t2i 模板路径；空=用仓库自带 pulid_t2i_template.json
    PULID_GUIDANCE: float = 3.5          # PuLID 出图 FluxGuidance
    # 出图前把中文 image_prompt 自动翻成英文（FLUX-dev 读不懂中文，会退化成动漫人像）。
    # 仅对 prompt_lang=="en" 的出图模型生效；对用户隐形。要关：.env 里设 IMAGE_PROMPT_AUTOTRANSLATE=false
    IMAGE_PROMPT_AUTOTRANSLATE: bool = True
    # 尾帧接续最大段数安全上限：0=不限（用户想接多长接多长，不写死）；>0 才作为保护性上限
    MAX_CONTINUATION_SEGMENTS: int = 0
    # 可插拔视觉模型（OpenAI 兼容多模态 /chat/completions）：用来「真看尾帧」推荐续段运镜，少抽卡。
    # 留空=不启用→推荐回退到纯文本据上下文推理。可指 Qwen-VL(DashScope 兼容)/GPT-4o/本地 LLaVA 等，不绑死厂商。
    VISION_BASE_URL: str = ""        # 如 https://dashscope.aliyuncs.com/compatible-mode/v1（空=不启用视觉）
    VISION_MODEL: str = ""           # 如 qwen-vl-max / gpt-4o
    VISION_API_KEY: str = ""
    VISION_TIMEOUT: int = 60
    # Wan2.2-I2V-A14B 原生最强出片（A100；5B 已彻底弃用）。守住原生 720p 级分辨率，别盲目超分。
    WAN_SIZE: str = "704*1280"
    WAN_FRAME_NUM: int = 81           # A14B/A100 单段更长更连贯、少接续缝（旧 24G 的 25 帧上限已取消）
    WAN_SAMPLE_STEPS: int = 30        # 原生最强：步数提到 30（可上探 40，更慢更稳）
    # ── Wan2.2 出片画质关键（官方 wan/configs/wan_i2v_A14B.py + shared_config.py）──
    # 缺 ModelSamplingSD3 shift → 运动僵硬/发糊/塌；CFG 官方=3.5(非5)；负向词用官方长串压崩坏。
    WAN_SHIFT: float = 5.0            # ModelSamplingSD3 sigma_shift（720p=5；480p 可降到 3）
    # 官方负向词原文（全角逗号别改半角，影响 umt5 分词）。压住 静止/过曝/morphing/畸形/JPEG伪影 等。
    WAN_VIDEO_NEGATIVE: str = (
        "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
        "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
        "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
        "杂乱的背景，三条腿，背景人很多，倒着走"
    )
    # 接续段拼接处接缝平滑:相邻段交叉淡化秒数(只在 segments≥2 时生效;单段无缝隙不受影响)。
    # 0=关(硬拼,会有尾帧续接的运动跳/色闪);0.2≈3帧淡化,通常净改善。运动跳变极大若起叠影可调小或设 0。
    VIDEO_SEAM_CROSSFADE: float = 0.2
    # ── Wan2.2-Lightning 极速档(4步蒸馏 LoRA;可逐镜切，关=A14B 满档精修)──
    # 默认关(精修档)；出片时传 lightning=true(面板「极速档」开关/更多参数)或这里设 true 走极速档。
    WAN_LIGHTNING: bool = False
    COMFYUI_WORKFLOW_I2V_LIGHTNING: str = "comfyui_workflows/i2v_fp8_lightning_template.json"
    # 出片精度(由 colab cell-1 按 GPU 探测写入环境变量;空=未探测)。极速档据此选模板:
    # 原生 fp8 卡(Blackwell/H100)=fp8;无原生 fp8 卡(A100/V100,探测为 fp16)→自动改用 bf16 极速档模板
    # ——A100(sm_80)无 FP8 张量核,跑 fp8 是软件模拟纯亏,bf16 更快且画质更高。
    I2V_PRECISION: str = ""
    # 极速档步数(可调):蒸馏 LoRA 按 4 步训,4=最快(贴训练点)、6=通常更干净、8=再稳更慢。
    # 模板用 %STEPS%/%BOUNDARY% 占位;切换步(高噪→低噪)取步数一半(高噪 0→BOUNDARY、低噪 BOUNDARY→end)。
    WAN_LIGHTNING_STEPS: int = 6
    # 蒸馏档专属 shift(别用满档的 5):社区蒸馏档常用 ~8,运动/清晰度更稳。可在面板 shift 覆盖。
    WAN_LIGHTNING_SHIFT: float = 8.0
    # i2v 高/低噪各自的 Lightning LoRA 文件名(放 ComfyUI/models/loras/;★高噪用 high、低噪用 low，别混)。
    WAN_LIGHTNING_LORA_HIGH: str = "wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors"
    WAN_LIGHTNING_LORA_LOW: str = "wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors"
    # LoRA 强度:i2v 官方基准 1.0/1.0；★实测 1.0/1.0 常运动太弱/慢动作 → HIGH 默认调到 1.5(low 保持 1.0)。
    # 别降高噪(社区"0.65-0.8"是 T2V 防过曝的，照搬到 i2v 会更不动)。
    WAN_LIGHTNING_STR_HIGH: float = 1.5
    WAN_LIGHTNING_STR_LOW: float = 1.0
    # ── 文生视频 t2v 档(Wan2.2-T2V-A14B；与 i2v 并存，由「出片模式=t2v」路由，不进用户下拉)──
    # t2v 不经 FLUX、不出图不选图，文本直接→视频；角色身份靠训好的 Wan-T2V 角色 LoRA(空=纯提示词)。
    COMFYUI_WORKFLOW_T2V: str = ""                                       # 满档 t2v 模板;空=用仓库自带 t2v_fp8_template.json
    COMFYUI_WORKFLOW_T2V_LIGHTNING: str = "comfyui_workflows/t2v_fp8_lightning_template.json"
    T2V_PRECISION: str = ""                                             # 同 I2V_PRECISION;空=未探测(cell1 写入)
    # t2v 角色 LoRA(训好后填;高/低噪各一)。空=不挂(provider 摘除 LoRA 节点)。强度 t2v 基准 ~0.8-1.0。
    WAN_T2V_LORA_HIGH: str = ""
    WAN_T2V_LORA_LOW: str = ""
    WAN_T2V_LORA_STR_HIGH: float = 1.0
    WAN_T2V_LORA_STR_LOW: float = 1.0
    # i2v 角色 LoRA(i2v 原生训的;用于尾帧续接锁脸)。高/低噪各一,空=不挂。训练「模式=i2v」产物自动写进项目级
    # wan_i2v_lora_* (见 lora_train._link_after_train);也可在 .env 设全局默认。强度可 0.8-1.0(i2v 原生不必压 0.5)。
    WAN_I2V_LORA_HIGH: str = ""
    WAN_I2V_LORA_LOW: str = ""
    WAN_I2V_LORA_STR_HIGH: float = 0.9
    WAN_I2V_LORA_STR_LOW: float = 0.9
    # t2v 极速档蒸馏 LoRA(★与 i2v 的不同文件!)。文件名以 HF lightx2v/Wan2.2-Distill-Loras 实际为准,可在 .env 覆盖。
    WAN_T2V_LIGHTNING_LORA_HIGH: str = "wan2.2_t2v_A14b_high_noise_lora_rank64_lightx2v_4step.safetensors"
    WAN_T2V_LIGHTNING_LORA_LOW: str = "wan2.2_t2v_A14b_low_noise_lora_rank64_lightx2v_4step.safetensors"
    # ── t2v 出片后端 ──────────────────────────────────────────────
    # t2v 走 ComfyUI(comfyui-t2v provider，配 COMFYUI_BASE_URL 才注册)。保留此键以便将来并存其它 t2v 后端。
    T2V_PROVIDER: str = "comfyui-t2v"
    # Stand-In 强锁脸(WeChatCV/Stand-In)文生视频后端:给一张参考脸跨镜硬锁身份,免训练。另起包装 server(默认 8190),
    # 不走 lightx2v(它自带 DiffSynth 引擎)。由「出片模式=t2v + 前端强锁脸开关 + 该角色有参考脸」路由(见 _do_render_t2v)。
    STANDIN_ENABLED: bool = False           # 配了端点 + 跑了 Colab §Stand-In 起 server 才注册;默认关
    STANDIN_BASE_URL: str = ""              # 如 http://127.0.0.1:8190(与 lightx2v 8189 错开)
    STANDIN_STEPS: int = 20                 # 锁脸无蒸馏采样步数(20 起细;Stand-In 不挂蒸馏 LoRA,身份来自参考脸)
    # 注:i2v 尾帧续接(镜N 用镜N-1 尾帧当首帧续生成)现走 ComfyUI i2v provider(wan2.2),
    # 复用 WAN_LIGHTNING_LORA_*(极速)+ WAN_T2V_LORA_*/项目级 i2v 角色 LoRA(锁脸);不再起独立 lightx2v i2v server。
    # ── 视频模型解耦：默认 Provider + LTX-Video 配置 ──────────────
    # 默认用哪个视频模型（对应 providers 注册名：wan2.2 / ltx）
    VIDEO_PROVIDER_DEFAULT: str = "wan2.2"
    # LTX-Video（部署后填 GPU_LTX_MODEL 即可启用；脚本自动上传）
    GPU_LTX_MODEL: str = ""                          # LTX diffusers 目录（如 /root/autodl-tmp/models/LTX-Video）或 HF id
    GPU_LTX_SCRIPT: str = "/root/autodl-tmp/ltx_i2v.py"
    # 复用 FLUX 的 T5-XXL text_encoder，省 ~19G 盘（留空则用 LTX 自带 text_encoder）
    GPU_LTX_T5_DIR: str = "/root/autodl-tmp/models/flux-dev/text_encoder_2"
    LTX_SIZE: str = "480*832"          # 默认竖屏快档：省显存(~10G)、更快，不会被卡上残留一点点占用就 OOM
    LTX_NUM_FRAMES: int = 121
    LTX_FPS: int = 24
    LTX_STEPS: int = 30                 # LTX 30 步已够；比 40 快约 1/4
    LTX_GUIDANCE: float = 3.0
    # ── LTX-Video 2.3（ComfyUI HTTP provider，与 Wan2.2 并列、用户在下拉里手选）──────────
    # 定位：LTX=快/音视频一体/走量；Wan=运动真实感/电影级控制/NSFW 生态成熟。走 ComfyUI 原生 LTXAV
    # 节点(需 ComfyUI v0.16+/torch≥2.4，与本仓默认钉的 v0.3.75 不能同实例共存——见
    # comfyui_workflows/README.md 的「LTX 2.3 接入」说明)。以下全部可在 .env/面板覆盖(不写死)。
    # 装好 LTX(节点+权重)后把 LTX2_ENABLED 设 true，它才并列进用户模型下拉(免没装时选了跑不了)。
    LTX2_ENABLED: bool = False
    # LTX 专属 ComfyUI 端点（双实例用）：非空=LTX 走这个地址(如另一端口/另一台跑 v0.16+ 的 ComfyUI，
    # 与 Wan 的 v0.3.75 实例隔离)；空=回落到 COMFYUI_BASE_URL(单实例，Wan/LTX 共用)。
    COMFYUI_LTX_BASE_URL: str = ""
    COMFYUI_WORKFLOW_LTX: str = ""        # LTX i2v workflow 模板路径；空=用仓库自带 ltx_i2v_template.json(脚手架，首跑前按官方模板核对)
    LTX2_SIZE: str = "704*1280"           # 默认竖屏(宽*高，须 32 的倍数)；2.3 可上 1088*1920(1080p)
    LTX2_FRAMES: int = 121                # 帧数须 8 的倍数+1(如 121≈5s@24fps)
    LTX2_FPS: int = 24                    # LTX 原生帧率较高，常用 24
    LTX2_STEPS: int = 30                  # dev 全量精修约 30；distilled 蒸馏档约 8
    LTX2_GUIDANCE: float = 3.0
    LTX2_DISTILLED: bool = False          # True=8步蒸馏极速档(类比 Wan Lightning)；False=dev 全量精修
    LTX2_KEEP_AUDIO: bool = False         # 默认丢 LTX 自带音(交角色声音圣经 TTS 统一音色)；True=保留 LTX 原生音轨
    # ── ComfyUI 后端（HTTP，可配置；对用户完全隐形）──────────────
    # 在 GPU 或任意机器上跑 ComfyUI，本框架通过它的 HTTP API 提交 workflow。
    # 关键：ComfyUI 不作为「用户可见的模型」出现。它**透明顶替**现有公开模型名的执行后端——
    #   用户面板里选的还是 Wan2.2 / FLUX，配了端点后这些就悄悄走 ComfyUI（白嫖 GGUF/SageAttention/
    #   调好不崩的图），下拉/日志/文案里不出现「ComfyUI」字样。换机器只改 COMFYUI_BASE_URL。
    COMFYUI_BASE_URL: str = ""            # 如 http://127.0.0.1:8188（空=完全不启用 ComfyUI）
    # 顶替哪个公开模型名的执行后端。取值："auto"=跟随当前默认模型；具体名（如 ltx/wan2.2/flux）=只顶替该模型；""=该环节不走 ComfyUI。
    COMFYUI_VIDEO_AS: str = "auto"        # 出片：默认 auto=配端点就让“你的默认出片模型”透明走 ComfyUI（本仓默认是 ltx）
    COMFYUI_IMAGE_AS: str = ""            # 出图：默认 ""=仍走 FLUX-SSH；设 "auto"/"flux" 才让出图透明走 ComfyUI
    COMFYUI_WORKFLOW_I2V: str = ""        # i2v workflow 模板(API格式 JSON)路径；空=用仓库自带 comfyui_workflows/i2v_template.json
    COMFYUI_TIMEOUT: int = 1800           # 单段出片超时（秒）
    COMFYUI_FRAMES: int = 81              # 默认帧数（i2v 用；对口型 S2V 改为按音频时长动态算）
    COMFYUI_FPS: int = 16                 # 默认帧率（Wan 系常用 16）
    # 对口型(S2V)单段一口气帧数上限：防 24G OOM/超长。0=不限，帧数完全跟音频走；
    # 若长台词 OOM，可设为如 113（≈7s@16fps），超长会告警并建议拆句/分镜。
    COMFYUI_S2V_MAX_FRAMES: int = 0
    COMFYUI_STEPS: int = 30               # 默认采样步数（原生最强；A14B GGUF 模板内步数已同步为 30）
    # ── 合成连贯性 ──
    # 镜间交叉叠化(秒)：0=硬切；0.4 左右让镜头切换更顺、减少"散"。失败自动回退硬切。
    ASSEMBLE_CROSSFADE: float = 0.4
    # 背景音乐文件(本地路径)：设了就在整片下垫一条低音量 BGM(贯穿全集=最便宜的连贯感)；空=不加。
    BGM_PATH: str = ""
    BGM_VOLUME: float = 0.18              # BGM 相对音量(垫在旁白下，别盖过人声)
    COMFYUI_SIZE: str = "720*1280"        # 默认分辨率（宽*高）：原生最强守住 720p 竖屏（旧 480*832 是快出档）
    # ComfyUI 文生图（t2i）：把出图也接到 ComfyUI（GGUF Flux / 更好采样器 / LoRA 叠加）
    # t2i workflow 模板路径。空=用仓库自带 flux t2i_template.json(FLUX-dev 系底模都用这个，含 LoraLoader)。
    COMFYUI_WORKFLOW_T2I: str = ""
    COMFYUI_T2I_SIZE: str = "768*1024"    # 出图默认分辨率（宽*高）
    COMFYUI_T2I_STEPS: int = 28           # 出图默认采样步数
    COMFYUI_T2I_N: int = 4                # 一次出几张候选图
    # 出图底模(ComfyUI t2i 的 UNET 文件名，放在 ComfyUI/models/unet/ 下)。可插拔：
    # 默认 flux1-dev；换无审查 Fluxed Up 等 FLUX-dev 微调=改成它的 .safetensors 文件名(配自带 flux 模板)。
    COMFYUI_FLUX_UNET: str = "flux1-dev.safetensors"
    # CivitAI 全合一 FLUX checkpoint(内含 CLIP+VAE，如 Fluxed Up)的文件名(在 ComfyUI/models/checkpoints/ 下)。
    # 用它=COMFYUI_WORKFLOW_T2I 指 comfyui_workflows/t2i_checkpoint_template.json + 本项设为该文件名。
    COMFYUI_FLUX_CKPT: str = ""
    # ComfyUI 后处理（放大/补帧）：合成后可选再过一道 workflow；留空=不做后处理
    COMFYUI_WORKFLOW_POST: str = ""       # 后处理 workflow 模板路径（空=关闭后处理）
    # ── 一键转规格（对已生成的低清成片按需放大到目标分辨率，如 4K）──────────────
    # 引擎可插拔：auto=配了 ComfyUI 走 AI 超分(RealESRGAN)、否则 ffmpeg 快缩；也可强制 comfyui / ffmpeg。
    UPSCALE_METHOD: str = "auto"          # auto / comfyui / ffmpeg
    UPSCALE_MODEL: str = "RealESRGAN_x2.pth"   # ComfyUI 超分模型名(放 models/upscale_models/;想更清下 RealESRGAN_x4.pth 改这里)
    COMFYUI_WORKFLOW_UPSCALE: str = ""    # 超分 workflow；空=回退 COMFYUI_WORKFLOW_POST / 仓库自带 post_upscale_template.json
    # 目标规格预设（名:宽*高，逗号分隔，可增减、不写死；前端下拉据此，API 也可直接传 width/height）
    UPSCALE_TARGETS: str = ("4K竖屏:2160*3840,4K横屏:3840*2160,2K竖屏:1440*2560,"
                            "1080P竖屏:1080*1920,1080P横屏:1920*1080,720P竖屏:720*1280")
    # ── 视频一键换脸（ReActor 等；后处理、产物落独立新文件，不覆盖原片）──────────────
    # 合规红线：仅用于你有权使用的脸（原创/AI 生成/本人授权）。换成可识别真人=deepfake，
    # ReelShort/DramaBox 等平台 ToS 与多地法律禁止；本功能仅作角色脸一致性/原创角色用途。
    # 端点门控：FACESWAP_ENABLED 且配了 COMFYUI_BASE_URL 且模板存在才注册可用，否则休眠。
    FACESWAP_ENABLED: bool = True
    COMFYUI_WORKFLOW_FACESWAP: str = ""   # 换脸 workflow；空=用仓库自带 comfyui_workflows/faceswap_video_template.json
    FACESWAP_SWAP_MODEL: str = "inswapper_128.onnx"        # 换脸模型(放 models/insightface/，ReActor 安装时自动下)
    # 面部修复(放 models/facerestore_models/，ReActor 首次用到时按需下)。可选 GFPGANv1.4.pth / codeformer-v0.1.0.pth(带 v)；
    # 逐帧修复会提清晰度但可能引入轻微闪烁——若模型没就位或想先跑通/避免闪烁，设 none。
    FACESWAP_RESTORE_MODEL: str = "GFPGANv1.4.pth"
    FACESWAP_RESTORE_VISIBILITY: float = 1.0               # 修复可见度 0~1
    FACESWAP_DET_MODEL: str = "retinaface_resnet50"        # 人脸检测器(retinaface_resnet50 质量最好)
    # Wan2.2-S2V 对口型（语音驱动）：人物开口说话的镜头用。图+音频→口型同步视频，走 ComfyUI。
    # 隐藏 Provider：不进用户模型下拉，由每镜「对口型」开关自动路由。端点门控同 COMFYUI_BASE_URL。
    COMFYUI_WORKFLOW_S2V: str = ""        # S2V workflow 模板路径；空=用仓库自带 comfyui_workflows/s2v_template.json
    COMFYUI_S2V_TTS_VOICE: str = "zh-CN-YunxiNeural"  # 对口型用的 TTS 音色（edge-tts；男声示例）
    # 配音引擎（解耦：edge-tts 默认/保底，可插拔自托管克隆引擎；见 pipeline/tts_providers）。
    TTS_PROVIDER_DEFAULT: str = "edge-tts"   # 默认配音引擎(edge-tts / indextts2)；裸音色 id 始终走 edge-tts
    # IndexTTS2 自托管克隆+情感:配了 ENABLED+BASE_URL 才注册(没起 server 时整条链自动只用 edge-tts，不报错)。
    INDEXTTS2_ENABLED: bool = False
    INDEXTTS2_BASE_URL: str = ""             # 包装 server 端点(Colab 跑「§IndexTTS2」格写入，默认 http://127.0.0.1:8191)
    INDEXTTS2_DEFAULT_EMOTION: str = ""      # 缺省情感(空=中性)；每镜可由 scene.emotion 覆盖
    # 口型对齐（出片后处理，引擎无关可插拔；不做 VideoProvider）。没配/server 没起=自动跳过，不报错。
    LIPSYNC_ENGINE: str = ""                  # ""=关(只配音不缝嘴) / "latentsync" / "wav2lip"
    LATENTSYNC_ENABLED: bool = False          # 门控：配了 ENABLED+BASE_URL 才会尝试缝嘴
    LATENTSYNC_BASE_URL: str = ""             # 包装 server 端点，默认 http://127.0.0.1:8192
    LATENTSYNC_STEPS: int = 20                # 采样步数 20~50
    LATENTSYNC_GUIDANCE: float = 1.5          # 引导强度 1.0~3.0
    LIPSYNC_MAX_SECONDS: float = 0.0          # >0 时跳过超长片(防 OOM)；0=不限
    # 本机产物落地目录
    NP2V_DB_PATH: Optional[str] = None
    NP2V_LOCAL_OUT: Optional[str] = None

    model_config = SettingsConfigDict(
        # 自动加载当前目录或上级目录的 .env 文件
        env_file = ".env",
        env_file_encoding = 'utf-8',
        case_sensitive = True,
        extra = "ignore" 
    )

settings = Settings()
