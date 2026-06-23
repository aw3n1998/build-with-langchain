#!/usr/bin/env python
"""
LTX-Video 图生视频远程推理脚本（在 GPU 服务器上执行；本框架自动上传，幂等）。

依赖（服务器一次性安装）：
  pip install "diffusers>=0.32" transformers accelerate imageio imageio-ffmpeg sentencepiece

约束：
  - 分辨率 width/height 需为 32 的倍数；
  - num_frames 建议 8 的倍数 +1（如 121 / 161）。
成功时在 stdout 打印一行  SAVED::<out_path>  供框架解析。
"""

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="LTX diffusers 目录（或 HF id）")
    ap.add_argument("--text_encoder", default="",
                    help="可选：外部 T5-XXL text_encoder 目录（复用 FLUX 的 text_encoder_2 可省 ~19G 盘）")
    ap.add_argument("--image", required=True, help="参考图绝对路径")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True, help="输出 mp4 绝对路径")
    ap.add_argument("--width", type=int, default=704)
    ap.add_argument("--height", type=int, default=1280)
    ap.add_argument("--num_frames", type=int, default=121)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--guidance", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--negative_prompt", default="worst quality, blurry, distorted, jittery, low detail, soft focus")
    # LTX 解码参数：默认 0=不覆盖(用 pipeline 自带值，已验证出干净片)。这个模型版本对它极敏感，给错会发黑/出噪，故不默认开。
    ap.add_argument("--decode_timestep", type=float, default=0.0)
    ap.add_argument("--decode_noise_scale", type=float, default=0.0)
    # 裁掉尾部退化帧：LTX 初代尾部约 1 个时间块(≈8帧)会糊/噪。多生成这么多帧再丢尾，保住时长+末帧干净。
    ap.add_argument("--trim_tail", type=int, default=8)
    args = ap.parse_args()

    import os
    # 抗显存碎片化：LTX 在高分辨率下接近吃满整卡，碎片化易导致"明明有空间却 OOM"。
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import torch
    from diffusers import LTXImageToVideoPipeline
    from diffusers.utils import export_to_video, load_image

    # 分辨率/帧数纠偏到约束上，避免管线报错
    w = (args.width // 32) * 32
    h = (args.height // 32) * 32
    n = ((args.num_frames - 1) // 8) * 8 + 1

    # 复用外部 T5（如 FLUX 的 text_encoder_2）：LTX 与 FLUX 都用 google/t5-v1.1-xxl，
    # 权重通用，省去 LTX 自带 text_encoder 的 ~19G 下载。
    if args.text_encoder:
        from transformers import T5EncoderModel
        te = T5EncoderModel.from_pretrained(args.text_encoder, torch_dtype=torch.bfloat16)
        pipe = LTXImageToVideoPipeline.from_pretrained(
            args.model, text_encoder=te, torch_dtype=torch.bfloat16)
    else:
        pipe = LTXImageToVideoPipeline.from_pretrained(args.model, torch_dtype=torch.bfloat16)
    # 显存吃紧时分块/卸载，单卡 24G 更稳（已验证可出干净片；画质优化等研究结论再调）
    pipe.enable_model_cpu_offload()
    try:
        pipe.vae.enable_tiling()
    except Exception:
        pass

    gen = None
    if args.seed is not None and args.seed >= 0:
        gen = torch.Generator(device="cuda").manual_seed(args.seed)

    image = load_image(args.image).resize((w, h))

    # 解码画质参数(decode_timestep/decode_noise_scale)对这个 LTX 版本极敏感，给错值会整片发黑/出噪，
    # 故只在显式传入(>0)时才覆盖，默认沿用 pipeline 自带值(已验证可出干净片)。
    extra = {}
    if args.decode_timestep > 0:
        extra["decode_timestep"] = args.decode_timestep
    if args.decode_noise_scale > 0:
        extra["decode_noise_scale"] = args.decode_noise_scale
    # LTX 尾部几帧会退化成糊/噪(初代 2B + 原始 VAE 的已知短板)。
    # 多生成 trim 帧、导出时丢掉尾部坏帧 → 末帧干净、时长不变，也避免坏帧沿"尾帧接续"传染。
    trim = max(0, int(args.trim_tail))
    n_gen = n + trim                      # n 是 8k+1，n_gen=n+8 仍是 8m+1，合法
    result = pipe(
        image=image,
        prompt=args.prompt,
        negative_prompt=args.negative_prompt,
        width=w,
        height=h,
        num_frames=n_gen,
        num_inference_steps=args.steps,
        guidance_scale=args.guidance,
        generator=gen,
        **extra,
    )
    frames = result.frames[0]
    if trim and len(frames) > n:
        frames = frames[:n]               # 丢掉尾部退化帧，保留干净的前 n 帧

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    export_to_video(frames, args.out, fps=args.fps)
    print(f"SAVED::{args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
