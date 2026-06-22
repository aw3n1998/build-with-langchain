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

from mirage.app.core.logger import get_logger

logger = get_logger("pipeline.assembler")

DEFAULT_VOICE = ""   # ★edge-tts 已弃用：空=走默认引擎(CosyVoice2)的默认音色(LibriVox 爬来的成熟女声)


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


def _tts(text: str, out_mp3: str, voice="") -> bool:
    """文本转配音(mp3/wav)。voice = edge-tts 音色 id(str) 或克隆音色 spec(dict)。
    引擎解耦到 tts_providers 注册表(edge-tts 默认，IndexTTS2 等可插拔)；引擎失败自动回退 edge-tts，
    再不行返回 False 由调用方退化为无旁白。换/加引擎不用动这里。"""
    from mirage.app.pipeline.tts_providers import synth_tts
    if isinstance(voice, str) and not voice.strip():
        voice = DEFAULT_VOICE
    return synth_tts(text or "", out_mp3, voice or DEFAULT_VOICE)


def _video_size(path: str) -> tuple[int, int]:
    res = _run([_ffmpeg(), "-hide_banner", "-i", path])
    m = re.search(r",\s*(\d{2,5})x(\d{2,5})[\s,]", res.stderr or "")
    if not m:
        raise RuntimeError(f"无法解析分辨率: {path}")
    return int(m.group(1)), int(m.group(2))


def conform_video(src: str, out: str, width: int = 0, height: int = 0, fps: int = 0) -> str:
    """把任意上传视频统一成本管线成片规格，供「上传视频续接」拼接：
      - 可选等比缩放 + 黑边填充到 width×height(不拉伸变形)；
      - 设帧率 fps；统一 H.264/yuv420p；去音轨(每镜成片静音，音频在合成整集时统一加)。
    width/height=0 → 保持原尺寸(仅统一帧率/编码)。失败抛 RuntimeError。"""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    vf = []
    if width and height:
        vf.append(f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease")
        vf.append(f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:color=black")
    if fps:
        vf.append(f"fps={int(fps)}")
    args = [_ffmpeg(), "-y", "-hide_banner", "-i", src]
    if vf:
        args += ["-vf", ",".join(vf)]
    args += ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", out]
    res = _run(args, timeout=900)
    if res.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
        raise RuntimeError(f"上传视频转码失败: {(res.stderr or '')[-400:]}")
    return out


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


def extract_first_frame(video_path: str, out_png: str) -> str:
    """抽取视频第一帧（周期重锚用：锚帧 = 链头镜1 的干净正脸首帧，每 K 镜把脸拉回它、防累积漂移）。"""
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    res = _run([_ffmpeg(), "-y", "-hide_banner", "-i", video_path,
                "-frames:v", "1", "-q:v", "2", out_png])
    if res.returncode != 0 or not os.path.exists(out_png):
        raise RuntimeError(f"抽取首帧失败: {(res.stderr or '')[-400:]}")
    return out_png


def concat_videos(paths: list[str], out_path: str, dedup_boundary: bool = False,
                  crossfade: float = 0.0) -> str:
    """尾帧接续的多段合一。

    crossfade>0：相邻段做 `xfade` 交叉淡化(重叠 crossfade 秒淡入淡出)，抹平尾帧续接的**运动跳/色闪**
        ——这是接缝抖动的低成本兜底(短淡化~0.2s 通常净改善；运动跳变极大时可能轻微叠影，设 0 关闭)。
        治本仍是潜空间多帧上下文续接，但那需换 ComfyUI 工作流；此处是纯 ffmpeg 的成片级平滑。优先于 dedup。
    dedup_boundary=True：尾帧接续里每段(除第一段)的**首帧 == 上一段的末帧**(拿末帧当起点生成的)，
        直接拼会出现重复帧 → 拼接处一帧冻结、看着"小卡顿"。开启后用 concat 滤镜丢掉后续段的首帧、重编码无缝拼。
    dedup_boundary=False：老行为，流复制(-c copy)快速拼，失败回退重编码。
    """
    ff = _ffmpeg()
    work = tempfile.mkdtemp(prefix="chain_")
    try:
        tmp_out = os.path.join(work, "out.mp4")
        ok = False
        if crossfade and crossfade > 0 and len(paths) > 1:
            # 接缝交叉淡化:相邻段重叠 crossfade 秒淡入淡出。offset 按累计时长滚动计算。
            durs = [_duration(p) for p in paths]
            inputs = []
            for p in paths:
                inputs += ["-i", p]
            fc = []
            prev = "0:v"
            running = durs[0]
            for i in range(1, len(paths)):
                off = max(0.0, running - crossfade)
                lab = f"xf{i}"
                fc.append(f"[{prev}][{i}:v]xfade=transition=fade:"
                          f"duration={crossfade:.3f}:offset={off:.3f}[{lab}]")
                prev = lab
                running = running + durs[i] - crossfade
            res = _run([ff, "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(fc),
                        "-map", f"[{prev}]", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "20", "-pix_fmt", "yuv420p", tmp_out], timeout=900)
            ok = res.returncode == 0      # xfade 失败(尺寸/时长异常)→ 退回 dedup/copy
        if not ok and dedup_boundary and len(paths) > 1:
            inputs = []
            for p in paths:
                inputs += ["-i", p]
            fc = []
            for i in range(len(paths)):
                # 第一段整段保留；后续段丢掉首帧(=上段末帧的重复帧)
                trim = "" if i == 0 else "trim=start_frame=1,"
                fc.append(f"[{i}:v]{trim}setpts=PTS-STARTPTS[v{i}]")
            fc.append("".join(f"[v{i}]" for i in range(len(paths))) +
                      f"concat=n={len(paths)}:v=1:a=0[outv]")
            res = _run([ff, "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(fc),
                        "-map", "[outv]", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "20", "-pix_fmt", "yuv420p", tmp_out], timeout=900)
            ok = res.returncode == 0      # 滤镜失败(如尺寸不一致)→ 退回 copy 拼
        if not ok:
            lst = os.path.join(work, "list.txt")
            with open(lst, "w", encoding="utf-8") as f:
                for p in paths:
                    f.write(f"file '{p}'\n")
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


def mux_audio_tracks(video_path: str, tracks: list, out_path: str) -> str:
    """把若干配音轨按各自起始秒数(offset)叠到视频上，输出带声成片(视频流 -c copy 不重编码)。

    tracks=[(offset_sec, audio_path), ...]。给「续接段带情感语音」用：每段人声 adelay 到它在
    成片里的起始位置，多段 amix。concat 会丢音轨，故配音统一在拼好后这里叠回去。空 tracks 原样返回。
    """
    tracks = [(o, a) for (o, a) in (tracks or []) if a and os.path.exists(a)]
    if not tracks:
        return video_path
    ff = _ffmpeg()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    inputs = ["-i", video_path]
    for _off, ap in tracks:
        inputs += ["-i", ap]
    fc, labels = [], []
    for i, (off, _ap) in enumerate(tracks):
        delay = int(max(0.0, float(off)) * 1000)
        fc.append(f"[{i + 1}:a]adelay={delay}|{delay}[a{i}]")
        labels.append(f"[a{i}]")
    if len(tracks) > 1:
        fc.append("".join(labels) + f"amix=inputs={len(tracks)}:normalize=0[aout]")
        amap = "[aout]"
    else:
        amap = labels[0]
    args = [ff, "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(fc),
            "-map", "0:v", "-map", amap, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out_path]
    res = _run(args, timeout=900)
    if res.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"配音叠加失败: {(res.stderr or '')[-400:]}")
    return out_path


def mix_sfx_under_voice(video_path: str, sfx_path: str, out_path: str,
                        *, sfx_gain: float = 0.45) -> str:
    """把 Foley 生成的音效叠到视频【已有音轨之下】：原人声/旁白满音量，SFX 降到 sfx_gain 后 amix。
    源片无音轨时直接挂 SFX。视频流 -c copy 不重编码。音效是按整段画面生成的(≈片长)，amix=longest+
    -shortest 收到片长。给「生成音效」后处理用：人声更响、环境/动作音效垫底且与画面同步。"""
    ff = _ffmpeg()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    has_voice = "Audio:" in (_run([ff, "-hide_banner", "-i", video_path]).stderr or "")
    if has_voice:
        fc = (f"[0:a]volume=1.0[v];[1:a]volume={float(sfx_gain)}[s];"
              f"[v][s]amix=inputs=2:duration=longest:normalize=0[aout]")
        args = [ff, "-y", "-hide_banner", "-i", video_path, "-i", sfx_path,
                "-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path]
    else:
        args = [ff, "-y", "-hide_banner", "-i", video_path, "-i", sfx_path,
                "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                "-b:a", "192k", "-shortest", out_path]
    res = _run(args, timeout=900)
    if res.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"音效叠轨失败: {(res.stderr or '')[-400:]}")
    return out_path


def extract_audio(video_path: str, out_wav: str) -> str:
    """抽取视频音轨为 wav（给口型 server 当驱动音）。无音轨返回 ""。"""
    probe = _run([_ffmpeg(), "-hide_banner", "-i", video_path])
    if "Audio:" not in (probe.stderr or ""):
        return ""
    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    res = _run([_ffmpeg(), "-y", "-hide_banner", "-i", video_path,
                "-vn", "-ac", "1", "-ar", "16000", out_wav])
    if res.returncode != 0 or not os.path.exists(out_wav) or os.path.getsize(out_wav) == 0:
        return ""
    return out_wav


def _srt_ts(t: float) -> str:
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def assemble_clips(
    clips: list[dict],
    out_path: str,
    *,
    voice: str = DEFAULT_VOICE,
    with_subtitles: bool = True,
    crossfade: float | None = None,
    bgm: str | None = None,
    dedup_boundary: bool = False,
) -> dict:
    """把分镜 clips 合成一条成片。

    Args:
        clips: [{"path": 本地mp4, "narration": 旁白文本(可空), "title": 标题(可空)}, ...] 按顺序。
        out_path: 输出 mp4 绝对路径。
        voice: edge-tts 音色。
        with_subtitles: 是否加旁白字幕（优先烧录，失败软字幕）。
        crossfade: 镜间交叉叠化秒数；None=用 settings.ASSEMBLE_CROSSFADE；0=硬切。失败自动回退硬切。
        bgm: 背景音乐文件路径；None=用 settings.BGM_PATH；空=不加。
        dedup_boundary: 整集由 i2v 跨镜续接生成时(镜 N 首帧 == 镜 N-1 尾帧)开启——丢掉第 2 镜起的首帧,
            消除拼接处的重复帧卡顿。独立出片(各镜不相干)保持 False。
    Returns:
        {"out": 路径, "duration": 总秒, "scenes": N, "tts": 用了旁白?, "subtitles": "burned|soft|none", "bgm": bool}
    """
    from mirage.app.core.config import settings
    ff = _ffmpeg()
    if not clips:
        raise ValueError("没有可合成的分镜片段")
    for c in clips:
        if not os.path.isfile(c["path"]):
            raise FileNotFoundError(f"分镜片段不存在: {c['path']}")
    cf = float(settings.ASSEMBLE_CROSSFADE if crossfade is None else crossfade) or 0.0
    bgm_path = (settings.BGM_PATH if bgm is None else bgm) or ""

    tw, th = _video_size(clips[0]["path"])  # 以第一段分辨率为基准，其余缩放+补边
    work = tempfile.mkdtemp(prefix="assemble_")
    try:
        return _assemble_in(work, clips, out_path, ff, tw, th,
                            voice=voice, with_subtitles=with_subtitles,
                            crossfade=cf, bgm=bgm_path, dedup_boundary=dedup_boundary)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)   # 中间片段每次几十MB，必须清理（成败都清）


def _xfade_chain(ff, parts: list[str], durs: list[float], cf: float, out: str) -> None:
    """把各 part 用 xfade(视频)+acrossfade(音频)链成一条，镜间交叉叠化。失败抛异常由调用方回退硬切。"""
    n = len(parts)
    args = [ff, "-y", "-hide_banner"]
    for p in parts:
        args += ["-i", p]
    vfl, afl = [], []
    prev_v, prev_a = "0:v", "0:a"
    acc = durs[0]
    for i in range(1, n):
        off = max(0.0, acc - cf)
        vfl.append(f"[{prev_v}][{i}:v]xfade=transition=fade:duration={cf:.3f}:offset={off:.3f}[vx{i}]")
        afl.append(f"[{prev_a}][{i}:a]acrossfade=d={cf:.3f}[ax{i}]")
        prev_v, prev_a = f"vx{i}", f"ax{i}"
        acc += durs[i] - cf
    args += ["-filter_complex", ";".join(vfl + afl),
             "-map", f"[{prev_v}]", "-map", f"[{prev_a}]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "44100", "-ac", "2", out]
    res = _run(args, timeout=1800)
    if res.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError((res.stderr or "")[-500:])


def _add_bgm(ff, video: str, bgm: str, out: str, vol: float) -> None:
    """整片下垫一条循环的低音量 BGM(amix，时长跟视频)。失败抛异常由调用方忽略 BGM。"""
    res = _run([ff, "-y", "-hide_banner", "-i", video, "-stream_loop", "-1", "-i", bgm,
                "-filter_complex",
                f"[1:a]volume={vol:.3f}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=3[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                "-c:a", "aac", "-ar", "44100", "-ac", "2", out], timeout=900)
    if res.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError((res.stderr or "")[-500:])


def _tts_dialogue(lines: list[dict], out_mp3: str, ff: str, default_voice: str) -> bool:
    """多角色对话：逐句按各自音色 TTS，再按序拼成一条 mp3。lines=[{voice,text}]。任一句出音即 True。"""
    base = os.path.dirname(out_mp3) or "."
    parts: list[str] = []
    for idx, ln in enumerate(lines):
        txt = (ln.get("text") or "").strip()
        if not txt:
            continue
        _lv = ln.get("voice")   # dict=克隆 spec / str=edge id;dict 不能 .strip()
        v = _lv if isinstance(_lv, dict) else ((_lv or "").strip() or default_voice)
        p = os.path.join(base, f"_dlg_{idx}.mp3")
        if _tts(txt, p, v) and os.path.isfile(p) and os.path.getsize(p) > 0:
            parts.append(p)
    if not parts:
        return False
    if len(parts) == 1:
        try:
            os.replace(parts[0], out_mp3)
            return True
        except OSError:
            return False
    listf = os.path.join(base, "_dlg_list.txt")
    with open(listf, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '%s'\n" % os.path.abspath(p).replace("'", "'\\''"))
    res = _run([ff, "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", listf, "-c", "copy", out_mp3])
    if res.returncode != 0:                          # 编码不一致 → 重编码再拼
        res = _run([ff, "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", listf, "-c:a", "libmp3lame", out_mp3])
    return res.returncode == 0 and os.path.isfile(out_mp3) and os.path.getsize(out_mp3) > 0


def _assemble_in(work: str, clips: list[dict], out_path: str, ff: str,
                 tw: int, th: int, *, voice: str, with_subtitles: bool,
                 crossfade: float = 0.0, bgm: str = "", dedup_boundary: bool = False) -> dict:
    parts: list[str] = []
    durs: list[float] = []
    sub_texts: list[str] = []
    tts_used = False
    FPS = 24   # 统一帧率，xfade 才能对齐不同来源(Wan/S2V fps 不同)的片段

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
            _v = c.get("voice")   # 每镜音色:dict=克隆 spec / str=edge id;dict 不能 .strip()
            v = _v if isinstance(_v, dict) else ((_v or "").strip() or voice)
            _dlg = c.get("dialogue") or []                 # 多角色对话：逐句各自音色拼一条；否则走单段旁白
            has_narr = _tts_dialogue(_dlg, mp3, ff, v) if _dlg else (bool(narration) and _tts(narration, mp3, v))
            ad = _duration(mp3) if has_narr else 0.0
            out_dur = max(vd, ad + 0.3) if has_narr else vd      # 旁白略留尾气口
            freeze = max(0.0, out_dur - vd)
            tts_used = tts_used or has_narr

        # 统一分辨率 + 帧率 + 末帧冻结补齐 + 统一编码
        # 跨镜 i2v 续接:第 2 镜起首帧 == 上一镜尾帧 → 丢首帧消除拼接处重复帧卡顿(在缩放前 trim 并重置时间戳)。
        dedup_prefix = "trim=start_frame=1,setpts=PTS-STARTPTS," if (dedup_boundary and i >= 1) else ""
        vf = (dedup_prefix +
              f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
              f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}")
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
        durs.append(_duration(part))
        sub_texts.append(subtitle)
        parts.append(part)

    merged = os.path.join(work, "merged.mp4")
    starts: list[float] = []   # 每段在成片里的起点(秒)，用于字幕定时
    used_xfade = False
    if crossfade and crossfade > 0 and len(parts) >= 2:
        try:
            _xfade_chain(ff, parts, durs, crossfade, merged)
            used_xfade = True
            acc = 0.0
            for d in durs:                       # 叠化：每段被前一段叠掉 crossfade 秒
                starts.append(acc); acc += d - crossfade
        except Exception as e:  # noqa: BLE001 - 叠化失败不该让合成失败
            logger.warning("[assembler] crossfade 失败，回退硬切: %s", e)
            used_xfade = False
    if not used_xfade:
        lst = os.path.join(work, "list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        res = _run([ff, "-y", "-hide_banner", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", merged])
        if res.returncode != 0:
            raise RuntimeError(f"拼接失败:\n{(res.stderr or '')[-800:]}")
        acc = 0.0
        for d in durs:
            starts.append(acc); acc += d

    # 字幕定时（据每段起点）
    subs: list[tuple[float, float, str]] = []
    for i, txt in enumerate(sub_texts):
        if txt:
            subs.append((starts[i] + 0.1, starts[i] + durs[i] - 0.1, txt))

    # 背景音乐：整片下垫一条低音量 BGM（贯穿=连贯感）。失败忽略，不影响成片。
    if bgm and os.path.isfile(bgm):
        from mirage.app.core.config import settings
        bgm_out = os.path.join(work, "bgm.mp4")
        try:
            _add_bgm(ff, merged, bgm, bgm_out, float(getattr(settings, "BGM_VOLUME", 0.18) or 0.18))
            merged = bgm_out
            logger.info("[assembler] 已垫背景音乐: %s", os.path.basename(bgm))
        except Exception as e:  # noqa: BLE001
            logger.warning("[assembler] BGM 失败，跳过: %s", e)
    elif bgm:
        logger.warning("[assembler] BGM 文件不存在，跳过: %s", bgm)

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
    from mirage.app.pipeline.postprocess import maybe_postprocess
    post = maybe_postprocess(out_path)

    total = _duration(out_path)
    logger.info("[assembler] 成片完成 %s（%.1fs, %d 段, 字幕=%s, 后处理=%s）",
                out_path, total, len(parts), sub_mode, post["note"])
    return {"out": out_path, "duration": total, "scenes": len(parts),
            "tts": tts_used, "subtitles": sub_mode, "postprocess": post["note"]}
