"""
流水线工具集 —— 把状态机（store）+ 远程 GPU（gpu_client）封装成 LangChain @tool，
供 video_agent（及 SkillRegistry 语义检索）按需调用。

设计原则（对齐本框架现有 tools.py）：
  - 每个工具返回**人类可读的字符串**（带 emoji 前缀），便于 Agent 直接转述给用户。
  - 工具只暴露编排动作，不暴露 SSH 凭据；凭据全部封装在 gpu_client 里走 .env。
  - 出图（FLUX）→ 选图（HITL）→ 图生视频（Wan2.2）三段对应状态机流转。
"""

from __future__ import annotations

import json
import os
import posixpath

from langchain_core.tools import tool

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline.runtime import (
    candidates_dir,
    get_workspace,
    is_within_known_root,
    model_config,
    set_model_config,
    video_dir,
)
from mirage.app.pipeline.store import SceneState, get_store
from mirage.app.pipeline.gpu_client import (
    GpuConfigError,
    GpuRunError,
    get_gpu_client,
)
from mirage.app.pipeline.providers import video_provider_registry
from mirage.app.pipeline.image_providers import image_provider_registry

logger = get_logger("pipeline.tools")


# ── 本地素材：读小说/剧本所在文件夹 ───────────────────────────────
def _resolve_in_workspace(path: str) -> str | None:
    """把用户给的路径解析成绝对路径，并校验必须落在工作目录（已知根）内。"""
    ws = get_workspace()
    abs_path = path if os.path.isabs(path) else os.path.join(ws, path)
    abs_path = os.path.abspath(abs_path)
    return abs_path if is_within_known_root(abs_path) else None


def _is_secret(path: str) -> bool:
    """敏感文件防护：禁止读取 .env / 私钥 / 凭据类文件。"""
    try:
        from mirage.app.services.tools import is_secret_path
        return is_secret_path(path)
    except Exception:
        return False


def _read_text_smart(abs_path: str) -> str:
    """智能解码文本：UTF-8(含BOM) → GB18030(GBK/GB2312) → UTF-16 → 兜底替换。

    中文小说常见 GBK/ANSI 编码，写死 UTF-8 会整篇乱码，故多编码回退。
    """
    with open(abs_path, "rb") as f:
        raw = f.read()
    # 可选：有 chardet 就用它先猜
    try:
        import chardet
        guess = chardet.detect(raw[:200000]).get("encoding")
    except Exception:
        guess = None
    for enc in [guess, "utf-8-sig", "gb18030", "utf-16", "big5"]:
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")  # 最后兜底


def _read_docx(abs_path: str) -> str:
    """零依赖读取 .docx 正文：docx 本质是 zip，解 word/document.xml。"""
    import re
    import zipfile

    with zipfile.ZipFile(abs_path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    # 段落 </w:p> 转换行；<w:t> 文本保留；其余标签去掉
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return xml


@tool
def list_workspace_files(path: str = "", pattern: str = "", subdir: str = "") -> str:
    """列出工作目录（含其任意子目录）下的文件，用于找小说/剧本/素材。

    支持进入子目录：path 可以是相对工作目录的子路径（如 "视频素材/即梦"）
    或工作目录内的绝对路径（如 "F:\\小说\\小说\\视频素材\\即梦"）。

    Args:
        path: 要列的目录，相对工作目录或工作目录内的绝对路径；留空=工作目录根。
        pattern: 可选通配，如 *.txt / *.docx / *小说*。
        subdir: path 的别名（兼容）。
    """
    import glob as _glob

    target = path or subdir
    base = _resolve_in_workspace(target) if target else get_workspace()
    if base is None or not os.path.isdir(base):
        return f"目录不存在或不在工作目录内: {target or '(根)'}"
    pat = os.path.join(base, pattern or "*")
    entries = [e for e in sorted(_glob.glob(pat)) if not _is_secret(e)]  # 隐藏密钥/凭据
    if not entries:
        return f"（{base} 下没有匹配 {pattern or '*'} 的文件）"
    lines = [f"{base}:"]
    for e in entries:
        name = os.path.basename(e)
        if os.path.isdir(e):
            lines.append(f"  {name}/")
        else:
            kb = os.path.getsize(e) / 1024
            lines.append(f"  {name} ({kb:.0f} KB)")
    lines.append("可用 read_text_file 读取某个文件内容（小说/剧本）。")
    return "\n".join(lines)


@tool
def read_text_file(path: str, max_chars: int = 8000, offset: int = 0) -> str:
    """读取工作目录下的文本文件内容（小说/剧本/设定），供 Agent 参考来写分镜与提示词。

    支持 .txt / .md / .docx；长文按 max_chars 截断，可用 offset 继续读后续部分。

    Args:
        path: 文件路径，相对工作目录或绝对路径（须在工作目录内）。
        max_chars: 单次最多返回字符数（默认 8000，避免一次塞爆上下文）。
        offset: 从第几个字符开始读（用于分段读长篇小说）。
    """
    abs_path = _resolve_in_workspace(path)
    if abs_path is None:
        return f"文件不在工作目录内（出于安全只能读工作目录下的文件）: {path}"
    if _is_secret(path) or _is_secret(abs_path):
        return "出于安全，禁止读取密钥/凭据类文件（.env、私钥、credentials 等）。"
    if not os.path.isfile(abs_path):
        return f"文件不存在: {abs_path}"
    ext = os.path.splitext(abs_path)[1].lower()
    try:
        if ext == ".docx":
            text = _read_docx(abs_path)
        elif ext in (".txt", ".md", ".markdown", ".text", ""):
            text = _read_text_smart(abs_path)
        else:
            return f"暂不支持的文件类型 {ext}（支持 .txt/.md/.docx）。"
    except Exception as e:  # noqa: BLE001
        return f"读取失败: {type(e).__name__}: {e}"

    total = len(text)
    chunk = text[offset: offset + max_chars]
    head = f"{os.path.basename(abs_path)}（共 {total} 字，本次 {offset}~{offset + len(chunk)}）:\n"
    tail = ""
    if offset + len(chunk) < total:
        tail = f"\n…（还有 {total - offset - len(chunk)} 字，继续读可设 offset={offset + len(chunk)}）"
    return head + chunk + tail


# ── 项目 / 分镜管理 ────────────────────────────────────────────────
@tool
def create_video_project(title: str, novel_text: str = "") -> str:
    """新建一个"小说转短剧"项目。返回项目 ID，后续加分镜/出图都要用到它。

    Args:
        title: 项目标题（如"第一章 One Coat Between Us"）。
        novel_text: 可选，原文片段，便于后续拆分分镜。
    """
    proj = get_store().create_project(title=title, novel_text=novel_text)
    return f"已创建项目 [{proj['id']}] 《{proj['title']}》。下一步：用 add_scene 添加分镜。"


@tool
def add_scene(
    project_id: str,
    scene_number: int,
    narration: str = "",
    image_prompt: str = "",
    motion_prompt: str = "",
    title: str = "",
    subtitle: str = "",
    dialogue: str = "",
) -> str:
    """给项目添加一个分镜（镜头）。状态初始为 DRAFT。

    Args:
        project_id: create_video_project 返回的项目 ID。
        scene_number: 镜头序号（决定成片拼接顺序）。
        narration: 旁白/台词（合成时转 TTS 配音）。
        image_prompt: 出图提示词（FLUX 用；角色触发词由工作目录配置自动注入，无需手写）。
        motion_prompt: 运镜/动态提示词（Wan2.2 图生视频用）。
        title: 镜头简短标题。
        subtitle: 屏幕字幕文本；留空则字幕沿用 narration。旁白≠字幕时（如标题卡/台词）单独给。
        dialogue: 多角色对话「说话人：台词」逐行（说话人用角色名）；一镜多人对话时填，合成按各角色音色逐句配音。
    """
    scene = get_store().add_scene(
        project_id=project_id,
        scene_number=scene_number,
        narration=narration,
        image_prompt=image_prompt,
        motion_prompt=motion_prompt,
        title=title,
        subtitle=subtitle,
        dialogue=dialogue,
    )
    return (
        f"已添加分镜 [{scene['id']}] #{scene['scene_number']} {scene['title']}"
        f"（状态 {scene['state']}）。"
    )


@tool
def list_project_scenes(project_id: str) -> str:
    """列出项目下所有分镜及其状态、候选图数量、视频路径。"""
    try:
        st = get_store().status(project_id)
    except ValueError as e:
        return f"{e}"
    lines = [f"项目《{st['project']['title']}》[{project_id}]:"]
    for s in st["scenes"]:
        vid = f"{s['video_path']}" if s.get("video_path") else ""
        lines.append(
            f"  #{s['scene_number']} {s['title'] or '(无题)'} "
            f"[{s['id']}] 状态={s['state']} 候选图={s['num_candidates']}{vid}"
        )
    if not st["scenes"]:
        lines.append("  （暂无分镜）")
    return "\n".join(lines)


# ── 出图（FLUX） ──────────────────────────────────────────────────
@tool
def register_candidate_image(scene_id: str, remote_image_path: str) -> str:
    """把一张已存在于 GPU 服务器上的候选图登记进某分镜（不触发出图，用于已有图）。

    适用：FLUX 已离线生成好若干 scene_*.png，直接登记为候选供选图。

    Args:
        scene_id: 目标分镜 ID。
        remote_image_path: 服务器上图片绝对路径，如 /root/autodl-tmp/cael_scenes/scene_10.png。
    """
    store = get_store()
    asset = store.add_asset(scene_id=scene_id, storage_path=remote_image_path, asset_type="IMAGE")
    store.set_scene_state(scene_id, SceneState.PENDING_HUMAN_SELECTION, force=True)
    return (
        f"已登记候选图 [{asset['id']}] → {remote_image_path}。"
        f"分镜进入 PENDING_HUMAN_SELECTION，等待选图（select_candidate）。"
    )


def _gpu_retry(fn, *, what: str, retries: int = 1):
    """跑一次 GPU 任务，遇到 GpuRunError（连接抖动/偶发 OOM 等）原参自动重试。

    小白最怕"红字恐慌"：共享 GPU 偶发失败时静默重试一次，多半就过了。
    GpuConfigError（没配 GPU）不重试，直接抛。
    """
    last = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except GpuRunError as e:
            last = e
            if attempt < retries:
                logger.warning("[retry] %s 第%d次失败，自动重试：%s", what, attempt + 1, e)
                import time
                time.sleep(3)
    raise last


def _apply_trigger(prompt: str, trigger: str | None = None) -> str:
    """把角色触发词加在提示词最前（已含则不重复）。trigger=None 时用工作目录配置；显式传入则用它（项目级优先）。"""
    tw = trigger if trigger is not None else model_config().get("trigger_word")
    if tw and tw.lower() not in (prompt or "").lower():
        return f"{tw}, {prompt}".strip(", ").strip()
    return prompt


@tool
def request_image_params(scene_id: str, image_prompt: str = "") -> str:
    """【出图前必调】请求用户确认出图参数：返回一个参数卡占位，前端会弹出可编辑的参数表单
    （提示词 / 张数 / 步数 / guidance / 尺寸 / seed），由用户改好点"出图"后才真正生成。

    用户说"出图/生成候选图/出几张图"时，先调用本工具弹参数卡，**不要直接** generate_candidates。

    Args:
        scene_id: 目标分镜 ID。
        image_prompt: 出图提示词；留空则用分镜自带的 image_prompt。
    """
    store = get_store()
    scene = store.get_scene(scene_id)
    if not scene:
        return f"分镜不存在: {scene_id}"
    prompt = _apply_trigger(image_prompt or scene.get("image_prompt") or "")
    # 机器可读载荷：流式层会解析成 param_form 事件弹卡片，并从展示文本里剥掉这一行。
    payload = {
        "scene_id": scene_id,
        "image_prompt": prompt,
        "n": settings.FLUX_N,
        "steps": settings.FLUX_STEPS,
        "guidance": settings.FLUX_GUIDANCE,
        "width": settings.FLUX_WIDTH,
        "height": settings.FLUX_HEIGHT,
        "seed": -1,
        "offload": settings.FLUX_OFFLOAD,
    }
    return "已弹出出图参数卡，请在卡片里确认参数后点「出图」。\n" \
           f"PARAM_FORM::{json.dumps(payload, ensure_ascii=False)}"


def _scene_ref_face(store, scene: dict) -> str:
    """取这一镜主角的参考脸路径（characters.ref_image_path）；无角色/无脸/文件不存在则空串。

    用于「角色有参考脸 → PuLID 锁脸出图」：一张脸即跨镜锁定同一身份（免训练）。
    """
    name = (scene.get("character") or "").strip()
    pid = scene.get("project_id")
    if not name or not pid:
        return ""
    try:
        for c in store.list_characters(pid):
            if (c.get("name") or "").strip() == name:
                rp = (c.get("ref_image_path") or "").strip()
                return rp if (rp and os.path.exists(rp)) else ""
    except Exception:  # noqa: BLE001
        pass
    return ""


@tool
def generate_candidates(
    scene_id: str,
    image_prompt: str = "",
    n: int = 0,
    steps: int = 0,
    guidance: float = -1.0,
    width: int = 0,
    height: int = 0,
    seed: int = -1,
    offload: str = "",
    model: str = "",
) -> str:
    """为分镜生成 N 张候选图（多种子），全部登记进状态库并落到工作目录供选图。

    通常由参数卡确认后触发（见 request_image_params）。分镜推进到 PENDING_HUMAN_SELECTION。
    具体用哪个出图模型由 image_provider_registry 决定：默认 FLUX(SSH)；
    配了 COMFYUI_BASE_URL 后可传 model="comfyui-img" 走 ComfyUI 文生图。

    Args:
        scene_id: 目标分镜 ID。
        image_prompt: 出图提示词；留空则用分镜自带的 image_prompt（角色触发词自动注入）。
        n: 出图张数；0=用默认（settings.FLUX_N）。
        steps: 采样步数；0=默认。
        guidance: 提示词贴合度；<0=默认。
        width/height: 尺寸；0=默认。
        seed: 起始种子；-1=随机。
        offload: 显存策略 model/sequential；空=默认。
        model: 出图模型注册名；空=用默认（IMAGE_PROVIDER_DEFAULT，缺省 flux）。
    """
    store = get_store()
    scene = store.get_scene(scene_id)
    if not scene:
        return f"分镜不存在: {scene_id}"
    provider = image_provider_registry.get(model)
    is_http = getattr(provider, "transport", "ssh") == "http"
    # 剧集级风格（每集一种风格）：通用风格词/触发词/LoRA/负向/默认尺寸。项目级优先，回退工作目录 config.json。
    pstyle = store.get_project_style(scene["project_id"]) if scene.get("project_id") else {}
    raw = image_prompt or scene.get("image_prompt") or ""
    style_words = (pstyle.get("style_prompt") or "").strip()
    if style_words and style_words.lower() not in raw.lower():
        raw = f"{raw}，{style_words}".strip("，").strip()
    # FLUX 等英文模型读不懂中文(CLIP 截断 + 纯英文训练 → 退化成动漫人像)。
    # 英文模型(prompt_lang=="en") + 开关开 + 含中文 → 出图前自动翻英文，对用户隐形；翻译失败退回原文不阻断。
    if getattr(provider, "prompt_lang", "any") == "en" and settings.IMAGE_PROMPT_AUTOTRANSLATE:
        from mirage.app.pipeline.prompt_gen import translate_to_english
        raw = translate_to_english(raw)
    trigger = (pstyle.get("trigger_word") or "").strip() or model_config().get("trigger_word")
    prompt = _apply_trigger(raw, trigger)
    if not prompt:
        return "没有出图提示词（image_prompt 为空）。"
    # 默认尺寸：用户没指定(0)且项目设了 default_size(如 768x1024) → 用项目默认
    if (not width or not height) and (pstyle.get("default_size") or "").strip():
        try:
            pw, ph = (int(x) for x in pstyle["default_size"].lower().replace("x", "*").split("*"))
            width = width or pw
            height = height or ph
        except (ValueError, TypeError):
            pass
    # LoRA / 负向词：项目级优先，回退工作目录
    lora = (pstyle.get("flux_lora") or "").strip() or (model_config().get("flux_lora") or None)
    params = {
        "n": (n or None), "steps": (steps or None), "guidance": guidance,
        "width": (width or None), "height": (height or None),
        "seed": seed, "offload": (offload or None),
        "flux_lora": lora,
        "negative": (pstyle.get("negative_prompt") or "").strip() or None,
    }
    local_dir = candidates_dir(scene_id)  # 落到当前工作目录
    # 角色有参考脸 + 开了 PuLID + 配了 ComfyUI → 走 PuLID 锁脸直出（免训练，跨镜同一张脸）；否则普通出图。
    ref_face = _scene_ref_face(store, scene)
    use_pulid = bool(ref_face) and settings.PULID_ENABLED and bool((settings.COMFYUI_BASE_URL or "").strip())

    if is_http or use_pulid:
        # http（ComfyUI）/ PuLID：候选图直接下到本地 local_dir，返回本地路径，无需 SSH 下载
        os.makedirs(local_dir, exist_ok=True)
        try:
            store.set_scene_state(scene_id, SceneState.PENDING_FLUX_GEN, force=True)
            if use_pulid:
                from mirage.app.pipeline.lora_bootstrap import pulid_generate
                local_paths = pulid_generate(
                    ref_face, prompt, out_dir=local_dir,
                    n=(n or settings.COMFYUI_T2I_N),
                    size=(f"{width}*{height}" if (width and height) else None),
                    steps=(steps or None),
                    seed=(seed if (seed is not None and seed >= 0) else None),
                    negative=params.get("negative"))
            else:
                local_paths = provider.generate(None, prompt=prompt, out_dir=local_dir, params=params)
        except GpuConfigError as e:
            return f"出图后端未配置: {e}"
        except GpuRunError as e:
            store.set_scene_state(scene_id, SceneState.FAILED, force=True)
            return f"出图失败: {e}"
        store.set_scene_state(scene_id, SceneState.PENDING_HUMAN_SELECTION, force=True)
        _who = "PuLID 锁脸" if use_pulid else provider.display_name
        lines = [f"{_who} 出 {len(local_paths)} 张候选 → 分镜 {scene_id} 进入 PENDING_HUMAN_SELECTION:"]
        img_markers = []
        for lp in local_paths:
            asset = store.add_asset(scene_id=scene_id, storage_path=lp, asset_type="IMAGE")
            lines.append(f"  [{asset['id']}] {os.path.basename(lp)} {lp}")
            img_markers.append(f"IMGFILE::{scene_id}::{asset['id']}::{lp}")
        lines.append("下一步：点选一张候选图即可（select_candidate）。")
        lines.extend(img_markers)
        return "\n".join(lines)

    # ssh（默认 FLUX）：provider 返回远程路径，工具层逐张下载到工作目录
    out_remote_dir = posixpath.join(settings.GPU_FLUX_OUT_ROOT, scene_id)
    try:
        store.set_scene_state(scene_id, SceneState.PENDING_FLUX_GEN, force=True)
        remote_imgs = _gpu_retry(
            lambda: provider.generate(get_gpu_client(), prompt=prompt, out_dir=out_remote_dir, params=params),
            what=f"出图 {scene_id}",
        )
    except GpuConfigError as e:
        return f"GPU 未配置: {e}"
    except GpuRunError as e:
        store.set_scene_state(scene_id, SceneState.FAILED, force=True)
        return f"出图失败: {e}"

    store.set_scene_state(scene_id, SceneState.PENDING_HUMAN_SELECTION, force=True)
    lines = [f"{provider.display_name} 出 {len(remote_imgs)} 张候选 → 分镜 {scene_id} 进入 PENDING_HUMAN_SELECTION:"]
    img_markers = []  # 机器可读：流式层解析成 image 事件
    for rp in remote_imgs:
        asset = store.add_asset(scene_id=scene_id, storage_path=rp, asset_type="IMAGE")
        name = posixpath.basename(rp)
        try:
            lp = os.path.join(local_dir, name)
            get_gpu_client().download(rp, lp)
            lines.append(f"  [{asset['id']}] {name} {lp}")
            img_markers.append(f"IMGFILE::{scene_id}::{asset['id']}::{lp}")
        except Exception as e:  # noqa: BLE001 - 下载失败不影响登记
            lines.append(f"  [{asset['id']}] {name} 下载失败: {e}")
    lines.append("下一步：点选一张候选图即可（select_candidate）。")
    lines.extend(img_markers)
    return "\n".join(lines)


# ── 选图（HITL） ──────────────────────────────────────────────────
@tool
def list_candidates(scene_id: str) -> str:
    """列出某分镜的所有候选图（含选中标记），供人/Agent 决策选哪张。"""
    assets = get_store().list_assets(scene_id, asset_type="IMAGE")
    if not assets:
        return f"（分镜 {scene_id} 暂无候选图）"
    lines = [f"分镜 {scene_id} 候选图:"]
    for a in assets:
        mark = "选中" if a["is_selected"] else ""
        lines.append(f"  [{a['id']}] {a['storage_path']} ({a['approval_status']}){mark}")
    return "\n".join(lines)


@tool
def select_candidate(scene_id: str, asset_id: str) -> str:
    """HITL 选图：选定一张候选图，分镜推进到 PENDING_VIDEO_GEN（可出视频）。

    Args:
        scene_id: 分镜 ID。
        asset_id: 选中的候选图 asset ID（来自 list_candidates）。
    """
    try:
        scene = get_store().select_asset(scene_id, asset_id)
    except ValueError as e:
        return f"{e}"
    return f"已选定 {asset_id}，分镜 {scene_id} → {scene['state']}。下一步：render_scene_video。"


# ── 图生视频（Wan2.2） ────────────────────────────────────────────
@tool
def request_video_params(scene_id: str, motion_prompt: str = "", model: str = "") -> str:
    """【出视频前必调】请求用户确认出视频参数：前端会弹出可编辑的参数表单
    （运镜提示词 + 该视频模型的专属参数），由用户选模型/改参数后点"出视频"才真正生成。

    用户说"出视频/生成视频/图生视频"时，先调用本工具弹参数卡，**不要直接** render_scene_video。
    支持多视频模型（如 wan2.2 / ltx），参数卡字段由所选模型自动决定。

    Args:
        scene_id: 目标分镜 ID（须已 select_candidate 选好图）。
        motion_prompt: 运镜/动态提示词；留空则用分镜自带的 motion_prompt。
        model: 视频模型名（wan2.2 / ltx ...）；留空用默认模型，用户也可在卡片上切换。
    """
    store = get_store()
    scene = store.get_scene(scene_id)
    if not scene:
        return f"分镜不存在: {scene_id}"
    if scene["state"] != SceneState.PENDING_VIDEO_GEN.value:
        return (f"分镜当前状态 {scene['state']}，需先选图（select_candidate）"
                f"进入 PENDING_VIDEO_GEN 才能出视频。")
    prompt = motion_prompt or scene.get("motion_prompt") or "缓慢推镜，电影质感，自然光影。"
    provider = video_provider_registry.get(model)
    payload = {
        "scene_id": scene_id,
        "motion_prompt": prompt,
        "model": provider.name,                       # 当前选中的模型
        "models": [                                   # 供卡片下拉切换的全部模型
            {"name": p["name"], "display_name": p["display_name"]}
            for p in video_provider_registry.list_providers()
        ],
        # 该模型的专属可调字段 + 通用的「接续段数」（尾帧接续：段越多镜头越长且连贯）
        "fields": provider.param_schema() + [{
            "key": "segments", "label": "接续段数(连贯加长)", "type": "number", "default": 1,
            "help": "尾帧接续：每段结束取最后一帧作为下一段的起始画面继续生成，再无缝拼接成"
                    "一条连续镜头。段数越多镜头越长（总时长≈单段×段数）。想多长填多少，没有写死上限；"
                    "也可以先出 1 段、看效果后在面板用「再续一段」逐段加长。",
        }],
    }
    return ("已弹出出视频参数卡，请在卡片里确认参数后点「出视频」。\n"
            f"VIDEO_PARAM_FORM::{json.dumps(payload, ensure_ascii=False)}")


def _s2v_frames_for_audio(seconds: float, fps: int, cap: int = 0, margin: float = 0.2) -> int:
    """对口型该出多少帧 = ⌈(音频秒数+余量)·fps⌉，向上取到 Wan 合法的 4n+1（时序步长4）。

    音频多长视频多长，口型跟满整句、不被写死的 81 帧截断。cap>0 时封顶（防显存 OOM/超长）。
    seconds/fps 非法 → 返回 0（调用方回退默认帧数）。
    """
    import math
    if seconds <= 0 or fps <= 0:
        return 0
    raw = int(math.ceil((seconds + margin) * fps))
    n = math.ceil(max(0, raw - 1) / 4)
    frames = 4 * n + 1
    if cap and cap > 0 and frames > cap:
        frames = cap
    return frames


def _compose_wan_prompt(scene: dict, motion_prompt: str = "") -> str:
    """把运镜词整理成 Wan2.2 i2v 提示词(尊重用户原意，不篡改)。

    - **只在含中文时**翻成英文：已是英文的不再丢给 LLM「翻译」(否则会被改写/篡改原意)。
    - **不追加任何运动描述**：旧版加 'smooth natural motion' 会和用户的 'crash zoom' 等
      剧烈运动冲突 → 模型收到矛盾指令、出片对不上提示词。只补轻量画质词(不涉及运动)。
    """
    base = (motion_prompt or scene.get("motion_prompt") or "").strip().rstrip("。.，,")
    if not base:
        base = "slow push-in"
    if settings.IMAGE_PROMPT_AUTOTRANSLATE and any("一" <= c <= "鿿" for c in base):
        try:
            from mirage.app.pipeline.prompt_gen import translate_to_english
            base = (translate_to_english(base) or base).strip()
        except Exception:  # noqa: BLE001
            pass
    return f"{base}, cinematic lighting, high detail"


def _do_render_lipsync_s2v(scene_id, scene, asset, prompt, params) -> str:
    """对口型出片：取该镜旁白(=台词)→TTS→连同选中人物图喂 Wan2.2-S2V，出口型同步片(成片自带人声)。

    整镜一段，不走尾帧接续（S2V 由音频长度决定时长）。S2V 是隐藏 Provider，端点门控。
    """
    store = get_store()
    line = (scene.get("narration") or "").strip()
    if not line:
        store.set_scene_state(scene_id, SceneState.PENDING_VIDEO_GEN, force=True)
        return "对口型需要一句台词：请先给这镜写「旁白」（即人物要说的话），再点出视频。"
    if not video_provider_registry.has("comfyui-s2v"):
        return ("对口型(S2V)还没就绪：需在 .env 配 COMFYUI_BASE_URL 且在 ComfyUI 部署 Wan2.2-S2V。"
                "暂未配置时，请把这镜的「对口型」关掉、用普通出片。")
    s2v = video_provider_registry.get("comfyui-s2v")
    local_dir = video_dir()
    final_local = os.path.join(local_dir, f"{scene['scene_number']:02d}_{scene_id}.mp4")
    # 本地人物图（选中候选）
    cur_image = os.path.join(candidates_dir(scene_id), posixpath.basename(asset["storage_path"]))
    if not os.path.exists(cur_image):
        try:
            get_gpu_client().download(asset["storage_path"], cur_image)
        except Exception:  # noqa: BLE001
            return f"对口型需要本地人物图，但本地没有：{cur_image}。请对该镜重新出图后再试。"
    # 旁白(台词) → TTS 本地音频
    from mirage.app.pipeline.assembler import _tts
    audio_local = os.path.join(local_dir, f"{scene['scene_number']:02d}_{scene_id}_voice.mp3")
    voice = (scene.get("voice") or "").strip() or settings.COMFYUI_S2V_TTS_VOICE   # 角色音色优先
    ok_tts = _tts(line, audio_local, voice)
    if not ok_tts:                       # edge-tts 偶发网络抖动：退避重试一次
        import time as _t; _t.sleep(1.0)
        ok_tts = _tts(line, audio_local, voice)
    if not ok_tts:
        return "对口型失败：台词转语音(TTS)没成功（edge-tts 需联网，已重试）。"
    # 只剔除真正"未设置"的(None/空串)；保留数值 0——seed=0 是合法可复现种子（与主 i2v 一致）。
    merged = {**s2v.default_params(),
              **{k: v for k, v in (params or {}).items() if v is not None and v != ""}}
    merged.pop("lipsync", None); merged.pop("segments", None); merged.pop("motion_prompts", None)
    merged["audio_path"] = audio_local
    # 帧数跟着音频走：否则写死 81帧≈5s 会把长台词截断（口型只对到一半）。
    if not merged.get("frames"):     # 用户没在参数卡显式指定才自动算
        from mirage.app.pipeline import log_bus
        from mirage.app.pipeline.assembler import _duration as _media_seconds
        fps = int(merged.get("fps") or settings.COMFYUI_FPS)
        try:
            dur = float(_media_seconds(audio_local))
        except Exception:            # noqa: BLE001 探测失败就退回默认帧数
            dur = 0.0
        frames = _s2v_frames_for_audio(dur, fps, cap=int(settings.COMFYUI_S2V_MAX_FRAMES or 0))
        if frames:
            merged["frames"] = frames
            cap = int(settings.COMFYUI_S2V_MAX_FRAMES or 0)
            if cap and frames >= cap:
                log_bus.emit(f"[对口型] 台词约 {dur:.1f}s 超过单段上限 {cap/fps:.1f}s，已截到上限；"
                             f"建议把这句拆短或拆成两镜，避免说不完。")
            else:
                log_bus.emit(f"[对口型] 台词 {dur:.1f}s → {frames} 帧 ≈ {frames/fps:.1f}s（口型跟满全句，不截断）")
    try:
        store.set_scene_state(scene_id, SceneState.PENDING_VIDEO_GEN, force=True)
        _gpu_retry(lambda: s2v.generate(None, image_path=cur_image, prompt=prompt,
                                        out_remote=final_local, params=merged),
                   what=f"对口型 {scene_id}")
    except GpuConfigError as e:
        return f"对口型后端未配置: {e}"
    except (GpuRunError, RuntimeError, OSError) as e:
        store.set_scene_state(scene_id, SceneState.FAILED, force=True)
        return f"对口型出片失败: {e}"
    store.set_scene_video(scene_id, final_local)
    store.set_scene_state(scene_id, SceneState.COMPLETED)
    return (f"对口型(Wan2.2-S2V)出片完成，分镜 {scene_id} 标记 COMPLETED（成片自带人声）。\n"
            f"已下载到本机: {final_local}\nVIDFILE::{scene_id}::{final_local}")


def _compose_t2v_prompt(scene, motion_prompt, pstyle) -> str:
    """t2v 提示词 = 画面描述(image_prompt + 风格词 + 触发词，英文化) + 运镜 + 画质尾。

    ★关键:t2v 没有首帧图,画面/主体/外貌/环境只能来自文本——不能像 i2v 那样只给运镜
    (_compose_wan_prompt 刻意只取 motion;对 i2v 对,对 t2v 会丢掉整段 image_prompt → 出空泛镜头)。
    """
    raw = (scene.get("image_prompt") or "").strip()
    style_words = (pstyle.get("style_prompt") or "").strip()
    if style_words and style_words.lower() not in raw.lower():
        raw = f"{raw}，{style_words}".strip("，").strip()
    if raw and settings.IMAGE_PROMPT_AUTOTRANSLATE:   # Wan/umt5 偏英文，同出图走翻译；失败退原文
        try:
            from mirage.app.pipeline.prompt_gen import translate_to_english
            raw = translate_to_english(raw) or raw
        except Exception:  # noqa: BLE001
            pass
    # 多角色一致性：该镜出场角色(scene.character)匹配项目角色 → 注入其触发词(trigger_word 或 名字 slug)；
    # 没匹配到/为空时回退项目级 pstyle.trigger_word(单角色/通用)。
    char_trigger = ""
    scene_char = (scene.get("character") or "").strip()
    if scene_char and scene.get("project_id"):
        try:
            from mirage.app.pipeline.lora_train import _slug
            for c in (get_store().list_characters(scene["project_id"]) or []):
                if (c.get("name") or "").strip() == scene_char:
                    char_trigger = (c.get("trigger_word") or "").strip() or _slug(c.get("name") or "")
                    break
        except Exception:  # noqa: BLE001 取角色失败就退回项目级触发词
            char_trigger = ""
    trigger = char_trigger or (pstyle.get("trigger_word") or "").strip() or model_config().get("trigger_word")
    raw = _apply_trigger(raw, trigger)
    motion = (motion_prompt or scene.get("motion_prompt") or "").strip()
    base = ", ".join(p for p in (raw, motion) if p) or "cinematic film still"
    return f"{base}, cinematic lighting, high detail"


def _do_render_t2v(scene_id, scene, motion_prompt, params) -> str:
    """文生视频出片：文本(画面+运镜) → Wan2.2-T2V 直接出视频，**不需选图/参考帧**。整镜一段。

    身份靠项目级 Wan-T2V 角色 LoRA(没训就纯提示词，身份不稳)。t2v 是隐藏 Provider，端点门控。
    """
    store = get_store()
    store.set_scene_video_mode(scene_id, "t2v")   # 标记本镜=t2v：合成时据此走 TTS 配音(t2v 无自带音轨)
    _prov = settings.T2V_PROVIDER or "comfyui-t2v"   # comfyui-t2v / lightx2v-t2v(纯 t2v 可不用 ComfyUI)
    if not video_provider_registry.has(_prov):
        return (f"文生视频(t2v)后端 '{_prov}' 未就绪：lightx2v 需 LIGHTX2V_ENABLED + LIGHTX2V_BASE_URL 且已起 server；"
                "ComfyUI 需 COMFYUI_BASE_URL。暂未就绪时把「出片模式」切回 i2v。")
    t2v = video_provider_registry.get(_prov)
    local_dir = video_dir()
    final_local = os.path.join(local_dir, f"{scene['scene_number']:02d}_{scene_id}.mp4")
    # 项目级风格/触发词/角色 LoRA：本镜读一次复用(出 prompt + 挂 LoRA 共用，避免逐镜重复读)
    try:
        pstyle = store.get_project_style(scene["project_id"]) if scene.get("project_id") else {}
    except Exception:  # noqa: BLE001
        pstyle = {}
    prompt = _compose_t2v_prompt(scene, motion_prompt, pstyle)   # ★带 image_prompt，否则出空泛镜头
    merged = {**t2v.default_params(),
              **{k: v for k, v in (params or {}).items() if v is not None and v != ""}}
    for _k in ("lipsync", "motion_prompts", "segments", "video_mode"):
        merged.pop(_k, None)
    # 项目级 Wan-T2V 角色 LoRA(训好后写进项目 style)；params 已显式带则不覆盖
    if not merged.get("wan_t2v_lora_high") and (pstyle.get("wan_t2v_lora_high") or "").strip():
        merged["wan_t2v_lora_high"] = pstyle["wan_t2v_lora_high"].strip()
    if not merged.get("wan_t2v_lora_low") and (pstyle.get("wan_t2v_lora_low") or "").strip():
        merged["wan_t2v_lora_low"] = pstyle["wan_t2v_lora_low"].strip()
    try:
        store.set_scene_state(scene_id, SceneState.PENDING_VIDEO_GEN, force=True)
        _gpu_retry(lambda: t2v.generate(None, image_path="", prompt=prompt,
                                        out_remote=final_local, params=merged),
                   what=f"文生视频 {scene_id}")
    except GpuConfigError as e:
        return f"文生视频后端未配置: {e}"
    except (GpuRunError, RuntimeError, OSError) as e:
        store.set_scene_state(scene_id, SceneState.FAILED, force=True)
        return f"文生视频出片失败: {e}"
    store.set_scene_video(scene_id, final_local)
    store.set_scene_state(scene_id, SceneState.COMPLETED)
    return (f"文生视频(Wan2.2-T2V)出片完成，分镜 {scene_id} 标记 COMPLETED。\n"
            f"已下载到本机: {final_local}\nVIDFILE::{scene_id}::{final_local}")


def do_render_scene_video(
    scene_id: str,
    motion_prompt: str = "",
    model: str = "",
    params: dict | None = None,
    download: bool = True,
) -> str:
    """出片核心（模型无关）：按所选 Provider 出图生视频 mp4 并下载回工作目录。

    被 @tool render_scene_video 与 /api/pipeline/render 共用。具体模型逻辑全在 Provider 里，
    这里只负责状态机校验、调度、下载、写回状态。
    """
    params = params or {}
    store = get_store()
    scene = store.get_scene(scene_id)
    if not scene:
        return f"分镜不存在: {scene_id}"
    # 文生视频(t2v)：不需要选图，文本直接→视频。在「必须已选图」校验之前分流。
    if (params.get("video_mode") or scene.get("video_mode") or "i2v") == "t2v":
        return _do_render_t2v(scene_id, scene, motion_prompt, params)
    # 出片的真实前提是「已选好一张图」，而不是 state 恰好等于某枚举。
    # 早先的中断/重生成可能让 state 漂移（选过图但 state 回退），这里以选中资产为准，更稳。
    asset = store.get_asset(scene["selected_asset_id"]) if scene.get("selected_asset_id") else None
    if not asset:
        return (f"分镜还没有选定候选图（当前状态 {scene['state']}）："
                f"请先出图并点选一张，再出视频。")
    if scene["state"] != SceneState.PENDING_VIDEO_GEN.value:
        store.set_scene_state(scene_id, SceneState.PENDING_VIDEO_GEN, force=True)  # 纠正漂移

    # 对口型(S2V)：勾了「对口型」就走语音驱动（图+台词音频→口型同步），整镜一段、不走 i2v/接续。
    if bool((params or {}).get("lipsync")) or bool(scene.get("lipsync")):
        ls_prompt = motion_prompt or scene.get("motion_prompt") or ""
        return _do_render_lipsync_s2v(scene_id, scene, asset, ls_prompt, params or {})

    provider = video_provider_registry.get(model)
    is_http = getattr(provider, "transport", "ssh") == "http"   # http(ComfyUI)：全程本地，不碰 SSH
    # 只剔除真正"未设置"的(None / 空串)；保留数值 0——seed=0 是合法可复现种子，
    # 旧的 `not in (None, "", 0)` 会连 0(及 False)一起吞掉，导致 seed=0 落空回退随机。
    merged = {**provider.default_params(), **{k: v for k, v in params.items() if v is not None and v != ""}}
    # 尾帧接续段数（流水线级参数，不传给模型）：每段取末帧作为下一段输入，拼成连续长镜头。
    # 段数不写死：上限由 settings.MAX_CONTINUATION_SEGMENTS 决定（0=不限）。
    try:
        n_seg = max(1, int(merged.pop("segments", 1) or 1))
    except (TypeError, ValueError):
        n_seg = 1
    _cap = settings.MAX_CONTINUATION_SEGMENTS
    segments = min(n_seg, _cap) if _cap and _cap > 0 else n_seg
    prompt = _compose_wan_prompt(scene, motion_prompt)   # Wan i2v 友好:英文化+运镜+光影尾
    # 每段独立提示词（AI 生成的分段运镜）：有则逐段用，缺则回退到统一 prompt
    seg_prompts = merged.pop("motion_prompts", None) or []
    if not isinstance(seg_prompts, list):
        seg_prompts = []

    local_dir = video_dir()  # 落到当前工作目录
    final_local = os.path.join(local_dir, f"{scene['scene_number']:02d}_{scene_id}.mp4")
    base = f"{scene_id}_{scene['scene_number']}"
    seg_locals: list[str] = []
    out_remote = ""

    if is_http:
        # ComfyUI 等 HTTP 后端：出片走本地图，不依赖 GPU 服务器。
        # 取本地候选副本；本地没有时尝试从 GPU 拉一次（若配了），仍拿不到则明确报错。
        gpu = None
        cur_image = os.path.join(candidates_dir(scene_id), posixpath.basename(asset["storage_path"]))
        if not os.path.exists(cur_image):
            try:
                get_gpu_client().download(asset["storage_path"], cur_image)
            except Exception:  # noqa: BLE001
                return (f"ComfyUI 出片需要本地参考图，但本地没有：{cur_image}。"
                        f"请对该分镜重新出图，或用「上传图片」补一张后再出视频。")
    else:
        # 参考图就绪保障：候选图的 storage_path 是「出图时那台 GPU」的服务器路径。
        # 换 GPU 机器或服务器清理后该文件会缺失；缺则用本地候选副本自动回传，做到换机器也能出片。
        try:
            gpu = get_gpu_client()
            remote_img = asset["storage_path"]
            if not gpu.exists(remote_img):
                local_img = os.path.join(candidates_dir(scene_id), posixpath.basename(remote_img))
                if not os.path.exists(local_img):
                    return (f"参考图在 GPU 服务器和本地都找不到：{remote_img}。"
                            f"可能是换了 GPU 机器且本地副本已删，请对该分镜重新出图后再出视频。")
                gpu.upload(local_img, remote_img)
        except GpuConfigError as e:
            return f"GPU 未配置: {e}"
        cur_image = remote_img

    try:
        for k in range(segments):
            prompt_k = _compose_wan_prompt(scene, seg_prompts[k]) if (k < len(seg_prompts) and seg_prompts[k]) else prompt
            seg_local = final_local if segments == 1 else os.path.join(
                local_dir, f"{scene['scene_number']:02d}_{scene_id}_seg{k + 1}.mp4")
            if is_http:
                # ComfyUI：成片直接写到本地 seg_local（Provider 内部 HTTP 下载），无 SSH 往返
                out_remote = seg_local
                _gpu_retry(
                    lambda p=prompt_k, o=seg_local, ci=cur_image: provider.generate(
                        None, image_path=ci, prompt=p, out_remote=o, params=merged),
                    what=f"出片 {scene_id} 段{k + 1}",
                )
                seg_locals.append(seg_local)
                if k < segments - 1:
                    # 尾帧接续：抽本段末帧 → 作为下一段 i2v 起始画面（全本地）
                    from mirage.app.pipeline.assembler import extract_last_frame
                    frame_local = os.path.join(local_dir, f"{base}_seg{k + 1}_last.png")
                    extract_last_frame(seg_local, frame_local)
                    cur_image = frame_local
                    logger.info("[render] 接续 %d/%d（http）：末帧已抽取，继续生成", k + 1, segments)
            else:
                out_remote = posixpath.join(
                    settings.GPU_OUTPUT_DIR,
                    f"{base}.mp4" if segments == 1 else f"{base}_seg{k + 1}.mp4",
                )
                _gpu_retry(
                    lambda p=prompt_k: provider.generate(gpu, image_path=cur_image, prompt=p,
                                                         out_remote=out_remote, params=merged),
                    what=f"出片 {scene_id} 段{k + 1}",
                )
                # 每段都拉回本地（接续抽帧 / 最终拼接都在本地做，复用带重试的传输）
                gpu.download(out_remote, seg_local)
                seg_locals.append(seg_local)
                if k < segments - 1:
                    # 尾帧接续：抽本段末帧 → 回传 GPU → 作为下一段 i2v 的起始画面
                    from mirage.app.pipeline.assembler import extract_last_frame
                    frame_local = os.path.join(local_dir, f"{base}_seg{k + 1}_last.png")
                    extract_last_frame(seg_local, frame_local)
                    cur_image = posixpath.join(settings.GPU_OUTPUT_DIR,
                                               f"{base}_seg{k + 1}_last.png")
                    gpu.upload(frame_local, cur_image)
                    logger.info("[render] 接续 %d/%d：末帧已回传，继续生成", k + 1, segments)
    except GpuConfigError as e:
        return f"GPU 未配置: {e}"
    except (GpuRunError, RuntimeError, OSError) as e:
        store.set_scene_state(scene_id, SceneState.FAILED, force=True)
        done = len(seg_locals)
        hint = f"（已完成 {done}/{segments} 段）" if segments > 1 and done else ""
        return f"图生视频失败{hint}: {e}"

    if segments > 1:
        # 多段拼接为最终成片：去重边界帧(尾帧接续每段首帧=上段末帧)，消除拼接处的一帧卡顿
        from mirage.app.pipeline.assembler import concat_videos
        try:
            concat_videos(seg_locals, final_local, dedup_boundary=True,
                          crossfade=settings.VIDEO_SEAM_CROSSFADE)
        except Exception as e:  # noqa: BLE001
            store.set_scene_state(scene_id, SceneState.FAILED, force=True)
            return f"接续段拼接失败: {e}"

    # 可选画质增强(RealESRGAN 放大;COMFYUI_WORKFLOW_POST 配了才跑,默认关)。就地替换,失败保原片、不阻断。
    try:
        from mirage.app.pipeline.postprocess import maybe_postprocess
        maybe_postprocess(final_local, fps=int(merged.get("fps") or settings.COMFYUI_FPS))
    except Exception:  # noqa: BLE001
        logger.warning("[render] 画质增强跳过(出错,保原片) scene=%s", scene_id)
    # 存本地最终成片路径 final_local；此前 SSH 单段误存远程 GPU 路径 out_remote，
    # 导致信任 scenes.video_path 的删除/状态逻辑拿到不存在的本地路径。
    store.set_scene_video(scene_id, final_local)
    store.set_scene_state(scene_id, SceneState.COMPLETED)
    seg_note = f"（尾帧接续 {segments} 段连续镜头）" if segments > 1 else ""
    msg = f"{provider.display_name} 出片完成{seg_note}，分镜 {scene_id} 标记 COMPLETED。"
    msg += f"\n已下载到本机: {final_local}"
    vid_marker = f"\nVIDFILE::{scene_id}::{final_local}"  # 供前端内嵌播放
    return msg + vid_marker


@tool
def render_scene_video(
    scene_id: str,
    motion_prompt: str = "",
    model: str = "",
    size: str = "",
    frame_num: int = 0,
    sample_steps: int = 0,
    segments: int = 1,
    download: bool = True,
) -> str:
    """对已选图的分镜调用远程视频模型出图生视频 mp4，完成后下载回工作目录。

    通常由参数卡确认后触发（见 request_video_params）。需先 select_candidate 选好图。
    支持多模型（wan2.2 / ltx ...），具体参数由模型决定。
    segments>1 时启用尾帧接续：每段末帧作为下一段起始画面连续生成并无缝拼接，
    生成 N 倍时长的连续长镜头（用户说"长一点/连贯/30秒"时可设 2-4）。

    Args:
        scene_id: 分镜 ID。
        motion_prompt: 运镜/动态提示词；留空则用分镜自带的 motion_prompt。
        model: 视频模型名（wan2.2 / ltx）；空=默认模型。
        size: 分辨率（如 704*1280 竖屏 / 1280*704 横屏）；空=默认。
        frame_num: 帧数（Wan2.2 24G 建议 ≤25）；0=默认。
        sample_steps: 采样步数；0=默认。
        download: 是否把成片下载到工作目录 video_out。
    """
    params: dict = {}
    if size:
        params["size"] = size
    if frame_num:
        params["frame_num"] = frame_num
    if sample_steps:
        params["sample_steps"] = sample_steps
    if segments and segments > 1:
        params["segments"] = segments
    return do_render_scene_video(scene_id, motion_prompt, model, params, download)


# ── 看效果再加长：在已生成的成片末尾，按尾帧接续逐段追加（段数不写死）─────────────
def _render_one_continuation(scene_id, scene, provider, is_http, gpu,
                             start_frame_local, prompt, merged, tag) -> str:
    """从一张本地起始帧出一段 i2v，返回本地 mp4 路径（http/ssh 都支持）。append 专用。"""
    local_dir = video_dir()
    seg_local = os.path.join(local_dir, f"{scene['scene_number']:02d}_{scene_id}_app{tag}.mp4")
    if is_http:
        _gpu_retry(
            lambda: provider.generate(None, image_path=start_frame_local, prompt=prompt,
                                      out_remote=seg_local, params=merged),
            what=f"追加段 {tag}")
    else:
        base = f"{scene_id}_{scene['scene_number']}_app{tag}"
        remote_frame = posixpath.join(settings.GPU_OUTPUT_DIR, f"{base}_start.png")
        remote_out = posixpath.join(settings.GPU_OUTPUT_DIR, f"{base}.mp4")
        gpu.upload(start_frame_local, remote_frame)
        _gpu_retry(
            lambda: provider.generate(gpu, image_path=remote_frame, prompt=prompt,
                                      out_remote=remote_out, params=merged),
            what=f"追加段 {tag}")
        gpu.download(remote_out, seg_local)
    return seg_local


def _undo_paths(final_local: str) -> list[str]:
    """该成片的「续段前快照」列表（按编号升序）。供「撤销上一段」回退。"""
    import glob, re
    base = final_local[:-4] if final_local.lower().endswith(".mp4") else final_local
    items = []
    for p in glob.glob(base + ".undo*.mp4"):
        m = re.search(r"\.undo(\d+)\.mp4$", p)
        if m:
            items.append((int(m.group(1)), p))
    return [p for _, p in sorted(items)]


def _next_undo_path(final_local: str) -> str:
    import re
    base = final_local[:-4] if final_local.lower().endswith(".mp4") else final_local
    ks = [int(re.search(r"\.undo(\d+)\.mp4$", p).group(1)) for p in _undo_paths(final_local)]
    return f"{base}.undo{(max(ks) + 1) if ks else 1}.mp4"


def undo_last_append_segment(scene_id: str) -> str:
    """撤销「上一段」续接：把成片回退到最近一次「再续一段」之前的版本（可多次回退）。"""
    store = get_store()
    scene = store.get_scene(scene_id)
    if not scene:
        return f"分镜不存在: {scene_id}"
    final_local = os.path.join(video_dir(), f"{scene['scene_number']:02d}_{scene_id}.mp4")
    snaps = _undo_paths(final_local)
    if not snaps:
        return "没有可回退的续段——这已是最初出的那一段，或还没「再续一段」过。"
    latest = snaps[-1]
    try:
        os.replace(latest, final_local)   # 用快照覆盖回成片，并消耗掉这个快照
    except PermissionError:
        return "回退失败：成片正被播放/占用（多半在浏览器里放着）。请暂停该视频后再点「撤销上一段」。"
    except OSError as e:
        return f"回退失败: {e}"
    store.set_scene_video(scene_id, final_local)
    store.set_scene_state(scene_id, SceneState.COMPLETED)
    left = len(_undo_paths(final_local))
    tip = f"（还可再回退 {left} 次）" if left else "（已回到最初那一段）"
    return (f"已撤销上一段续接，成片回退到上一版{tip}。可重新「再续一段」。\n"
            f"VIDFILE::{scene_id}::{final_local}")


def append_scene_segment(scene_id: str, motion_prompt: str = "", model: str = "",
                         params: dict | None = None, count: int = 1) -> str:
    """在分镜**已生成**的成片末尾，按尾帧接续再追加 count 段，就地变长（看效果再决定加多少）。

    与 do_render_scene_video 的区别：不重出整条，而是取「现有成片的末帧」作为起点生成新段，
    拼到现有成片后面。可反复调用，每次加几段都行——段数不写死。
    """
    import time as _time
    params = params or {}
    store = get_store()
    scene = store.get_scene(scene_id)
    if not scene:
        return f"分镜不存在: {scene_id}"
    local_dir = video_dir()
    final_local = os.path.join(local_dir, f"{scene['scene_number']:02d}_{scene_id}.mp4")
    if not os.path.exists(final_local):
        return "这个分镜还没有已生成的视频，无法追加。请先出一段视频，再用「再续一段」加长。"

    provider = video_provider_registry.get(model)
    is_http = getattr(provider, "transport", "ssh") == "http"
    # 保留数值 0（seed=0 可复现），只剔除 None/空串——与主 i2v 渲染一致。
    merged = {**provider.default_params(),
              **{k: v for k, v in params.items() if v is not None and v != ""}}
    merged.pop("segments", None)
    seg_prompts = merged.pop("motion_prompts", None) or []
    if not isinstance(seg_prompts, list):
        seg_prompts = []
    prompt_default = _compose_wan_prompt(scene, motion_prompt)   # Wan i2v 友好(同主渲染)
    try:
        count = max(1, int(count or 1))
    except (TypeError, ValueError):
        count = 1

    gpu = None
    if not is_http:
        try:
            gpu = get_gpu_client()
        except GpuConfigError as e:
            return f"GPU 未配置: {e}"

    from mirage.app.pipeline.assembler import extract_last_frame, concat_videos
    # 续段前给现有成片打快照 → 「撤销上一段」可回退到本次续接之前（可多次）
    import shutil as _shutil
    try:
        _shutil.copy2(final_local, _next_undo_path(final_local))
    except OSError:
        pass
    done = 0
    try:
        for i in range(count):
            tag = f"{int(_time.time())}_{i + 1}"
            prompt_i = seg_prompts[i] if i < len(seg_prompts) and seg_prompts[i] else prompt_default
            frame_local = os.path.join(local_dir, f"{scene['scene_number']:02d}_{scene_id}_applast.png")
            extract_last_frame(final_local, frame_local)   # 取「现有成片」的末帧作起点
            new_seg = _render_one_continuation(scene_id, scene, provider, is_http, gpu,
                                               frame_local, prompt_i, merged, tag)
            tmp_final = final_local + ".tmp.mp4"
            # 去重边界帧：新段首帧=现有成片末帧(拿它当起点生成的) → 不去重会卡一帧
            concat_videos([final_local, new_seg], tmp_final, dedup_boundary=True)
            try:
                os.replace(tmp_final, final_local)         # 同目录同盘，原子替换，路径不变
            except PermissionError:
                # Windows：成片正被播放/读取会锁文件。清掉临时件，给可操作提示，不留 .tmp 残骸
                for _f in (tmp_final, new_seg):
                    try:
                        os.remove(_f)
                    except OSError:
                        pass
                hint = f"（已成功追加 {done} 段）" if done else ""
                return (f"追加失败：成片文件被占用，多半正在浏览器里播放{hint}。"
                        f"请暂停/关闭该视频后再点「再续一段」。")
            done += 1
            try:
                os.remove(new_seg)                         # 拼接后单段没用了，清掉省空间
            except OSError:
                pass
            logger.info("[append] 分镜 %s 追加第 %d/%d 段完成", scene_id, i + 1, count)
    except GpuConfigError as e:
        return f"GPU 未配置: {e}"
    except (GpuRunError, RuntimeError, OSError) as e:
        hint = f"（已成功追加 {done}/{count} 段）" if done else ""
        return f"追加视频段失败{hint}: {e}"

    store.set_scene_video(scene_id, final_local)
    store.set_scene_state(scene_id, SceneState.COMPLETED)
    msg = (f"已在分镜 {scene_id} 的成片末尾追加 {done} 段（尾帧接续），视频已变长。\n成片: {final_local}")
    return msg + f"\nVIDFILE::{scene_id}::{final_local}"


def append_uploaded_video(scene_id: str, uploaded_path: str, motion_prompt: str = "",
                          model: str = "", params: dict | None = None, count: int = 1) -> str:
    """把【上传的视频】拼到该镜成片末尾，再从它的尾帧 AI 续写 count 段（尾帧接续）。

    - 有现有成片 V：成片变 V + 上传视频 U（+ AI 续写 C）；会给 V 打撤销快照(可「撤销上一段」回退)。
    - 无现有成片：上传视频成为该镜成片，再 AI 续写。
    - 上传视频自动统一到成片分辨率/帧率、去音轨(音频在合成整集时统一加)。
    - count=0：只拼接上传视频、不 AI 续写。
    """
    import shutil as _sh
    params = params or {}
    store = get_store()
    scene = store.get_scene(scene_id)
    if not scene:
        return f"分镜不存在: {scene_id}"
    if not (uploaded_path and os.path.exists(uploaded_path)):
        return f"上传的视频文件不存在: {uploaded_path}"
    from mirage.app.pipeline.assembler import conform_video, concat_videos, _video_size
    local_dir = video_dir()
    final_local = os.path.join(local_dir, f"{scene['scene_number']:02d}_{scene_id}.mp4")
    has_final = os.path.exists(final_local)
    tw = th = 0
    if has_final:
        try:
            tw, th = _video_size(final_local)        # 对齐现有成片分辨率，避免拼接尺寸不一
        except Exception:  # noqa: BLE001
            tw = th = 0
    fps = int(params.get("fps") or settings.COMFYUI_FPS)
    conformed = os.path.join(local_dir, f"{scene['scene_number']:02d}_{scene_id}_upload.mp4")
    try:
        conform_video(uploaded_path, conformed, tw, th, fps)
    except Exception as e:  # noqa: BLE001
        return f"上传视频转码失败: {e}"
    if has_final:
        try:
            _sh.copy2(final_local, _next_undo_path(final_local))     # 撤销快照
        except OSError:
            pass
        tmp = final_local + ".tmp.mp4"
        try:
            concat_videos([final_local, conformed], tmp, dedup_boundary=False)  # 上传段非续生成，不去边界帧
            os.replace(tmp, final_local)
        except Exception as e:  # noqa: BLE001
            for _f in (tmp, conformed):
                try:
                    os.remove(_f)
                except OSError:
                    pass
            return f"拼接上传视频失败: {e}"
        try:
            os.remove(conformed)
        except OSError:
            pass
    else:
        try:
            os.replace(conformed, final_local)
        except OSError:
            _sh.copy2(conformed, final_local)
            try:
                os.remove(conformed)
            except OSError:
                pass
    store.set_scene_video(scene_id, final_local)
    store.set_scene_state(scene_id, SceneState.COMPLETED, force=True)
    head = f"已把上传视频接到分镜 {scene_id} 成片末尾。"
    try:
        cnt = max(0, int(count if count is not None else 1))
    except (TypeError, ValueError):
        cnt = 1
    if cnt >= 1:
        cont = append_scene_segment(scene_id, motion_prompt, model, params, cnt)
        return head + " 并从其尾帧 AI 续写：\n" + cont
    return head + f"\nVIDFILE::{scene_id}::{final_local}"


@tool
def append_scene_video(scene_id: str, motion_prompt: str = "", model: str = "",
                       size: str = "", segments: int = 1) -> str:
    """在分镜【已生成视频】的末尾，按尾帧接续再追加 segments 段，让它变长（看效果再加，可反复用）。

    用户说"这镜再长一点/后面再接一段/不够长"且该镜已有成片时用本工具，
    比重出整条更省（只生成新增的段并拼到末尾）。段数不写死，想加几段填几段。

    Args:
        scene_id: 分镜 ID（必须已经出过视频）。
        motion_prompt: 新增段的运镜/动态提示词；留空用分镜自带的。
        model: 视频模型名；空=默认。
        size: 分辨率；空=默认（建议与原片一致，否则拼接会重编码）。
        segments: 追加多少段（默认 1）。
    """
    params: dict = {}
    if size:
        params["size"] = size
    return append_scene_segment(scene_id, motion_prompt, model, params, count=segments)


@tool
def project_status(project_id: str) -> str:
    """查看整个项目的进度汇总（JSON），含每个分镜状态与产物。"""
    try:
        st = get_store().status(project_id)
    except ValueError as e:
        return f"{e}"
    return json.dumps(st, ensure_ascii=False, indent=2)


@tool
def open_production_panel(project_id: str) -> str:
    """【拆完分镜后必调】为项目打开「制作面板」：用户在面板上一键全部出图、逐个点选、一键出片合成，
    全程点按钮、不用再逐条对话。拆好所有分镜后调用本工具，然后让用户去面板操作即可，不要自己逐个出图。

    Args:
        project_id: 项目 ID。
    """
    return (f"已为项目打开制作面板，请在下方面板里操作：先「一键全部出图」，"
            f"每个分镜点选一张满意的图，再「一键出片并合成」。\nPRODUCTION::{project_id}")


@tool
def assemble_episode(project_id: str, voice: str = "", with_subtitles: bool = True) -> str:
    """【成片合成】把项目下所有已出片的分镜按顺序拼成一条完整短剧 mp4（本地完成，不占 GPU）。

    自动：分镜旁白(narration)经 TTS 配音、音画对齐（旁白长则末帧冻结）、统一分辨率、
    旁白字幕（烧录优先）。产物 episode_<project>.mp4 落工作目录 video_out 并内嵌播放。

    用户说"合成/拼起来/出完整视频/成片"时调用。需至少一个分镜已完成出片。

    Args:
        project_id: 项目 ID。
        voice: TTS 音色；空=默认男声 zh-CN-YunxiNeural（女声可用 zh-CN-XiaoxiaoNeural）。
        with_subtitles: 是否加旁白字幕（默认加）。
    """
    from mirage.app.pipeline.assembler import assemble_clips, DEFAULT_VOICE

    store = get_store()
    try:
        st = store.status(project_id)
    except ValueError as e:
        return f"{e}"
    scenes = sorted(st["scenes"], key=lambda s: s["scene_number"])
    if not scenes:
        return "项目下没有分镜。"

    local = video_dir()
    # 角色音色表(声音圣经)：说话人名 → 该角色 TTS 音色，供多角色对话逐句配音
    char_voice = {}
    try:
        for _c in (store.list_characters(project_id) or []):
            _nm = (_c.get("name") or "").strip()
            if _nm:
                char_voice[_nm] = (_c.get("voice") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    clips, missing = [], []
    for s in scenes:
        p = os.path.join(local, f"{s['scene_number']:02d}_{s['id']}.mp4")
        if not os.path.isfile(p):
            missing.append(f"#{s['scene_number']} {s['title'] or s['id']}（状态 {s['state']}）")
            continue
        clip = {"path": p, "narration": s.get("narration") or "",
                "subtitle": s.get("subtitle") or "", "title": s.get("title") or "",
                "voice": s.get("voice") or "",   # 每镜音色(角色圣经)；空=用全集默认
                # 对口型(S2V)片自带人声→别重配音(否则口型错位)；但 t2v 片无音轨,必须走 TTS 配音 → 不 keep_audio
                "keep_audio": bool(s.get("lipsync")) and (s.get("video_mode") or "i2v") != "t2v"}
        # 多角色对话「说话人：台词」逐行 → 各自匹配角色音色；字幕用对话原文。仅非对口型镜生效。
        _dlg = []
        for _raw in (s.get("dialogue") or "").splitlines():
            _raw = _raw.strip()
            if not _raw:
                continue
            _spk, _sep, _txt = _raw.partition("：")
            if not _sep:
                _spk, _sep, _txt = _raw.partition(":")
            _spk, _txt = (_spk.strip(), _txt.strip()) if _sep else ("", _raw)
            if not _txt:
                continue
            _dlg.append({"speaker": _spk, "text": _txt, "voice": char_voice.get(_spk, "")})
        if _dlg and not clip["keep_audio"]:
            clip["dialogue"] = _dlg
            clip["subtitle"] = "\n".join((d["speaker"] + "：" + d["text"]) if d["speaker"] else d["text"] for d in _dlg)
        clips.append(clip)
    if not clips:
        return "没有任何分镜已出片，请先对各分镜出图→选图→出视频。"

    out = os.path.join(local, f"episode_{project_id}.mp4")
    try:
        info = assemble_clips(clips, out, voice=(voice or DEFAULT_VOICE),
                              with_subtitles=with_subtitles)
    except Exception as e:  # noqa: BLE001
        return f"成片合成失败: {type(e).__name__}: {e}"

    msg = (f"成片完成：{info['scenes']} 段分镜 → {info['duration']:.1f} 秒"
           f"（旁白TTS={'有' if info['tts'] else '无'}，字幕={info['subtitles']}）。\n"
           f"输出: {out}")
    if missing:
        msg += "\n未纳入（尚未出片）: " + "、".join(missing)
    return msg + f"\nVIDFILE::episode::{out}"


def upscale_video(scene_id: str = "", project_id: str = "", kind: str = "scene",
                  width: int = 0, height: int = 0, method: str = "auto") -> str:
    """一键转规格：把某个已生成的低清成片放大到目标 width×height（如 4K），落**独立新文件**（不覆盖原片）。

    kind='scene' → 转某个分镜成片；kind='episode' → 转整集成片。引擎 method=auto/comfyui/ffmpeg（可配）。
    """
    from mirage.app.pipeline import postprocess
    from mirage.app.pipeline import log_bus
    w, h = int(width or 0), int(height or 0)
    if w <= 0 or h <= 0:
        return "转规格失败：目标宽高无效。"
    if kind == "episode":
        if not project_id:
            return "转规格失败：缺 project_id。"
        src = os.path.join(video_dir(), f"episode_{project_id}.mp4")
        tag = "episode"
    else:
        st = get_store()
        scene = st.get_scene(scene_id)
        if not scene:
            return f"分镜不存在: {scene_id}"
        src = (scene.get("video")
               or os.path.join(video_dir(), f"{scene.get('scene_number', 0):02d}_{scene_id}.mp4"))
        tag = scene_id
    if not os.path.exists(src):
        return f"转规格失败：找不到成片 {src}（先出片/合成）。"
    out = os.path.splitext(src)[0] + f"_{w}x{h}.mp4"
    log_bus.emit(f"[转规格] {os.path.basename(src)} → {w}×{h} …")
    r = postprocess.upscale_to(src, out, width=w, height=h, method=method)
    if not r.get("applied"):
        return f"转规格失败：{r.get('note')}"
    return (f"已转规格 {w}×{h}（{r.get('note')}）。原片保留：{os.path.basename(src)}\n"
            f"VIDFILE::{tag}::{out}")


def faceswap_scene_video(scene_id: str = "", face_path: str = "", project_id: str = "",
                         kind: str = "scene") -> str:
    """一键换脸：把 face_path 的源脸换到某分镜/整集【已有成片】里的人物上，产物落独立新文件(不覆盖原片)。

    kind='scene' → 换某分镜成片；kind='episode' → 换整集成片。源脸由前端上传后存盘传入 face_path。
    合规红线：仅用于你有权使用的脸(原创/AI 生成/本人授权)；换可识别真人=deepfake,平台 ToS 与法律禁止。
    """
    from mirage.app.pipeline import faceswap, log_bus
    if not (face_path and os.path.exists(face_path)):
        return "换脸失败：源脸图片缺失（先上传一张脸）。"
    if kind == "episode":
        if not project_id:
            return "换脸失败：缺 project_id。"
        src = os.path.join(video_dir(), f"episode_{project_id}.mp4")
        tag = "episode"
    else:
        st = get_store()
        scene = st.get_scene(scene_id)
        if not scene:
            return f"分镜不存在: {scene_id}"
        src = (scene.get("video")
               or os.path.join(video_dir(), f"{scene.get('scene_number', 0):02d}_{scene_id}.mp4"))
        tag = scene_id
    if not os.path.exists(src):
        return f"换脸失败：找不到成片 {src}（先出片/合成）。"
    out = os.path.splitext(src)[0] + "_swap.mp4"
    log_bus.emit(f"[换脸] {os.path.basename(src)} ← 源脸 …")
    r = faceswap.faceswap_video(src, face_path, out)
    if not r.get("applied"):
        return f"换脸失败：{r.get('note')}"
    return (f"换脸完成（产物为独立新文件，原片保留：{os.path.basename(src)}）。\n"
            f"VIDFILE::{tag}::{out}")


@tool
def configure_character(trigger_word: str = "", flux_lora: str = "", negative_prompt: str = "") -> str:
    """配置本工作目录的角色/风格（写入 .agent/config.json），出图时自动注入，无需写死在提示词里。

    用户说"这个角色的触发词是 X""用这个 LoRA""换成 XX 风格"等时调用本工具。
    只更新填了的字段，留空的不动。

    Args:
        trigger_word: 角色/LoRA 触发词，出图时自动加在提示词最前（如某个角色的专属触发词）。
        flux_lora: FLUX LoRA 文件在 GPU 上的路径；留空则用 .env 默认。
        negative_prompt: 可选负向提示词。
    """
    import os
    lora_in = (flux_lora or "").strip()
    lora_to_set = None                       # None=不动该字段（留空时不覆盖既有配置）
    warn = ""
    if lora_in and lora_in.lower() != "none":
        name = os.path.basename(lora_in)
        try:
            from mirage.app.pipeline import comfy_http as ch
            avail = ch.available_loras(ch.base_url())
        except Exception:  # noqa: BLE001
            avail = None
        if avail is not None and name not in avail:
            sample = "、".join(sorted(avail)[:8]) or "（loras 目录为空）"
            return (f"❌ 没给你设 LoRA：ComfyUI 的 loras 目录里没有「{name}」这个文件——"
                    f"硬设会让出图被校验打回、整批失败（这正是刚才的故障）。\n"
                    f"现有可用 LoRA：{sample}。\n"
                    f"要这个角色的 LoRA：先去「角色 & LoRA」面板训练它，或把正确文件名/路径发我；"
                    f"我不会替你编一个不存在的文件名。触发词需要的话我可以单独设。")
        lora_to_set = name                   # 通过校验 or 无法核实 → 存 basename（匹配 models/loras/）
        if avail is None:
            warn = "（注：没连上 ComfyUI 核实该 LoRA 是否真实存在；出图时若不存在会自动跳过 LoRA、不再整批失败）"
    elif lora_in.lower() == "none":
        lora_to_set = ""                     # 显式清空 LoRA（回退 .env 默认）
    m = set_model_config(
        trigger_word=(trigger_word if trigger_word != "" else None),
        flux_lora=lora_to_set,
        negative_prompt=(negative_prompt if negative_prompt != "" else None),
    )
    return (f"已更新工作目录角色配置：触发词='{m['trigger_word'] or '（无）'}'，"
            f"LoRA='{m['flux_lora'] or '默认(.env)'}'。出图时会自动注入触发词。{warn}")


@tool
def get_character_config() -> str:
    """查看本工作目录当前的角色/风格配置（触发词 / LoRA / 负向词）。"""
    m = model_config()
    return json.dumps(m, ensure_ascii=False)


# ── 分组导出（供 ai_service 注入 SkillRegistry） ───────────────────
# 单轨化：request_image_params / request_video_params（对话内弹参数卡）已下线——
# 出图/选图/出片/合成一律走「制作面板」（open_production_panel），对话只负责拆分镜与答疑，
# 避免"对话卡片 + 面板"两套交互并存把用户绕晕。函数保留以兼容旧会话历史的标记重建。
pipeline_tools = [
    list_workspace_files,
    read_text_file,
    create_video_project,
    add_scene,
    list_project_scenes,
    register_candidate_image,
    generate_candidates,
    list_candidates,
    select_candidate,
    render_scene_video,
    append_scene_video,
    project_status,
    open_production_panel,
    assemble_episode,
    configure_character,
    get_character_config,
]
