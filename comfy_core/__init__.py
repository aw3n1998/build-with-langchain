"""
comfy_core —— ComfyUI / 视频 Provider 执行核心（解耦、自包含）。

唯一真源（single source of truth）：ComfyUI HTTP 调用、视频 Provider 注册表与各
provider 实现、远程 GPU 客户端、实时日志总线、provider 配置都集中在这里。

**不依赖 mirage.***：本包不 import 任何 mirage 代码，因此 GPU worker 只需带上
`comfy_core/` + `colab/worker/` 即可独立部署出片，无需 FastAPI / store / accounts /
langchain。Web 后端则通过 `mirage/app/pipeline/*` 下的薄 re-export shim 继续无缝使用。

provider 读取的配置见 `comfy_core.config.ProviderSettings`（与后端 Settings 同源同默认，
后端 Settings 直接继承它，避免重复定义）。
"""
