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
