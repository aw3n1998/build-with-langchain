"""
流水线状态机存储 —— 架构文档 DDL 的 SQLite 精简实现。

为什么用 SQLite 而非架构文档里的 Postgres？
  本框架（build-with-langchain）已用 langgraph-checkpoint-sqlite 做会话持久化，
  这里复用同一套轻量持久化栈，避免为"一个能力"引入 Postgres+Celery+Redis 整套重型基建。
  表结构与状态机语义和架构文档完全对齐，未来要换 Postgres 只需替换本文件。

线程安全：每次操作开新连接（check_same_thread=False + 短事务），适配 FastAPI async 多线程。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from agent_lab.app.core.logger import get_logger

logger = get_logger("pipeline.store")


class SceneState(str, Enum):
    """分镜状态机 —— 与架构文档 scenes.state CHECK 约束一致。"""
    DRAFT = "DRAFT"
    PENDING_FLUX_GEN = "PENDING_FLUX_GEN"
    PENDING_HUMAN_SELECTION = "PENDING_HUMAN_SELECTION"
    PENDING_VIDEO_GEN = "PENDING_VIDEO_GEN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# 合法状态流转（防止非法跳转）
_ALLOWED_TRANSITIONS: dict[SceneState, set[SceneState]] = {
    SceneState.DRAFT: {SceneState.PENDING_FLUX_GEN, SceneState.FAILED},
    SceneState.PENDING_FLUX_GEN: {SceneState.PENDING_HUMAN_SELECTION, SceneState.FAILED},
    SceneState.PENDING_HUMAN_SELECTION: {SceneState.PENDING_VIDEO_GEN, SceneState.PENDING_FLUX_GEN, SceneState.FAILED},
    SceneState.PENDING_VIDEO_GEN: {SceneState.COMPLETED, SceneState.FAILED},
    SceneState.COMPLETED: {SceneState.PENDING_VIDEO_GEN},  # 允许重渲染
    SceneState.FAILED: {SceneState.PENDING_FLUX_GEN, SceneState.PENDING_VIDEO_GEN},
}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    novel_text  TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'IN_PROGRESS',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scene_number  INTEGER NOT NULL,
    title         TEXT DEFAULT '',
    narration     TEXT NOT NULL DEFAULT '',
    image_prompt  TEXT NOT NULL DEFAULT '',
    motion_prompt TEXT NOT NULL DEFAULT '',
    state         TEXT NOT NULL DEFAULT 'DRAFT',
    selected_asset_id TEXT,
    video_path    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenes_project ON scenes(project_id);
CREATE INDEX IF NOT EXISTS idx_scenes_state   ON scenes(state);

CREATE TABLE IF NOT EXISTS assets (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    scene_id      TEXT NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    asset_type    TEXT NOT NULL DEFAULT 'IMAGE',
    storage_path  TEXT NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'PENDING',
    is_selected   INTEGER NOT NULL DEFAULT 0,
    metadata      TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_scene ON assets(scene_id);
"""


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class TransitionError(RuntimeError):
    """非法状态流转。"""


class PipelineStore:
    """流水线状态库。所有方法返回纯 dict，便于直接序列化给工具/前端。"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        logger.info("[PipelineStore] 状态库就绪: %s", db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ── 项目 ──────────────────────────────────────────────────────
    def create_project(self, title: str, novel_text: str = "") -> dict:
        pid = _uid()
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO projects(id,title,novel_text,status,created_at) VALUES(?,?,?,?,?)",
                (pid, title, novel_text, "IN_PROGRESS", _now()),
            )
        logger.info("[PipelineStore] 新建项目 %s: %s", pid, title)
        return self.get_project(pid)

    def get_project(self, project_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def list_projects(self) -> list[dict]:
        """本工作目录的全部项目（新→旧），供制作面板入口选择/默认取最新。"""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    # ── 分镜 ──────────────────────────────────────────────────────
    def add_scene(
        self,
        project_id: str,
        scene_number: int,
        narration: str = "",
        image_prompt: str = "",
        motion_prompt: str = "",
        title: str = "",
    ) -> dict:
        if not self.get_project(project_id):
            raise ValueError(f"项目不存在: {project_id}")
        sid = _uid()
        ts = _now()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO scenes(id,project_id,scene_number,title,narration,
                   image_prompt,motion_prompt,state,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (sid, project_id, scene_number, title, narration,
                 image_prompt, motion_prompt, SceneState.DRAFT.value, ts, ts),
            )
        return self.get_scene(sid)

    def get_scene(self, scene_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()
        return dict(row) if row else None

    def list_scenes(self, project_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scenes WHERE project_id=? ORDER BY scene_number", (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def set_scene_state(self, scene_id: str, new_state: SceneState, *, force: bool = False) -> dict:
        scene = self.get_scene(scene_id)
        if not scene:
            raise ValueError(f"分镜不存在: {scene_id}")
        cur = SceneState(scene["state"])
        new_state = SceneState(new_state)
        if not force and new_state not in _ALLOWED_TRANSITIONS.get(cur, set()) and new_state != cur:
            raise TransitionError(f"非法状态流转: {cur.value} → {new_state.value}")
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE scenes SET state=?, updated_at=? WHERE id=?",
                (new_state.value, _now(), scene_id),
            )
        logger.info("[PipelineStore] 分镜 %s 状态: %s → %s", scene_id, cur.value, new_state.value)
        return self.get_scene(scene_id)

    def set_scene_video(self, scene_id: str, video_path: str) -> dict:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE scenes SET video_path=?, updated_at=? WHERE id=?",
                (video_path, _now(), scene_id),
            )
        return self.get_scene(scene_id)

    # ── 候选素材 ──────────────────────────────────────────────────
    def add_asset(
        self,
        scene_id: str,
        storage_path: str,
        asset_type: str = "IMAGE",
        metadata: Optional[dict] = None,
    ) -> dict:
        scene = self.get_scene(scene_id)
        if not scene:
            raise ValueError(f"分镜不存在: {scene_id}")
        aid = _uid()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO assets(id,project_id,scene_id,asset_type,storage_path,
                   approval_status,is_selected,metadata,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (aid, scene["project_id"], scene_id, asset_type, storage_path,
                 "PENDING", 0, json.dumps(metadata or {}), _now()),
            )
        return self.get_asset(aid)

    def get_asset(self, asset_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        d["is_selected"] = bool(d["is_selected"])
        return d

    def list_assets(self, scene_id: str, asset_type: Optional[str] = None) -> list[dict]:
        q = "SELECT * FROM assets WHERE scene_id=?"
        params: list[Any] = [scene_id]
        if asset_type:
            q += " AND asset_type=?"
            params.append(asset_type)
        q += " ORDER BY created_at"
        with self._conn() as conn:
            rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            d["is_selected"] = bool(d["is_selected"])
            out.append(d)
        return out

    def select_asset(self, scene_id: str, asset_id: str) -> dict:
        """HITL 选图：把某候选标记为选中，并把分镜推进到 PENDING_VIDEO_GEN。"""
        asset = self.get_asset(asset_id)
        if not asset or asset["scene_id"] != scene_id:
            raise ValueError("候选素材不属于该分镜")
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE assets SET is_selected=0, approval_status='REJECTED' WHERE scene_id=?", (scene_id,))
            conn.execute(
                "UPDATE assets SET is_selected=1, approval_status='APPROVED' WHERE id=?", (asset_id,)
            )
            conn.execute("UPDATE scenes SET selected_asset_id=? WHERE id=?", (asset_id, scene_id))
        self.set_scene_state(scene_id, SceneState.PENDING_VIDEO_GEN)
        return self.get_scene(scene_id)

    # ── 汇总 ──────────────────────────────────────────────────────
    def status(self, project_id: str) -> dict:
        proj = self.get_project(project_id)
        if not proj:
            raise ValueError(f"项目不存在: {project_id}")
        scenes = self.list_scenes(project_id)
        for s in scenes:
            s["num_candidates"] = len(self.list_assets(s["id"], "IMAGE"))
        return {"project": proj, "scenes": scenes}


# ── 单例工厂（按 db_path 缓存，支持每个工作目录独立状态库）──────────
_STORES: dict[str, PipelineStore] = {}
_SINGLETON_LOCK = threading.Lock()


def _default_db_path() -> str:
    """默认状态库路径：优先 NP2V_DB_PATH；否则当前工作目录的 .agent/pipeline.db。"""
    env = os.environ.get("NP2V_DB_PATH")
    if env:
        return env
    try:
        from agent_lab.app.pipeline.runtime import state_db
        return state_db()
    except Exception:
        workspace = os.environ.get("AGENT_WORKSPACE", os.getcwd())
        return os.path.join(workspace, "pipeline.db")


def get_store(db_path: Optional[str] = None) -> PipelineStore:
    """获取状态库（按 db_path 缓存）。db_path 默认取当前工作目录的 .agent/pipeline.db。

    每个工作目录有独立状态库，所以项目/分镜/候选图都随该文件夹自包含。
    """
    if db_path is None:
        db_path = _default_db_path()
    key = os.path.abspath(db_path)
    store = _STORES.get(key)
    if store is None:
        with _SINGLETON_LOCK:
            store = _STORES.get(key)
            if store is None:
                store = PipelineStore(db_path)
                _STORES[key] = store
    return store
