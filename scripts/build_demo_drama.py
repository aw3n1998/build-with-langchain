# -*- coding: utf-8 -*-
"""一键把样板短剧《王牌扫地僧》第一集(16 分镜)建进 AgentLab(默认工作目录 repo/agent_workspace)。
建完打开制作面板就能从「出图」开始。运行：python scripts/build_demo_drama.py"""
from __future__ import annotations
import importlib, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_lab.app.pipeline import runtime
# 工作目录：命令行第1参数指定（要和前端「工作目录」一致）；缺省用仓库 agent_workspace
WS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_workspace")
runtime.set_workspace(WS)
pt = importlib.import_module("agent_lab.app.pipeline.pipeline_tools")
from agent_lab.app.pipeline.store import get_store

# 主角统一外貌(没 LoRA 时靠描述压一压漂移)：中年硬朗、短寸花白发、左眉旧疤
CM = "中年硬朗男人，短寸花白头发，左眉一道旧疤，深邃沉稳的眼神"

SCENES = [
    dict(n=1, lip=False, t="片头标题卡",
         img="暴雨夜，霓虹灯下一座贵族学校大门金属校徽特写，反光，冷色调，电影质感，写实",
         mo="缓慢推近校门，雨丝飘落，灯光摇曳",
         nar="他扫了三年地。没人知道，这把扫帚，扫平过三个国家的战场。",
         sub="王牌扫地僧"),
    dict(n=2, lip=True, t="泼咖啡羞辱",
         img=f"清晨校门口，穿保安制服的{CM}低头沉静扫地，西装革履的傲慢副校长居高临下泼咖啡，写实人像，浅景深",
         mo="镜头从扫帚摇到陈默平静的脸，再切到副校长轻蔑的表情",
         nar="就是你？把校门口扫干净点，别让我再看见垃圾——包括你。"),
    dict(n=3, lip=False, t="擦咖啡·军牌",
         img=f"{CM}低头擦去脸上的咖啡，手腕一枚磨损的旧军牌特写，眼神深处一闪锋芒，冷峻写实，强对比布光",
         mo="极缓慢推近到眼睛，背景虚化",
         nar="他没有抬头。有些刀，藏在鞘里太久，连自己都快忘了它有多快。"),
    dict(n=4, lip=True, t="女儿被嘲笑",
         img="明亮教室，一个朴素清秀的女高中生被几个名牌打扮的同学围着嘲笑，她攥紧书包带，写实",
         mo="镜头缓缓环绕，定格在女孩强忍的眼神",
         nar="连校服都买不起吧？你爸不就是给我们看大门的那个。"),
    dict(n=5, lip=False, t="女儿强忍",
         img="女高中生低头攥紧书包，眼眶泛红强忍泪水，窗光打在侧脸，写实，情绪感",
         mo="缓慢推近侧脸",
         nar="她没有哭。爸爸说过，陈家的脊梁，不能弯。"),
    dict(n=6, lip=True, t="加密电话",
         img=f"昏暗值班室，{CM}握着一部老式加密手机贴在耳边，神色骤然凝肃，窗外光线压抑，写实",
         mo="镜头从手机推到陈默骤变的脸，轻微手持晃动制造紧张",
         nar="……明白。目标在这所学校。我，接手。"),
    dict(n=7, lip=False, t="旧照片·铺垫",
         img=f"深夜，{CM}独自坐在狭小宿舍，手中一张泛黄的战友合影，墙上挂着叠得方正的旧军装，暖黄孤灯，写实",
         mo="从照片缓缓拉远到陈默孤独的背影，灯光微微闪烁",
         nar="兄弟们，这一次的战场，是我女儿的学校。这一仗，我不能输。",
         sub="风暴，将至"),
    dict(n=8, lip=False, t="次日·校车",
         img="清晨阳光，一辆黄色校车停在校门口，孩子们背着书包陆续上车，温暖日常",
         mo="平移跟随校车缓缓驶出校门",
         nar="没有人知道，这辆校车，今天不会准时到达。"),
    dict(n=9, lip=True, t="歹徒劫车",
         img="荒僻公路，蒙面持枪的歹徒头目拦停校车猛拍车门，紧张惊悚，冷色调",
         mo="急推歹徒持枪的手，再切到惊恐的车窗，手持晃动",
         nar="都给我老实点！谁敢动，我就让这车上的小崽子，一个都回不了家！"),
    dict(n=10, lip=False, t="车内尖叫",
         img="校车内，孩子们惊恐尖叫蜷缩，女高中生护住身边的低年级孩子，昏暗压迫感",
         mo="快速摇过一张张惊恐的脸",
         nar="女儿没有尖叫。她把最小的孩子，护在身后——像她父亲那样。"),
    dict(n=11, lip=False, t="陈默狂奔",
         img=f"校门口，{CM}骤然扔下扫帚，眼神锐利如刀，转身狂奔，衣摆翻飞，动感",
         mo="跟拍狂奔，镜头剧烈晃动，速度感",
         nar="三年没出手了。但有些本能，早就刻进了骨头里。"),
    dict(n=12, lip=True, t="拦车对峙",
         img=f"公路上，{CM}徒手挡在校车前，与持枪的歹徒头目近距离对峙，肃杀对视",
         mo="正反打，缓慢逼近的张力",
         nar="放了孩子。我给你三秒——这是你活命唯一的机会。"),
    dict(n=13, lip=False, t="三分钟制服",
         img=f"高速动作场面，{CM}闪电近身格斗，接连放倒多名持枪歹徒，凌厉残影",
         mo="快切加冲击运镜，凌厉",
         nar="第一秒，缴枪。第二秒，锁喉。第三秒——结束。"),
    dict(n=14, lip=False, t="女儿震惊",
         img=f"多名歹徒被反绑跪地，孩子们涌出校车，女高中生怔怔望着满身气场的父亲{CM}，逆光",
         mo="缓推到女儿震惊的脸",
         nar="那个她以为只会扫地的父亲，此刻，像一座山。"),
    dict(n=15, lip=True, t="军车封街敬礼",
         img=f"一排黑色军车封街呼啸而至，威严的老将军推门下车，对穿保安制服的{CM}笔直敬礼，震撼大场面",
         mo="大全景拉到将军敬礼，定格",
         nar="陈队长，任务交接完毕。一路辛苦——欢迎归队。"),
    dict(n=16, lip=False, t="钩子·众人哗然",
         img=f"校门口，副校长腿一软跌坐在地，师生哗然失语，{CM}缓缓回头深邃一瞥，电影感",
         mo="缓慢推近陈默回头的眼神，周围虚化",
         nar="他是谁？这个问题，明天，会传遍整座城市。",
         sub="他，是谁"),
]


def main() -> int:
    msg = pt.create_video_project.func(title="王牌扫地僧·第一集", novel_text="隐藏身份/战神归来 短剧样板")
    pid = msg.split("[", 1)[1].split("]", 1)[0]
    store = get_store()
    n_lip = 0
    for s in SCENES:
        m = pt.add_scene.func(project_id=pid, scene_number=s["n"], title=s["t"],
                              narration=s["nar"], image_prompt=s["img"],
                              motion_prompt=s["mo"], subtitle=s.get("sub", ""))
        sid = m.split("[", 1)[1].split("]", 1)[0]
        if s["lip"]:
            store.set_scene_lipsync(sid, True); n_lip += 1
    print(f"=== 已建项目 {pid} ：{len(SCENES)} 分镜（其中 {n_lip} 个对口型镜头）===")
    print(f"工作目录: {WS}")
    print(f"项目ID: {pid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
