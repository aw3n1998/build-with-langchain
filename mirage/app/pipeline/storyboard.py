"""
小说 → 自动拆分镜（导演式排镜）。

把一段小说/剧情文本交给 LLM 当"导演"，一次拆成 N 个分镜，每镜给齐：
标题 / 出图提示词 / 运镜 / 旁白(或台词) / 字幕 / 是否对口型 / 出场角色。
照 prompt_gen 的现成模式调 ai_service._llm + 健壮 JSON 容错，失败有保底。

把项目踩过的坑写进 system，让导演自动遵守：
- 人物写【明确年龄数字】（FLUX 把"高中生"画成小孩）；
- 全剧统一风格词；台词控制在能一口气说完（对口型 S2V 单段 ~7s 上限）；
- 连贯优先：按叙事 beat 切镜（少而长），同场景连续镜复用同一段 environment 描述，防背景漂移；
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
    "2) 每个分镜对象字段（全部必填，值用中文，但 image_prompt、motion_prompt **必须用英文**）：\n"
    "   - title: 6字内的镜头小标题\n"
    "   - image_prompt: 出图画面描述，**必须用英文**（出图模型 FLUX 只懂英文；中文会被画成毫不相关的乱图——头号坑）。\n"
    "     **人物务必写明确年龄数字**（如 '17-year-old'、'40-year-old man'，别只写 teenager/old man，否则画错年龄）；\n"
    "     同一角色每镜复用同一段英文外貌描述（hair / face / clothing / distinctive features），保证跨镜是同一个人；结尾统一带英文风格词。\n"
    "   - motion_prompt: 图生视频运镜(喂 Wan2.2，**优先英文**——运镜术语英文更稳)。写**一段**(非一句)，按公式：\n"
    "     [主体的一个具体动作，先轻后重、单一方向；若是复杂动作只取它的【一个子步骤】并写出中间过程(slowly / gradually / continuous / smooth motion)，别只给最终结果] + [单一运镜术语] + [光影/氛围]。运镜术语**只选一个**英文：\n"
    "     push-in / pull-out / pan left / pan right / tilt up / tilt down / orbit / following shot / static shot，别堆两个矛盾运镜。\n"
    "     例：'slowly turns head toward camera, a faint smile forms, gentle push-in, soft warm rim light, shallow depth of field'。\n"
    "   - narration: 这镜的【单一】声音。若 lipsync=true 写【那一个人物要说的台词】；若 false 写画外音旁白。\n"
    "     ≤约25字/7秒能一口气说完，太长拆到下一镜。**两人及以上对话别写这里，用 dialogue。**\n"
    "   - dialogue: 多角色对话。【仅当这一镜里两个及以上角色你一句我一句对话】时填，否则给空数组 []。\n"
    "     格式：[{\"speaker\":\"角色名(必须用上面角色表里的原名)\",\"text\":\"台词(中文，每句≤约20字)\"}, ...]，按说话顺序。\n"
    "     填了 dialogue 的镜：lipsync 必须 false（画面给场景，各角色按各自音色配音，不做单脸对口型）、narration 留空。\n"
    "   - subtitle: 屏幕大字（片头标题/钩子/留空）。普通解说镜可留空（会自动用旁白/对话）。\n"
    "   - lipsync: 布尔。这镜【单个】人物**正脸近景**开口说话=true（对口型镜：image_prompt 必须含 'frontal face close-up, facing camera'，否则后期没法对口型）；\n"
    "     画外音/背影/侧脸/远景/空镜/物件特写/【多人对话(用dialogue)】一律 false（看不到嘴=纯配音画外音，镜头可任意景别）。\n"
    "   - character: 这镜的主要出场角色名（用用户给的角色名；无具体人物如空镜/物件则填空串）。\n"
    "3) 连贯优先：按【叙事 beat】切镜——一个动作单元 / 一句关键对话 = 一镜，别把同一段动作切成很多碎镜（镜越少、每镜越长，跨镜漂移越少、越连贯）。\n"
    "   **动作与台词分镜**：若一个 beat 既有明显动作又有一句反应台词（如摔倒后喊「好疼」），拆成两镜——先动作镜（lipsync=false、景别随意），紧跟一个正脸台词镜（lipsync=true、image_prompt 给正脸近景）；别把动作+台词塞一镜（否则配音/对口型对不上时机）。\n"
    "   **★复杂/多步动作必须拆成多个递进短镜（重要，否则会跳变/瞬移）**：脱衣/换装/穿戴、打斗格斗、起身→走动→坐下、翻越/爬/跳、复杂手部操作（开锁/解扣/倒水/点烟）等——单个约 5 秒文生镜根本演不出中间过程，模型会走捷径直接「跳变」（如衣服突然从身上消失、没有过渡）。把这类动作拆成 3-5 个连续短镜，**每镜只演一个最小子动作**，并把中间机械细节写进 motion_prompt（英文 + slowly / gradually / continuous / smooth cloth physics）。示例（脱外套）：镜A 指尖抓衣领向下解→镜B 外套滑下一侧肩膀→镜C 袖子褪到手肘→镜D 外套褪下垂落手中。这些镜 character 同一人、environment 复用、景别可递进（特写手→中景→全身），靠剪辑连成一套完整动作。注意：这与上一条『少切碎镜』不冲突——简单叙事别过度切，但复杂【物理动作】是必须拆的例外。\n"
    "   同一场景的连续镜，environment（地点/布景/光线/时间）用**同一段英文描述**复用，防止背景在镜间漂移；景别仍可有节奏（空镜/中景/特写），但不必每镜都换。\n"
    "   **★多人不同框（防串脸，重要）**：训了 LoRA 的主角和【其他人（配角/路人/对手/美女等）】尽量**不要放进同一镜**——t2v 全局角色 LoRA 会把同框的他人也画成主角那张脸。把『相遇/对手戏/对话』拆成**主角单人镜 + 他人单人镜**交替（每镜 character 只填一个人，他人镜的 character 留空），靠剪辑制造『同框』感。\n"
    "   实在要同框：必须给【他人】写明确且与主角**明显不同**的英文外貌（不同发色/脸型/年龄数字/服装），别让他人外貌空泛，否则必串脸。\n"
    "4) 短剧命脉：开头要有钩子，结尾留悬念。\n"
    "只输出这个 JSON 数组，不要任何解释、前后缀、代码块标记。"
)

_FIELDS = ("title", "image_prompt", "motion_prompt", "narration", "subtitle", "lipsync", "character", "dialogue")


def _coerce_dialogue(v) -> str:
    """把 LLM 的 dialogue（数组 [{speaker,text}] 或多行文本）规整成「说话人：台词」逐行文本。"""
    lines = []
    if isinstance(v, list):
        for it in v:
            if isinstance(it, dict):
                spk = str(it.get("speaker") or it.get("name") or "").strip()
                txt = str(it.get("text") or it.get("line") or "").strip()
            else:
                spk, txt = "", str(it or "").strip()
            if txt:
                lines.append(f"{spk}：{txt}" if spk else txt)
    elif isinstance(v, str):
        lines = [ln.strip() for ln in v.splitlines() if ln.strip()]
    return "\n".join(lines)


def _as_bool(v) -> bool:
    """稳健解析 LLM 给的布尔：真布尔直接用，字符串按字面判定。

    防 `bool("false") == True` 这类坑——LLM 偶尔把布尔写成字符串
    "false"/"否"，直接 bool() 会因非空串恒真而把该镜误判成对口型。
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "是", "对", "真")
    return bool(v)


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
                        "lipsync": _as_bool(it.get("lipsync")),
                        "character": str(it.get("character") or "").strip(),
                        "dialogue": _coerce_dialogue(it.get("dialogue")),
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
                       "subtitle": "", "lipsync": False, "character": "", "dialogue": ""})
    return scenes


async def breakdown_storyboard(novel_text: str, n: int, *, style: str = "",
                               characters: list[dict] | None = None,
                               llm_config=None) -> list[dict]:
    """把小说文本拆成 N 个分镜。

    Args:
        novel_text: 小说/剧情文本。
        n: 想要的分镜数。
        style: 本集统一风格词（拼到每镜 image_prompt 末尾，保证全集一个调性）。
        characters: 角色圣经 [{"name","appearance","voice"}...]；导演据此写人物外貌、判断 character 字段。
        llm_config: 前端「导演/分镜模型」配置(AgentLLMConfig|dict|None)；非空=按它现造(UI 覆盖)，
            空=回退 STORYBOARD_* env → 全局默认。让前端选 grok/OpenRouter 等真正生效。
    Returns:
        长度严格为 n 的分镜 dict 列表，字段见 _FIELDS。
    """
    n = max(1, int(n or 1))
    from mirage.app.services.ai_service import ai_service
    from langchain_core.messages import SystemMessage, HumanMessage

    char_block = ""
    if characters:
        lines = []
        any_lora = False
        for c in characters:
            nm = str(c.get("name") or "").strip()
            ap = str(c.get("appearance") or "").strip()
            # 已训角色 LoRA(有 trained_lora_id 或绑了触发词)→身份由 LoRA 锁定,外貌该从简,别和 LoRA 学到的脸打架。
            has_lora = bool((c.get("trained_lora_id") or "").strip()) or bool((c.get("trigger_word") or "").strip())
            if nm:
                if has_lora:
                    any_lora = True
                    lines.append(f"- {nm}［已训LoRA·身份靠触发词，外貌从简］：{ap or '(外貌可自拟)'}")
                else:
                    lines.append(f"- {nm}：{ap or '(外貌自拟，但每镜保持一致)'}")
        if lines:
            char_block = "本剧角色（image_prompt 写到该角色时，把其外貌**翻成英文**写进去；character 字段填其原名）：\n" + "\n".join(lines) + "\n"
            if any_lora:
                char_block += ("注：标了［已训LoRA］的角色，身份由 LoRA 自动锁定——其 image_prompt 只写**精简中性外貌**"
                               "（性别 + 大致年龄 + 本镜服装/动作/景别即可），**不要堆 hair/face/distinctive features 长串**，"
                               "以免外貌词与 LoRA 学到的脸打架（这类角色靠触发词+LoRA 保证是同一个人，不靠文字描述）。\n")

    human = (
        f"{char_block}"
        f"统一风格词（每镜 image_prompt 结尾都带上）：{style or '电影感，写实，浅景深'}\n"
        f"需要分镜数 N：{n}\n"
        f"小说/剧情文本：\n{(novel_text or '').strip()[:6000]}"
    )
    try:
        llm = ai_service.storyboard_llm_for(llm_config)   # 前端导演模型 > STORYBOARD_* env > 全局默认
        resp = await llm.ainvoke([
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=human),
        ])
        out = _coerce_scenes(getattr(resp, "content", "") or "", n, style)
        logger.info("[storyboard] 拆出 %d 个分镜", len(out))
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[storyboard] LLM 拆分镜失败，返回 N 个空白镜待手填: %s", e)
        return _coerce_scenes("", n, style)
