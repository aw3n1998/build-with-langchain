# -*- coding: utf-8 -*-
"""连贯性 Demo：一条简单剧情《清晨咖啡馆》端到端跑成片。
同一人物 + 统一暖色风格(项目级) + 连续旁白 + 镜间 crossfade ⇒ 连贯。
直接调真实流水线函数(出图 FLUX / 出片 Wan / 新合成器)，不经后端/前端。
运行：python scripts/coffee_demo.py
"""
from __future__ import annotations
import importlib, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_lab.app.pipeline import runtime
WS = r"F:\小说\coffee_demo"
runtime.set_workspace(WS)
pt = importlib.import_module("agent_lab.app.pipeline.pipeline_tools")
from agent_lab.app.pipeline.store import get_store

store = get_store()
CHAR = "二十岁年轻女子，长直黑发，米色针织毛衣"          # 人物一致：每个人物镜都用同一段描述
SEGMENTS = 2                                            # 每镜尾帧接续 2 段 ≈ 加长到约 4 秒

SCENES = [
    dict(n=1, t="片头·空镜", img="清晨阳光洒进温馨咖啡馆，窗边空座位，木质桌面，暖光",
         mo="缓慢推近窗边座位", nar="清晨第一缕阳光，落在熟悉的窗边。"),
    dict(n=2, t="她在窗边", img=f"{CHAR}，坐在窗边，双手捧着咖啡杯，望向窗外，温柔微笑",
         mo="镜头缓缓推近她的侧脸", nar="她总爱这个位置，看着街角慢慢醒来。"),
    dict(n=3, t="咖啡特写", img="一杯冒着热气的拿铁咖啡特写，奶泡拉花，暖光，木质桌面，浅景深",
         mo="热气缓缓上升，镜头轻微推近", nar="一杯热咖啡，足够温暖整个早晨。"),
    dict(n=4, t="翻开书", img=f"{CHAR}，低头翻开一本书，侧脸，柔和的窗光",
         mo="镜头沿桌面缓缓平移到她的手", nar="翻开一页书，时间慢了下来。"),
    dict(n=5, t="窗外落叶", img="咖啡馆窗外，几片金黄树叶在暖阳里缓缓飘落，逆光，柔焦",
         mo="跟随飘落的叶子缓缓下移", nar="窗外的叶子，落得不慌不忙。"),
    dict(n=6, t="回眸微笑", img=f"{CHAR}，抬起头望向镜头，温柔地微笑，暖光，浅景深",
         mo="缓慢推近她的笑脸", nar="这样的清晨，刚刚好。"),
]


def _id(msg: str) -> str:
    return msg.split("[", 1)[1].split("]", 1)[0]


def main() -> int:
    t0 = time.time()
    pid = _id(pt.create_video_project.func(title="清晨咖啡馆·连贯Demo", novel_text="连贯性 demo"))
    # 剧集级统一风格（出图自动套用到每镜）
    store.update_project_style(
        pid, style_prompt="温暖晨光，咖啡馆，电影感，写实摄影，柔光，浅景深，暖色调，胶片质感",
        flux_lora="none", default_size="768x1024")
    print(f"=== 项目 {pid} @ {WS} ===", flush=True)

    sids = []
    for s in SCENES:
        sids.append(_id(pt.add_scene.func(
            project_id=pid, scene_number=s["n"], title=s["t"],
            narration=s["nar"], image_prompt=s["img"], motion_prompt=s["mo"])))

    for sid, s in zip(sids, SCENES):
        print(f"[{time.time()-t0:5.0f}s] 镜{s['n']} 出图…", flush=True)
        pt.generate_candidates.func(scene_id=sid, n=1, steps=22)   # FLUX(项目风格自动注入+中文翻英)
        imgs = store.list_assets(sid, "IMAGE")
        if not imgs:
            print(f"  !! 镜{s['n']} 没出到图，跳过", flush=True); continue
        store.select_asset(sid, imgs[0]["id"])                      # 自动选第一张
        print(f"[{time.time()-t0:5.0f}s] 镜{s['n']} 出片(×{SEGMENTS}段)…", flush=True)
        pt.do_render_scene_video(sid, params={"segments": SEGMENTS})  # Wan 尾帧接续

    print(f"[{time.time()-t0:5.0f}s] 合成整集(crossfade+旁白+字幕)…", flush=True)
    res = pt.assemble_episode.func(project_id=pid)
    print("=== DONE ===", flush=True)
    print(res, flush=True)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
