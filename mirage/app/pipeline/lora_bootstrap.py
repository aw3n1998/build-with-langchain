"""数据集自举 —— 免上传自训人物 LoRA：让系统自己造一套训练图。

两种模式(共用同一套打标 + 落盘 + 喂给 lora_train 执行器)：
- **text**（纯文字零图）：只用角色外貌提示词 + 变体(姿势/景别/光照/表情)循环出图。
  完全免上传，但 FLUX 不锁人脸 ID，多张之间脸会飘 → 适合不在意长相的配角。
  复用已跑通的 ComfyUI t2i 出图(image_provider_registry 默认 http provider)。
- **pulid**（单张脸图自举，task#27 接入）：给 1 张脸 → PuLID 锁 ID 批量同人图，脸最稳。

生成的图落进该 LoRA 任务目录(lora_train/{tid}/)，每张配 `{基名}.txt` caption
(ai-toolkit caption_ext=txt 读)。caption = 触发词 + 变体描述，让 LoRA 学「触发词=此人」
而不过拟合单一姿势。张数(count)可配(settings.LORA_BOOTSTRAP_COUNT)，变体列表是默认值、可加可减。
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger
from mirage.app.pipeline import lora_train
from mirage.app.pipeline.image_providers import image_provider_registry

logger = get_logger("pipeline.lora_bootstrap")

# 参考脸/图片扩展名(与 lora_train._IMG_EXTS 一致)；_find_ref_face 用。
_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# 变体提示词（英文，FLUX 友好；通用摄影变体，仅原创虚构成年角色）。默认列表，可加可减；
# count 超过列表长度时循环复用并换 seed，保证多样性。不写死张数。
_VARIATIONS = [
    "front view, neutral expression, plain background",
    "three-quarter view, soft studio lighting",
    "side profile portrait, plain background",
    "looking at camera, natural daylight, upper body",
    "slight smile, head and shoulders, plain background",
    "looking away, cinematic lighting",
    "close-up portrait, sharp focus, detailed face",
    "full body, standing, plain background",
    "dramatic side lighting, upper body",
    "soft backlight, head and shoulders, plain background",
    "outdoor, natural light, upper body",
    "studio headshot, even lighting, plain background",
]

_NEG = "lowres, blurry, deformed, extra fingers, watermark, text, multiple people, collage"

# 视频自举(video 模式)动作清单：教 i2v「脸转走再转回」的跨角度一致性——每段单一连贯转动动作，塞满整段
# (loader 沿整段等间距抽 num_frames 帧)。重点覆盖非正脸视角(侧/3-4/背)，否则模型没见过就转不出来。
_VIDEO_VARIATIONS = [
    "slowly turning head from front to left profile and back, plain background",
    "slowly turning head from front to right profile and back",
    "slowly rotating the whole body 180 degrees, back to camera then turning to face again",
    "slowly rotating in place a full 360 degrees, face going away and coming back into view",
    "walking a few steps then turning around to look back at the camera",
    "nodding and slightly tilting the head up and down, upper body",
    "slow camera orbit around the person, the face angle changing gradually",
    "looking left, then right, then back to center, head and shoulders",
    "three-quarter view with a slight head turn, soft studio lighting",
    "side profile slowly turning to face the camera, natural daylight",
]

_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


def _count_clips(d: str) -> int:
    """统计视频 clip 数(video 模式的"够不够开训"以此为准，而非图片数)。"""
    if not os.path.isdir(d):
        return 0
    return len([f for f in os.listdir(d) if f.lower().endswith(_VIDEO_EXTS)])


def _frame_sharp_enough(path: str, thresh: float = 60.0) -> bool:
    """Laplacian 方差判清晰度：抽出的锚帧太糊(运动模糊)就丢，免污染身份监督。cv2 缺则放行(不拦)。"""
    try:
        import cv2  # ai-toolkit/ComfyUI 环境已带 opencv
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return True
        return float(cv2.Laplacian(img, cv2.CV_64F).var()) >= thresh
    except Exception:  # noqa: BLE001
        return True


def _maybe_en(text: str) -> str:
    """外貌若是中文，按出图同款策略翻成英文(FLUX 读不懂中文)。失败/关闭则原样返回。"""
    if not settings.IMAGE_PROMPT_AUTOTRANSLATE:
        return text
    try:
        from mirage.app.pipeline.prompt_gen import translate_to_english
        return translate_to_english(text) or text
    except Exception:  # noqa: BLE001
        return text


def _write_caption(img_path: str, caption: str) -> None:
    cap = os.path.splitext(img_path)[0] + ".txt"
    with open(cap, "w", encoding="utf-8") as f:
        f.write(caption)


def bootstrap_text(store, training: dict, dataset_dir: str, *, appearance: str, trigger: str,
                   count: int, size: Optional[str] = None, steps: Optional[int] = None,
                   seed: Optional[int] = None) -> list[str]:
    """纯文字零图自举：外貌 + 变体循环出图，落 dataset_dir + 写 caption。返回新图路径。"""
    provider = image_provider_registry.get("")        # "" → 默认出图 provider（Colab 上是 ComfyUI/http）
    if provider is None:
        raise RuntimeError("没有可用的出图后端，无法自举训练集。")
    if getattr(provider, "transport", "ssh") != "http":
        raise RuntimeError("自动造训练集目前需要 ComfyUI(http)出图后端(Colab)。SSH 出图后端暂不支持自举。")

    app_en = _maybe_en(appearance or "") or trigger
    base_seed = seed if (seed is not None and seed >= 0) else int(time.time_ns() % 2_000_000_000)
    made: list[str] = []
    os.makedirs(dataset_dir, exist_ok=True)
    for i in range(max(1, int(count))):
        var = _VARIATIONS[i % len(_VARIATIONS)]
        prompt = f"{app_en}, {var}, photorealistic, high detail, solo, one person"
        params = {
            "n": 1,
            "size": size or settings.COMFYUI_T2I_SIZE,
            "steps": steps or settings.COMFYUI_T2I_STEPS,
            "seed": (base_seed + i) % 2_000_000_000,
            "negative": _NEG,
            "flux_lora": "none",        # 自举=造新角色训练集，不叠任何已有 LoRA
        }
        try:
            paths = provider.generate(None, prompt=prompt, out_dir=dataset_dir, params=params)
        except Exception as e:  # noqa: BLE001
            logger.warning("自举出图第 %d 张失败：%s", i + 1, e)
            continue
        for p in paths:
            _write_caption(p, f"{trigger}, {var}")
            made.append(p)
        store.update_lora_training(training["id"], image_count=lora_train.count_images(dataset_dir),
                                   message=f"自动造训练集中…已 {len(made)}/{count} 张")
    cnt = lora_train.count_images(dataset_dir)
    store.update_lora_training(training["id"], image_count=cnt,
                               message=f"自动造训练集完成：生成 {len(made)} 张（目录共 {cnt} 张）。可点开训。")
    logger.info("文字自举完成 tid=%s 生成 %d 张", training["id"], len(made))
    return made


def _find_ref_face(dataset_dir: str) -> Optional[str]:
    """PuLID 参考脸：取 {dataset_dir}/_ref/ 下第一张图（上传时存这，不计入训练图数）。"""
    rd = os.path.join(dataset_dir, "_ref")
    if os.path.isdir(rd):
        for fn in sorted(os.listdir(rd)):
            if fn.lower().endswith(_IMG_EXTS):
                return os.path.join(rd, fn)
    return None


def bootstrap_pulid(store, training: dict, dataset_dir: str, *, appearance: str, trigger: str,
                    count: int, ref_image: Optional[str] = None, size: Optional[str] = None,
                    steps: Optional[int] = None, seed: Optional[int] = None) -> list[str]:
    """单张脸图自举：PuLID 锁参考脸 ID，批量生成同一身份多张(换姿势/景别/光照)，落盘 + 打标。"""
    import shutil

    import httpx

    from mirage.app.pipeline import comfy_http as ch

    ref = ref_image or _find_ref_face(dataset_dir)
    if not ref or not os.path.exists(ref):
        raise RuntimeError("PuLID 单脸自举需要先上传 1 张参考脸图。")
    base = ch.base_url()
    template = ch.load_workflow(settings.COMFYUI_WORKFLOW_PULID, "pulid_t2i_template.json", "pulid-t2i")
    size = size or settings.COMFYUI_T2I_SIZE
    try:
        width, height = (int(x) for x in str(size).replace("x", "*").split("*"))
    except ValueError:
        width, height = 768, 1024
    app_en = _maybe_en(appearance or "") or trigger
    base_seed = seed if (seed is not None and seed >= 0) else int(time.time_ns() % 2_000_000_000)
    made: list[str] = []
    os.makedirs(dataset_dir, exist_ok=True)
    with httpx.Client() as client:
        face_name = ch.upload_image(client, base, ref)        # 参考脸传到 ComfyUI input 区
        client_id = f"mirage-pulid-{os.getpid()}-{int(time.time())}"
        for i in range(max(1, int(count))):
            var = _VARIATIONS[i % len(_VARIATIONS)]
            prompt = f"{app_en}, {var}, photorealistic, high detail, solo, one person"
            mapping = {
                "%UNET%": settings.COMFYUI_FLUX_UNET or "flux1-dev.safetensors",
                "%PULID_MODEL%": settings.PULID_MODEL,
                "%FACE%": face_name,
                "%PULID_WEIGHT%": float(settings.PULID_WEIGHT),
                "%PROMPT%": prompt,
                "%NEG_PROMPT%": _NEG,
                "%GUIDANCE%": float(settings.PULID_GUIDANCE),
                "%WIDTH%": width, "%HEIGHT%": height,
                "%STEPS%": int(steps or settings.COMFYUI_T2I_STEPS),
                "%SEED%": (base_seed + i) % 2_000_000_000,
            }
            graph = ch.fill_template(template, mapping)
            try:
                pid = ch.submit(client, base, graph, client_id)
                outs = ch.wait(client, base, pid, label="pulid")
            except Exception as e:  # noqa: BLE001
                logger.warning("PuLID 自举第 %d 张失败：%s", i + 1, e)
                continue
            for it in ch.collect_outputs(outs):
                fn = it.get("filename", "")
                if fn.lower().endswith(ch.IMAGE_EXTS):
                    out_path = os.path.join(dataset_dir, f"pulid_{i:02d}_{fn}")
                    try:
                        ch.download_view(client, base, it, out_path)
                        _write_caption(out_path, f"{trigger}, {var}")
                        made.append(out_path)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("PuLID 下载第 %d 张失败：%s", i + 1, e)
                    break
            store.update_lora_training(training["id"], image_count=lora_train.count_images(dataset_dir),
                                       message=f"PuLID 单脸自举中…已 {len(made)}/{count} 张")
    # 真实参考脸也纳入训练集(它是该角色的真图，有助一致性)
    try:
        ext = os.path.splitext(ref)[1].lower() or ".png"
        dst = os.path.join(dataset_dir, f"ref_face{ext}")
        if not os.path.exists(dst):
            shutil.copy(ref, dst)
            _write_caption(dst, f"{trigger}, portrait, reference")
    except Exception:  # noqa: BLE001
        pass
    cnt = lora_train.count_images(dataset_dir)
    store.update_lora_training(training["id"], image_count=cnt,
                               message=f"PuLID 单脸自举完成：生成 {len(made)} 张（目录共 {cnt} 张）。可点开训。")
    logger.info("PuLID 自举完成 tid=%s 生成 %d 张", training["id"], len(made))
    return made


def pulid_generate(ref_image: str, prompt: str, *, out_dir: str, n: int = 1,
                   size: Optional[str] = None, steps: Optional[int] = None,
                   seed: Optional[int] = None, negative: Optional[str] = None,
                   guidance: Optional[float] = None, name_prefix: str = "pulid") -> list[str]:
    """PuLID 单参考脸【直出】：锁定 ref_image 的人脸 ID，按 prompt 出 n 张落 out_dir，返回本地路径。

    供 batch_generate「角色有参考脸 → 锁脸出图」复用，免训练即可跨镜同一张脸。
    与 bootstrap_pulid 共用同一套 ComfyUI 调用（pulid_t2i_template.json）；这里不写 caption、
    不做训练集 bookkeeping，纯出图。失败按 comfy_http 约定抛 GpuConfigError/GpuRunError。
    """
    import httpx

    from mirage.app.pipeline import comfy_http as ch
    from mirage.app.pipeline.gpu_client import GpuRunError

    if not ref_image or not os.path.exists(ref_image):
        raise GpuRunError(f"PuLID 锁脸出图需要角色参考脸，未找到：{ref_image}")
    base = ch.base_url()
    template = ch.load_workflow(settings.COMFYUI_WORKFLOW_PULID, "pulid_t2i_template.json", "pulid-t2i")
    size = size or settings.COMFYUI_T2I_SIZE
    try:
        width, height = (int(x) for x in str(size).replace("x", "*").split("*"))
    except ValueError:
        width, height = 768, 1024
    base_seed = seed if (seed is not None and seed >= 0) else int(time.time_ns() % 2_000_000_000)
    neg = negative or _NEG
    made: list[str] = []
    os.makedirs(out_dir, exist_ok=True)
    with httpx.Client() as client:
        face_name = ch.upload_image(client, base, ref_image)
        client_id = f"mirage-pulid-{os.getpid()}-{int(time.time())}"
        for i in range(max(1, int(n))):
            mapping = {
                "%UNET%": settings.COMFYUI_FLUX_UNET or "flux1-dev.safetensors",
                "%PULID_MODEL%": settings.PULID_MODEL,
                "%FACE%": face_name,
                "%PULID_WEIGHT%": float(settings.PULID_WEIGHT),
                "%PROMPT%": prompt,
                "%NEG_PROMPT%": neg,
                "%GUIDANCE%": float(guidance if guidance is not None else settings.PULID_GUIDANCE),
                "%WIDTH%": width, "%HEIGHT%": height,
                "%STEPS%": int(steps or settings.COMFYUI_T2I_STEPS),
                "%SEED%": (base_seed + i) % 2_000_000_000,
            }
            graph = ch.fill_template(template, mapping)
            pid = ch.submit(client, base, graph, client_id)
            outs = ch.wait(client, base, pid, label="pulid")
            for it in ch.collect_outputs(outs):
                fn = it.get("filename", "")
                if fn.lower().endswith(ch.IMAGE_EXTS):
                    out_path = os.path.join(out_dir, f"{name_prefix}_{i:02d}_{fn}")
                    ch.download_view(client, base, it, out_path)
                    made.append(out_path)
                    break
    return made


def bootstrap_video(store, training: dict, dataset_dir: str, *, appearance: str, trigger: str,
                    count: int, size: Optional[str] = None, steps: Optional[int] = None,
                    seed: Optional[int] = None) -> list[str]:
    """视频自举(造 i2v 原生 LoRA 训练集)：用【项目已训好的 t2v LoRA】按转身动作清单批量出短视频 clip
    (.mp4)落 dataset_dir + 同名 .txt；再抽每段首帧(过糊则丢)落 dataset_dir/_imgs 当静图锚桶(治脸漂)。
    之后 start_training(mode='i2v') 喂视频训 i2v。★前置：项目须已有训好的 t2v LoRA(否则身份不稳、白造)。"""
    from mirage.app.pipeline.assembler import extract_first_frame
    from mirage.app.pipeline.providers import video_provider_registry

    pid = training.get("project_id")
    try:
        pstyle = (store.get_project_style(pid) or {}) if pid else {}
    except Exception:  # noqa: BLE001
        pstyle = {}
    hi = (pstyle.get("wan_t2v_lora_high") or settings.WAN_T2V_LORA_HIGH or "").strip()
    lo = (pstyle.get("wan_t2v_lora_low") or settings.WAN_T2V_LORA_LOW or "").strip()
    if not hi:
        raise RuntimeError("造 i2v 视频集需要项目已有训好的 t2v 角色 LoRA(先训 t2v、自动挂上后再来造)。")
    prov = video_provider_registry.get(settings.T2V_PROVIDER or "comfyui-t2v")
    if prov is None or getattr(prov, "transport", "ssh") != "http":
        raise RuntimeError("造 i2v 视频集需要 ComfyUI(http) t2v 出片后端(Colab)。")

    app_en = _maybe_en(appearance or "") or trigger
    base_seed = seed if (seed is not None and seed >= 0) else int(time.time_ns() % 2_000_000_000)
    imgs_dir = dataset_dir.rstrip("/\\") + "_imgs"   # 同级目录(非子目录)：与 build_aitk_config 一致，避免被视频桶 glob
    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(imgs_dir, exist_ok=True)
    made: list[str] = []
    for i in range(max(1, int(count))):
        var = _VIDEO_VARIATIONS[i % len(_VIDEO_VARIATIONS)]
        prompt = f"{app_en}, {var}, photorealistic, high detail, solo, one person"
        params = {
            "wan_t2v_lora_high": hi, "wan_t2v_lora_low": lo or hi,   # 挂项目 t2v LoRA → 同一张脸
            "lightning": "1",                                         # 极速档(蒸馏 LoRA)；否则满档 4 步=噪声
            "size": size or settings.COMFYUI_T2I_SIZE,                # 竖屏
            "frames": int(settings.COMFYUI_FRAMES),                   # 81 帧 → i2v loader 抽 81 帧够用
            "fps": int(settings.COMFYUI_FPS),
            "seed": (base_seed + i) % 2_000_000_000,
        }
        out_clip = os.path.join(dataset_dir, f"clip_{i:02d}.mp4")
        try:
            prov.generate(None, image_path="", prompt=prompt, out_remote=out_clip, params=params)
        except Exception as e:  # noqa: BLE001
            logger.warning("造 i2v clip 第 %d 段失败：%s", i + 1, e)
            continue
        if not (os.path.exists(out_clip) and os.path.getsize(out_clip) > 0):
            continue
        _write_caption(out_clip, f"{trigger}, {var}")                # clip_XX.txt：触发词+动作(不写五官)
        made.append(out_clip)
        # 抽首帧 → 静图锚桶(干净身份监督)；运动模糊太糊的丢掉
        try:
            anchor = os.path.join(imgs_dir, f"anchor_{i:02d}.png")
            extract_first_frame(out_clip, anchor)
            if os.path.exists(anchor) and _frame_sharp_enough(anchor):
                _write_caption(anchor, f"{trigger}, portrait")
            elif os.path.exists(anchor):
                os.remove(anchor)                                    # 太糊→不进锚桶
        except Exception as e:  # noqa: BLE001
            logger.warning("抽锚帧第 %d 失败：%s", i + 1, e)
        store.update_lora_training(training["id"], image_count=_count_clips(dataset_dir),
                                   message=f"造 i2v 视频集中…已 {len(made)}/{count} 段")
    n_clip = _count_clips(dataset_dir)
    n_anchor = lora_train.count_images(imgs_dir)
    store.update_lora_training(training["id"], image_count=n_clip,
                               message=f"i2v 视频集就绪：{n_clip} 段 clip + {n_anchor} 张锚帧。可点开训(i2v)。")
    logger.info("视频自举完成 tid=%s clip=%d 锚帧=%d", training["id"], n_clip, n_anchor)
    return made


def bootstrap(store, training: dict, dataset_dir: str, *, mode: str = "text",
              appearance: str = "", trigger: str = "", count: int = 0,
              ref_image: Optional[str] = None, size: Optional[str] = None,
              steps: Optional[int] = None, seed: Optional[int] = None) -> list[str]:
    """自举调度。mode=text(零图) / pulid(单脸) / video(t2v LoRA 造转身视频→i2v 集)。返回新产物路径。"""
    trigger = trigger or lora_train._slug(training.get("trigger_word") or training.get("name"))
    count = int(count or settings.LORA_BOOTSTRAP_COUNT)
    mode = (mode or "text").lower()
    if mode == "video":
        return bootstrap_video(store, training, dataset_dir, appearance=appearance, trigger=trigger,
                               count=count, size=size, steps=steps, seed=seed)
    if mode == "pulid":
        return bootstrap_pulid(store, training, dataset_dir, appearance=appearance, trigger=trigger,
                               count=count, ref_image=ref_image, size=size, steps=steps, seed=seed)
    return bootstrap_text(store, training, dataset_dir, appearance=appearance, trigger=trigger,
                          count=count, size=size, steps=steps, seed=seed)


# ── 后台线程launcher：自举(16 张出图耗时数分钟)不能阻塞 HTTP，异步跑 + 可选造完即训 ──
_BOOT_RUNNING: dict[str, threading.Thread] = {}
_BOOT_LOCK = threading.Lock()


def _do_bootstrap(store, tid, dataset_dir, mode, appearance, trigger, count, auto_train, size, steps, seed,
                  train_mode="t2v"):
    try:
        t = store.get_lora_training(tid)
        if not t:
            return
        bootstrap(store, t, dataset_dir, mode=mode, appearance=appearance, trigger=trigger,
                  count=count, size=size, steps=steps, seed=seed)
        # video 模式产物是 clip(.mp4)，"够不够开训"以 clip 数为准；其余模式以图片数为准。
        cnt = _count_clips(dataset_dir) if mode == "video" else lora_train.count_images(dataset_dir)
        unit = "段 clip" if mode == "video" else "张"
        if cnt < 5:
            store.update_lora_training(tid, status="DRAFT",
                                       message=f"自举只出了 {cnt} {unit}(<5)。检查出图后端是否正常，或手动补后开训。")
        elif auto_train:
            # ★造完即训按 train_mode 走 t2v/i2v(原先写死 t2v=隐患)；video 模式→i2v 原生 LoRA
            lora_train.start_training(store, tid, dataset_dir, trigger=trigger, mode=(train_mode or "t2v"))
        else:
            store.update_lora_training(tid, status="DRAFT", message=f"训练集就绪 {cnt} {unit}，可点开训。")
    except Exception as e:  # noqa: BLE001
        logger.exception("自举异常 tid=%s", tid)
        try:
            store.update_lora_training(tid, status="FAILED", message=f"自举失败：{e}")
        except Exception:  # noqa: BLE001
            pass
    finally:
        with _BOOT_LOCK:
            _BOOT_RUNNING.pop(tid, None)


def start_bootstrap(store, training_id: str, dataset_dir: str, *, mode: str = "text",
                    appearance: str = "", trigger: str = "", count: int = 0,
                    auto_train: bool = True, size: Optional[str] = None,
                    steps: Optional[int] = None, seed: Optional[int] = None,
                    train_mode: str = "t2v") -> dict:
    """异步开始自举(+可选造完即训)。立即返回，前端轮询 lora 列表看进度。
    train_mode=造完即训的目标(t2v/i2v)；video 模式应传 i2v。"""
    t = store.get_lora_training(training_id)
    if not t:
        raise ValueError(f"训练任务不存在: {training_id}")
    trigger = trigger or lora_train._slug(t.get("trigger_word") or t.get("name"))
    cnt = int(count or settings.LORA_BOOTSTRAP_COUNT)
    _unit = "段" if (mode or "") == "video" else "张"
    with _BOOT_LOCK:
        if training_id in _BOOT_RUNNING and _BOOT_RUNNING[training_id].is_alive():
            return t  # 已在自举，别重复
        th = threading.Thread(
            target=_do_bootstrap,
            args=(store, training_id, dataset_dir, (mode or "text"), appearance, trigger, cnt,
                  bool(auto_train), size, steps, seed, (train_mode or "t2v")),
            name=f"loraboot-{training_id[:6]}", daemon=True)
        _BOOT_RUNNING[training_id] = th
        # 登记 + 状态写 + start() 纳入同一把锁：否则"已登记未 start"窗口里 is_alive()==False，
        # 并发调用会误判"没在自举"而重复开线程（与 lora_train.py 的 29c1e9f 加固一致）。
        store.update_lora_training(training_id, status="BOOTSTRAPPING", trigger_word=trigger,
                                   message=f"自动造训练集中…（{mode} 模式，目标 {cnt} {_unit}，造完{'自动开训' if auto_train else '待开训'}）")
        th.start()
    return store.get_lora_training(training_id)
