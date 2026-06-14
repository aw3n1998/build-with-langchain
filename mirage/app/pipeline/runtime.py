"""
流水线运行时上下文 —— 把"当前工作目录"按请求传给工具，避免硬编码落地路径。

为什么用 contextvar：generate_candidates / render_scene_video 是全局 @tool，
不方便逐个透传参数。每次对话请求在 ai_service 里 set_workspace(...)，工具内部
用 get_workspace() 读取；LangChain 调同步工具时会 copy_context()，contextvar 能
正确传播到执行线程。

工作目录来源优先级：
  请求显式传入 > 环境变量 AGENT_WORKSPACE > 当前进程工作目录(cwd)/mirage_workspace
  （旧 agent_workspace 目录存在时回退沿用，老数据不丢）
"""

from __future__ import annotations

import os
from contextvars import ContextVar

# 当前请求的工作目录（绝对路径）；None 表示用默认。
_workspace: ContextVar[str | None] = ContextVar("np2v_workspace", default=None)

# 曾经用过的工作目录根集合（供 /api/file 静态服图做安全校验，跨请求共享）。
_known_roots: set[str] = set()

# 多租户预留口子：user_id -> 允许的工作目录集合。toC 时用它做"用户只能进自己目录"的名单制越权校验。
# 现为空、不启用（单用户无感）。
_user_workspaces: dict[str, set[str]] = {}


def default_workspace() -> str:
    """没显式指定时的默认工作目录。

    默认目录名由 agent_workspace 改为 mirage_workspace；带回退：若新名目录不存在
    而旧 agent_workspace 仍在，则沿用旧目录，避免老用户数据找不到。
    （环境变量名仍保留 AGENT_WORKSPACE，不破坏已有 .env。）
    """
    env = os.environ.get("AGENT_WORKSPACE")
    if env:
        return os.path.abspath(env)
    cwd = os.getcwd()
    new = os.path.abspath(os.path.join(cwd, "mirage_workspace"))
    old = os.path.abspath(os.path.join(cwd, "agent_workspace"))
    if not os.path.isdir(new) and os.path.isdir(old):
        return old
    return new


def set_workspace(path: str | None, user_id: str | None = None):
    """设置本请求工作目录，返回 token（可用于 reset，通常不需要）。

    显式指定工作目录时**立即创建 .agent 结构**，让用户一选目录就能看到它生效，
    而不是等到建项目/出图才懒创建。

    user_id（预留口子）：toC 多租户时传入，做"该用户只能进自己目录"的越权校验。
    现默认 None，不启用——单用户行为完全不变。
    """
    # TODO(toC): user_id 不为 None 时，校验 abs_path 属于 _user_workspaces.get(user_id, set())，否则拒绝(防越权)；
    #            首次进入时把目录加进该用户的名单。
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
                "_note": "蜃景 工作目录数据（小说转短剧流水线）。可随项目一起拷贝/版本管理。",
                "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                "structure": {
                    "pipeline.db": "项目/分镜/候选图状态库（SQLite）",
                    "candidates/": "FLUX 出的候选图（按分镜分子目录）",
                    "video_out/": "Wan2.2 出的成片 mp4",
                },
                # 角色/模型配置：出图时自动注入，换角色/风格只改这里，不用动代码或提示词
                "model": {
                    "trigger_word": "",       # 角色触发词（LoRA 触发词），自动加在出图提示词最前
                    "flux_lora": "",          # FLUX LoRA 路径覆盖（留空=用 .env 的默认）
                    "negative_prompt": "",    # 可选负向提示词
                },
            }, f, ensure_ascii=False, indent=2)
    return d


def _config_path() -> str:
    return os.path.join(agent_dir(), "config.json")


def workspace_config() -> dict:
    """读取当前工作目录的 .agent/config.json（损坏/不存在则返回空 dict）。"""
    import json
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def model_config() -> dict:
    """角色/模型相关的工作目录级配置（触发词 / LoRA / 负向词），带兜底默认。"""
    m = workspace_config().get("model") or {}
    return {
        "trigger_word": (m.get("trigger_word") or "").strip(),
        "flux_lora": (m.get("flux_lora") or "").strip(),
        "negative_prompt": (m.get("negative_prompt") or "").strip(),
    }


def set_model_config(trigger_word: str | None = None,
                     flux_lora: str | None = None,
                     negative_prompt: str | None = None) -> dict:
    """更新工作目录级模型配置（只改传入的非 None 字段），写回 config.json 并返回最新值。"""
    import json
    cfg = workspace_config()
    m = dict(cfg.get("model") or {})
    if trigger_word is not None:
        m["trigger_word"] = trigger_word
    if flux_lora is not None:
        m["flux_lora"] = flux_lora
    if negative_prompt is not None:
        m["negative_prompt"] = negative_prompt
    cfg["model"] = m
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return model_config()


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
