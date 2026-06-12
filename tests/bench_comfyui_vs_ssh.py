# -*- coding: utf-8 -*-
"""
出片后端基准对比：同一张参考图 + 同一句提示词，分别用「SSH 后端」和「ComfyUI 后端」各出一条 i2v，
打印各自的 **GPU 型号 / 耗时 / 成功失败 / 产物大小 / 出片过程峰值显存占用·总显存**。
用来用**数据**回答“ComfyUI 出片是不是没那么卡了”、以及“这张卡(4090/5090…)够不够、快多少”。

GPU 信息来源：ComfyUI 半走 GET /system_stats；SSH 半走远端 nvidia-smi（独立通道后台轮询取峰值）。

为什么直接构造 Provider（不走注册表）：
  ComfyUI 对用户隐形=注册表里同一个模型名只剩 ComfyUI 版（顶替了 SSH 版）。要同时跑两个后端做对比，
  必须**绕过注册表**、各自直接 new 出来：SSH 用 LtxProvider/Wan22Provider，ComfyUI 用 ComfyUIProvider。

前置条件（缺哪个就自动跳过哪一半，不报错）：
  - SSH 半：.env 配好 GPU_HOST/SSH（以及所选模型，如 GPU_LTX_MODEL）。
  - ComfyUI 半：.env 配 COMFYUI_BASE_URL，且 COMFYUI_WORKFLOW_I2V 指向能跑的 workflow。
  两半都需要参考图是**本地文件**。

用法：
  python tests/bench_comfyui_vs_ssh.py --image ref.png --model ltx
  python tests/bench_comfyui_vs_ssh.py --image ref.png --model wan2.2 --frames 81 --steps 20 --size 480*832
  python tests/bench_comfyui_vs_ssh.py --image ref.png --skip-ssh        # 只验 ComfyUI 半能不能出片
"""
from __future__ import annotations

import argparse
import os
import posixpath
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _size_of(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _common_params(args) -> dict:
    """一份“宽松”参数：含各 Provider 可能用到的不同键名，各取所需、未知键被忽略。"""
    p: dict = {"seed": args.seed}
    if args.size:
        p["size"] = args.size
    if args.frames:
        p.update({"frames": args.frames, "num_frames": args.frames, "frame_num": args.frames})
    if args.steps:
        p.update({"steps": args.steps, "sample_steps": args.steps})
    if args.fps:
        p["fps"] = args.fps
    return p


# ── GPU 型号 / 显存采集（ComfyUI 走 /system_stats；SSH 走 nvidia-smi）─────────
def _gb(bytes_val) -> float:
    try:
        return float(bytes_val) / (1024 ** 3)
    except (TypeError, ValueError):
        return 0.0


def _comfy_sysinfo(base: str) -> dict:
    """ComfyUI 那台机器的 GPU 型号 + 总显存。"""
    import httpx
    try:
        d = httpx.get(f"{base.rstrip('/')}/system_stats", timeout=10).json()
        dev = (d.get("devices") or [{}])[0]
        return {"name": dev.get("name", "?"), "vram_total": dev.get("vram_total", 0)}
    except Exception as e:  # noqa: BLE001
        return {"name": f"(取不到: {e})", "vram_total": 0}


def _ssh_sysinfo(gpu) -> dict:
    """SSH 那台机器的 GPU 型号 / 总显存 / 驱动。"""
    try:
        res = gpu.run("nvidia-smi --query-gpu=name,memory.total,driver_version "
                      "--format=csv,noheader,nounits", timeout=30)
        name, total_mb, drv = (x.strip() for x in
                               (res.stdout or "").strip().splitlines()[0].split(","))
        return {"name": name, "vram_total": float(total_mb) * 1024 ** 2, "driver": drv}
    except Exception as e:  # noqa: BLE001
        return {"name": f"(取不到: {e})", "vram_total": 0, "driver": "?"}


class _VramPoller(threading.Thread):
    """后台每隔 interval 秒采一次显存，记录出片过程中的峰值。sample()→(used_bytes, total_bytes)。"""
    def __init__(self, sample, interval: float = 1.0):
        super().__init__(daemon=True)
        self._sample, self._interval = sample, interval
        self._stop = threading.Event()
        self.peak_used = 0.0
        self.vram_total = 0.0

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                used, total = self._sample()
                if total:
                    self.vram_total = total
                if used and used > self.peak_used:
                    self.peak_used = used
            except Exception:  # noqa: BLE001 - 采样失败不影响出片
                pass
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self.is_alive():
            self.join(timeout=3)


def _comfy_sampler(base: str):
    import httpx
    b = base.rstrip("/")

    def _s():
        d = httpx.get(f"{b}/system_stats", timeout=5).json()
        dev = (d.get("devices") or [{}])[0]
        total = float(dev.get("vram_total", 0) or 0)
        free = float(dev.get("vram_free", 0) or 0)
        return (total - free, total)
    return _s


def _ssh_sampler(gpu):
    def _s():
        res = gpu.run("nvidia-smi --query-gpu=memory.used,memory.total "
                      "--format=csv,noheader,nounits", timeout=15)
        used_mb, total_mb = (float(x) for x in
                             (res.stdout or "0,0").strip().splitlines()[0].split(","))
        return (used_mb * 1024 ** 2, total_mb * 1024 ** 2)
    return _s


def _run_comfy(args) -> dict:
    """ComfyUI 后端：本地图 → ComfyUI → 本地 mp4。"""
    from agent_lab.app.core.config import settings
    from agent_lab.app.pipeline.providers.comfyui import ComfyUIProvider

    if not settings.COMFYUI_BASE_URL:
        return {"backend": "ComfyUI", "skipped": "未配置 COMFYUI_BASE_URL"}
    base = settings.COMFYUI_BASE_URL
    info = _comfy_sysinfo(base)
    out = os.path.join(args.out_dir, "bench_comfyui.mp4")
    prov = ComfyUIProvider()
    poller = _VramPoller(_comfy_sampler(base), interval=1.0)
    poller.start()
    t0 = time.perf_counter()
    try:
        prov.generate(None, image_path=args.image, prompt=args.prompt,
                      out_remote=out, params=_common_params(args))
        r = {"backend": "ComfyUI", "ok": True, "sec": time.perf_counter() - t0,
             "bytes": _size_of(out), "out": out}
    except Exception as e:  # noqa: BLE001
        r = {"backend": "ComfyUI", "ok": False, "sec": time.perf_counter() - t0,
             "err": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    finally:
        poller.stop()
    r.update(gpu_name=info["name"], vram_total=info["vram_total"] or poller.vram_total,
             peak_used=poller.peak_used)
    return r


def _run_ssh(args) -> dict:
    """SSH 后端：上传图 → 远程出片 → 下载。复刻 do_render_scene_video 的 SSH 路径精简版。"""
    from agent_lab.app.core.config import settings
    from agent_lab.app.pipeline.gpu_client import GpuConfigError, get_gpu_client
    from agent_lab.app.pipeline.providers.ltx import LtxProvider
    from agent_lab.app.pipeline.providers.wan22 import Wan22Provider

    prov = LtxProvider() if args.model == "ltx" else Wan22Provider()
    try:
        gpu = get_gpu_client()
    except GpuConfigError as e:
        return {"backend": f"SSH·{args.model}", "skipped": f"GPU 未配置: {e}"}

    info = _ssh_sysinfo(gpu)
    base = settings.GPU_OUTPUT_DIR or "/root/autodl-tmp"   # 远程产物根目录（核验确认的真实设置名）
    remote_img = posixpath.join(base, "bench", os.path.basename(args.image))
    remote_out = posixpath.join(base, "bench", "bench_ssh.mp4")
    local_out = os.path.join(args.out_dir, "bench_ssh.mp4")
    poller = _VramPoller(_ssh_sampler(gpu), interval=2.0)  # 独立 ssh 通道采样，不与出片争用
    t0 = time.perf_counter()
    try:
        gpu.upload(args.image, remote_img)
        poller.start()   # 上传完再开始采，避免把上传/空载算进峰值
        prov.generate(gpu, image_path=remote_img, prompt=args.prompt,
                      out_remote=remote_out, params=_common_params(args))
        gpu.download(remote_out, local_out)
        r = {"backend": f"SSH·{args.model}", "ok": True, "sec": time.perf_counter() - t0,
             "bytes": _size_of(local_out), "out": local_out}
    except Exception as e:  # noqa: BLE001
        r = {"backend": f"SSH·{args.model}", "ok": False, "sec": time.perf_counter() - t0,
             "err": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    finally:
        poller.stop()
    r.update(gpu_name=info["name"], vram_total=info["vram_total"] or poller.vram_total,
             peak_used=poller.peak_used, driver=info.get("driver", "?"))
    return r


def _vram_str(r: dict) -> str:
    """峰值显存/总显存，如 18.4/32G；采不到则 -。"""
    peak, total = r.get("peak_used", 0), r.get("vram_total", 0)
    if total:
        return f"{_gb(peak):.1f}/{_gb(total):.0f}G"
    return f"{_gb(peak):.1f}G" if peak else "-"


def _print(rows: list[dict]) -> None:
    print("\n" + "=" * 72)
    print(f"{'后端':<13}{'结果':<8}{'耗时':<10}{'产物':<10}{'峰值/总显存':<14}")
    print("-" * 72)
    for r in rows:
        if r.get("skipped"):
            print(f"{r['backend']:<13}{'跳过':<8}{r['skipped']}")
            continue
        ok = "✅成功" if r.get("ok") else "❌失败/卡"
        sec = f"{r['sec']:.1f}s"
        mb = f"{r.get('bytes', 0) / 1e6:.2f}MB" if r.get("ok") else "-"
        print(f"{r['backend']:<13}{ok:<8}{sec:<10}{mb:<10}{_vram_str(r):<14}")
        gpu = r.get("gpu_name") or ""
        drv = f" · 驱动 {r['driver']}" if r.get("driver") and r["driver"] != "?" else ""
        if gpu:
            print(f"   └─ GPU: {gpu}{drv}")
        if not r.get("ok") and r.get("err"):
            print(f"   └─ {r['err']}")
    print("=" * 72)
    oks = [r for r in rows if r.get("ok")]
    if len(oks) == 2:
        a, b = oks
        faster, slower = (a, b) if a["sec"] <= b["sec"] else (b, a)
        ratio = slower["sec"] / faster["sec"] if faster["sec"] else 0
        print(f"→ {faster['backend']} 比 {slower['backend']} 快 {ratio:.2f}×（两者都成功）")
    elif len(oks) == 1:
        print(f"→ 只有 {oks[0]['backend']} 成功出片（另一半失败/跳过，见上）")
    print("提示：耗时含模型加载（ComfyUI 模型常驻，连出多条第二条起更快）；"
          "峰值显存看“这张卡撑不撑得住/离 OOM 多近”，换卡(如 4090→5090)对比这一列最直接。\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="ComfyUI 出片后端 vs SSH 出片后端 基准对比")
    ap.add_argument("--image", required=True, help="本地参考图（首帧）路径")
    ap.add_argument("--prompt", default="slow cinematic push-in, subtle natural motion",
                    help="运镜/动态提示词")
    ap.add_argument("--model", choices=["ltx", "wan2.2"], default="",
                    help="SSH 半对比哪个模型；留空=用 .env 的 VIDEO_PROVIDER_DEFAULT")
    ap.add_argument("--frames", type=int, default=0, help="帧数（对齐两半；0=各用各的默认）")
    ap.add_argument("--steps", type=int, default=0, help="采样步数（0=默认）")
    ap.add_argument("--size", default="", help="分辨率 宽*高（0=默认）")
    ap.add_argument("--fps", type=int, default=0, help="帧率（0=默认）")
    ap.add_argument("--seed", type=int, default=12345, help="固定 seed 便于公平对比")
    ap.add_argument("--out-dir", default="bench_out", help="产物落地目录")
    ap.add_argument("--skip-ssh", action="store_true", help="只跑 ComfyUI 半")
    ap.add_argument("--skip-comfy", action="store_true", help="只跑 SSH 半")
    args = ap.parse_args()

    if not os.path.isfile(args.image):
        print(f"参考图不存在: {args.image}"); return 2
    if not args.model:
        from agent_lab.app.core.config import settings
        args.model = settings.VIDEO_PROVIDER_DEFAULT or "ltx"
    os.makedirs(args.out_dir, exist_ok=True)

    print(f"基准对比：image={args.image} model(SSH)={args.model} "
          f"frames={args.frames or '默认'} steps={args.steps or '默认'} size={args.size or '默认'}")
    rows = []
    if not args.skip_comfy:
        print("\n[1/2] 跑 ComfyUI 后端…")
        rows.append(_run_comfy(args))
    if not args.skip_ssh:
        print("[2/2] 跑 SSH 后端…")
        rows.append(_run_ssh(args))
    _print(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
