from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime
import uuid

class BaseSchema(BaseModel):
    """所有 Schema 的基类，提供通用配置"""
    # Pydantic V2 使用 model_config 代替内部类 Config
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )

class AIRequest(BaseSchema):
    """统一的 AI 请求模型"""
    # request_id: 对标 Java 的私有变量并赋予初始值
    # Field(default_factory=...): 对标 Java 的构造函数或延迟加载，每次实例化都会调用 lambda 生成新的 UUID
    # 类似 Java: private String requestId = UUID.randomUUID().toString();
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # session_id: ... (三个点) 表示 "Required"，即必填项
    # 对标 Java: 在带参构造函数中强制要求的参数，或者使用 @NotNull 注解
    # 如果实例化 AIRequest 时没传 session_id，Pydantic 会直接抛出异常（类似校验失败）
    session_id: str = Field(..., description="会话ID，用于追踪上下文")
    content: str = Field(..., min_length=1, description="输入文本")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    @field_validator('content')
    @classmethod
    def content_check(cls, v: str):
        if len(v.strip()) == 0:
            raise ValueError("Content cannot be empty or just whitespace")
        return v

class AIResponse(BaseSchema):
    """统一的 AI 响应模型"""
    request_id: str
    content: str
    raw_output: Dict[str, Any] = Field(default_factory=dict)
    finish_reason: Optional[str] = None
    tokens_used: int = 0
