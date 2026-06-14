"""
出图模型 Provider 抽象 + 注册表 —— 把「具体用哪个模型出候选图」从流水线工具里解耦出来。

与 providers/base.py 的 VideoProvider 同款思路（出片那套的镜像）：
  - GpuClient 退回成纯传输层（run/upload/download），不认识任何出图模型；
  - 每个出图模型 = 一个 ImageProvider 子类，自带：命令/调用方式、参数 schema、传输方式；
  - 新增出图模型（如 ComfyUI 文生图）= 写一个文件 + register 一行，工具/路由/前端零改动。

为什么单独一套（不复用 VideoProvider）：
  出图与出片的 generate 形参不同（出图无参考图、返回的是「一组」候选图路径），
  且要能各自独立选模型（出图走 FLUX、出片走 Wan/ComfyUI 互不影响）。故并行一套，结构照抄。

传输方式（transport）：
  - "ssh"：generate 返回**远程**路径，工具层负责下载到工作目录（现有 FLUX 行为）。
  - "http"：generate 直接把候选图下载到**本地** out_dir 并返回本地路径（ComfyUI 纯本地分支）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from mirage.app.core.logger import get_logger

if TYPE_CHECKING:
    from mirage.app.pipeline.gpu_client import GpuClient

logger = get_logger("pipeline.image_providers")


class ImageProvider(ABC):
    """一个候选图生成模型（文生图）的适配器。子类只需声明元信息 + 实现 generate。"""

    # 唯一标识（前端/工具用它选模型），如 "flux" / "comfyui-img"
    name: str = ""
    # 人类可读名（参数卡下拉显示），如 "FLUX (SSH)"
    display_name: str = ""
    # 能力声明：{"t2i"} 文生图
    capabilities: set[str] = {"t2i"}
    # 传输方式：ssh 走 GpuClient（返回远程路径）；http 走 ComfyUI（返回本地路径）
    transport: str = "ssh"
    # 提示词语言：'en'=只懂英文(如 FLUX-dev，中文需先翻译)；'any'=不挑语言(默认)
    prompt_lang: str = "any"

    @abstractmethod
    def param_schema(self) -> list[dict]:
        """返回该模型可调参数的字段定义（驱动前端出图参数卡）。"""
        raise NotImplementedError

    def default_params(self) -> dict:
        """从 schema 推出默认参数字典（key -> default）。"""
        return {f["key"]: f.get("default") for f in self.param_schema()}

    @abstractmethod
    def generate(
        self,
        gpu: "GpuClient",
        *,
        prompt: str,
        out_dir: str,
        params: dict,
    ) -> list[str]:
        """生成 N 张候选图，返回路径列表。

        Args:
            gpu: 纯传输层客户端（ssh 模型用；http 模型忽略，可传 None）。
            prompt: 出图提示词（触发词已在工具层注入）。
            out_dir: ssh→远程输出目录；http→本地输出目录。
            params: 已与 default_params 合并后的参数字典。

        Returns:
            ssh 传输：远程图绝对路径列表（工具层负责下载）。
            http 传输：本地图绝对路径列表（provider 已下载好）。
        失败抛 GpuRunError / GpuConfigError。
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


class ImageProviderRegistry:
    """出图 Provider 注册表（与 video_provider_registry 同款热插拔）。"""

    def __init__(self) -> None:
        self._providers: dict[str, ImageProvider] = {}
        self._default: Optional[str] = None

    def register(self, provider: ImageProvider, *, default: bool = False) -> None:
        if not provider.name:
            raise ValueError("ImageProvider.name 不能为空")
        self._providers[provider.name] = provider
        if default or self._default is None:
            self._default = provider.name
        logger.info("[image_providers] 注册出图模型 %s（default=%s）", provider.name, default)

    def get(self, name: str = "") -> ImageProvider:
        """按名取 provider；name 为空取默认。找不到则回退默认并告警。"""
        if name and name in self._providers:
            return self._providers[name]
        if name:
            logger.warning("[image_providers] 未知出图模型 %s，回退默认 %s", name, self._default)
        if not self._default:
            raise RuntimeError("没有任何出图模型被注册")
        return self._providers[self._default]

    def set_default(self, name: str) -> None:
        if name in self._providers:
            self._default = name

    @property
    def default_name(self) -> str:
        return self._default or ""

    def list_providers(self) -> list[dict]:
        """所有已注册出图模型的自描述列表（供参数卡的模型下拉 + /api 查询）。"""
        return [p.info() for p in self._providers.values()]

    def has(self, name: str) -> bool:
        return name in self._providers


# 全局单例
image_provider_registry = ImageProviderRegistry()
