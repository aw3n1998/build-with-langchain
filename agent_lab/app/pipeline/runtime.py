"""
流水线运行时上下文 —— 把"当前工作目录"按请求传给工具，避免硬编码落地路径。

为什么用 contextvar：generate_candidates / render_scene_video 是全局 @tool，
不方便逐个透传参数。每次对话请求在 ai_service 里 set_workspace(...)，工具内部
用 get_workspace() 读取；LangChain 调同步工具时会 copy_context()，contextvar 能
正确传播到执行线程。

工作目录来源优先级：
  请求显式传入 > 环境变量 AGENT_WORKSPACE > 当前进程工作目录(cwd)/agent_workspace
"""

from __future__ import annotations

import os
from contextvars import ContextVar

# 当前请求的工作目录（绝对路径）；None 表示用默认。
_workspace: ContextVar[str | None] = ContextVar("np2v_workspace", default=None)

# 曾经用过的工作目录根集合（供 /api/file 静态服图做安全校验，跨请求共享）。
_known_roots: set[str] = set()


def default_workspace() -> str:
    """没显式指定时的默认工作目录。"""
    env = os.environ.get("AGENT_WORKSPACE")
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(os.getcwd(), "agent_workspace"))


def set_workspace(path: str | None):
    """设置本请求工作目录，返回 token（可用于 reset，通常不需要）。

    显式指定工作目录时**立即创建 .agent 结构**，让用户一选目录就能看到它生效，
    而不是等到建项目/出图才懒创建。
    """
    abs_path = os.path.abspath(path) if path else None
    if abs_path:
        _known_roots.add(os.path.realpath(abs_path))
    _known_roots.add(os.path.realpath(default_workspace()))
    token = _workspace.set(abs_path)
    if abs_path:
        try:
            # 立即把 .agent/ 及其子目录建好（config.json/candidates/video_out）
            agent_dir()
            candidates_dir()
            video_dir()
        except Exception:
            pass
    return token


def explicit_workspace() -> str | None:
    """取本请求**显式设置**的工作目录（未设置返回 None）。

    给通用文件工具用：用户在网页选了工作目录就以它为根，否则保持各自默认。
    """
    ws = _workspace.get()
    return os.path.abspath(ws) if ws else None


def get_workspace() -> str:
    """取当前工作目录（绝对路径），保证存在。"""
    ws = _workspace.get() or default_workspace()
    os.makedirs(ws, exist_ok=True)
    _known_roots.add(os.path.realpath(ws))
    return ws


def is_within_known_root(abs_path: str) -> bool:
    """供静态服图：abs_path 是否落在任意已知工作目录根下（防穿越）。"""
    try:
        rp = os.path.realpath(abs_path)
    except Exception:
        return False
    for root in _known_roots | {os.path.realpath(default_workspace())}:
        try:
            if os.path.commonpath([root, rp]) == root:
                return True
        except Exception:
            continue
    return False


def agent_dir() -> str:
    """每个工作目录下的 .agent 文件夹（类似 .claude）：放本项目的状态库 / 产物 / 配置。"""
    d = os.path.join(get_workspace(), ".agent")
    os.makedirs(d, exist_ok=True)
    # 首次创建时落一份说明 + 配置，便于用户识别
    cfg = os.path.join(d, "config.json")
    if not os.path.exists(cfg):
        import json
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({
                "_note": "AgentLab 工作目录数据（小说转短剧流水线）。可随项目一起拷贝/版本管理。",
                "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                "structure": {
                    "pipeline.db": "项目/分镜/候选图状态库（SQLite）",
                    "candidates/": "FLUX 出的候选图（按分镜分子目录）",
                    "video_out/": "Wan2.2 出的成片 mp4",
                },
            }, f, ensure_ascii=False, indent=2)
    return d


def state_db() -> str:
    """本工作目录的流水线状态库路径：<workspace>/.agent/pipeline.db。"""
    return os.path.join(agent_dir(), "pipeline.db")


def candidates_dir(scene_id: str = "") -> str:
    base = os.path.join(agent_dir(), "candidates")
    d = os.path.join(base, scene_id) if scene_id else base
    os.makedirs(d, exist_ok=True)
    return d


def video_dir() -> str:
    d = os.path.join(agent_dir(), "video_out")
    os.makedirs(d, exist_ok=True)
    return d


def is_within_workspace(abs_path: str) -> bool:
    """路径安全：abs_path 是否在当前工作目录下（防目录穿越）。"""
    try:
        ws = os.path.realpath(get_workspace())
        rp = os.path.realpath(abs_path)
        return os.path.commonpath([ws, rp]) == ws
    except Exception:
        return False
