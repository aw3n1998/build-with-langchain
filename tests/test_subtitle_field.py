# -*- coding: utf-8 -*-
"""
字幕独立于旁白 单测：
  1) 新库：add_scene/update 能分别存取 narration(配音) 与 subtitle(上屏)；留空字幕=空串(assembler 层回退旁白)；
  2) 老库迁移：对没有 subtitle 列的旧 scenes 表，PipelineStore 初始化时自动补列，且旧数据保留。

运行：python tests/test_subtitle_field.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from agent_lab.app.pipeline.store import PipelineStore

    tmp = tempfile.mkdtemp(prefix="subtitle_test_")

    # 1) 全新库：字幕与旁白各自独立
    st = PipelineStore(os.path.join(tmp, "new.db"))
    proj = st.create_project("t")
    sc = st.add_scene(proj["id"], 1, narration="旁白原文", subtitle="王帅全球之旅", title="x")
    assert sc["subtitle"] == "王帅全球之旅" and sc["narration"] == "旁白原文", sc
    sc2 = st.update_scene_prompts(sc["id"], subtitle="改后的字幕")
    assert sc2["subtitle"] == "改后的字幕" and sc2["narration"] == "旁白原文", "改字幕不应动旁白"
    sc3 = st.add_scene(proj["id"], 2, narration="只有旁白")
    assert sc3["subtitle"] == "", "不给字幕应为空串（assembler 层回退旁白）"
    print("[subtitle] 新库 add/update 字幕≠旁白 OK")

    # 2) 老库迁移：建一个没有 subtitle 列的旧 scenes 表
    db2 = os.path.join(tmp, "old.db")
    conn = sqlite3.connect(db2)
    conn.executescript("""
      CREATE TABLE projects(id TEXT PRIMARY KEY, title TEXT, novel_text TEXT,
        status TEXT, created_at TEXT);
      CREATE TABLE scenes(id TEXT PRIMARY KEY, project_id TEXT, scene_number INTEGER,
        title TEXT DEFAULT '', narration TEXT NOT NULL DEFAULT '',
        image_prompt TEXT NOT NULL DEFAULT '', motion_prompt TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'DRAFT', selected_asset_id TEXT, video_path TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    """)
    conn.execute("INSERT INTO projects VALUES('p1','old','','IN_PROGRESS','t')")
    conn.execute("INSERT INTO scenes(id,project_id,scene_number,narration,created_at,updated_at)"
                 " VALUES('s1','p1',1,'老旁白','t','t')")
    conn.commit(); conn.close()

    before = {r[1] for r in sqlite3.connect(db2).execute("PRAGMA table_info(scenes)")}
    assert "subtitle" not in before, "前置：旧表本不应有 subtitle 列"

    st2 = PipelineStore(db2)   # 初始化触发迁移
    after = {r[1] for r in sqlite3.connect(db2).execute("PRAGMA table_info(scenes)")}
    assert "subtitle" in after, "迁移未补 subtitle 列"
    old_scene = st2.get_scene("s1")
    assert old_scene["narration"] == "老旁白" and old_scene["subtitle"] == "", \
        f"老数据应保留、新列默认空: {old_scene}"
    st2.update_scene_prompts("s1", subtitle="补的字幕")
    assert st2.get_scene("s1")["subtitle"] == "补的字幕", "老库迁移后应能写字幕"
    print("[subtitle] 老库迁移 + 旧数据保留 + 可写字幕 OK")

    print("\n=== 字幕独立于旁白（含老库迁移） 单测通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
