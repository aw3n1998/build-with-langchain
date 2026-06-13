#!/usr/bin/env python3
"""
种子脚本：把《ASHBORN》EP1 灌进某工作目录的 pipeline 库
（建项目 + 本集风格 + 4 个角色圣经[英文音色] + 8 个分镜，lipsync 在 SHOT 2/5/8）。

用法（在仓库根运行）:
    python scripts/seed_ashborn_ep1.py /content/cael_video_out      # Colab
    python scripts/seed_ashborn_ep1.py "F:/小说/小说"               # 本地

跑完打印 project_id；之后到工作台/对话里：①一键全部出图 → 选图 → ②一键出片并合成。
台词为英文(发欧美平台)；出图提示词为英文(直接喂 FLUX，内嵌人物一致性锚点)。
"""
import os
import sys

# 让脚本能 import mirage.*（仓库根加进 sys.path）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mirage.app.pipeline import runtime          # noqa: E402
from mirage.app.pipeline.store import PipelineStore  # noqa: E402

WORKSPACE = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

# ── 本集统一风格（出图自动拼到每镜提示词后）──────────────────
STYLE = ("cinematic dark fantasy, grand obsidian black-marble magic hall, "
         "hundreds of richly dressed nobles, warm gold candlelight, "
         "black-gold flame as recurring visual motif, dramatic rim lighting, "
         "film grain, photoreal, vertical 9:16 composition, subject centered upper third")
NEGATIVE = ("lowres, blurry, deformed, extra fingers, mutated hands, watermark, text, "
            "modern clothing, cartoon, anime, low detail")

# ── 角色圣经（外貌锚点用于跨镜一致；音色用英文嗓念英文台词）──
CHARACTERS = [
    ("Caelan", "teenage boy, ash-smeared face, messy black hair, defiant green eyes, "
                "ragged grey servant tunic; later black-gold flame burning in his eyes", "en-US-GuyNeural"),
    ("Roland", "arrogant young noble, slicked blonde hair, white-gold ornate robe, "
                "conjures white flame in his palm", "en-GB-RyanNeural"),
    ("Seraphina", "haughty noblewoman, silver hair, crimson-and-gold gown, emerald jewelry", "en-GB-SoniaNeural"),
    ("The Ember", "(no on-screen face) ancient sentient voice inside Caelan, deep echoing", "en-US-ChristopherNeural"),
]

# ── 8 个分镜 ───────────────────────────────────────────────
# 每条: (scene_number, title, image_prompt[英], motion_prompt, narration[英台词], subtitle, lipsync, voice)
SCENES = [
    (1, "Hook — kneeling in ash",
     "ash-smeared teenage boy with messy black hair and defiant green eyes in a ragged grey servant tunic, "
     "forced to kneel on a white jade floor by two armored guards, hundreds of nobles watching, crash-zoom on his dirt-smeared face as he lifts his eyes",
     "crash zoom into the boy's ash-smeared face, he raises defiant eyes",
     "You? Marry into House Vale? A boy who cleans ashes?",
     "THEY CALLED HIM NOTHING.", False, "en-GB-SoniaNeural"),

    (2, "The broken betrothal",
     "haughty noblewoman with silver hair, crimson-and-gold gown and emerald jewelry standing on a raised dais, "
     "sneering as she tosses a betrothal ring down, low-angle shot looking up at her, grand obsidian hall",
     "close-up of the ring bouncing on jade floor, then low-angle up at her",
     "The betrothal is void. I won't be chained to a servant with no Ember in his blood.",
     "The betrothal is void.", True, "en-GB-SoniaNeural"),

    (3, "The young master arrives",
     "arrogant young noble with slicked blonde hair in a white-gold ornate robe striding forward, "
     "a ball of white flame in his palm lighting half his face, side-lit, slow motion, grand obsidian hall",
     "slow dolly-in, white-flame side light across his face",
     "Don't cry, ash-boy. Let me give you a parting gift.",
     "Let me give you a parting gift.", False, "en-GB-RyanNeural"),

    (4, "Branded, thrown into the ash",
     "the ash-smeared boy struck on the chest by a brand of white flame, screaming, knocked into a heap of cold "
     "furnace ash in the corner of the hall, ash dust bursting upward, nobles laughing, dynamic motion blur",
     "fast whip-pan plus ash particles, overhead POV falling into the ash heap",
     "", "But nothing... was about to wake up.", False, ""),

    (5, "The Ember awakens",
     "extreme close-up of the boy's eye half-buried in ash, a black-gold flame igniting inside his pupil, "
     "the white slave-brand on his chest being devoured from within by black flame",
     "extreme close-up on the pupil, black-gold fire ignites within",
     "...Who's there? In my head?",
     "At last... after ten thousand years... a host who refuses to die.", True, "en-US-GuyNeural"),

    (6, "First leak of power",
     "the boy pushing up from the ash, his palm pressed to the white jade floor leaving a scorched black handprint, "
     "silent black flame creeping outward, nearby nobles recoiling in horror",
     "push-in from his hand to the scorch mark, slow-burning black flame",
     "They branded you a slave. Good. Let them watch a slave become a god.",
     "Let them watch a slave become a god.", False, "en-US-ChristopherNeural"),

    (7, "They see the forbidden fire",
     "the blonde noble's grin freezing as he stares at impossible black flame, the silver-haired noblewoman slowly "
     "turning with shrinking pupils, rapid intercut of three faces, grand obsidian hall",
     "rapid face cuts: shocked noble, suspicious noblewoman, cold-eyed boy",
     "That fire... that's impossible. That bloodline was burned out of the world!",
     "That bloodline was burned out of the world!", False, "en-GB-RyanNeural"),

    (8, "Episode-end hook",
     "the boy standing tall, ash sliding off his shoulders, black-gold flame dancing between his fingers, lifting "
     "his eyes to stare down the entire hall, heroic low-angle shot, black-flame key light, freeze frame",
     "heroic low-angle, black-flame key light, freeze on his cold stare",
     "You wanted a servant. I'll give you an emperor.",
     "EP 2 — The House will burn.", True, "en-US-GuyNeural"),
]


def main() -> None:
    runtime.set_workspace(WORKSPACE)
    store = PipelineStore(runtime.state_db())

    proj = store.create_project("ASHBORN · EP1 — They Called Him Nothing")
    pid = proj["id"]
    store.update_project_style(pid, style_prompt=STYLE, negative_prompt=NEGATIVE, default_size="768x1024")

    for name, appearance, voice in CHARACTERS:
        store.add_character(pid, name=name, appearance=appearance, voice=voice)

    for n, title, image_prompt, motion, narration, subtitle, lipsync, voice in SCENES:
        sc = store.add_scene(pid, scene_number=n, title=title, image_prompt=image_prompt,
                             motion_prompt=motion, narration=narration, subtitle=subtitle)
        if voice:
            store.set_scene_voice(sc["id"], voice)
        if lipsync:
            store.set_scene_lipsync(sc["id"], True)

    print("OK  workspace =", runtime.get_workspace())
    print("OK  project_id =", pid, "  title =", proj["title"])
    print("    角色:", len(CHARACTERS), " 分镜:", len(SCENES), " 对口型镜: 2/5/8")
    print("下一步：工作台选中该剧集 → 一键全部出图 → 选图 → 一键出片并合成。")


if __name__ == "__main__":
    main()
