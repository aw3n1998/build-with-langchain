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


def bootstrap(store, training: dict, dataset_dir: str, *, mode: str = "text",
              appearance: str = "", trigger: str = "", count: int = 0,
              ref_image: Optional[str] = None, size: Optional[str] = None,
              steps: Optional[int] = None, seed: Optional[int] = None) -> list[str]:
    """自举调度。mode=text(零图) / pulid(单脸)。返回新图路径。"""
    trigger = trigger or lora_train._slug(training.get("trigger_word") or training.get("name"))
    count = int(count or settings.LORA_BOOTSTRAP_COUNT)
    mode = (mode or "text").lower()
    if mode == "pulid":
        return bootstrap_pulid(store, training, dataset_dir, appearance=appearance, trigger=trigger,
                               count=count, ref_image=ref_image, size=size, steps=steps, seed=seed)
    return bootstrap_text(store, training, dataset_dir, appearance=appearance, trigger=trigger,
                          count=count, size=size, steps=steps, seed=seed)


# ── 后台线程launcher：自举(16 张出图耗时数分钟)不能阻塞 HTTP，异步跑 + 可选造完即训 ──
_BOOT_RUNNING: dict[str, threading.Thread] = {}
_BOOT_LOCK = threading.Lock()


def _do_bootstrap(store, tid, dataset_dir, mode, appearance, trigger, count, auto_train, size, steps, seed):
    try:
        t = store.get_lora_training(tid)
        if not t:
            return
        bootstrap(store, t, dataset_dir, mode=mode, appearance=appearance, trigger=trigger,
                  count=count, size=size, steps=steps, seed=seed)
        cnt = lora_train.count_images(dataset_dir)
        if cnt < 5:
            store.update_lora_training(tid, status="DRAFT",
                                       message=f"自举只出了 {cnt} 张(<5)。检查出图后端是否正常，或手动补图后开训。")
        elif auto_train:
            lora_train.start_training(store, tid, dataset_dir, trigger=trigger)   # 造完即训
        else:
            store.update_lora_training(tid, status="DRAFT", message=f"训练集就绪 {cnt} 张，可点开训。")
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
                    steps: Optional[int] = None, seed: Optional[int] = None) -> dict:
    """异步开始自举(+可选造完即训)。立即返回，前端轮询 lora 列表看进度。"""
    t = store.get_lora_training(training_id)
    if not t:
        raise ValueError(f"训练任务不存在: {training_id}")
    trigger = trigger or lora_train._slug(t.get("trigger_word") or t.get("name"))
    cnt = int(count or settings.LORA_BOOTSTRAP_COUNT)
    with _BOOT_LOCK:
        if training_id in _BOOT_RUNNING and _BOOT_RUNNING[training_id].is_alive():
            return t  # 已在自举，别重复
        th = threading.Thread(
            target=_do_bootstrap,
            args=(store, training_id, dataset_dir, (mode or "text"), appearance, trigger, cnt,
                  bool(auto_train), size, steps, seed),
            name=f"loraboot-{training_id[:6]}", daemon=True)
        _BOOT_RUNNING[training_id] = th
    store.update_lora_training(training_id, status="BOOTSTRAPPING", trigger_word=trigger,
                               message=f"自动造训练集中…（{mode} 模式，目标 {cnt} 张，造完{'自动开训' if auto_train else '待开训'}）")
    th.start()
    return store.get_lora_training(training_id)
