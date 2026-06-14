# -*- coding: utf-8 -*-
"""10 秒连贯短剧《深夜便利店》——建在用户工作目录 F:\\小说\\小说，出现在剧集工作台。
5 镜单段 ≈ 10 秒。同一人物 + 统一冷暖对比风格(项目级) + 连续旁白 + crossfade ⇒ 连贯。
运行：python scripts/short_demo.py
"""
from __future__ import annotations
import importlib, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mirage.app.pipeline import runtime
WS = r"F:\小说\小说"                                   # 用户真实工作目录 → 进剧集工作台
runtime.set_workspace(WS)
pt = importlib.import_module("mirage.app.pipeline.pipeline_tools")
from mirage.app.pipeline.store import get_store

store = get_store()
CHAR = "穿米色风衣的年轻男人，短发，干净侧脸"           # 人物一致
SEGMENTS = 1                                            # 单段 ≈ 2s，5 镜 ≈ 10s

SCENES = [
    dict(n=1, t="深夜街道", img="深夜城市空旷街道，霓虹路灯，地面湿漉漉的反光，细雨，冷蓝色调",
         mo="缓慢推近空荡的街道", nar="城市睡了，灯还醒着。"),
    dict(n=2, t="独行背影", img=f"{CHAR}，独自走在湿漉漉的夜街上，背影，霓虹反光，冷调",
         mo="跟拍他的背影缓缓前行", nar="他习惯了一个人，走完最后一段路。"),
    dict(n=3, t="便利店灯", img="雨夜街角一家便利店，暖黄色灯光招牌，玻璃橱窗，与冷色街道形成对比",
         mo="镜头从冷色街道缓缓摇到暖光招牌", nar="拐角那家便利店，总亮着灯。"),
    dict(n=4, t="推门进店", img=f"{CHAR}，推开便利店玻璃门，暖黄灯光打在脸上，神情放松",
         mo="镜头随门推开，暖光铺满画面", nar="推开门的一瞬间，世界忽然暖了。"),
    dict(n=5, t="靠窗微笑", img=f"{CHAR}，端着一杯热咖啡靠窗坐下，望向窗外，淡淡微笑，暖光",
         mo="缓慢推近他的侧脸微笑", nar="一杯热的，就够了。"),
]


def _id(msg: str) -> str:
    return msg.split("[", 1)[1].split("]", 1)[0]


def main() -> int:
    t0 = time.time()
    pid = _id(pt.create_video_project.func(title="深夜便利店·10秒Demo", novel_text="10秒连贯短剧"))
    store.update_project_style(
        pid, style_prompt="电影感，写实摄影，夜景，冷暖对比，霓虹，浅景深，胶片质感",
        flux_lora="none", default_size="768x1024")
    print(f"=== 项目 {pid} @ {WS} ===", flush=True)

    sids = [_id(pt.add_scene.func(project_id=pid, scene_number=s["n"], title=s["t"],
                                  narration=s["nar"], image_prompt=s["img"], motion_prompt=s["mo"]))
            for s in SCENES]

    for sid, s in zip(sids, SCENES):
        print(f"[{time.time()-t0:5.0f}s] 镜{s['n']} 出图…", flush=True)
        pt.generate_candidates.func(scene_id=sid, n=1, steps=22)
        imgs = store.list_assets(sid, "IMAGE")
        if not imgs:
            print(f"  !! 镜{s['n']} 没出到图，跳过", flush=True); continue
        store.select_asset(sid, imgs[0]["id"])
        print(f"[{time.time()-t0:5.0f}s] 镜{s['n']} 出片…", flush=True)
        pt.do_render_scene_video(sid, params={"segments": SEGMENTS})

    print(f"[{time.time()-t0:5.0f}s] 合成整集(crossfade+旁白+字幕)…", flush=True)
    res = pt.assemble_episode.func(project_id=pid)
    print("=== DONE ===", flush=True)
    print(res, flush=True)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
