# -*- coding: utf-8 -*-
"""对口型(S2V)帧数=按音频时长动态算 的单测：6秒台词不再被写死的81帧截断。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mirage.app.pipeline.pipeline_tools import _s2v_frames_for_audio

FPS = 16


def test_six_second_line_not_truncated():
    """6 秒台词 → 帧数覆盖到 ≥6s（旧写死 81帧≈5.06s 会截掉最后~1s）。"""
    f = _s2v_frames_for_audio(6.0, FPS)
    assert f / FPS >= 6.0, f"6s 台词应出 ≥6s，实际 {f/FPS:.2f}s"
    assert f > 81, f"应比写死的 81 帧长，实际 {f}"


def test_is_wan_legal_4n_plus_1():
    """Wan 时序步长 4 → 帧数必须是 4n+1。"""
    for sec in (1.0, 2.3, 4.0, 5.0, 6.0, 7.5, 9.9):
        f = _s2v_frames_for_audio(sec, FPS)
        assert (f - 1) % 4 == 0, f"{sec}s → {f} 帧不是 4n+1"


def test_covers_audio_length():
    """生成时长应 ≥ 音频时长（不截断），且不过度超长（余量 < 1s+一步长）。"""
    for sec in (1.0, 3.3, 5.7, 6.0):
        f = _s2v_frames_for_audio(sec, FPS)
        out = f / FPS
        assert out >= sec, f"{sec}s 被截到 {out:.2f}s"
        assert out - sec < 1.0, f"{sec}s 余量过大到 {out:.2f}s"


def test_cap_limits_overlong():
    """超长台词被 cap 封顶（防 OOM）。"""
    f = _s2v_frames_for_audio(20.0, FPS, cap=113)
    assert f == 113, f"应封顶到 113，实际 {f}"


def test_invalid_returns_zero():
    """时长/fps 非法 → 0（调用方回退默认帧数）。"""
    assert _s2v_frames_for_audio(0, FPS) == 0
    assert _s2v_frames_for_audio(5, 0) == 0
    assert _s2v_frames_for_audio(-3, FPS) == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}")
    print("S2V 帧数动态算：全部通过")
