# -*- coding: utf-8 -*-
"""
flux_select.py —— 输入提示词 → 远程 FLUX 出 N 张候选 → 拉回本地 → 你选图。

这是一个**完全独立**的脚本：只依赖 paramiko（pip install paramiko），不 import mirage，
可以单独拷到任何机器跑；也可以放在本仓库里和框架共存。

两种用法
─────────
1) 交互式（最简单）：
       python flux_select.py
   依次问你：提示词 / 张数 / 步数 / guidance / 尺寸 / 起始种子（回车用默认）。

2) 命令行（可脚本化、可控所有参数）：
       python flux_select.py --prompt "ch4r_cael standing in the rain, cinematic" \
           --n 4 --steps 28 --guidance 3.5 --width 768 --height 1024 --seed -1
   常用开关：
       --prompt    提示词（给了就走非交互模式）
       --n         出图张数（默认 4）
       --steps     采样步数（默认 28，越大越精细越慢）
       --guidance  提示词贴合度（默认 3.5，越大越"听话"但可能失真）
       --width/--height  尺寸（默认 768x1024 竖屏 9:16）
       --seed      起始种子（默认 -1=随机；N 张用 seed, seed+1, ...）
       --lora      LoRA 路径（默认 cael；填 none 关闭角色 LoRA）
       --style     在提示词前自动加一段统一电影风格（保证和已有分镜同款质感）
       --no-open   出图后不自动打开本地文件夹

连接配置（环境变量覆盖，默认指向你当前的 AutoDL 服务器）
       GPU_SSH_HOST / GPU_SSH_PORT / GPU_SSH_USER / GPU_SSH_KEY_PATH
   注意：AutoDL 重启后 host/port 可能变，变了就设这几个环境变量或改下面 DEFAULT_*。
"""

from __future__ import annotations

import argparse
import os
import posixpath
import sys
from datetime import datetime

# ── 连接默认值（可被同名环境变量覆盖） ───────────────────────────────
DEFAULT_HOST = os.environ.get("GPU_SSH_HOST", "connect.bjb1.seetacloud.com")
DEFAULT_PORT = int(os.environ.get("GPU_SSH_PORT", "14558"))
DEFAULT_USER = os.environ.get("GPU_SSH_USER", "root")
DEFAULT_KEY = os.environ.get(
    "GPU_SSH_KEY_PATH", r"C:\Users\qwr52\.gemini\antigravity\scratch\id_ed25519"
)

# ── 服务器端固定路径 ─────────────────────────────────────────────────
REMOTE_PY = "/root/autodl-tmp/miniconda3/bin/python"
REMOTE_SCRIPT = "/root/autodl-tmp/flux_candidates.py"
REMOTE_OUT_ROOT = "/root/autodl-tmp/flux_candidates_out"
REMOTE_ENV = (
    "export CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1 && "
    "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True && "
    # cu13 的 nvjitlink 库目录不在默认 loader 路径，否则 bitsandbytes 导入即报缺库。
    "export LD_LIBRARY_PATH="
    "/root/autodl-tmp/miniconda3/lib/python3.12/site-packages/nvidia/cu13/lib"
    ":$LD_LIBRARY_PATH && "
)

# ── 本地落地目录 ─────────────────────────────────────────────────────
LOCAL_OUT_ROOT = os.environ.get(
    "FLUX_LOCAL_OUT", r"C:\Users\qwr52\.gemini\antigravity\scratch\cael_candidates"
)

# ── 统一电影风格（--style 时前置；和你已有分镜同款） ──────────────────
CORE_STYLE = (
    "Cinematic film still, dark medieval fantasy, cold desaturated palette, "
    "moody low-key lighting, photorealistic, 35mm film grain, 4K, 9:16. "
)

# 服务器出图脚本（随仓库携带，首次运行自动上传，无需手动部署）。
# 已随 gpu_client 迁入解耦核心 comfy_core/remote_scripts/（单一真源）。
_REMOTE_SOURCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "comfy_core", "remote_scripts", "flux_candidates.py",
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
    # AutoDL connect 代理会掐掉长时间无数据流的 channel，心跳保活避免提前断成 exit -1。
    tr = client.get_transport()
    if tr is not None:
        tr.set_keepalive(20)
    return client


def _upload_remote_script(client) -> None:
    """把服务器出图脚本推上去（幂等）。本地源缺失时，只要服务器已有就跳过（便于单独拷贝运行）。"""
    sftp = client.open_sftp()
    try:
        if os.path.exists(_REMOTE_SOURCE):
            sftp.put(_REMOTE_SOURCE, REMOTE_SCRIPT)
            return
        try:
            sftp.stat(REMOTE_SCRIPT)  # 服务器已有，直接用
        except IOError:
            raise FileNotFoundError(
                f"本地缺出图脚本 {_REMOTE_SOURCE}，服务器也没有 {REMOTE_SCRIPT}。"
            )
    finally:
        sftp.close()


def _run_stream(client, cmd: str) -> tuple[int, list[str]]:
    """执行远程命令并实时打印输出，收集 SAVED::<path> 行。"""
    stdin, stdout, stderr = client.exec_command(REMOTE_ENV + cmd, get_pty=True)
    saved: list[str] = []
    for raw in iter(stdout.readline, ""):
        line = raw.rstrip("\n")
        if not line:
            continue
        if line.startswith("SAVED::"):
            path = line.split("::", 1)[1].strip()
            saved.append(path)
            print(f"    ✓ 出图: {posixpath.basename(path)}")
        else:
            print(f"    {line}")
    code = stdout.channel.recv_exit_status()
    return code, saved


def _download(client, remote_paths, local_dir) -> list[str]:
    os.makedirs(local_dir, exist_ok=True)
    sftp = client.open_sftp()
    local_paths = []
    try:
        for rp in remote_paths:
            lp = os.path.join(local_dir, posixpath.basename(rp))
            sftp.get(rp, lp)
            local_paths.append(lp)
    finally:
        sftp.close()
    return local_paths


def _ask(prompt, default=None):
    suffix = f" [{default}]" if default not in (None, "") else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val if val else (default if default is not None else "")


def parse_args(argv):
    p = argparse.ArgumentParser(description="FLUX 出候选图并选图")
    p.add_argument("--prompt", default=None)
    p.add_argument("--n", type=int, default=4)
    p.add_argument("--steps", type=int, default=28)
    p.add_argument("--guidance", type=float, default=3.5)
    p.add_argument("--width", type=int, default=768)
    p.add_argument("--height", type=int, default=1024)
    p.add_argument("--seed", type=int, default=-1)
    p.add_argument("--offload", choices=["model", "sequential"], default="model",
                   help="显存策略：model=快(默认)；sequential=慢但最稳，OOM 时用")
    p.add_argument("--lora", default="default")  # default→用 cael；none→关闭；或自定义路径
    p.add_argument("--style", action="store_true", help="提示词前置统一电影风格")
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--key", default=DEFAULT_KEY)
    return p.parse_args(argv)


def main(argv=None):
    if sys.platform == "win32":  # 保证中文提示/输入在任意终端编码下不乱码
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdin.reconfigure(encoding="utf-8")
        except Exception:
            pass

    a = parse_args(argv or sys.argv[1:])

    interactive = a.prompt is None
    if interactive:
        print("=== FLUX 出候选图（交互模式，直接回车=默认） ===")
        a.prompt = _ask("提示词（角色镜头记得带 ch4r_cael）")
        if not a.prompt:
            print("未输入提示词，退出。")
            return 1
        a.n = int(_ask("出几张", a.n))
        a.steps = int(_ask("采样步数", a.steps))
        a.guidance = float(_ask("guidance", a.guidance))
        size = _ask("尺寸 WxH", f"{a.width}x{a.height}")
        if "x" in size:
            a.width, a.height = (int(v) for v in size.lower().split("x"))
        a.seed = int(_ask("起始种子(-1随机)", a.seed))
        if _ask("加统一电影风格? y/n", "y").lower().startswith("y"):
            a.style = True

    prompt = (CORE_STYLE + a.prompt) if a.style else a.prompt
    lora_arg = {
        "default": "/root/autodl-tmp/output/cael_flux_lora_v1/cael_flux_lora_v1.safetensors",
        "none": "none",
    }.get(a.lora, a.lora)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    remote_out = posixpath.join(REMOTE_OUT_ROOT, stamp)
    local_out = os.path.join(LOCAL_OUT_ROOT, stamp)

    print(f"\n连接 {a.user}@{a.host}:{a.port} ...")
    client = _connect(a.host, a.port, a.user, a.key)
    try:
        _upload_remote_script(client)
        cmd = (
            f"{REMOTE_PY} {REMOTE_SCRIPT} "
            f"--prompt {_q(prompt)} --n {a.n} --outdir {_q(remote_out)} "
            f"--lora {_q(lora_arg)} --steps {a.steps} --guidance {a.guidance} "
            f"--width {a.width} --height {a.height} --seed {a.seed} --offload {a.offload}"
        )
        print(f"出图中（首次加载 FLUX 约 1-2 分钟，之后每张 ~10s）...\n")
        code, saved = _run_stream(client, cmd)
        if code != 0 or not saved:
            print(f"\n❌ 出图失败（exit {code}）。")
            return 1

        print(f"\n下载 {len(saved)} 张到本机 ...")
        local_paths = _download(client, saved, local_out)
    finally:
        client.close()

    print(f"\n=== 候选图已就绪: {local_out} ===")
    for i, lp in enumerate(local_paths, 1):
        print(f"  [{i}] {os.path.basename(lp)}")

    if not a.no_open and sys.platform == "win32":
        try:
            os.startfile(local_out)  # 打开资源管理器看图
        except Exception:
            pass

    # ── 选图（HITL） ──
    while True:
        sel = input(f"\n选哪张? 1-{len(local_paths)}（0=都不要）: ").strip()
        if sel == "0":
            print("未选图。重跑可换种子/提示词再试。")
            return 0
        if sel.isdigit() and 1 <= int(sel) <= len(local_paths):
            chosen_local = local_paths[int(sel) - 1]
            chosen_remote = saved[int(sel) - 1]
            break
        print("输入无效，再来一次。")

    # 记录选择，给视频环节用
    record = os.path.join(local_out, "SELECTED.txt")
    with open(record, "w", encoding="utf-8") as f:
        f.write(f"local={chosen_local}\nremote={chosen_remote}\nprompt={prompt}\n")
    print(f"\n✅ 已选: {os.path.basename(chosen_local)}")
    print(f"   本地: {chosen_local}")
    print(f"   服务器: {chosen_remote}")
    print(f"   （已写入 {record}，下一步可拿这张图喂 Wan2.2 出视频）")
    return 0


def _q(s: str) -> str:
    """给远程命令行参数加单引号转义（服务器是 Linux/bash）。"""
    return "'" + str(s).replace("'", "'\\''") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
