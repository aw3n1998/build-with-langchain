"""
小说/剧情 → AI 分析人物 & 风格（喂给「一键自动填充」编排）。

与 storyboard.breakdown_storyboard 同款：调 ai_service._llm + 健壮 JSON 容错 + 失败保底。
- extract_characters：抽主要角色（明确年龄外貌 + 从音色表选音色）。
- generate_style：据题材定本集统一画风（风格词/负向词/默认尺寸）。
"""

from __future__ import annotations

import json
import re

from mirage.app.core.logger import get_logger

logger = get_logger("pipeline.novel_analyze")

# 常用 edge-tts 音色（与前端角色圣经一致；供 LLM 给角色选音色）。
_VOICES: list[tuple[str, str]] = [
    ("zh-CN-YunxiNeural", "云希·男·活泼"),
    ("zh-CN-YunyangNeural", "云扬·男·沉稳"),
    ("zh-CN-YunjianNeural", "云健·男·浑厚"),
    ("zh-CN-YunxiaNeural", "云夏·男·少年"),
    ("zh-CN-XiaoxiaoNeural", "晓晓·女·温柔"),
    ("zh-CN-XiaoyiNeural", "晓伊·女·少女"),
    ("zh-CN-XiaohanNeural", "晓涵·女·成熟"),
    ("en-US-GuyNeural", "EN·Guy·男·年轻沉稳"),
    ("en-US-ChristopherNeural", "EN·Christopher·男·低沉旁白"),
    ("en-US-JennyNeural", "EN·Jenny·女·自然"),
    ("en-US-AriaNeural", "EN·Aria·女·成熟"),
]
_VOICE_IDS = {v for v, _ in _VOICES}

_DEFAULT_STYLE = {
    # ★英文★：style_prompt 会拼到每镜 image_prompt 末尾喂 FLUX，中文会把整张图带成乱图。
    "style_prompt": "cinematic film still, photorealistic, shallow depth of field",
    "negative_prompt": "low quality, blurry, extra fingers, deformed, watermark, text",
    "default_size": "768x1024",
}


def _first_json(text: str, opener: str):
    """从 LLM 文本里取第一个 JSON 数组/对象（兼容代码块包裹）。opener='[' 或 '{'。"""
    closer = "]" if opener == "[" else "}"
    m = re.search(rf"\{opener}.*\{closer}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception as e:  # noqa: BLE001
        logger.warning("[novel_analyze] JSON 解析失败: %s", e)
        return None


def _coerce_characters(text: str, max_n: int) -> list[dict]:
    data = _first_json(text, "[")
    out: list[dict] = []
    if isinstance(data, list):
        for it in data:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            if not name:
                continue
            voice = str(it.get("voice") or "").strip()
            if voice not in _VOICE_IDS:   # LLM 给了非法/空音色 → 留空（用默认音色）
                voice = ""
            out.append({
                "name": name[:24],
                "appearance": str(it.get("appearance") or "").strip(),
                "voice": voice,
            })
    return out[:max(1, int(max_n or 1))]


def _coerce_style(text: str) -> dict:
    data = _first_json(text, "{")
    if not isinstance(data, dict):
        return dict(_DEFAULT_STYLE)
    out = dict(_DEFAULT_STYLE)
    for k in ("style_prompt", "negative_prompt", "default_size"):
        v = str(data.get(k) or "").strip()
        if v:
            out[k] = v
    return out


async def extract_characters(novel_text: str, max_n: int = 6, *, llm_config=None) -> list[dict]:
    """从小说文本抽主要角色，返回 [{name, appearance, voice}]（失败返回 []）。

    llm_config: 前端「导演模型」(AgentLLMConfig|dict|None)。非空=用它(与拆分镜同一个模型,
        如 grok/OpenRouter)；空=回退 STORYBOARD_* env → 全局默认。★关键★：全局 LLM key 若留空
        (Colab 默认 DEEPSEEK_KEY 可空)，抽角色就会静默失败返回空——必须复用用户实际配的那个模型。
    """
    from mirage.app.services.ai_service import ai_service
    from langchain_core.messages import SystemMessage, HumanMessage

    voices = "\n".join(f"  {vid} — {label}" for vid, label in _VOICES)
    system = (
        "你是选角 / 人设师。从用户给的小说/剧情里抽出主要出场角色（戏份多的优先）。\n"
        "输出一个 JSON 数组，每个角色对象字段（全部必填）：\n"
        "  - name: 角色名（用文中名字；没名字就起个贴切的）\n"
        "  - appearance: 外貌设定。务必含【明确年龄数字】+ 性别 + 发型/脸型/穿着/标志特征，\n"
        "    一句话让出图模型稳定画出同一个人（例：45岁中年男，短寸花白发，左眉旧疤，深色风衣）。\n"
        "  - voice: 从下面音色表挑一个最贴合该角色性别/气质的【音色 id】（只填 id 本身）：\n"
        f"{voices}\n"
        "只输出 JSON 数组，不要任何解释、前后缀、代码块标记。"
    )
    human = (
        f"最多抽 {max_n} 个角色。\n"
        f"小说/剧情文本：\n{(novel_text or '').strip()[:6000]}"
    )
    try:
        llm = ai_service.storyboard_llm_for(llm_config)   # 与拆分镜同一个模型 > STORYBOARD_* env > 全局默认
        resp = await llm.ainvoke([
            SystemMessage(content=system), HumanMessage(content=human),
        ])
        out = _coerce_characters(getattr(resp, "content", "") or "", max_n)
        logger.info("[novel_analyze] 抽出 %d 个角色", len(out))
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[novel_analyze] 抽角色失败，返回空: %s", e)
        return []


async def generate_style(novel_text: str, style_refs: list[str] | None = None,
                         *, llm_config=None) -> dict:
    """据小说题材/氛围生成本集统一画风，返回 {style_prompt, negative_prompt, default_size}。

    style_refs: 用户在模板库里存过的偏好风格词；传入则让 AI 尽量贴近这些口味（F→E 的「下次自动」）。
    llm_config: 同 extract_characters——复用前端配的导演模型，避免全局 key 空时静默用默认风格。
    """
    from mirage.app.services.ai_service import ai_service
    from langchain_core.messages import SystemMessage, HumanMessage

    system = (
        "你是短剧美术指导。据题材/氛围给这一集定**统一画风**（全集一个调性）。\n"
        "输出一个 JSON 对象，字段：\n"
        "  - style_prompt: 一句通用风格词，**必须用英文**（会拼到每镜出图词末尾喂 FLUX，中文会画成乱图）。\n"
        "    写实/电影感/色调/光线/景深等，如 'cinematic film still, photorealistic, moody lighting, shallow depth of field'。\n"
        "  - negative_prompt: 不想要的元素，**用英文**（如 'low quality, blurry, extra fingers, deformed, watermark'）。\n"
        "  - default_size: 出图尺寸，竖屏短剧默认 768x1024（横屏题材可 1024x768）\n"
        "只输出这个 JSON 对象，不要解释/代码块标记。"
    )
    ref_block = ""
    if style_refs:
        refs = "；".join(s for s in style_refs if s)[:600]
        if refs:
            ref_block = f"用户偏好的画风参考（尽量贴近这些口味，可融合）：{refs}\n"
    human = f"{ref_block}小说/剧情文本：\n{(novel_text or '').strip()[:4000]}"
    try:
        llm = ai_service.storyboard_llm_for(llm_config)
        resp = await llm.ainvoke([
            SystemMessage(content=system), HumanMessage(content=human),
        ])
        out = _coerce_style(getattr(resp, "content", "") or "")
        logger.info("[novel_analyze] 生成风格: %s", out.get("style_prompt"))
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[novel_analyze] 生成风格失败，用默认: %s", e)
        return dict(_DEFAULT_STYLE)
