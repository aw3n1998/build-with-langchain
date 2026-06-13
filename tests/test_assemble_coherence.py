# -*- coding: utf-8 -*-
"""合成连贯性：crossfade 叠化 + BGM 背景音乐 的单测（用 ffmpeg 合成的小片，无 GPU）。"""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mirage.app.pipeline import assembler

FF = assembler._ffmpeg()


def _gen(path, dur=2):
    subprocess.run([FF, "-y", "-hide_banner", "-f", "lavfi",
                    "-i", f"testsrc=size=480x854:rate=30:duration={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={dur}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
                   capture_output=True)


def _clips(d, n=3):
    out = []
    for i in range(n):
        p = os.path.join(d, f"c{i}.mp4"); _gen(p)
        out.append({"path": p, "narration": "", "subtitle": f"镜{i+1}"})
    return out


def test_crossfade_shortens_and_burns():
    d = tempfile.mkdtemp()
    clips = _clips(d)
    out = os.path.join(d, "xf.mp4")
    r = assembler.assemble_clips(clips, out, with_subtitles=True, crossfade=0.4, bgm="")
    assert os.path.isfile(out)
    assert r["subtitles"] == "burned"
    # 3×2s − 2×0.4s 叠化 ≈ 5.2s（< 硬切的 6s）
    assert 4.8 < r["duration"] < 5.7, r["duration"]


def test_hardcut_fallback_when_no_crossfade():
    d = tempfile.mkdtemp()
    clips = _clips(d)
    out = os.path.join(d, "hc.mp4")
    r = assembler.assemble_clips(clips, out, with_subtitles=True, crossfade=0.0, bgm="")
    assert os.path.isfile(out)
    assert 5.7 < r["duration"] < 6.5, r["duration"]   # 3×2s ≈ 6s


def test_bgm_mixed_in():
    d = tempfile.mkdtemp()
    clips = _clips(d, 2)
    bgm = os.path.join(d, "bgm.m4a")
    subprocess.run([FF, "-y", "-hide_banner", "-f", "lavfi",
                    "-i", "sine=frequency=200:duration=20", "-c:a", "aac", bgm], capture_output=True)
    out = os.path.join(d, "b.mp4")
    r = assembler.assemble_clips(clips, out, with_subtitles=False, crossfade=0.4, bgm=bgm)
    assert os.path.isfile(out) and r["duration"] > 2.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  [ok] {name}")
    print("ASSEMBLE_COHERENCE_OK")
