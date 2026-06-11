"""
小说转视频流水线 —— 独立离线自检脚本（无需 Docker / GPU / LLM）。

跑通状态机全链路：建项目 → 加分镜 → 登记候选图 → 选图(HITL) → （模拟）出片。
GPU 段若未在 .env 配置，会优雅跳过，仅验证状态流转与工具封装。

用法：
    python pipeline_demo.py
"""

from __future__ import annotations

import os
import tempfile

# 用临时 DB，避免污染工作区
os.environ.setdefault("NP2V_DB_PATH", os.path.join(tempfile.gettempdir(), "np2v_demo.db"))

from agent_lab.app.pipeline.store import SceneState, get_store
from agent_lab.app.pipeline.pipeline_tools import pipeline_tools  # 校验工具无语法/依赖问题


def main() -> None:
    db = os.environ["NP2V_DB_PATH"]
    if os.path.exists(db):
        os.remove(db)
    store = get_store(db)

    print("=== 1) 建项目 ===")
    proj = store.create_project("第一章 One Coat Between Us", novel_text="（原文略）")
    pid = proj["id"]
    print("project:", pid)

    print("\n=== 2) 加分镜 ===")
    s1 = store.add_scene(pid, 1, narration="少年低头执笔书写",
                         image_prompt="ch4r_cael writing by candlelight",
                         motion_prompt="烛光摇曳，火苗轻微跳动，缓慢推镜，电影暖调",
                         title="烛光书写")
    sid = s1["id"]
    print("scene:", sid, "state =", s1["state"])
    assert s1["state"] == SceneState.DRAFT.value

    print("\n=== 3) 登记候选图（已有 scene_10.png） ===")
    a1 = store.add_asset(sid, "/root/autodl-tmp/cael_scenes/scene_10.png", "IMAGE")
    a2 = store.add_asset(sid, "/root/autodl-tmp/cael_scenes/scene_7.png", "IMAGE")
    store.set_scene_state(sid, SceneState.PENDING_HUMAN_SELECTION, force=True)
    print("候选:", [a["id"] for a in store.list_assets(sid)])
    print("state =", store.get_scene(sid)["state"])

    print("\n=== 4) HITL 选图 ===")
    scene = store.select_asset(sid, a1["id"])
    print("选定:", a1["id"], "→ state =", scene["state"])
    assert scene["state"] == SceneState.PENDING_VIDEO_GEN.value

    print("\n=== 5) 模拟出片（不调 GPU），标记 COMPLETED ===")
    store.set_scene_video(sid, "/root/autodl-tmp/pipeline_out/scene_10.mp4")
    store.set_scene_state(sid, SceneState.COMPLETED)
    final = store.get_scene(sid)
    print("video:", final["video_path"], "state =", final["state"])
    assert final["state"] == SceneState.COMPLETED.value

    print("\n=== 6) 项目汇总 ===")
    st = store.status(pid)
    for s in st["scenes"]:
        print(f"  #{s['scene_number']} {s['title']} {s['state']} 候选={s['num_candidates']}")

    print(f"\n=== 7) 工具清单（{len(pipeline_tools)} 个，已可注入 SkillRegistry） ===")
    for t in pipeline_tools:
        print("  -", t.name)

    print("\n✅ 状态机全链路自检通过。GPU 段需在 .env 配 GPU_SSH_* 后由 render_scene_video 触发。")


if __name__ == "__main__":
    main()
