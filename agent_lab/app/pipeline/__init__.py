"""
小说转短剧视频流水线（Novel-to-Video Pipeline）—— build-with-langchain 扩展模块

把 headless / 解耦 / 人在回路（HITL）的小说转视频架构，原生集成进 LangGraph 框架：
  - store.py        : 轻量 SQLite 状态机（projects / scenes / assets），对应架构文档 DDL
  - gpu_client.py   : 远程 GPU 客户端，跑 FLUX.1-dev 出图 + Wan2.2-TI2V-5B 图生视频
  - pipeline_tools.py: LangChain @tool 封装，供 Agent（video_agent）按需检索调用

状态机（与架构文档一致）：
  DRAFT → PENDING_FLUX_GEN → PENDING_HUMAN_SELECTION → PENDING_VIDEO_GEN → COMPLETED / FAILED
HITL 卡点在 PENDING_HUMAN_SELECTION：出图后暂停，由人（或上层 Agent）选图再恢复。
"""

from agent_lab.app.pipeline.store import (
    SceneState,
    PipelineStore,
    get_store,
)
from agent_lab.app.pipeline.gpu_client import (
    GpuClient,
    GpuConfigError,
    GpuRunError,
    get_gpu_client,
)
from agent_lab.app.pipeline.pipeline_tools import pipeline_tools

__all__ = [
    "SceneState",
    "PipelineStore",
    "get_store",
    "GpuClient",
    "GpuConfigError",
    "GpuRunError",
    "get_gpu_client",
    "pipeline_tools",
]
