# -*- coding: utf-8 -*-
"""剧集/分镜自助管理 + 每集风格 的 store 单测（临时 DB，无 GPU）。"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_lab.app.pipeline.store import PipelineStore


def _store():
    return PipelineStore(os.path.join(tempfile.mkdtemp(), "t.db"))


def test_project_style_roundtrip():
    s = _store(); pid = s.create_project("剧")["id"]
    s.update_project_style(pid, style_prompt="写实,电影感", flux_lora="none", default_size="768x1024")
    st = s.get_project_style(pid)
    assert st["style_prompt"] == "写实,电影感"
    assert st["flux_lora"] == "none" and st["default_size"] == "768x1024"
    # 只改一个字段，其余不动
    s.update_project_style(pid, trigger_word="hero")
    st2 = s.get_project_style(pid)
    assert st2["trigger_word"] == "hero" and st2["style_prompt"] == "写实,电影感"


def test_project_rename_delete():
    s = _store(); pid = s.create_project("旧名")["id"]
    s.rename_project(pid, "新名"); assert s.get_project(pid)["title"] == "新名"
    s.add_scene(pid, 1, title="镜")
    assert s.delete_project(pid) is True
    assert s.get_project(pid) is None and s.list_scenes(pid) == []   # 级联删分镜


def test_scene_add_delete_edit_title_number():
    s = _store(); pid = s.create_project("剧")["id"]
    sid = s.add_scene(pid, 1, title="A")["id"]
    s.update_scene_prompts(sid, title="B", scene_number=9, image_prompt="p")
    g = s.get_scene(sid)
    assert g["title"] == "B" and g["scene_number"] == 9 and g["image_prompt"] == "p"
    assert s.delete_scene(sid) is True and s.get_scene(sid) is None


def test_old_db_migrates_project_style_cols():
    """旧库（无风格列）打开后应被 _migrate 补齐，get_project_style 不报错。"""
    import sqlite3
    d = tempfile.mkdtemp(); db = os.path.join(d, "old.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE projects(id TEXT PRIMARY KEY, title TEXT NOT NULL, "
                 "novel_text TEXT DEFAULT '', status TEXT DEFAULT 'IN_PROGRESS', created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO projects(id,title,created_at) VALUES('p1','老剧','2026-01-01')")
    conn.commit(); conn.close()
    s = PipelineStore(db)   # 触发 _migrate
    st = s.get_project_style("p1")
    assert st["style_prompt"] == "" and st["flux_lora"] == ""   # 补的列默认空


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  [ok] {name}")
    print("SCENE_EPISODE_MGMT_OK")
