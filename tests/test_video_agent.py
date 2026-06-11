# -*- coding: utf-8 -*-
"""
test_video_agent.py —— 端到端跑一次 video agent（真实 LLM + 真实 GPU）。

走的就是正式栈：ai_service.astream_chat → 关键词自动路由到 video 子 Agent →
LLM 自主调用 pipeline_tools（建项目/加分镜/FLUX 出图/选图/Wan2.2 出片）。

第一次有边界：只让它出 2 张候选图就停，验证 LLM→工具→GPU 链路。
"""
from __future__ import annotations

import asyncio
import os
import sys

# 中文输出不乱码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 状态库落到仓库内固定文件，便于事后核对
os.environ.setdefault("NP2V_DB_PATH", os.path.join(ROOT, "pipeline.db"))

from agent_lab.app.services.ai_service import ai_service  # noqa: E402

PROMPT = (
    "我要把一段小说做成短剧视频，先跑一个测试分镜。请按步骤：\n"
    "1) 建项目，名字叫『测试·烛光』；\n"
    "2) 加一个分镜：少年在烛光下低头执笔书写。"
    "image_prompt 用 'ch4r_cael writing by candlelight, cinematic, warm tone'，"
    "motion_prompt 用 '烛光摇曳，火苗轻微跳动，缓慢推镜，电影暖调'；\n"
    "3) 用 generate_candidates 出 2 张候选图（n=2）。\n"
    "出完候选图就停下来，用 list_candidates 把候选列出来等我选，"
    "这一步先不要调用 render_scene_video 生成视频。"
)


async def main():
    session_id = "test-video-agent"
    print("=" * 60)
    print("用户 >", PROMPT)
    print("=" * 60)
    print("AI > ", end="", flush=True)
    async for event in ai_service.astream_chat(session_id, PROMPT):
        t = event.get("type")
        if t == "chunk":
            print(event["content"], end="", flush=True)
        elif t == "interrupt":
            print(f"\n[HITL 暂停] {event.get('content')}")
    print("\n" + "=" * 60)

    # 收尾：直接查状态库确认 agent 到底做了什么
    from agent_lab.app.pipeline.store import get_store
    store = get_store(os.environ["NP2V_DB_PATH"])
    print("DB:", os.environ["NP2V_DB_PATH"])
    import sqlite3
    con = sqlite3.connect(os.environ["NP2V_DB_PATH"])
    for tbl in ("projects", "scenes", "assets"):
        try:
            rows = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl}: {rows} 行")
        except Exception as e:
            print(f"  {tbl}: 查询失败 {e}")
    con.close()


if __name__ == "__main__":
    asyncio.run(main())
