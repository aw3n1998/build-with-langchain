"""
Part A 单测：分段运镜提示词的解析(_coerce) + suggest_segment_prompts(用假 LLM，不调真 API)。

运行：python tests/test_segment_prompts.py
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _install_fake_ai_service(content: str):
    """在 import prompt_gen 前，把 ai_service 换成返回固定 content 的假实现。"""
    mod = types.ModuleType("agent_lab.app.services.ai_service")

    class _Resp:
        def __init__(self, c):
            self.content = c

    class _FakeLLM:
        def __init__(self, c):
            self._c = c

        async def ainvoke(self, _msgs):
            return _Resp(self._c)

    class _FakeAI:
        pass

    ai = _FakeAI()
    ai._llm = _FakeLLM(content)
    mod.ai_service = ai
    sys.modules["agent_lab.app.services.ai_service"] = mod


def test_coerce():
    from agent_lab.app.pipeline.prompt_gen import _coerce

    # 1) 干净 JSON 数组，长度正好
    assert _coerce('["a","b","c"]', 3) == ["a", "b", "c"]
    # 2) JSON 被代码块包裹
    assert _coerce('```json\n["x","y"]\n```', 2) == ["x", "y"]
    # 3) LLM 多给了 → 截断到 N
    assert _coerce('["1","2","3","4"]', 2) == ["1", "2"]
    # 4) LLM 少给了 → 补最后一条到 N
    assert _coerce('["only"]', 3) == ["only", "only", "only"]
    # 5) 非 JSON，按行/序号切
    out = _coerce("1. push in slowly\n2) pull back\n- final hold", 3)
    assert out == ["push in slowly", "pull back", "final hold"], out
    # 6) 完全空 → 有保底，且长度对齐
    out = _coerce("", 2)
    assert len(out) == 2 and all(isinstance(s, str) and s for s in out)
    print("test_coerce OK")


def test_suggest_aligns_length():
    # LLM 只给 1 条，但要 3 段 → 对齐成 3
    _install_fake_ai_service('["slow push-in on the face"]')
    # 确保拿到的是套了假 ai_service 的新模块
    sys.modules.pop("agent_lab.app.pipeline.prompt_gen", None)
    from agent_lab.app.pipeline.prompt_gen import suggest_segment_prompts

    out = asyncio.run(suggest_segment_prompts("a woman by the window", "镜头慢慢推近", 3))
    assert isinstance(out, list) and len(out) == 3, out
    assert all(isinstance(s, str) and s for s in out), out
    print("test_suggest_aligns_length OK ->", out)


def test_suggest_handles_garbage():
    # LLM 返回一堆散文 → 仍能切出 >=1 段并对齐到 N
    _install_fake_ai_service("Here you go:\nFirst, slowly push in.\nThen pull back wide.")
    sys.modules.pop("agent_lab.app.pipeline.prompt_gen", None)
    from agent_lab.app.pipeline.prompt_gen import suggest_segment_prompts

    out = asyncio.run(suggest_segment_prompts("street scene", "", 2))
    assert len(out) == 2 and all(out), out
    print("test_suggest_handles_garbage OK ->", out)


if __name__ == "__main__":
    test_coerce()
    test_suggest_aligns_length()
    test_suggest_handles_garbage()
    print("\nALL PASS")
