"""
分段运镜提示词生成 —— 把"一个动作/运镜"用大模型拆成 N 段递进的英文提示词，供尾帧接续逐段使用。

为什么：尾帧接续（一个分镜拆 N 段连续生成再拼接）若 N 段共用同一句提示词，做不出"动作递进"；
用户也常写不出每段提示词（尤其英文）。这里让 LLM 据画面 + 一句中文意图（可空）自动生成 N 段，
每段从上一段末帧继续，把动作平滑分成 N 步。
"""

from __future__ import annotations

import json
import re

from agent_lab.app.core.logger import get_logger

logger = get_logger("pipeline.prompt_gen")

_SYSTEM = (
    "你是图生视频(image-to-video，尾帧接续)的运镜提示词生成器。"
    "图生视频会让一张静态图动起来：它只能做镜头运动(推/拉/摇/移/环绕)与可连续完成的细微动态"
    "(风吹、发丝、衣料飘动、缓慢转身、表情渐变、光影流动)，"
    "做不了多步骤的复杂语义动作——所以每段只描述这一类可实现的运动。\n"
    "用户会给：画面描述、期望的动作或运镜(可能为空)、需要的段数 N。\n"
    "规则：\n"
    "1) 输出恰好 N 段，每段对应一个视频片段；\n"
    "2) 每段都从上一段的最后一帧继续(尾帧接续)，把期望的动作/运镜平滑地分成 N 步递进——"
    "第1段起势、中间推进、最后一段收束；\n"
    "3) 每段是一句简短的英文运镜提示词(motion prompt)，不要写角色长相/不要解释/不要序号；\n"
    "4) 期望为空时，就根据画面设计一个自然、有电影感的递进运镜。\n"
    "只输出一个 JSON 字符串数组，长度严格为 N，例如：[\"...\",\"...\"]。不要输出别的任何内容。"
)


def _coerce(text: str, n: int) -> list[str]:
    """把 LLM 输出解析成长度严格为 N 的字符串列表（容错）。"""
    arr: list[str] = []
    # 1) 优先解析 JSON 数组（含被代码块包裹的情况）
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                arr = [str(x).strip() for x in data if str(x).strip()]
        except Exception:  # noqa: BLE001
            arr = []
    # 2) 回退：按行/序号切
    if not arr:
        for line in text.splitlines():
            s = line.strip().strip("-•").strip()
            s = re.sub(r"^\s*\d+[\.\)、]\s*", "", s)  # 去掉 "1. " "2)" 这类序号
            s = s.strip().strip('"').strip()
            if s:
                arr.append(s)
    if not arr:
        arr = [text.strip()] if text.strip() else []
    # 3) 强制对齐长度 N：不足补最后一条，超出截断
    if not arr:
        arr = ["slow cinematic push-in, subtle motion"]
    if len(arr) < n:
        arr = arr + [arr[-1]] * (n - len(arr))
    return arr[:n]


async def suggest_segment_prompts(image_prompt: str, intent: str, n: int) -> list[str]:
    """生成 N 段递进的英文运镜提示词。

    Args:
        image_prompt: 该分镜的画面描述（出图提示词）。
        intent: 用户的中文意图（想要什么动作/运镜），可为空。
        n: 段数。
    """
    from agent_lab.app.core.config import settings
    _cap = settings.MAX_CONTINUATION_SEGMENTS      # 段数不写死：0=不限
    n = max(1, int(n or 1))
    if _cap and _cap > 0:
        n = min(n, _cap)
    from agent_lab.app.services.ai_service import ai_service
    from langchain_core.messages import SystemMessage, HumanMessage

    human = (
        f"画面描述：{image_prompt or '(无)'}\n"
        f"期望的动作/运镜：{intent.strip() if intent and intent.strip() else '(未指定，请据画面设计自然递进的运镜)'}\n"
        f"段数 N：{n}"
    )
    try:
        resp = await ai_service._llm.ainvoke([
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=human),
        ])
        out = _coerce(getattr(resp, "content", "") or "", n)
        logger.info("[prompt_gen] 生成 %d 段运镜提示词", len(out))
        return out
    except Exception as e:  # noqa: BLE001 - 失败给一个保底的递进推镜
        logger.warning("[prompt_gen] LLM 生成失败，用保底提示词: %s", e)
        base = "slow cinematic push-in, subtle handheld sway, soft ambient motion"
        return [f"{base} ({i + 1}/{n})" for i in range(n)]


_TRANSLATE_SYSTEM = (
    "You are a prompt translator for the FLUX text-to-image model, which only understands English. "
    "Translate the user's image prompt into ONE concise, vivid English prompt. "
    "Preserve every visual detail: subject, scene, composition, lighting, color tone, lens/camera, style and mood; "
    "keep quality/style words (photorealistic, cinematic, 8k, shallow depth of field, etc.). "
    "Do NOT invent a person or character that isn't described. "
    "When the source names a school stage or age group (小学生/初中生/高中生/大学生/青少年/儿童 etc.), "
    "add an explicit approximate age in years so the model renders the right age — "
    "e.g. 高中生 -> 'teenage high-school student, about 16-17 years old', 大学生 -> 'young adult, about 20'. "
    "Leave untouched any token that looks like a LoRA trigger word (an alphanumeric id such as ch4r_cael) — copy it verbatim. "
    "Output ONLY the English prompt: no quotes, no notes, no numbering, under 75 words."
)


def _has_cjk(s: str) -> bool:
    """是否含中日文字符（含汉字/假名）——FLUX 读不懂这些，需先翻英文。"""
    return any(
        "一" <= ch <= "鿿" or "぀" <= ch <= "ヿ" or "㐀" <= ch <= "䶿"
        for ch in (s or "")
    )


def translate_to_english(text: str) -> str:
    """把中文（或含 CJK 的）出图提示词同步翻成英文，供 FLUX 等英文模型出图。

    - 空 / 不含 CJK → 原样返回（已是英文不动）；
    - LLM 失败 → 原样返回（绝不阻断出图，最坏退回老行为）。
    同步实现：generate_candidates 是同步工具（跑在线程池里），用 `_llm.invoke` 而非 ainvoke。
    """
    t = (text or "").strip()
    if not t or not _has_cjk(t):
        return t
    from agent_lab.app.services.ai_service import ai_service
    from langchain_core.messages import SystemMessage, HumanMessage
    try:
        resp = ai_service._llm.invoke([
            SystemMessage(content=_TRANSLATE_SYSTEM),
            HumanMessage(content=t),
        ])
        en = _one_line(getattr(resp, "content", "") or "")
        if en:
            logger.info("[prompt_gen] 出图词中→英: %r -> %r", t[:40], en[:80])
            return en
        return t
    except Exception as e:  # noqa: BLE001 - 翻译失败不阻断出图
        logger.warning("[prompt_gen] 出图词翻译失败，用原文: %s", e)
        return t


def _one_line(text: str) -> str:
    """把模型输出收成干净的一句：取首个非空行，去掉引号/序号/前后空白。"""
    for raw in (text or "").splitlines():
        ln = re.sub(r"^\s*\d+[\.\)、]\s*", "", raw.strip())   # 先去 "1. " / "1) " 之类
        ln = ln.strip('"“”\'').strip()                        # 再去引号
        if ln:
            return ln
    return (text or "").strip()


async def suggest_continuation_prompt(scene: dict, prior_prompts: list[str],
                                      tail_frame_path: str, lang: str = "zh") -> dict:
    """据「现有成片的末帧 + 画面/旁白/前几段运镜」，推荐**下一段**的运镜提示词。

    防抽卡：用户不用自己憋提示词，点一下就有一句可改的推荐。
    - 配了视觉模型(VISION_*)→ 真看末帧图给建议（saw_frame=True）；
    - 没配 → 回退纯文本，据画面设定 + 已用运镜推断（saw_frame=False）。
    语言不限：lang="zh" 给中文（Wan2.2 原生支持中文提示词），"en" 给英文。

    Returns: {"prompt": 一句运镜提示词, "saw_frame": 是否真看了图}
    """
    lang_name = "中文" if (lang or "zh").lower().startswith("zh") else "English"
    ctx_scene = scene.get("image_prompt") or scene.get("title") or ""
    narr = scene.get("narration") or ""
    prior = "；".join(p for p in (prior_prompts or []) if p) or "(无)"
    system = (
        f"你是分镜运镜导演。给你的图是一段视频的最后一帧，它将作为「尾帧接续」下一段的起始画面。"
        f"图生视频只能做镜头运动(推/拉/摇/移/环绕)与可连续完成的细微动态(风吹、发丝、衣料、缓慢转身、"
        f"表情渐变、光影流动)，做不了多步复杂动作。"
        f"请只输出一句【{lang_name}】运镜/动态提示词，描述镜头如何从这一帧自然地继续运动。"
        f"不要解释、不要引号、不要编号，只要一句话。"
    )
    user_text = (
        f"画面设定：{ctx_scene or '(无)'}\n旁白：{narr or '(无)'}\n"
        f"前面已用过的运镜：{prior}\n请给下一段的运镜提示词（一句话，{lang_name}）。"
    )

    # 1) 优先视觉模型：真看末帧图
    from agent_lab.app.services.vision import suggest_from_image, vision_enabled
    saw = vision_enabled()
    out = suggest_from_image(tail_frame_path, system, user_text) if saw else None
    if out:
        return {"prompt": _one_line(out), "saw_frame": True}

    # 2) 回退：纯文本据上下文推理（看不到图，但据设定 + 前段递进）
    from agent_lab.app.services.ai_service import ai_service
    from langchain_core.messages import SystemMessage, HumanMessage
    sys2 = system + "（注意：你看不到实际画面，请据上面的文字设定与已用运镜，推断自然的下一段运镜。）"
    try:
        resp = await ai_service._llm.ainvoke([SystemMessage(content=sys2),
                                              HumanMessage(content=user_text)])
        return {"prompt": _one_line(getattr(resp, "content", "") or ""), "saw_frame": False}
    except Exception as e:  # noqa: BLE001 - 保底
        logger.warning("[prompt_gen] 续段推荐失败，用保底: %s", e)
        fallback = "缓慢推近，主体保持自然的细微动态" if lang_name == "中文" \
            else "slow push-in, subject keeps subtle natural motion"
        return {"prompt": fallback, "saw_frame": False}
