# -*- coding: utf-8 -*-
"""
防抽卡·续段运镜提示词 AI 推荐 单测。

断言：
  1) _one_line 把模型输出收成干净一句（去引号/序号/空白）；
  2) vision_enabled() 仅在配了 VISION_BASE_URL+MODEL 时为真；
  3) 配了视觉模型 → 用「真看尾帧」结果，saw_frame=True；
  4) 没配视觉模型 → 回退纯文本 LLM（mock），saw_frame=False；中/英语言都通。
不连真实网络/模型。运行：python tests/test_continuation_prompt.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import mirage.app.services.vision as vision
    from mirage.app.pipeline import prompt_gen
    from mirage.app.core.config import settings

    scene = {"image_prompt": "她站在窗前", "narration": "夜色渐深",
             "title": "窗前", "motion_prompt": "缓慢推近"}

    # 1) _one_line 清洗
    assert prompt_gen._one_line('1. "缓慢推近，她回头"\n多余行') == "缓慢推近，她回头"
    assert prompt_gen._one_line("  \n  slow push-in  ") == "slow push-in"
    print("[cont] _one_line 清洗 OK")

    # 2) vision_enabled 逻辑
    settings.VISION_BASE_URL = ""; settings.VISION_MODEL = ""
    assert vision.vision_enabled() is False
    settings.VISION_BASE_URL = "http://fake-vl"; settings.VISION_MODEL = "qwen-vl-max"
    assert vision.vision_enabled() is True
    print("[cont] vision_enabled OK")

    # 3) 配了视觉 + mock 真看图 → saw_frame=True，用视觉结果
    vision.suggest_from_image = lambda *a, **k: '推近，她缓缓转头，发丝轻扬'
    r = asyncio.run(prompt_gen.suggest_continuation_prompt(
        scene, ["缓慢推近"], "no_such_frame.png", "zh"))
    assert r["saw_frame"] is True and "转头" in r["prompt"], r
    print("[cont] 视觉模型真看尾帧 OK ->", r)

    # 4) 没配视觉 → 回退纯文本 LLM（mock ai_service._llm）→ saw_frame=False
    settings.VISION_BASE_URL = ""   # 关掉视觉
    from mirage.app.services import ai_service as ai_mod

    class _Resp:
        content = "缓慢拉远，光影在墙上流动"

    class _LLM:
        async def ainvoke(self, msgs):
            # 顺带断言系统提示词里带了语言要求
            joined = " ".join(getattr(m, "content", "") for m in msgs)
            assert "中文" in joined or "English" in joined, "系统提示未指定语言"
            return _Resp()

    ai_mod.ai_service._llm = _LLM()
    r2 = asyncio.run(prompt_gen.suggest_continuation_prompt(
        scene, ["缓慢推近"], "no_such_frame.png", "zh"))
    assert r2["saw_frame"] is False and "拉远" in r2["prompt"], r2
    print("[cont] 无视觉→纯文本回退 OK ->", r2)

    # en 语言也走通（仍是文本回退）
    r3 = asyncio.run(prompt_gen.suggest_continuation_prompt(
        scene, [], "no_such_frame.png", "en"))
    assert r3["saw_frame"] is False and r3["prompt"], r3
    print("[cont] 英文语言 OK ->", r3)

    print("\n=== 续段推荐(vision + 纯文本回退) 单测通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
