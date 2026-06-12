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
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    OPENAI_API_BASE: str = "https://api.deepseek.com/v1"
    MODEL_NAME: str = "deepseek-chat"
    EMBEDDING_MODEL_NAME: str = "text-embedding-3-small"

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
    GPU_WAN_CKPT: str = "/root/autodl-tmp/models/Wan-AI/Wan2.2-TI2V-5B"
    GPU_FLUX_SCRIPT: Optional[str] = None           # 旧版单图脚本（已弃用，保留向后兼容）
    GPU_OUTPUT_DIR: str = "/root/autodl-tmp/pipeline_out"
    GPU_SCENES_DIR: str = "/root/autodl-tmp/cael_scenes"
    # FLUX 多候选出图（单次加载、多种子；本地源会自动上传，无需手动部署）
    GPU_FLUX_CANDIDATES_SCRIPT: str = "/root/autodl-tmp/flux_candidates.py"
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
    # Wan2.2 已验证可跑通的省显存配置（单卡 24G）
    WAN_SIZE: str = "704*1280"
    WAN_FRAME_NUM: int = 25
    WAN_SAMPLE_STEPS: int = 25
    # ── 视频模型解耦：默认 Provider + LTX-Video 配置 ──────────────
    # 默认用哪个视频模型（对应 providers 注册名：wan2.2 / ltx）
    VIDEO_PROVIDER_DEFAULT: str = "wan2.2"
    # LTX-Video（部署后填 GPU_LTX_MODEL 即可启用；脚本自动上传）
    GPU_LTX_MODEL: str = ""                          # LTX diffusers 目录（如 /root/autodl-tmp/models/LTX-Video）或 HF id
    GPU_LTX_SCRIPT: str = "/root/autodl-tmp/ltx_i2v.py"
    # 复用 FLUX 的 T5-XXL text_encoder，省 ~19G 盘（留空则用 LTX 自带 text_encoder）
    GPU_LTX_T5_DIR: str = "/root/autodl-tmp/models/flux-dev/text_encoder_2"
    LTX_SIZE: str = "704*1280"
    LTX_NUM_FRAMES: int = 121
    LTX_FPS: int = 24
    LTX_STEPS: int = 40
    LTX_GUIDANCE: float = 3.0
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
    COMFYUI_FRAMES: int = 81              # 默认帧数
    COMFYUI_FPS: int = 16                 # 默认帧率（Wan 系常用 16）
    COMFYUI_STEPS: int = 20               # 默认采样步数
    COMFYUI_SIZE: str = "480*832"         # 默认分辨率（宽*高）
    # ComfyUI 文生图（t2i）：把出图也接到 ComfyUI（GGUF Flux / 更好采样器 / LoRA 叠加）
    COMFYUI_WORKFLOW_T2I: str = ""        # t2i workflow 模板路径；空=用仓库自带 comfyui_workflows/t2i_template.json
    COMFYUI_T2I_SIZE: str = "768*1024"    # 出图默认分辨率（宽*高）
    COMFYUI_T2I_STEPS: int = 28           # 出图默认采样步数
    COMFYUI_T2I_N: int = 4                # 一次出几张候选图
    # ComfyUI 后处理（放大/补帧）：合成后可选再过一道 workflow；留空=不做后处理
    COMFYUI_WORKFLOW_POST: str = ""       # 后处理 workflow 模板路径（空=关闭后处理）
    # Wan2.2-S2V 对口型（语音驱动）：人物开口说话的镜头用。图+音频→口型同步视频，走 ComfyUI。
    # 隐藏 Provider：不进用户模型下拉，由每镜「对口型」开关自动路由。端点门控同 COMFYUI_BASE_URL。
    COMFYUI_WORKFLOW_S2V: str = ""        # S2V workflow 模板路径；空=用仓库自带 comfyui_workflows/s2v_template.json
    COMFYUI_S2V_TTS_VOICE: str = "zh-CN-YunxiNeural"  # 对口型用的 TTS 音色（edge-tts；男声示例）
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
