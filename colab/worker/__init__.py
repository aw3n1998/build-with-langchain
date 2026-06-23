"""Mirage GPU worker —— 跑在 GPU 机器上的「领任务」程序（拉取式架构 worker 端，分层包）。

跑法（仓库根目录）：
  BACKEND_URL=https://你的后端 WORKER_TOKEN=和后端一致 COMFYUI_BASE_URL=http://127.0.0.1:8188 \
  PYTHONPATH=. python -m colab.worker

分层：config(配置) / gpu(nvidia-smi) / transport(HTTP 权威通道 + WS 实时状态) / runner(出片) /
agent(生命周期). 横向扩展=多台 GPU 各跑一个、连同一 BACKEND_URL；一台 ComfyUI 只起一个 worker。
"""
__version__ = "0.2.0"
