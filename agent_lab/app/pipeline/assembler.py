"""
成片合成器 —— 把各分镜的独立 mp4 拼成一条完整短剧（本地完成，不占 GPU）。

链路最后一公里：
  分镜 clips（无声、时长 1~5s 不一）
    → 每段统一编码/分辨率，narration 经 edge-tts 配旁白（音频比视频长则冻结末帧补齐）
    → 按 scene_number 顺序 concat
    → 旁白字幕（SRT：优先烧进画面，失败则软字幕 mov_text，再失败无字幕）
    → episode_<project>.mp4

依赖（均为本地、免费）：
  - imageio-ffmpeg：自带 ffmpeg 静态二进制，无需系统安装；
  - edge-tts：微软在线 TTS（需联网）；不可用时自动退化为无旁白合成。
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

from agent_lab.app.core.logger import get_logger

logger = get_logger("pipeline.assembler")

DEFAULT_VOICE = "zh-CN-YunxiNeural"   # 沉稳男声旁白；女声可用 zh-CN-XiaoxiaoNeural


def _ffmpeg() -> str:
    """找 ffmpeg：优先 imageio-ffmpeg 自带二进制，回退系统 PATH。"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _run(args: list[str], cwd: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    """跑 ffmpeg（隐藏横幅，stderr 捕获用于报错/解析时长）。"""
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def _duration(path: str) -> float:
    """从 `ffmpeg -i` 的 stderr 解析媒体时长（imageio-ffmpeg 不带 ffprobe）。"""
    res = _run([_ffmpeg(), "-hide_banner", "-i", path])
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", res.stderr or "")
    if not m:
        raise RuntimeError(f"无法解析时长: {path}")
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


def _tts(text: str, out_mp3: str, voice: str = DEFAULT_VOICE) -> bool:
    """edge-tts 文本转旁白 mp3。失败（断网/未安装）返回 False，由调用方退化处理。"""
    try:
        import asyncio
        import edge_tts

        async def gen():
            await edge_tts.Communicate(text, voice).save(out_mp3)

        asyncio.run(gen())
        return os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1000
    except Exception as e:  # noqa: BLE001
        logger.warning("[assembler] TTS 失败（退化为无旁白）: %s", e)
        return False


def _video_size(path: str) -> tuple[int, int]:
    res = _run([_ffmpeg(), "-hide_banner", "-i", path])
    m = re.search(r",\s*(\d{2,5})x(\d{2,5})[\s,]", res.stderr or "")
    if not m:
        raise RuntimeError(f"无法解析分辨率: {path}")
    return int(m.group(1)), int(m.group(2))


def extract_last_frame(video_path: str, out_png: str) -> str:
    """抽取视频最后一帧（尾帧接续用：作为下一段 i2v 的输入图）。"""
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    res = _run([_ffmpeg(), "-y", "-hide_banner", "-sseof", "-0.2", "-i", video_path,
                "-frames:v", "1", "-q:v", "2", out_png])
    if res.returncode != 0 or not os.path.exists(out_png):
        # 个别短片 -sseof 取不到，回退全解码取最后一帧
        res = _run([_ffmpeg(), "-y", "-hide_banner", "-i", video_path,
                    "-vf", "select='eq(n,0)+gt(n,0)'", "-vsync", "vfr",
                    "-update", "1", out_png])
        if res.returncode != 0 or not os.path.exists(out_png):
            raise RuntimeError(f"抽取末帧失败: {(res.stderr or '')[-400:]}")
    return out_png


def concat_videos(paths: list[str], out_path: str) -> str:
    """同源片段快速拼接（流复制；失败回退重编码）。用于尾帧接续的多段合一。"""
    ff = _ffmpeg()
    work = tempfile.mkdtemp(prefix="chain_")
    try:
        lst = os.path.join(work, "list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for p in paths:
                f.write(f"file '{p}'\n")
        tmp_out = os.path.join(work, "out.mp4")
        res = _run([ff, "-y", "-hide_banner", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", tmp_out])
        if res.returncode != 0:   # 极少数封装差异导致 copy 失败 → 重编码兜底
            res = _run([ff, "-y", "-hide_banner", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "20", "-pix_fmt", "yuv420p", tmp_out], timeout=900)
            if res.returncode != 0:
                raise RuntimeError(f"片段拼接失败: {(res.stderr or '')[-400:]}")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        if os.path.exists(out_path):
            os.remove(out_path)
        import shutil
        shutil.move(tmp_out, out_path)
        return out_path
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)


def _srt_ts(t: float) -> str:
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def assemble_clips(
    clips: list[dict],
    out_path: str,
    *,
    voice: str = DEFAULT_VOICE,
    with_subtitles: bool = True,
    crossfade: float = 0.0,
) -> dict:
    """把分镜 clips 合成一条成片。

    Args:
        clips: [{"path": 本地mp4, "narration": 旁白文本(可空), "title": 标题(可空)}, ...] 按顺序。
        out_path: 输出 mp4 绝对路径。
        voice: edge-tts 音色。
        with_subtitles: 是否加旁白字幕（优先烧录，失败软字幕）。
        crossfade: 预留（当前硬切）。
    Returns:
        {"out": 路径, "duration": 总秒, "scenes": N, "tts": 用了旁白?, "subtitles": "burned|soft|none"}
    """
    ff = _ffmpeg()
    if not clips:
        raise ValueError("没有可合成的分镜片段")
    for c in clips:
        if not os.path.isfile(c["path"]):
            raise FileNotFoundError(f"分镜片段不存在: {c['path']}")

    tw, th = _video_size(clips[0]["path"])  # 以第一段分辨率为基准，其余缩放+补边
    work = tempfile.mkdtemp(prefix="assemble_")
    try:
        return _assemble_in(work, clips, out_path, ff, tw, th,
                            voice=voice, with_subtitles=with_subtitles)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)   # 中间片段每次几十MB，必须清理（成败都清）


def _assemble_in(work: str, clips: list[dict], out_path: str, ff: str,
                 tw: int, th: int, *, voice: str, with_subtitles: bool) -> dict:
    parts: list[str] = []
    subs: list[tuple[float, float, str]] = []   # (start, end, text)
    t_cursor = 0.0
    tts_used = False

    for i, c in enumerate(clips):
        clip = c["path"]
        narration = (c.get("narration") or "").strip()              # 配音用（TTS）
        subtitle = (c.get("subtitle") or "").strip() or narration   # 字幕用：独立字幕优先，没有则回退旁白
        keep_audio = bool(c.get("keep_audio"))                       # 对口型片自带人声：保留它，别重配音(否则口型错位)
        vd = _duration(clip)
        if keep_audio:
            has_narr = False
            out_dur, freeze = vd, 0.0     # 用片子自带音轨，时长以视频为准，不冻结
        else:
            mp3 = os.path.join(work, f"narr_{i}.mp3")
            has_narr = bool(narration) and _tts(narration, mp3, voice)
            ad = _duration(mp3) if has_narr else 0.0
            out_dur = max(vd, ad + 0.3) if has_narr else vd      # 旁白略留尾气口
            freeze = max(0.0, out_dur - vd)
            tts_used = tts_used or has_narr

        # 统一分辨率 + 末帧冻结补齐 + 统一编码（后续 concat 可直接 -c copy）
        vf = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
              f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1")
        if freeze > 0.05:
            vf += f",tpad=stop_mode=clone:stop_duration={freeze:.3f}"
        part = os.path.join(work, f"part_{i}.mp4")
        args = [ff, "-y", "-hide_banner", "-i", clip]
        if keep_audio:
            probe = _run([ff, "-hide_banner", "-i", clip])   # 探一下源片到底有没有音轨
            if "Audio:" in (probe.stderr or ""):
                amap = "0:a"     # 源片自带音轨（S2V 人声），保留它
            else:                # 源片其实无音轨 → 补静音，保证每个 part 都有音轨(concat 一致)
                args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]; amap = "1:a"
        elif has_narr:
            args += ["-i", mp3]; amap = "1:a"
        else:
            args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]; amap = "1:a"
        args += ["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", amap,
                 "-t", f"{out_dur:.3f}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "2", part]
        res = _run(args, timeout=900)
        if res.returncode != 0:
            raise RuntimeError(f"分镜 {i+1} 处理失败:\n{(res.stderr or '')[-800:]}")
        real = _duration(part)
        if subtitle:
            subs.append((t_cursor + 0.05, t_cursor + real - 0.05, subtitle))
        t_cursor += real
        parts.append(part)

    # 顺序拼接（各 part 编码一致，流复制零损耗）
    lst = os.path.join(work, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    merged = os.path.join(work, "merged.mp4")
    res = _run([ff, "-y", "-hide_banner", "-f", "concat", "-safe", "0",
                "-i", lst, "-c", "copy", merged])
    if res.returncode != 0:
        raise RuntimeError(f"拼接失败:\n{(res.stderr or '')[-800:]}")

    # 字幕：烧录（在 work 目录用相对路径，避开 Windows 盘符转义地狱）→ 软字幕 → 无
    sub_mode = "none"
    final_src = merged
    if with_subtitles and subs:
        srt = os.path.join(work, "subs.srt")
        with open(srt, "w", encoding="utf-8") as f:
            for n, (st, en, txt) in enumerate(subs, 1):
                f.write(f"{n}\n{_srt_ts(st)} --> {_srt_ts(en)}\n{txt}\n\n")
        burned = os.path.join(work, "burned.mp4")
        res = _run([ff, "-y", "-hide_banner", "-i", "merged.mp4",
                    "-vf", "subtitles=subs.srt:force_style="
                           "'FontSize=14,Outline=1,MarginV=28'",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "copy", "burned.mp4"], cwd=work, timeout=900)
        if res.returncode == 0 and os.path.exists(burned):
            final_src, sub_mode = burned, "burned"
        else:
            soft = os.path.join(work, "soft.mp4")
            res = _run([ff, "-y", "-hide_banner", "-i", merged, "-i", srt,
                        "-c", "copy", "-c:s", "mov_text",
                        "-metadata:s:s:0", "language=chi", soft])
            if res.returncode == 0 and os.path.exists(soft):
                final_src, sub_mode = soft, "soft"
            else:
                logger.warning("[assembler] 字幕烧录与软封装均失败，输出无字幕版")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)
    import shutil
    shutil.move(final_src, out_path)   # 临时目录在 C 盘、产物可能在其它盘，os.replace 跨盘会报错

    # 可选 ComfyUI 后处理（放大/补帧）：默认关；失败安全（保留原片，不影响成片交付）
    from agent_lab.app.pipeline.postprocess import maybe_postprocess
    post = maybe_postprocess(out_path)

    total = _duration(out_path)
    logger.info("[assembler] 成片完成 %s（%.1fs, %d 段, 字幕=%s, 后处理=%s）",
                out_path, total, len(parts), sub_mode, post["note"])
    return {"out": out_path, "duration": total, "scenes": len(parts),
            "tts": tts_used, "subtitles": sub_mode, "postprocess": post["note"]}
