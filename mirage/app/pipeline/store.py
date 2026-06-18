"""
流水线状态机存储 —— 架构文档 DDL 的 SQLite 精简实现。

为什么用 SQLite 而非架构文档里的 Postgres？
  本框架（蜃景 Mirage）已用 langgraph-checkpoint-sqlite 做会话持久化，
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

from mirage.app.core.logger import get_logger

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
    style_prompt    TEXT NOT NULL DEFAULT '',
    trigger_word    TEXT NOT NULL DEFAULT '',
    flux_lora       TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    default_size    TEXT NOT NULL DEFAULT '',
    wan_t2v_lora_high TEXT NOT NULL DEFAULT '',
    wan_t2v_lora_low  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scene_number  INTEGER NOT NULL,
    title         TEXT DEFAULT '',
    narration     TEXT NOT NULL DEFAULT '',
    subtitle      TEXT NOT NULL DEFAULT '',
    lipsync       INTEGER NOT NULL DEFAULT 0,
    image_prompt  TEXT NOT NULL DEFAULT '',
    motion_prompt TEXT NOT NULL DEFAULT '',
    voice         TEXT NOT NULL DEFAULT '',
    dialogue      TEXT NOT NULL DEFAULT '',
    character     TEXT NOT NULL DEFAULT '',
    video_mode    TEXT NOT NULL DEFAULT 'i2v',
    state         TEXT NOT NULL DEFAULT 'DRAFT',
    selected_asset_id TEXT,
    video_path    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenes_project ON scenes(project_id);
CREATE INDEX IF NOT EXISTS idx_scenes_state   ON scenes(state);

CREATE TABLE IF NOT EXISTS characters (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL DEFAULT '',
    appearance  TEXT NOT NULL DEFAULT '',
    voice       TEXT NOT NULL DEFAULT '',
    trigger_word    TEXT NOT NULL DEFAULT '',   -- 多角色 LoRA 触发词(空=回退角色名 slug)
    ref_image_path  TEXT NOT NULL DEFAULT '',   -- 参考脸图(PuLID 单脸自举/展示)
    trained_lora_id TEXT NOT NULL DEFAULT '',   -- 已训 LoRA → lora_trainings.id(反向链)
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_characters_project ON characters(project_id);

CREATE TABLE IF NOT EXISTS lora_trainings (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name         TEXT NOT NULL DEFAULT '',
    trigger_word TEXT NOT NULL DEFAULT '',
    char_id      TEXT,
    status       TEXT NOT NULL DEFAULT 'DRAFT',   -- DRAFT/PENDING_BACKEND/QUEUED/TRAINING/DONE/FAILED
    image_count  INTEGER NOT NULL DEFAULT 0,
    images_dir   TEXT NOT NULL DEFAULT '',
    output_path  TEXT NOT NULL DEFAULT '',
    steps        INTEGER NOT NULL DEFAULT 0,
    message      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lora_project ON lora_trainings(project_id);

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

CREATE TABLE IF NOT EXISTS templates (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,        -- style / motion / prompt
    name        TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',   -- style=风格 dict 的 JSON；motion/prompt=文本
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_templates_kind ON templates(kind);
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
            self._migrate(conn)

    def _migrate(self, conn) -> None:
        """对老库补列（CREATE TABLE IF NOT EXISTS 不会给旧表加新列）。逐列尝试，已存在则跳过。"""
        cols = {r[1] for r in conn.execute("PRAGMA table_info(scenes)").fetchall()}
        if "subtitle" not in cols:   # 字幕独立于旁白：旧库补这一列
            conn.execute("ALTER TABLE scenes ADD COLUMN subtitle TEXT NOT NULL DEFAULT ''")
            logger.info("[PipelineStore] 迁移：scenes 补列 subtitle")
        if "lipsync" not in cols:    # 对口型(S2V)开关：旧库补这一列
            conn.execute("ALTER TABLE scenes ADD COLUMN lipsync INTEGER NOT NULL DEFAULT 0")
            logger.info("[PipelineStore] 迁移：scenes 补列 lipsync")
        if "voice" not in cols:      # 每镜 TTS 音色(角色声音圣经)：旧库补这一列
            conn.execute("ALTER TABLE scenes ADD COLUMN voice TEXT NOT NULL DEFAULT ''")
            logger.info("[PipelineStore] 迁移：scenes 补列 voice")
        if "dialogue" not in cols:   # 多角色对话(每行「说话人：台词」)：旧库补这一列
            conn.execute("ALTER TABLE scenes ADD COLUMN dialogue TEXT NOT NULL DEFAULT ''")
            logger.info("[PipelineStore] 迁移：scenes 补列 dialogue")
        if "character" not in cols:  # 本镜主角名(PuLID 锁脸/音色路由按它查角色)：旧库补这一列
            conn.execute("ALTER TABLE scenes ADD COLUMN character TEXT NOT NULL DEFAULT ''")
            logger.info("[PipelineStore] 迁移：scenes 补列 character")
        if "video_mode" not in cols:  # 出片模式 i2v/t2v(t2v=文生视频，不出图不选图)：旧库补这一列
            conn.execute("ALTER TABLE scenes ADD COLUMN video_mode TEXT NOT NULL DEFAULT 'i2v'")
            logger.info("[PipelineStore] 迁移：scenes 补列 video_mode")
        # 项目级风格（每集一种风格）：旧库给 projects 补列
        pcols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
        for col in ("style_prompt", "trigger_word", "flux_lora", "negative_prompt", "default_size",
                    "wan_t2v_lora_high", "wan_t2v_lora_low"):
            if col not in pcols:
                conn.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
                logger.info("[PipelineStore] 迁移：projects 补列 %s", col)
        # 角色参考脸 + 已训 LoRA 反向链 + 多角色 LoRA 触发词：旧库给 characters 补列
        ccols = {r[1] for r in conn.execute("PRAGMA table_info(characters)").fetchall()}
        for col in ("ref_image_path", "trained_lora_id", "trigger_word"):
            if col not in ccols:
                conn.execute(f"ALTER TABLE characters ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
                logger.info("[PipelineStore] 迁移：characters 补列 %s", col)

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

    def rename_project(self, project_id: str, title: str) -> dict:
        if not self.get_project(project_id):
            raise ValueError(f"项目不存在: {project_id}")
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE projects SET title=? WHERE id=?", (title, project_id))
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        """删除项目及其全部分镜/候选（外键 ON DELETE CASCADE）。返回是否删到。"""
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        logger.info("[PipelineStore] 删除项目 %s（删到 %d 行）", project_id, cur.rowcount)
        return cur.rowcount > 0

    _STYLE_COLS = ("style_prompt", "trigger_word", "flux_lora", "negative_prompt", "default_size",
                   "wan_t2v_lora_high", "wan_t2v_lora_low")

    def get_project_style(self, project_id: str) -> dict:
        """项目级风格（每集一种风格）：通用风格词/触发词/LoRA/负向词/默认尺寸。缺失返回空串。"""
        p = self.get_project(project_id) or {}
        return {k: (p.get(k) or "") for k in self._STYLE_COLS}

    def update_project_style(self, project_id: str, **fields) -> dict:
        """只更新传入的风格字段（None 跳过）。返回最新风格 dict。"""
        if not self.get_project(project_id):
            raise ValueError(f"项目不存在: {project_id}")
        sets, params = [], []
        for col in self._STYLE_COLS:
            val = fields.get(col)
            if val is not None:
                sets.append(f"{col}=?"); params.append(str(val))
        if sets:
            params.append(project_id)
            with self._lock, self._conn() as conn:
                conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", params)
        return self.get_project_style(project_id)

    def set_project_novel(self, project_id: str, novel_text: str) -> None:
        """把小说原文存进项目（供重拆/存档）。"""
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE projects SET novel_text=? WHERE id=?", (novel_text or "", project_id))

    # ── 角色/声音圣经（每剧角色：名字 + 外貌 + 固定 TTS 音色）──────────
    def list_characters(self, project_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM characters WHERE project_id=? ORDER BY created_at", (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def add_character(self, project_id: str, name: str, appearance: str = "", voice: str = "",
                      ref_image_path: str = "", trained_lora_id: str = "") -> dict:
        if not self.get_project(project_id):
            raise ValueError(f"项目不存在: {project_id}")
        cid = _uid()
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO characters(id,project_id,name,appearance,voice,ref_image_path,trained_lora_id,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (cid, project_id, name or "", appearance or "", voice or "",
                 ref_image_path or "", trained_lora_id or "", _now()),
            )
        return self.get_character(cid)

    def get_character(self, char_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM characters WHERE id=?", (char_id,)).fetchone()
        return dict(row) if row else None

    def update_character(self, char_id: str, *, name: str | None = None,
                         appearance: str | None = None, voice: str | None = None,
                         ref_image_path: str | None = None, trained_lora_id: str | None = None,
                         trigger_word: str | None = None) -> dict:
        sets, params = [], []
        for col, val in (("name", name), ("appearance", appearance), ("voice", voice),
                         ("ref_image_path", ref_image_path), ("trained_lora_id", trained_lora_id),
                         ("trigger_word", trigger_word)):
            if val is not None:
                sets.append(f"{col}=?"); params.append(val)
        if sets:
            params.append(char_id)
            with self._lock, self._conn() as conn:
                conn.execute(f"UPDATE characters SET {', '.join(sets)} WHERE id=?", params)
        return self.get_character(char_id)

    def delete_character(self, char_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM characters WHERE id=?", (char_id,))
        return cur.rowcount > 0

    def set_scene_voice(self, scene_id: str, voice: str) -> dict:
        """设这一镜的 TTS 音色（角色圣经路由用；空=用全集默认）。"""
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE scenes SET voice=?, updated_at=? WHERE id=?", (voice or "", _now(), scene_id))
        return self.get_scene(scene_id)

    # ── 人物 LoRA 训练（门控，等 Colab 训练后端接入）──────────────
    def add_lora_training(self, project_id: str, name: str, trigger_word: str = "",
                          char_id: str = "", images_dir: str = "", image_count: int = 0,
                          steps: int = 0, status: str = "DRAFT", message: str = "") -> dict:
        tid = _uid()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO lora_trainings(id,project_id,name,trigger_word,char_id,status,
                   image_count,images_dir,output_path,steps,message,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tid, project_id, name or "", trigger_word or "", char_id or "", status,
                 int(image_count), images_dir or "", "", int(steps), message or "", _now()),
            )
        return self.get_lora_training(tid)

    def get_lora_training(self, tid: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM lora_trainings WHERE id=?", (tid,)).fetchone()
        return dict(row) if row else None

    def list_lora_trainings(self, project_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM lora_trainings WHERE project_id=? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def update_lora_training(self, tid: str, **fields) -> dict:
        cols = ("name", "status", "output_path", "message", "image_count", "steps", "trigger_word", "char_id")
        sets, params = [], []
        for c in cols:
            if c in fields and fields[c] is not None:
                sets.append(f"{c}=?"); params.append(fields[c])
        if sets:
            params.append(tid)
            with self._lock, self._conn() as conn:
                conn.execute(f"UPDATE lora_trainings SET {', '.join(sets)} WHERE id=?", params)
        return self.get_lora_training(tid)

    def delete_lora_training(self, tid: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM lora_trainings WHERE id=?", (tid,))
        return cur.rowcount > 0

    # ── 可复用模板库（per-workspace；风格/运镜/提示词，跨剧集复用）──────
    def add_template(self, kind: str, name: str, content: str) -> dict:
        tid = _uid()
        with self._lock, self._conn() as conn:
            conn.execute("INSERT INTO templates(id,kind,name,content,created_at) VALUES(?,?,?,?,?)",
                         (tid, kind, name, content, _now()))
        return self.get_template(tid)

    def get_template(self, tid: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()
        return dict(row) if row else None

    def list_templates(self, kind: str = "") -> list[dict]:
        with self._conn() as conn:
            if kind:
                rows = conn.execute("SELECT * FROM templates WHERE kind=? ORDER BY created_at DESC", (kind,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM templates ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_template(self, tid: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM templates WHERE id=?", (tid,))
        return cur.rowcount > 0

    # ── 分镜 ──────────────────────────────────────────────────────
    def add_scene(
        self,
        project_id: str,
        scene_number: int,
        narration: str = "",
        image_prompt: str = "",
        motion_prompt: str = "",
        title: str = "",
        subtitle: str = "",
        dialogue: str = "",
        character: str = "",
    ) -> dict:
        if not self.get_project(project_id):
            raise ValueError(f"项目不存在: {project_id}")
        sid = _uid()
        ts = _now()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO scenes(id,project_id,scene_number,title,narration,subtitle,
                   image_prompt,motion_prompt,dialogue,character,state,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, project_id, scene_number, title, narration, subtitle,
                 image_prompt, motion_prompt, dialogue, character, SceneState.DRAFT.value, ts, ts),
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
        new_state = SceneState(new_state)
        # 读取当前态 + 合法性校验 + 写入 放在同一把锁、同一连接里完成，
        # 否则"先 get_scene 校验、再开锁更新"之间会有 TOCTOU 窗口：
        # 并发(或批量出片)时校验通过后状态被别的线程改掉，仍按旧判断写入，可越过状态机。
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT state FROM scenes WHERE id=?", (scene_id,)).fetchone()
            if not row:
                raise ValueError(f"分镜不存在: {scene_id}")
            cur = SceneState(row["state"])
            if not force and new_state not in _ALLOWED_TRANSITIONS.get(cur, set()) and new_state != cur:
                raise TransitionError(f"非法状态流转: {cur.value} → {new_state.value}")
            conn.execute(
                "UPDATE scenes SET state=?, updated_at=? WHERE id=?",
                (new_state.value, _now(), scene_id),
            )
        logger.info("[PipelineStore] 分镜 %s 状态: %s → %s", scene_id, cur.value, new_state.value)
        return self.get_scene(scene_id)

    def update_scene_prompts(self, scene_id: str,
                             image_prompt: str | None = None,
                             motion_prompt: str | None = None,
                             narration: str | None = None,
                             subtitle: str | None = None,
                             title: str | None = None,
                             scene_number: int | None = None,
                             dialogue: str | None = None,
                             character: str | None = None) -> dict:
        """更新分镜的提示词/旁白/字幕/标题/镜号/多角色对话/主角（只改传入的非 None 字段）。
        字幕独立于旁白：旁白配音、字幕上屏；dialogue=「说话人：台词」逐行，合成时按角色音色逐句配音；
        character=本镜主角名（PuLID 锁脸/音色按它查角色）。"""
        sets, params = [], []
        for col, val in (("image_prompt", image_prompt),
                         ("motion_prompt", motion_prompt),
                         ("narration", narration),
                         ("subtitle", subtitle),
                         ("dialogue", dialogue),
                         ("character", character),
                         ("title", title)):
            if val is not None:
                sets.append(f"{col}=?")
                params.append(val)
        if scene_number is not None:
            sets.append("scene_number=?")
            params.append(int(scene_number))
        if sets:
            sets.append("updated_at=?")
            params.append(_now())   # 统一走 _now()(UTC+Z)，与全表其它 updated_at 一致
            params.append(scene_id)
            with self._lock, self._conn() as conn:
                conn.execute(f"UPDATE scenes SET {', '.join(sets)} WHERE id=?", params)
        return self.get_scene(scene_id)

    def delete_scene(self, scene_id: str) -> bool:
        """删除分镜及其候选图（assets 外键 CASCADE）。返回是否删到。"""
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM scenes WHERE id=?", (scene_id,))
        logger.info("[PipelineStore] 删除分镜 %s（删到 %d 行）", scene_id, cur.rowcount)
        return cur.rowcount > 0

    def set_scene_lipsync(self, scene_id: str, on: bool) -> dict:
        """设置某镜是否「对口型」(走 Wan2.2-S2V 语音驱动出片)。"""
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE scenes SET lipsync=?, updated_at=? WHERE id=?",
                         (1 if on else 0, _now(), scene_id))
        return self.get_scene(scene_id)

    def set_scene_video_mode(self, scene_id: str, mode: str) -> dict:
        """设置某镜出片模式：'i2v'(图生，默认) / 't2v'(文生视频，不出图不选图)。"""
        mode = mode if mode in ("i2v", "t2v") else "i2v"
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE scenes SET video_mode=?, updated_at=? WHERE id=?",
                         (mode, _now(), scene_id))
        return self.get_scene(scene_id)

    def delete_asset(self, asset_id: str) -> Optional[str]:
        """删除一张候选图（DB 记录），返回它的 storage_path（供调用方删本地文件）。

        若删的是已选中的图，自动清掉分镜的 selected_asset_id 并回退到「待选图」。
        """
        asset = self.get_asset(asset_id)
        if not asset:
            return None
        scene_id = asset["scene_id"]
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
            scene = conn.execute("SELECT selected_asset_id FROM scenes WHERE id=?", (scene_id,)).fetchone()
            if scene and scene["selected_asset_id"] == asset_id:
                conn.execute("UPDATE scenes SET selected_asset_id=NULL WHERE id=?", (scene_id,))
        # 若分镜还有别的候选 → 回到待选图；否则回到草稿
        remaining = self.list_assets(scene_id, "IMAGE")
        self.set_scene_state(
            scene_id,
            SceneState.PENDING_HUMAN_SELECTION if remaining else SceneState.DRAFT,
            force=True,
        )
        return asset["storage_path"]

    def clear_scene_video(self, scene_id: str) -> dict:
        """删除分镜成片：清空 video_path，状态回到「已选·待出片」（图还在，可重出）。"""
        scene = self.get_scene(scene_id)
        if not scene:
            return {}
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE scenes SET video_path=NULL WHERE id=?", (scene_id,))
        target = SceneState.PENDING_VIDEO_GEN if scene.get("selected_asset_id") \
            else SceneState.PENDING_HUMAN_SELECTION
        self.set_scene_state(scene_id, target, force=True)
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
        from mirage.app.pipeline.runtime import state_db
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
