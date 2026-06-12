# -*- coding: utf-8 -*-
"""
Part C 单测：出图 Provider 化的零回归保证。

核心断言：FluxSshImageProvider.generate(fake_gpu, ...) 对 gpu.generate_candidates 的调用
与重构前 pipeline_tools.generate_candidates 里那段内联代码**逐参一致**（n/steps/guidance/
width/height/seed/offload/lora 的「0/-1/空 → None/默认」映射不变）。再验证注册表默认是 flux。

运行：python tests/test_image_providers.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeGpu:
    """记录 generate_candidates 调用的假 GpuClient。"""
    def __init__(self):
        self.calls = []

    def generate_candidates(self, prompt, out_dir, **kw):
        self.calls.append({"prompt": prompt, "out_dir": out_dir, **kw})
        return ["/root/out/a.png", "/root/out/b.png"]


def _tool_params(*, n=0, steps=0, guidance=-1.0, width=0, height=0, seed=-1,
                 offload="", flux_lora=None):
    """复刻 pipeline_tools.generate_candidates 打包 params 的方式（保持同款 0/空→None）。"""
    return {
        "n": (n or None), "steps": (steps or None), "guidance": guidance,
        "width": (width or None), "height": (height or None),
        "seed": seed, "offload": (offload or None), "flux_lora": flux_lora,
    }


def main() -> int:
    from agent_lab.app.pipeline.image_providers import image_provider_registry
    from agent_lab.app.pipeline.image_providers.flux_ssh import FluxSshImageProvider

    # 1) 注册表：默认是 flux，空名/未知名都回退到 flux
    assert image_provider_registry.default_name == "flux", \
        f"默认出图模型应为 flux，实际 {image_provider_registry.default_name}"
    assert isinstance(image_provider_registry.get(""), FluxSshImageProvider)
    assert isinstance(image_provider_registry.get("不存在的模型"), FluxSshImageProvider)
    assert image_provider_registry.get("").transport == "ssh"
    print("[img] 注册表默认 flux / 回退 OK")

    # 2) info/schema 字段齐全（驱动前端出图参数卡）
    info = image_provider_registry.get("flux").info()
    keys = {f["key"] for f in info["fields"]}
    assert {"n", "steps", "guidance", "width", "height", "seed", "offload"} <= keys, \
        f"出图参数卡字段缺失: {keys}"
    assert info["name"] == "flux" and info["capabilities"] == ["t2i"]
    print("[img] schema 字段 OK ->", sorted(keys))

    prov = FluxSshImageProvider()

    # 3) 显式参数：逐参透传，类型正确
    gpu = FakeGpu()
    out = prov.generate(gpu, prompt="a girl, cinematic",
                        out_dir="/root/autodl-tmp/flux_candidates_out/s1",
                        params=_tool_params(n=4, steps=28, guidance=3.5, width=768,
                                            height=1024, seed=7, offload="model",
                                            flux_lora="/root/lora/cael.safetensors"))
    assert out == ["/root/out/a.png", "/root/out/b.png"], "应原样返回远程路径列表"
    c = gpu.calls[0]
    assert c["prompt"] == "a girl, cinematic"
    assert c["out_dir"] == "/root/autodl-tmp/flux_candidates_out/s1"
    assert c["n"] == 4 and c["steps"] == 28 and c["guidance"] == 3.5
    assert c["width"] == 768 and c["height"] == 1024
    assert c["seed"] == 7 and c["offload"] == "model"
    assert c["lora"] == "/root/lora/cael.safetensors"
    print("[img] 显式参数逐参透传 OK")

    # 4) 默认/空参数：0/-1/空 → None（让 GpuClient 各自取 settings 默认），与重构前一致
    gpu2 = FakeGpu()
    prov.generate(gpu2, prompt="x", out_dir="/o", params=_tool_params())  # 全默认
    d = gpu2.calls[0]
    assert d["n"] is None and d["steps"] is None, "0 张/0 步应 → None（用默认）"
    assert d["guidance"] is None, "guidance<0 应 → None（用默认）"
    assert d["width"] is None and d["height"] is None, "0 尺寸应 → None"
    assert d["seed"] == -1, "seed 默认 -1 透传"
    assert d["offload"] is None, "空 offload 应 → None"
    assert d["lora"] is None, "无 LoRA 应 → None"
    print("[img] 默认参数 0/-1/空→None 映射 OK（零回归）")

    print("\n=== ImageProvider(Part C) 单测通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
