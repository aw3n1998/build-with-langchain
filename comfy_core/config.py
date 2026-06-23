"""
comfy_core 的 Provider 配置 —— 视频/ComfyUI 执行所需配置的**唯一真源**。

这里集中定义被 comfy_core 下所有 provider + comfy_http + gpu_client 读取的全部配置字段
（共 88 个，从后端 config.py 逐字搬来：同类型、同默认值、同 env 加载行为）。后端
`mirage.app.core.config.Settings` 直接 **继承** 本类，因此 provider 字段只在此处定义一份，
后端不再重复；同一份 `.env`/环境变量在两侧读出完全一致的值。

为何独立成文件：worker 侧只带 `comfy_core/` 即可（无 mirage），`from comfy_core.config import
settings` 就能拿到出片所需的全部参数，不引入 accounts/billing/LLM 等后端专属配置。

env 加载行为与后端保持一致（env_file=".env"、case_sensitive=True、extra="ignore"），
这样后端无关的环境变量（AUTH_*/BILLING_*/LLM key 等）不会因为出现在 .env 里而报错。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class ProviderSettings(BaseSettings):
    # ── 远程 GPU（SSH：FLUX 出图 + LTX/Wan SSH 出片）──────────────
    GPU_SSH_HOST: Optional[str] = None
    GPU_SSH_PORT: int = 22
    GPU_SSH_USER: str = "root"
    GPU_SSH_KEY_PATH: Optional[str] = None          # 私钥路径（优先于密码）
    GPU_SSH_PASSWORD: Optional[str] = None
    GPU_PYTHON: str = "/root/autodl-tmp/miniconda3/bin/python"
    GPU_WAN_REPO: str = "/root/autodl-tmp/Wan2.2"
    GPU_WAN_CKPT: str = "/root/autodl-tmp/models/Wan-AI/Wan2.2-I2V-A14B"   # A14B 双专家(5B 已彻底弃用)
    # FLUX 多候选出图（单次加载、多种子；本地源会自动上传，无需手动部署）
    GPU_FLUX_CANDIDATES_SCRIPT: str = "/root/autodl-tmp/flux_candidates.py"
    GPU_FLUX_BASE: str = "/root/autodl-tmp/models/flux-dev"
    GPU_FLUX_LORA: str = "/root/autodl-tmp/output/cael_flux_lora_v1/cael_flux_lora_v1.safetensors"
    FLUX_N: int = 4
    FLUX_STEPS: int = 28
    FLUX_GUIDANCE: float = 3.5
    FLUX_WIDTH: int = 768
    FLUX_HEIGHT: int = 1024
    FLUX_OFFLOAD: str = "model"                      # model=快(压线24G)；sequential=慢但最稳

    # ── Wan2.2-I2V-A14B 原生最强出片（A100；5B 已彻底弃用）──
    WAN_SIZE: str = "704*1280"
    WAN_FRAME_NUM: int = 81           # A14B/A100 单段更长更连贯、少接续缝（旧 24G 的 25 帧上限已取消）
    WAN_SAMPLE_STEPS: int = 30        # 原生最强：步数提到 30（可上探 40，更慢更稳）
    WAN_SHIFT: float = 5.0            # ModelSamplingSD3 sigma_shift（720p=5；480p 可降到 3）
    # 官方负向词原文（全角逗号别改半角，影响 umt5 分词）。压住 静止/过曝/morphing/畸形/JPEG伪影 等。
    WAN_VIDEO_NEGATIVE: str = (
        "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
        "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
        "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
        "杂乱的背景，三条腿，背景人很多，倒着走"
    )
    # ── Wan2.2-Lightning 极速档(4步蒸馏 LoRA;可逐镜切，关=A14B 满档精修)──
    WAN_LIGHTNING: bool = False
    COMFYUI_WORKFLOW_I2V_LIGHTNING: str = "comfyui_workflows/i2v_fp8_lightning_template.json"
    I2V_PRECISION: str = ""
    WAN_LIGHTNING_STEPS: int = 6
    WAN_LIGHTNING_SHIFT: float = 8.0
    WAN_LIGHTNING_LORA_HIGH: str = "wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors"
    WAN_LIGHTNING_LORA_LOW: str = "wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors"
    WAN_LIGHTNING_STR_HIGH: float = 1.5
    WAN_LIGHTNING_STR_LOW: float = 1.0
    # ── 文生视频 t2v 档(Wan2.2-T2V-A14B；与 i2v 并存，由「出片模式=t2v」路由，不进用户下拉)──
    COMFYUI_WORKFLOW_T2V: str = ""                                       # 满档 t2v 模板;空=用仓库自带 t2v_fp8_template.json
    COMFYUI_WORKFLOW_T2V_LIGHTNING: str = "comfyui_workflows/t2v_fp8_lightning_template.json"
    T2V_PRECISION: str = ""                                             # 同 I2V_PRECISION;空=未探测(cell1 写入)
    WAN_T2V_LORA_HIGH: str = ""
    WAN_T2V_LORA_LOW: str = ""
    WAN_T2V_LORA_STR_HIGH: float = 1.0
    WAN_T2V_LORA_STR_LOW: float = 1.0
    WAN_I2V_LORA_HIGH: str = ""
    WAN_I2V_LORA_LOW: str = ""
    WAN_I2V_LORA_STR_HIGH: float = 0.9
    WAN_I2V_LORA_STR_LOW: float = 0.9
    WAN_T2V_LIGHTNING_LORA_HIGH: str = "wan2.2_t2v_A14b_high_noise_lora_rank64_lightx2v_4step.safetensors"
    WAN_T2V_LIGHTNING_LORA_LOW: str = "wan2.2_t2v_A14b_low_noise_lora_rank64_lightx2v_4step.safetensors"
    # ── t2v 出片后端 ──────────────────────────────────────────────
    T2V_PROVIDER: str = "comfyui-t2v"
    # Stand-In 强锁脸(WeChatCV/Stand-In)文生视频后端
    STANDIN_ENABLED: bool = False           # 配了端点 + 跑了 Colab §Stand-In 起 server 才注册;默认关
    STANDIN_BASE_URL: str = ""              # 如 http://127.0.0.1:8190(与 lightx2v 8189 错开)
    STANDIN_STEPS: int = 20                 # 锁脸无蒸馏采样步数(20 起细;Stand-In 不挂蒸馏 LoRA,身份来自参考脸)

    # ── 视频模型解耦：默认 Provider + LTX-Video 配置 ──────────────
    VIDEO_PROVIDER_DEFAULT: str = "wan2.2"
    # LTX-Video（部署后填 GPU_LTX_MODEL 即可启用；脚本自动上传）
    GPU_LTX_MODEL: str = ""                          # LTX diffusers 目录（如 /root/autodl-tmp/models/LTX-Video）或 HF id
    GPU_LTX_SCRIPT: str = "/root/autodl-tmp/ltx_i2v.py"
    GPU_LTX_T5_DIR: str = "/root/autodl-tmp/models/flux-dev/text_encoder_2"
    LTX_SIZE: str = "480*832"          # 默认竖屏快档：省显存(~10G)、更快，不会被卡上残留一点点占用就 OOM
    LTX_NUM_FRAMES: int = 121
    LTX_FPS: int = 24
    LTX_STEPS: int = 30                 # LTX 30 步已够；比 40 快约 1/4
    LTX_GUIDANCE: float = 3.0
    # ── LTX-Video 2.3（ComfyUI HTTP provider，与 Wan2.2 并列、用户在下拉里手选）──────────
    LTX2_ENABLED: bool = False
    COMFYUI_LTX_BASE_URL: str = ""
    COMFYUI_WORKFLOW_LTX: str = ""        # LTX i2v workflow 模板路径；空=用仓库自带 ltx_i2v_template.json
    LTX2_SIZE: str = "704*1280"           # 默认竖屏(宽*高，须 32 的倍数)；2.3 可上 1088*1920(1080p)
    LTX2_FRAMES: int = 121                # 帧数须 8 的倍数+1(如 121≈5s@24fps)
    LTX2_FPS: int = 24                    # LTX 原生帧率较高，常用 24
    LTX2_STEPS: int = 30                  # dev 全量精修约 30；distilled 蒸馏档约 8
    LTX2_GUIDANCE: float = 3.0
    LTX2_DISTILLED: bool = False          # True=8步蒸馏极速档(类比 Wan Lightning)；False=dev 全量精修
    LTX2_KEEP_AUDIO: bool = False         # 默认丢 LTX 自带音(交角色声音圣经 TTS 统一音色)；True=保留 LTX 原生音轨
    # ── Sulphur 2（LTX-2.3 无审查 fine-tune，NSFW 生产）──
    SULPHUR2_ENABLED: bool = False
    SULPHUR2_BASE_URL: str = ""            # Sulphur 专属 ComfyUI 端点；空=回落 COMFYUI_BASE_URL
    COMFYUI_WORKFLOW_SULPHUR_T2V: str = "" # 空=用仓库自带 comfyui_workflows/sulphur_t2v_template.json
    COMFYUI_WORKFLOW_SULPHUR_I2V: str = ""
    SULPHUR2_SIZE: str = "704*1280"        # 竖屏~720p；宽高须 32 倍数
    SULPHUR2_FRAMES: int = 121             # 须 8n+1(121≈5s@24fps)
    SULPHUR2_FPS: int = 24
    SULPHUR2_STEPS: int = 30               # dev 档 25-35；distilled 蒸馏档约 8
    SULPHUR2_GUIDANCE: float = 4.0         # Sulphur/LTX 常用 3.5-5
    SULPHUR2_DISTILLED: bool = False       # True=8步蒸馏极速档；False=dev 全量精修
    SULPHUR2_KEEP_AUDIO: bool = False      # 默认丢 LTX 自带音(交 TTS 统一音色)；True=保留原生音轨
    SULPHUR_LORA_STRENGTH: float = 1.0     # 出片挂角色 LoRA 强度(Sulphur/LTX 单 LoRA)

    # ── ComfyUI 后端（HTTP，可配置；对用户完全隐形）──────────────
    COMFYUI_BASE_URL: str = ""            # 如 http://127.0.0.1:8188（空=完全不启用 ComfyUI）
    COMFYUI_VIDEO_AS: str = "auto"        # 出片：默认 auto=配端点就让“你的默认出片模型”透明走 ComfyUI（本仓默认是 ltx）
    COMFYUI_WORKFLOW_I2V: str = ""        # i2v workflow 模板(API格式 JSON)路径；空=用仓库自带 comfyui_workflows/i2v_template.json
    COMFYUI_TIMEOUT: int = 1800           # 单段出片超时（秒）
    COMFYUI_FRAMES: int = 81              # 默认帧数（i2v 用；对口型 S2V 改为按音频时长动态算）
    COMFYUI_FPS: int = 16                 # 默认帧率（Wan 系常用 16）
    COMFYUI_STEPS: int = 30               # 默认采样步数（原生最强；A14B GGUF 模板内步数已同步为 30）
    COMFYUI_SIZE: str = "720*1280"        # 默认分辨率（宽*高）：原生最强守住 720p 竖屏（旧 480*832 是快出档）
    # Wan2.2-S2V 对口型（语音驱动）workflow 模板路径
    COMFYUI_WORKFLOW_S2V: str = ""        # S2V workflow 模板路径；空=用仓库自带 comfyui_workflows/s2v_template.json

    model_config = SettingsConfigDict(
        # 自动加载当前目录或上级目录的 .env 文件
        env_file = ".env",
        env_file_encoding = 'utf-8',
        case_sensitive = True,
        extra = "ignore"
    )


settings = ProviderSettings()
