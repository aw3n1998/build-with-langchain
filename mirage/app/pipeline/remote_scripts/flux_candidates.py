# -*- coding: utf-8 -*-
"""
FLUX 多候选出图（服务器端）—— 只加载一次模型，循环不同种子出 N 张。

为什么单独写：原 /root/autodl-tmp/generate.py 把随机种子写死成 42，
同一提示词跑 N 次得到完全一样的图；且每次调用都重载一遍 FLUX（耗时大头）。
本脚本加载一次模型，用 base_seed+i 出 N 张不同的候选，供人选图。

被 flux_select.py 自动上传到服务器后调用，逐张打印 `SAVED::<path>` 供本地解析下载。
"""

import argparse
import gc
import os
import random

import torch
from diffusers import FluxPipeline


def main():
    p = argparse.ArgumentParser(description="FLUX 多候选出图")
    p.add_argument("--prompt", required=True)
    p.add_argument("--n", type=int, default=4, help="出图张数")
    p.add_argument("--outdir", required=True)
    p.add_argument(
        "--lora",
        default="/root/autodl-tmp/output/cael_flux_lora_v1/cael_flux_lora_v1.safetensors",
        help="LoRA 权重路径；填 none 关闭",
    )
    p.add_argument("--base", default="/root/autodl-tmp/models/flux-dev", help="FLUX 底模目录")
    p.add_argument("--steps", type=int, default=28)
    p.add_argument("--guidance", type=float, default=3.5)
    p.add_argument("--width", type=int, default=768)
    p.add_argument("--height", type=int, default=1024)
    p.add_argument("--seed", type=int, default=-1, help="起始种子；-1=随机")
    p.add_argument(
        "--offload", choices=["model", "sequential"], default="model",
        help="显存策略：model=整模型搬卡(快,压线24G)；sequential=逐层搬卡(慢,占用~3G,最稳)",
    )
    a = p.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    base_seed = a.seed if a.seed >= 0 else random.randint(0, 2**31 - 1)
    print(f"[flux] base_seed={base_seed} n={a.n} {a.width}x{a.height} steps={a.steps} "
          f"guidance={a.guidance} offload={a.offload}", flush=True)

    print("[flux] loading base model...", flush=True)
    pipe = FluxPipeline.from_pretrained(a.base, torch_dtype=torch.bfloat16)

    if a.lora and a.lora.lower() != "none" and os.path.exists(a.lora):
        print(f"[flux] loading LoRA {a.lora}", flush=True)
        pipe.load_lora_weights(a.lora)
    else:
        print("[flux] LoRA 未加载（无路径或已关闭）", flush=True)

    # 省显存：offload 决定 transformer 搬卡粒度；VAE 分块降低解码峰值
    if a.offload == "sequential":
        pipe.enable_sequential_cpu_offload()  # 逐层搬卡，~3G，最稳但慢
    else:
        pipe.enable_model_cpu_offload()       # 整模型搬卡，快，但 12B transformer 压线 24G
    try:
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()
    except Exception:
        pass

    def _free():
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    for i in range(a.n):
        seed = base_seed + i
        print(f"[flux] generating {i + 1}/{a.n} seed={seed}", flush=True)
        try:
            image = pipe(
                prompt=a.prompt,
                num_inference_steps=a.steps,
                guidance_scale=a.guidance,
                width=a.width,
                height=a.height,
                generator=torch.Generator("cuda").manual_seed(seed),
            ).images[0]
        except torch.cuda.OutOfMemoryError:
            _free()
            print(f"[flux] OOM at {i + 1}/{a.n}，跳过该张；建议加 --offload sequential 重试。", flush=True)
            continue
        out = os.path.join(a.outdir, f"cand_{i + 1}_seed{seed}.png")
        image.save(out)
        print(f"SAVED::{out}", flush=True)
        _free()  # 清缓存，防多张累积碎片再次 OOM

    print("[flux] done", flush=True)


if __name__ == "__main__":
    main()
