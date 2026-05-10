from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os

class Settings(BaseSettings):
    # 项目元数据
    PROJECT_NAME: str = "Omni-Intelligence Platform"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # OpenAI / DeepSeek 配置 (优先从 .env 读取)
    OPENAI_API_KEY: str = "sk-placeholder"
    OPENAI_API_BASE: str = "https://api.deepseek.com/v1"
    MODEL_NAME: str = "deepseek-chat"

    # 网络高级配置
    SKIP_SSL_VERIFY: bool = True
    REQUEST_TIMEOUT: int = 30

    model_config = SettingsConfigDict(
        # 自动加载当前目录或上级目录的 .env 文件
        env_file = ".env",
        env_file_encoding = 'utf-8',
        case_sensitive = True,
        extra = "ignore" 
    )

settings = Settings()
