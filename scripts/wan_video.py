# -*- coding: utf-8 -*-
"""
wan_video.py —— 拿选中的图喂 Wan2.2-TI2V-5B 出视频 → 拉回本地。

和 flux_select.py 配套：flux_select 出图选图后会写 SELECTED.txt，
本脚本默认自动读取最新的 SELECTED.txt（选中图的服务器路径），问你运镜提示词，
在 GPU 上跑 Wan2.2 图生视频（已验证的省显存配置），再把 mp4 下载到本机。

完全独立：只依赖 paramiko，不 import mirage，可单独拷走运行。

两种用法
─────────
1) 交互式（最简单，接着 flux_select 用）：
       python wan_video.py
   自动找最新选中的图，问你运镜提示词，回车=默认。

2) 命令行（可控所有参数）：
       python wan_video.py --image /root/autodl-tmp/flux_candidates_out/xxx/cand_4.png \
           --prompt "candle flickering, man writing slowly, cinematic" \
           --frames 25 --steps 25 --size 704*1280
   常用开关：
       --image    服务器上图片绝对路径（不给则读最新 SELECTED.txt）
       --local-image  本机图片路径（会先上传到服务器再用）
       --prompt   运镜/动态提示词（给了就走非交互）
       --frames   帧数（默认 25；越多越长越吃显存，24G 建议 ≤25）
       --steps    采样步数（默认 25）
       --size     分辨率（默认 704*1280 竖屏；或 1280*704 横屏）
       --name     输出文件名（默认按时间戳）

连接配置同 flux_select：环境变量 GPU_SSH_HOST/PORT/USER/KEY_PATH 覆盖。
"""

from __future__ import annotations

import argparse
import glob
import os
import posixpath
import sys
from datetime import datetime

# ── 连接默认值（环境变量可覆盖；默认指向当前 AutoDL 服务器） ──────────
DEFAULT_HOST = os.environ.get("GPU_SSH_HOST", "connect.bjb1.seetacloud.com")
DEFAULT_PORT = int(os.environ.get("GPU_SSH_PORT", "14558"))
DEFAULT_USER = os.environ.get("GPU_SSH_USER", "root")
DEFAULT_KEY = os.environ.get(
    "GPU_SSH_KEY_PATH", r"C:\Users\qwr52\.gemini\antigravity\scratch\id_ed25519"
)

# ── 服务器端路径（Wan2.2 已验证可跑通的环境） ────────────────────────
REMOTE_PY = "/root/autodl-tmp/miniconda3/bin/python"
WAN_REPO = "/root/autodl-tmp/Wan2.2"
WAN_CKPT = "/root/autodl-tmp/models/Wan-AI/Wan2.2-TI2V-5B"
REMOTE_OUT_DIR = "/root/autodl-tmp/pipeline_out"
REMOTE_IMG_DIR = "/root/autodl-tmp/cael_scenes"
REMOTE_ENV = (
    "export CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1 && "
    "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True && "
    # cu13 的 nvjitlink 库目录不在默认 loader 路径，否则 bitsandbytes 导入即报
    # libnvJitLink.so.13 缺失，连带 Wan2.2 起不来。
    "export LD_LIBRARY_PATH="
    "/root/autodl-tmp/miniconda3/lib/python3.12/site-packages/nvidia/cu13/lib"
    ":$LD_LIBRARY_PATH && "
)

# ── 本地路径 ─────────────────────────────────────────────────────────
LOCAL_VIDEO_OUT = os.environ.get(
    "WAN_LOCAL_OUT", r"C:\Users\qwr52\.gemini\antigravity\scratch\cael_video_out"
)
LOCAL_CAND_ROOT = os.environ.get(
    "FLUX_LOCAL_OUT", r"C:\Users\qwr52\.gemini\antigravity\scratch\cael_candidates"
)


def _connect(host, port, user, key_path):
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host, port=port, username=user,
        key_filename=os.path.expanduser(key_path),
        timeout=30, allow_agent=False, look_for_keys=False,
    )
    # AutoDL connect 代理会掐掉长时间无数据流的 channel（Wan 加载/采样几十秒不刷屏），
    # 心跳保活避免提前断成 exit -1。
    tr = client.get_transport()
    if tr is not None:
        tr.set_keepalive(20)
    return client


def _run_stream(client, cmd: str) -> int:
    stdin, stdout, stderr = client.exec_command(REMOTE_ENV + cmd, get_pty=True)
    for raw in iter(stdout.readline, ""):
        line = raw.rstrip("\n")
        if line:
            print(f"    {line}")
    return stdout.channel.recv_exit_status()


def _upload(client, local_path, remote_path):
    sftp = client.open_sftp()
    try:
        sftp.put(local_path, remote_path)
    finally:
        sftp.close()


def _download(client, remote_path, local_path) -> str:
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    sftp = client.open_sftp()
    try:
        sftp.get(remote_path, local_path)
    finally:
        sftp.close()
    return local_path


def _q(s: str) -> str:
    return "'" + str(s).replace("'", "'\\''") + "'"


def _ask(prompt, default=None):
    suffix = f" [{default}]" if default not in (None, "") else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val if val else (default if default is not None else "")


def _latest_selected() -> tuple[str | None, str | None]:
    """找最新的 SELECTED.txt，返回 (远程图片路径, 当时的出图提示词)。"""
    pattern = os.path.join(LOCAL_CAND_ROOT, "*", "SELECTED.txt")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not files:
        return None, None
    remote, prompt = None, None
    with open(files[0], "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("remote="):
                remote = line.split("=", 1)[1].strip()
            elif line.startswith("prompt="):
                prompt = line.split("=", 1)[1].strip()
    print(f"（读取最新选中图: {files[0]}）")
    return remote, prompt


def parse_args(argv):
    p = argparse.ArgumentParser(description="Wan2.2 图生视频")
    p.add_argument("--image", default=None, help="服务器上图片绝对路径")
    p.add_argument("--local-image", default=None, help="本机图片路径（先上传）")
    p.add_argument("--prompt", default=None, help="运镜/动态提示词")
    p.add_argument("--frames", type=int, default=25)
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--size", default="704*1280")
    p.add_argument("--name", default=None)
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--key", default=DEFAULT_KEY)
    return p.parse_args(argv)


def main(argv=None):
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdin.reconfigure(encoding="utf-8")
        except Exception:
            pass

    a = parse_args(argv or sys.argv[1:])
    interactive = a.prompt is None

    remote_img = a.image
    local_to_upload = a.local_image
    suggested_motion = None
    if remote_img is None and local_to_upload is None:
        remote_img, _ = _latest_selected()
        if remote_img is None:
            print("没找到选中的图（SELECTED.txt）。用 --image 或 --local-image 指定，或先跑 flux_select.py 选图。")
            return 1

    if interactive:
        print("=== Wan2.2 图生视频（交互模式，回车=默认） ===")
        if remote_img:
            print(f"输入图: {remote_img}")
        a.prompt = _ask(
            "运镜/动态提示词（如：candle flickering, slow push-in, cinematic）",
            suggested_motion or "subtle motion, slow cinematic push-in, natural light",
        )
        a.size = _ask("分辨率", a.size)
        a.frames = int(_ask("帧数", a.frames))
        a.steps = int(_ask("采样步数", a.steps))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = a.name or f"wan_{stamp}"
    remote_mp4 = posixpath.join(REMOTE_OUT_DIR, f"{name}.mp4")
    local_mp4 = os.path.join(LOCAL_VIDEO_OUT, f"{name}.mp4")

    print(f"\n连接 {a.user}@{a.host}:{a.port} ...")
    client = _connect(a.host, a.port, a.user, a.key)
    try:
        if local_to_upload:
            remote_img = posixpath.join(REMOTE_IMG_DIR, os.path.basename(local_to_upload))
            print(f"上传图片 → {remote_img}")
            client.exec_command(f"mkdir -p {REMOTE_IMG_DIR}")
            _upload(client, local_to_upload, remote_img)

        cmd = (
            f"cd {WAN_REPO} && {REMOTE_PY} generate.py "
            f"--task ti2v-5B --size {a.size} --ckpt_dir {WAN_CKPT} "
            f"--offload_model True --convert_model_dtype --t5_cpu "
            f"--frame_num {a.frames} --sample_steps {a.steps} "
            f"--image {_q(remote_img)} --prompt {_q(a.prompt)} "
            f"--save_file {_q(remote_mp4)}"
        )
        print("出视频中（加载模型 + 采样，约 2-4 分钟）...\n")
        code = _run_stream(client, cmd)
        if code != 0:
            print(f"\n❌ Wan2.2 出视频失败（exit {code}）。")
            return 1

        print(f"\n下载成片到本机 ...")
        _download(client, remote_mp4, local_mp4)
    finally:
        client.close()

    print(f"\n✅ 成片: {local_mp4}")
    if not a.no_open and sys.platform == "win32":
        try:
            os.startfile(os.path.dirname(local_mp4))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
