# -*- coding: utf-8 -*-
"""auto_plan.estimate_storyboard 单测：目标秒数 → 分镜数/每镜段数/每段帧数（Wan 合法 4k+1）。

默认 COMFYUI_FPS=16、COMFYUI_FRAMES=81 → 单段 ≈5.06s；连贯档每镜 2 段(≈10s)，快切档 1 段。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mirage.app.pipeline.auto_plan import estimate_storyboard, _to_4kp1


def test_to_4kp1():
    assert _to_4kp1(81) == 81          # 4*20+1 已合法
    assert (_to_4kp1(80) - 1) % 4 == 0
    assert _to_4kp1(0) >= 5
    for f in (5, 6, 7, 8, 100, 121):
        assert (_to_4kp1(f) - 1) % 4 == 0


def test_60s_coherence_few_long_shots():
    r = estimate_storyboard(60)
    assert 5 <= r["n_shots"] <= 7, r          # 60s/≈10s ≈ 6 个长镜
    assert r["segments_per_shot"] == 2, r     # 连贯=每镜 2 段连续长镜
    assert abs(r["est_total_sec"] - 60) <= 12, r


def test_60s_fastcut_more_short_shots():
    r = estimate_storyboard(60, coherence=False)
    assert 11 <= r["n_shots"] <= 13, r        # 60s/≈5s ≈ 12 个快切
    assert r["segments_per_shot"] == 1, r


def test_30s_coherence():
    r = estimate_storyboard(30)
    assert 2 <= r["n_shots"] <= 4, r
    assert r["segments_per_shot"] == 2, r


def test_bounds_min_and_max():
    assert estimate_storyboard(1)["n_shots"] >= 1            # 极短也至少 1 镜
    big = estimate_storyboard(100000)
    assert big["n_shots"] <= 40, big                         # 上限 40（与 routes 一致）
    assert big["segments_per_shot"] <= 4, big                # 段数甜区上限


def test_frames_are_wan_legal():
    r = estimate_storyboard(60)
    assert (r["frames_per_segment"] - 1) % 4 == 0, r


def test_sec_per_shot_consistent():
    r = estimate_storyboard(60)
    expected = r["segments_per_shot"] * r["frames_per_segment"] / r["fps"]
    assert abs(r["sec_per_shot"] - expected) < 0.02, r


def test_custom_sec_per_shot():
    r = estimate_storyboard(60, sec_per_shot=15.0)
    assert r["n_shots"] == 4, r                              # 60/15
    assert r["segments_per_shot"] == 3, r                    # ceil(15/5.06)=3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}")
    print("estimate_storyboard：全部通过")
