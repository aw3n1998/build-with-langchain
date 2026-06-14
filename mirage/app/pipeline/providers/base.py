"""
视频模型 Provider 抽象 + 注册表 —— 把「具体用哪个视频模型出片」从流水线工具里解耦出来。

为什么要这层？
  原先 Wan2.2 的命令、参数、模型路径写死在 gpu_client.generate_video 与 pipeline_tools 里，
  换/加模型（如 LTX-Video）要改传输层、工具层、参数卡三处。抽出 Provider 后：
    - GpuClient 退回成纯传输层（run/upload/download），不认识任何模型；
    - 每个模型 = 一个 VideoProvider 子类，自带：命令模板、env、模型路径、参数 schema；
    - 新增模型 = 写一个文件 + register 一行，工具/路由/前端零改动（参数卡由 schema 驱动）。

参数 schema 字段格式（驱动前端「出视频参数卡」动态渲染）：
    {"key": "size", "label": "分辨率", "type": "select", "default": "704*1280",
     "options": [{"value": "704*1280", "label": "704×1280 竖屏"}, ...]}
    {"key": "frame_num", "label": "帧数(≤25稳)", "type": "number", "default": 25}
  type 取值：number / text / select。select 必带 options。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from mirage.app.core.logger import get_logger

if TYPE_CHECKING:
    from mirage.app.pipeline.gpu_client import GpuClient

logger = get_logger("pipeline.providers")


class VideoProvider(ABC):
    """一个视频生成模型的适配器。子类只需声明元信息 + 实现 generate。"""

    # 唯一标识（前端/工具用它选模型），如 "wan2.2" / "ltx"
    name: str = ""
    # 人类可读名（参数卡下拉显示），如 "Wan2.2-I2V-A14B"（5B 已弃用）
    display_name: str = ""
    # 能力声明：{"i2v"} 图生视频 / {"t2v"} 文生视频 / {"s2v"} 语音驱动(对口型)
    capabilities: set[str] = {"i2v"}
    # 隐藏：不进用户可见的模型下拉（如 S2V 由「对口型」开关自动路由，不让用户手选）
    hidden: bool = False

    @abstractmethod
    def param_schema(self) -> list[dict]:
        """返回该模型可调参数的字段定义（驱动前端参数卡）。不含通用的 motion_prompt。"""
        raise NotImplementedError

    def default_params(self) -> dict:
        """从 schema 推出默认参数字典（key -> default）。"""
        return {f["key"]: f.get("default") for f in self.param_schema()}

    @abstractmethod
    def generate(
        self,
        gpu: "GpuClient",
        *,
        image_path: str,
        prompt: str,
        out_remote: str,
        params: dict,
    ) -> None:
        """在 GPU 上出片，产物落在 out_remote。失败抛 GpuRunError。

        Args:
            gpu: 纯传输层客户端（run/upload/download）。
            image_path: 服务器上的参考图绝对路径（i2v 用；t2v 模型可忽略）。
            prompt: 运镜/动态提示词。
            out_remote: 服务器上成片输出绝对路径（.mp4）。
            params: 已与 default_params 合并后的参数字典。
        """
        raise NotImplementedError

    def info(self) -> dict:
        """给前端/接口的自描述（名字 + 能力 + 字段 schema）。"""
        return {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "capabilities": sorted(self.capabilities),
            "fields": self.param_schema(),
        }


class ProviderRegistry:
    """视频 Provider 注册表（与 agent_registry 同款热插拔思路）。"""

    def __init__(self) -> None:
        self._providers: dict[str, VideoProvider] = {}
        self._default: Optional[str] = None

    def register(self, provider: VideoProvider, *, default: bool = False) -> None:
        if not provider.name:
            raise ValueError("VideoProvider.name 不能为空")
        self._providers[provider.name] = provider
        if default or self._default is None:
            self._default = provider.name
        logger.info("[providers] 注册视频模型 %s（default=%s）", provider.name, default)

    def get(self, name: str = "") -> VideoProvider:
        """按名取 provider；name 为空取默认。找不到则回退默认并告警。"""
        if name and name in self._providers:
            return self._providers[name]
        if name:
            logger.warning("[providers] 未知视频模型 %s，回退默认 %s", name, self._default)
        if not self._default:
            raise RuntimeError("没有任何视频模型被注册")
        return self._providers[self._default]

    def set_default(self, name: str) -> None:
        if name in self._providers:
            self._default = name

    @property
    def default_name(self) -> str:
        return self._default or ""

    def list_providers(self) -> list[dict]:
        """用户可见模型的自描述列表（供参数卡的模型下拉 + /api 查询）。隐藏 Provider(如 S2V)不列。"""
        return [p.info() for p in self._providers.values() if not getattr(p, "hidden", False)]

    def has(self, name: str) -> bool:
        return name in self._providers


# 全局单例
video_provider_registry = ProviderRegistry()
