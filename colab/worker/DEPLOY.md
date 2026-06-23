# GPU Worker 独立部署

worker 已和 Web 后端**解耦**：出片执行核心全在 `comfy_core/`（实测**零 `import mirage`**），
worker 只依赖它。部署到 GPU 机**只需拷这几样**，不用带 FastAPI / 账号 / store / langchain / 前端。

## 拷什么（部署 bundle）
```
<部署目录>/
├── comfy_core/         # 出片执行核心(providers + comfy_http + gpu_client + log_bus + config + logger)
├── colab/worker/       # worker 程序(config / gpu / transport / agent / runner / __main__)
└── comfyui_workflows/  # 出片 workflow 模板(provider 填占位符用)；或用 COMFYUI_WORKFLOWS_DIR 指别处
```
> SSH 出片(wan2.2/ltx)还要带 `comfy_core/remote_scripts/`；纯 ComfyUI/Sulphur HTTP worker 不用。

## 装依赖
```bash
pip install -r requirements-worker.txt   # 纯 HTTP worker 只有 httpx / pydantic-settings / websockets
```

## 配 .env（或直接环境变量）
```bash
BACKEND_URL=http://<后端公网>:8000      # worker 主动连后端拉任务（后端永远不连 GPU）
WORKER_TOKEN=<和后端一致>               # 后端设了才校验；开发态可空
WORKER_MODELS=sulphur2                  # ★本机能跑哪些模型，写【引擎名】(comfyui-t2v / sulphur2…，不是显示名 wan2.2)；留空=通配
COMFYUI_BASE_URL=http://127.0.0.1:8188  # 本机 ComfyUI
# 出片配置（和后端同名，comfy_core 的 ProviderSettings 从 env 读）：
SULPHUR2_ENABLED=1
SULPHUR2_BASE_URL=http://127.0.0.1:8188
# COMFYUI_WORKFLOWS_DIR=/abs/path/to/comfyui_workflows   # 模板不在仓库默认位置时指过去
```

## 跑
```bash
python -m colab.worker        # 从 bundle 根目录跑；多台连同一 BACKEND_URL = 横向扩展
```
后端设 `DISPATCH_MODE=worker` 才会把出片任务入队给 worker 拉取。状态/队列/取消见后端「算力」面板。
首次真机如缺依赖按报错补即可。

## 为什么「改逻辑只改一处」
出片 / provider 逻辑全部只在 `comfy_core/` 这一份。后端通过 `mirage/app/pipeline/` 下的**薄转发 shim**
（`comfy_http` / `gpu_client` / `log_bus` / `providers`）复用**同一份** comfy_core，worker 也直接 import 它。
所以改出片逻辑只动 comfy_core，**后端和 worker 同时生效**，不必两边各改一遍。
