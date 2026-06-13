"""
小说 → 自动拆分镜（导演式排镜）。

把一段小说/剧情文本交给 LLM 当"导演"，一次拆成 N 个分镜，每镜给齐：
标题 / 出图提示词 / 运镜 / 旁白(或台词) / 字幕 / 是否对口型 / 出场角色。
照 prompt_gen 的现成模式调 ai_service._llm + 健壮 JSON 容错，失败有保底。

把项目踩过的坑写进 system，让导演自动遵守：
- 人物写【明确年龄数字】（FLUX 把"高中生"画成小孩）；
- 全剧统一风格词；台词控制在能一口气说完（对口型 S2V 单段 ~7s 上限）；
- 景别有节奏：空镜/全景交代环境 → 中景 → 特写给情绪；
- 角色一致：同一角色每镜复用同一段外貌描述。
"""

from __future__ import annotations

import json
import re

from mirage.app.core.logger import get_logger

logger = get_logger("pipeline.storyboard")

_SYSTEM = (
    "你是短剧导演 + 分镜师。把用户给的小说/剧情文本拆成一集竖屏短剧的连续分镜。\n"
    "硬性要求：\n"
    "1) 输出恰好 N 个分镜，按时间顺序，每镜是一个 JSON 对象，整体是一个长度严格为 N 的 JSON 数组。\n"
    "2) 每个分镜对象字段（全部必填，值用中文，除 image_prompt 可中文也可英文）：\n"
    "   - title: 6字内的镜头小标题\n"
    "   - image_prompt: 出图画面描述。**人物务必写明确年龄数字**（如'17岁'、'40岁中年'，别只写'高中生/老人'，否则模型会画错年龄）；\n"
    "     同一角色每镜复用同一段外貌描述（发型/脸型/穿着/特征），保证跨镜是同一个人；结尾统一带风格词。\n"
    "   - motion_prompt: 一句运镜/动态（推/拉/摇/移/环绕 + 可连续的细微动态），简短。\n"
    "   - narration: 这镜的声音。若 lipsync=true 这里写【人物要说的台词】；若 false 写画外音旁白。\n"
    "     台词控制在能一口气说完（≤约25字/7秒），太长就拆到下一镜。\n"
    "   - subtitle: 屏幕大字（片头标题/钩子/留空）。普通解说镜可留空（会自动用旁白）。\n"
    "   - lipsync: 布尔。这镜有人物开口说台词=true（走对口型）；画外音/空镜/物件特写=false。\n"
    "   - character: 这镜的主要出场角色名（用用户给的角色名；无具体人物如空镜/物件则填空串）。\n"
    "3) 景别要有节奏：开场用空镜/全景交代环境，中间中景推进，情绪点用特写；别每镜都大特写或都全景。\n"
    "4) 短剧命脉：开头要有钩子，结尾留悬念。\n"
    "只输出这个 JSON 数组，不要任何解释、前后缀、代码块标记。"
)

_FIELDS = ("title", "image_prompt", "motion_prompt", "narration", "subtitle", "lipsync", "character")


def _coerce_scenes(text: str, n: int, style: str = "") -> list[dict]:
    """把 LLM 输出解析成长度严格为 N 的分镜 dict 列表（健壮容错）。"""
    scenes: list[dict] = []
    m = re.search(r"\[.*\]", text or "", re.S)        # 取第一个 JSON 数组（含被代码块包裹的情况）
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                for i, it in enumerate(data):
                    if not isinstance(it, dict):
                        continue
                    img = str(it.get("image_prompt") or "").strip()
                    if style and img and style.lower() not in img.lower():
                        img = f"{img}，{style}".strip("，")
                    scenes.append({
                        "title": str(it.get("title") or f"镜{i + 1}").strip()[:20],
                        "image_prompt": img,
                        "motion_prompt": str(it.get("motion_prompt") or "缓慢推近，自然光影").strip(),
                        "narration": str(it.get("narration") or "").strip(),
                        "subtitle": str(it.get("subtitle") or "").strip(),
                        "lipsync": bool(it.get("lipsync")),
                        "character": str(it.get("character") or "").strip(),
                    })
        except Exception as e:  # noqa: BLE001
            logger.warning("[storyboard] JSON 解析失败，将走保底: %s", e)
    # 对齐长度 N：超出截断；不足补占位（让用户在面板补全，不静默丢内容）
    scenes = [s for s in scenes if s.get("image_prompt")]
    if len(scenes) > n:
        scenes = scenes[:n]
    while len(scenes) < n:
        k = len(scenes) + 1
        scenes.append({"title": f"镜{k}", "image_prompt": (style or "电影感，写实").strip("，"),
                       "motion_prompt": "缓慢推近，自然光影", "narration": "",
                       "subtitle": "", "lipsync": False, "character": ""})
    return scenes


async def breakdown_storyboard(novel_text: str, n: int, *, style: str = "",
                               characters: list[dict] | None = None) -> list[dict]:
    """把小说文本拆成 N 个分镜。

    Args:
        novel_text: 小说/剧情文本。
        n: 想要的分镜数。
        style: 本集统一风格词（拼到每镜 image_prompt 末尾，保证全集一个调性）。
        characters: 角色圣经 [{"name","appearance","voice"}...]；导演据此写人物外貌、判断 character 字段。
    Returns:
        长度严格为 n 的分镜 dict 列表，字段见 _FIELDS。
    """
    n = max(1, int(n or 1))
    from mirage.app.services.ai_service import ai_service
    from langchain_core.messages import SystemMessage, HumanMessage

    char_block = ""
    if characters:
        lines = []
        for c in characters:
            nm = str(c.get("name") or "").strip()
            ap = str(c.get("appearance") or "").strip()
            if nm:
                lines.append(f"- {nm}：{ap or '(外貌自拟，但每镜保持一致)'}")
        if lines:
            char_block = "本剧角色（image_prompt 写到该角色时用其外貌、character 字段填其名）：\n" + "\n".join(lines) + "\n"

    human = (
        f"{char_block}"
        f"统一风格词（每镜 image_prompt 结尾都带上）：{style or '电影感，写实，浅景深'}\n"
        f"需要分镜数 N：{n}\n"
        f"小说/剧情文本：\n{(novel_text or '').strip()[:6000]}"
    )
    try:
        resp = await ai_service._llm.ainvoke([
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=human),
        ])
        out = _coerce_scenes(getattr(resp, "content", "") or "", n, style)
        logger.info("[storyboard] 拆出 %d 个分镜", len(out))
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[storyboard] LLM 拆分镜失败，返回 N 个空白镜待手填: %s", e)
        return _coerce_scenes("", n, style)
