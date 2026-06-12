# -*- coding: utf-8 -*-
"""
Mock-GPU 端到端测试：不连 GPU/SSH，把「建项目→拆分镜→出图→选图→出片(含尾帧接续)→合成整集」
全链路自动跑一遍。每次改动后运行本脚本（约 30 秒），即可知道有没有改坏主流程。

用法（仓库根目录）:  python tests/e2e_mock.py
依赖：本机 ffmpeg（imageio-ffmpeg 自带）；TTS 被替换为离线桩，不需要联网。
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 1x1 透明 PNG（候选图占位，只需"文件存在且可读"）
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63fcffff3f0300050201f7a8d5ad00"
    "00000049454e44ae426082"
)


def make_mp4(path: str, seconds: float = 1.0, color: str = "red") -> str:
    """用 ffmpeg 色块源造一段小视频（代替 GPU 出片产物）。"""
    from agent_lab.app.pipeline.assembler import _ffmpeg, _run
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    res = _run([_ffmpeg(), "-y", "-hide_banner",
                "-f", "lavfi", "-i", f"color=c={color}:s=320x576:r=24:d={seconds}",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", path])
    assert res.returncode == 0, f"造测试视频失败: {res.stderr[-300:]}"
    return path


class FakeGpu:
    """替身 GPU 客户端：不碰网络。download 时就地伪造产物。"""

    def __init__(self):
        self.uploads, self.downloads = [], []

    def exists(self, remote):            # 参考图就绪检查 → 永远在
        return True

    def upload(self, local, remote, **kw):
        self.uploads.append((local, remote))

    def download(self, remote, local, **kw):
        self.downloads.append((remote, local))
        if remote.endswith(".png"):
            os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
            with open(local, "wb") as f:
                f.write(_PNG)
        else:  # mp4：色块视频（颜色随段号变化，肉眼可辨拼接）
            color = ["red", "green", "blue", "yellow"][len(self.downloads) % 4]
            make_mp4(local, seconds=1.0, color=color)
        return local

    def generate_candidates(self, prompt, out_remote_dir, **kw):
        n = kw.get("n") or 2
        return [f"{out_remote_dir}/cand_{i}_seed100{i}.png" for i in range(1, n + 1)]


class FakeProvider:
    """替身视频模型：generate 是 no-op（真正产物由 FakeGpu.download 伪造），但记录每段收到的 prompt。"""
    name = "mock"
    display_name = "MockVideo"
    capabilities = {"i2v"}

    def __init__(self):
        self.prompts = []   # 每次 generate 收到的 prompt，按段顺序

    def param_schema(self):
        return [{"key": "size", "label": "size", "type": "text", "default": "320*576"}]

    def default_params(self):
        return {f["key"]: f.get("default") for f in self.param_schema()}

    def generate(self, gpu, *, image_path, prompt, out_remote, params):
        self.prompts.append(prompt)
        return None


def main() -> int:
    ws = tempfile.mkdtemp(prefix="e2e_ws_")
    print(f"[e2e] 临时工作目录: {ws}")

    import importlib
    from agent_lab.app.pipeline import runtime
    # 包 __init__ 导出了同名列表 pipeline_tools，会遮蔽子模块名，必须用 importlib 取真模块
    pt = importlib.import_module("agent_lab.app.pipeline.pipeline_tools")
    from agent_lab.app.pipeline.providers import video_provider_registry
    from agent_lab.app.pipeline import assembler

    runtime.set_workspace(ws)
    fake = FakeGpu()
    fake_provider = FakeProvider()
    pt.get_gpu_client = lambda: fake                      # 替换 GPU 客户端
    video_provider_registry.register(fake_provider)       # 注册替身模型
    assembler._tts = lambda *a, **k: False                # TTS 离线桩（无旁白音轨）

    # 1) 建项目 + 2 个分镜
    msg = pt.create_video_project.func(title="E2E 测试集", novel_text="...")
    pid = msg.split("[")[1].split("]")[0]
    print(f"[e2e] 项目 {pid}")
    s_msgs = [pt.add_scene.func(project_id=pid, scene_number=i, title=f"镜{i}",
                                narration=f"第{i}镜旁白", image_prompt=f"scene {i} prompt")
              for i in (1, 2)]
    sids = [m.split("[")[1].split("]")[0] for m in s_msgs]

    # 2) 出图（FakeGpu 出 2 张/镜）→ 断言候选落库 + 本地 png + IMGFILE 标记
    for sid in sids:
        out = pt.generate_candidates.func(scene_id=sid)
        assert "IMGFILE::" in out, f"出图无 IMGFILE 标记:\n{out}"
    from agent_lab.app.pipeline.store import get_store
    store = get_store()
    for sid in sids:
        assets = store.list_assets(sid, "IMAGE")
        assert len(assets) == 2, f"分镜 {sid} 候选数 {len(assets)} != 2"
        local = os.path.join(runtime.candidates_dir(sid), "cand_1_seed1001.png")
        assert os.path.exists(local), "本地候选 png 未落盘"
    print("[e2e] 出图 OK（候选登记 + 本地落盘 + 标记）")

    # 3) 选图
    for sid in sids:
        a = store.list_assets(sid, "IMAGE")[0]
        out = pt.select_candidate.func(scene_id=sid, asset_id=a["id"])
        assert "PENDING_VIDEO_GEN" in out, f"选图未推进状态:\n{out}"
    print("[e2e] 选图 OK")

    # 4) 出片：镜1 单段；镜2 尾帧接续 2 段（覆盖抽帧/回传/拼接路径）
    out1 = pt.do_render_scene_video(sids[0], "", "mock", {})
    assert "VIDFILE::" in out1 and "COMPLETED" in out1, f"单段出片失败:\n{out1}"
    out2 = pt.do_render_scene_video(sids[1], "", "mock", {"segments": 2})
    assert "VIDFILE::" in out2 and "接续 2 段" in out2, f"接续出片失败:\n{out2}"
    final2 = os.path.join(runtime.video_dir(), f"02_{sids[1]}.mp4")
    assert os.path.exists(final2), "接续成片未落盘"
    assert abs(assembler._duration(final2) - 2.0) < 0.4, "接续成片时长应≈2s（2×1s）"
    print("[e2e] 出片 OK（单段 + 尾帧接续拼接，时长校验通过）")

    # 4b) 每段独立提示词：2 段接续下发 ["AAA","BBB"]，断言两段分别收到（Part A 核心）
    fake_provider.prompts.clear()
    out2b = pt.do_render_scene_video(
        sids[1], "", "mock", {"segments": 2, "motion_prompts": ["AAA-seg1", "BBB-seg2"]})
    assert "VIDFILE::" in out2b, f"分段提示词出片失败:\n{out2b}"
    assert fake_provider.prompts == ["AAA-seg1", "BBB-seg2"], \
        f"每段提示词未逐段下发，实际收到: {fake_provider.prompts}"
    # 回退路径：不给 motion_prompts 时，两段共用统一 prompt（向后兼容）
    fake_provider.prompts.clear()
    pt.do_render_scene_video(sids[1], "运镜统一句", "mock", {"segments": 2})
    assert fake_provider.prompts == ["运镜统一句", "运镜统一句"], \
        f"无分段提示词时应全段共用，实际: {fake_provider.prompts}"
    print("[e2e] 每段独立提示词 OK（逐段下发 + 缺省回退）")

    # 4c) 看效果再「追加一段」：在已生成成片末尾续接，时长应增长（可反复、段数不写死）
    final1 = os.path.join(runtime.video_dir(), f"01_{sids[0]}.mp4")
    assert os.path.exists(final1), "镜1 单段成片应已存在"
    dur0 = assembler._duration(final1)
    fake_provider.prompts.clear()
    outa = pt.append_scene_segment(sids[0], "追加段提示词", "mock", {}, count=1)
    assert "VIDFILE::" in outa and "追加 1 段" in outa, f"追加一段失败:\n{outa}"
    dur1 = assembler._duration(final1)
    assert dur1 > dur0 + 0.6, f"追加后成片应变长（{dur0:.1f}→{dur1:.1f}s）"
    assert fake_provider.prompts == ["追加段提示词"], f"追加段未用指定提示词: {fake_provider.prompts}"
    pt.append_scene_segment(sids[0], "", "mock", {}, count=2)   # 反复追加 + 一次多段
    dur2 = assembler._duration(final1)
    assert dur2 > dur1 + 1.2, f"再追加 2 段应继续变长（{dur1:.1f}→{dur2:.1f}s）"
    # 守卫：对「还没出过视频」的分镜追加应被拒绝
    s3 = pt.add_scene.func(project_id=pid, scene_number=3, title="镜3", narration="", image_prompt="p3")
    sid3 = s3.split("[")[1].split("]")[0]
    novid = pt.append_scene_segment(sid3, "", "mock", {})
    assert "还没有已生成的视频" in novid, f"对无成片分镜追加应被拒绝: {novid}"
    print(f"[e2e] 追加一段 OK（{dur0:.1f}→{dur1:.1f}→{dur2:.1f}s，可反复、段数自由、无片守卫）")

    # 4d) 字幕独立于旁白：给镜1设一个与旁白不同的字幕，合成走带独立字幕的路径（烧字幕不崩）
    store.update_scene_prompts(sids[0], subtitle="独立标题字幕")
    assert store.get_scene(sids[0])["subtitle"] == "独立标题字幕"
    assert store.get_scene(sids[0])["narration"], "旁白应仍在（字幕不覆盖旁白）"
    print("[e2e] 字幕≠旁白 字段 OK")

    # 4e) 对口型(S2V)路由：lipsync=on → do_render 走 S2V 路径（无端点优雅降级 + 有端点拿到音频）
    # 先确保「无 S2V 端点」状态——本测试不依赖 .env 是否配了 COMFYUI_BASE_URL
    video_provider_registry._providers.pop("comfyui-s2v", None)
    store.set_scene_lipsync(sids[1], True)
    assert store.get_scene(sids[1])["lipsync"] == 1
    out_no = pt.do_render_scene_video(sids[1], "", "mock", {"lipsync": True})
    assert "还没就绪" in out_no or "S2V" in out_no, f"无 S2V 端点应优雅提示: {out_no}"

    class FakeS2V(FakeProvider):           # 假 S2V：记录拿到的音频，产出占位 mp4
        name = "comfyui-s2v"; capabilities = {"s2v"}; hidden = True
        def __init__(self):
            super().__init__(); self.audio = None
        def generate(self, gpu, *, image_path, prompt, out_remote, params):
            self.audio = params.get("audio_path"); self.prompts.append(prompt)
            make_mp4(out_remote, seconds=1.0, color="purple"); return None

    fake_s2v = FakeS2V()
    video_provider_registry.register(fake_s2v)
    orig_tts = assembler._tts
    assembler._tts = lambda text, out, voice=None: (open(out, "wb").write(b"x"), True)[1]
    try:
        out_ls = pt.do_render_scene_video(sids[1], "", "mock", {"lipsync": True})
    finally:
        assembler._tts = orig_tts          # 还原，后续合成仍用无 TTS 桩
    assert "VIDFILE::" in out_ls and "对口型" in out_ls, f"S2V 出片失败: {out_ls}"
    assert fake_s2v.audio and os.path.exists(fake_s2v.audio), "S2V 应收到 TTS 音频路径"
    # 关掉镜2的 lipsync，免得后面整集合成被这一镜影响
    store.set_scene_lipsync(sids[1], False)
    print("[e2e] 对口型(S2V) 路由 OK（无端点降级 + 有端点走 S2V 拿到音频）")

    # 5) 合成整集（拼接 + 字幕；TTS 桩=无旁白音）
    out = pt.assemble_episode.func(project_id=pid)
    assert "成片完成" in out and "VIDFILE::episode::" in out, f"合成失败:\n{out}"
    ep = os.path.join(runtime.video_dir(), f"episode_{pid}.mp4")
    assert os.path.exists(ep) and assembler._duration(ep) > 2.5, "整集时长异常"
    print(f"[e2e] 合成 OK（整集 {assembler._duration(ep):.1f}s）")

    # 6) Agent 注册完整性：任何 agent 模块语法/导入错误都会让它从注册表消失（曾真实发生）
    from agent_lab.app.services.agent_registry import agent_registry
    agent_registry.discover_agents() if hasattr(agent_registry, "discover_agents") else None
    registered = set(agent_registry.get_valid_agents())
    for must in ("video", "general", "code", "file", "shell", "batch"):
        assert must in registered, f"agent '{must}' 未注册（模块导入失败？）：{registered}"
    print(f"[e2e] agent 注册 OK（{sorted(registered)}）")

    # 7) 消息清洗（防 400）回归
    from agent_lab.app.services.msg_utils import sanitize_messages
    from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
    bad = [HumanMessage("hi"),
           AIMessage(content="", tool_calls=[{"id": "x", "name": "t", "args": {}}])]
    assert len(sanitize_messages(bad)) == 1, "sanitize 未剔除悬空 tool_calls"
    print("[e2e] sanitize OK")

    print("\n=== E2E 全链路通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
