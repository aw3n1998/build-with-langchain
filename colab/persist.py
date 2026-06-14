"""
Colab 持久化 + 后台服务辅助。

三个核心问题的解法都在这里:
- 模型/产物**重下** → link_models: 把 ComfyUI/models/<sub> move-safe 软链到 Drive
  （已有真实文件先挪到 Drive 再软链，**绝不 rmtree 删数据**；顺序无关，先下后软链也安全）。
- 服务**一停 cell 就被杀** → start_bg: start_new_session=True 让服务脱离内核进程组，
  中断 cell / KeyboardInterrupt 不再波及它。
- 起服务要**等就绪** → wait_http / running。

用法（notebook 里）:
    import sys; sys.path.insert(0, '/content/mirage/colab')
    import persist
    persist.link_models('/content/drive/MyDrive/mirage_models', '/content/ComfyUI/models',
                        ['unet','clip','vae','audio_encoders','loras','pulid','text_encoders'])
    persist.start_bg(['python','/content/ComfyUI/main.py','--listen','127.0.0.1','--port','8188'],
                     '/content/comfyui.log')
    persist.wait_http('http://127.0.0.1:8188/')
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.request


def link_models(cache: str, comfy_models: str, subs: list[str]) -> str:
    """把 comfy_models/<sub> 逐个 move-safe 软链到 cache/<sub>（Drive）。

    - 已是软链 → 跳过。
    - 是真实目录（如下载早于软链）→ 把里面文件**挪到 Drive**（不覆盖已存在的），删空壳，再软链。**不删数据。**
    - 是其它文件 → 删该文件项后软链。
    """
    os.makedirs(comfy_models, exist_ok=True)
    for d in subs:
        src = os.path.join(cache, d)
        os.makedirs(src, exist_ok=True)
        tgt = os.path.join(comfy_models, d)
        if os.path.islink(tgt):
            continue
        if os.path.isdir(tgt):
            for fn in os.listdir(tgt):
                s = os.path.join(tgt, fn)
                dst = os.path.join(src, fn)
                if os.path.isfile(s) and not os.path.exists(dst):
                    shutil.move(s, dst)
            shutil.rmtree(tgt)
        elif os.path.exists(tgt):
            os.remove(tgt)
        os.symlink(src, tgt)
    return comfy_models


def link_dir(drive_path: str, local_path: str) -> str:
    """通用 move-safe 软链:把 local_path 软链到 drive_path（已有真实内容先挪过去）。"""
    os.makedirs(drive_path, exist_ok=True)
    if os.path.islink(local_path):
        return local_path
    if os.path.isdir(local_path):
        for fn in os.listdir(local_path):
            s = os.path.join(local_path, fn)
            dst = os.path.join(drive_path, fn)
            if not os.path.exists(dst):
                shutil.move(s, dst)
        shutil.rmtree(local_path)
    elif os.path.exists(local_path):
        os.remove(local_path)
    os.symlink(drive_path, local_path)
    return local_path


def running(url: str) -> bool:
    """服务是否已在跑（HTTP 可达）。"""
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def start_bg(cmd: list[str], log_path: str, cwd: str | None = None):
    """后台起服务，**start_new_session=True 脱离内核进程组**——停 cell / 中断不会杀它。返回 Popen。"""
    return subprocess.Popen(
        cmd, cwd=cwd,
        stdout=open(log_path, "w"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def wait_http(url: str, timeout: int = 120, interval: int = 3) -> bool:
    """轮询直到 url 可达或超时；返回是否就绪。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if running(url):
            return True
        time.sleep(interval)
    return running(url)


def ensure_service(name: str, cmd: list[str], url: str, log_path: str,
                   cwd: str | None = None, timeout: int = 120) -> bool:
    """若 url 不可达就 detached 起 cmd 并等就绪；已在跑则跳过。打印结果，返回是否就绪。"""
    if running(url):
        print(f"{name}: ✓ 已在运行")
        return True
    print(f"{name}: 启动中…（首启较慢，请等本格跑完）")
    start_bg(cmd, log_path, cwd=cwd)
    ok = wait_http(url, timeout=timeout)
    if ok:
        print(f"{name}: ✓ ready")
    else:
        tail = ""
        try:
            tail = open(log_path).read()[-2000:]
        except Exception:  # noqa: BLE001
            pass
        print(f"{name}: ✗ 未就绪，看 {log_path}\n{tail}")
    return ok
