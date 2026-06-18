"""人物 LoRA 训练执行器。

Colab 单机(后端 + ai-toolkit + ComfyUI 同机)→ 默认**本地子进程**训练：
    {sys.executable} {settings.AI_TOOLKIT_DIR}/run.py {config}
照搬 notebook colab_deploy.ipynb LW1/LW2 的 **Wan2.2-T2V** ai-toolkit 配方
(sd_trainer / lora / arch=wan22_14b MoE 双专家 / caption_ext=txt)。**一次出 high+low 两个**
safetensors 拷到 settings.COMFYUI_LORA_DIR —— t2v 文生视频出片按文件名加载这套 LoRA。
（前端「角色 & LoRA」的「开始训练 / 造图+开训」入口走这里；FLUX 图像 LoRA 训练已弃用。）

可插拔：settings.LORA_TRAIN_ENDPOINT 非空时改为 POST 远程训练服务，
不改代码即可在「本地跑」与「远程派发」之间切换(SSH/独立 GPU 场景)。

线程模型：本地训练在 daemon 线程里跑(单次约数十分钟)，用传入的 store
更新状态(PipelineStore 每次操作开新 check_same_thread=False 连接，跨线程安全)。
注意：训练子进程是后端进程的子进程，后端若被重启(Colab 断线)会一并中断 →
状态停在 TRAINING，用户重新开训即可(v1 不做断点续训)。
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from typing import Optional

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("pipeline.lora_train")

# 正在本地训练的任务(防同一任务重复开训)。tid -> Thread
_RUNNING: dict[str, threading.Thread] = {}
_RUNNING_LOCK = threading.Lock()

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _slug(s: Optional[str]) -> str:
    """安全文件名/触发词：仅留小写字母数字下划线连字符；空则回退。"""
    s = re.sub(r"[^a-z0-9_\-]+", "_", (s or "").strip().lower()).strip("_")
    return s or "char"


# 角色 LoRA「完全对不上人物」的头号坑：拿常见词当触发词。
# 触发词必须是【无预训练语义的罕见 token】，身份才会绑到它身上；用 char/person/角色名 这类
# 常见词，身份会糊进该词原有语义→出片渲染的是预训练里的「某个人」而非你训的人（症状：完全是别人）。
# 官方 ai-toolkit 示例特意用 p3r5on（而非 person）就是这个道理。
_COMMON_TRIGGERS = {
    "char", "chars", "character", "characters", "person", "people", "human", "humans",
    "man", "men", "woman", "women", "boy", "girl", "guy", "lady", "male", "female",
    "face", "portrait", "subject", "model", "figure", "actor", "actress", "hero",
    "img", "image", "photo", "pic", "ohwx",  # ohwx 太常被教程用、已被污染
}


def _rare_trigger(name: Optional[str] = None, seed: str = "") -> str:
    """生成一个【罕见、无预训练语义】的触发 token——角色身份能否绑定的命门。

    取 name(+seed) 的稳定哈希拼成 zq<6hex>（如 zq3f9a1c）：稀有、确定、跨机一致、可复现。
    不用随机数（构建环境禁随机、且同名要稳定出同一 token，caption 与出片注入才会一致）。
    """
    import hashlib
    base = f"{(name or '').strip().lower()}|{seed}".encode("utf-8")
    return "zq" + hashlib.md5(base).hexdigest()[:6]


def effective_trigger(stored: Optional[str], name: Optional[str] = None) -> str:
    """把「用户填的触发词」规整成真正能用的 token——caption 打标、出片注入、测试预览统一走这里，保证一致。

    规则：用户填了好词（罕见、非常见词）→ 清洗后直接用；留空 / 填了常见词（char/person/角色名…）
    → 自动换成 _rare_trigger 生成的罕见 token（这是身份绑得上的前提，用户无需自己琢磨触发词）。
    """
    raw = (stored or "").strip()
    s = _slug(raw)                      # 注意 _slug 空输入会回退成 "char"
    nm = _slug(name)                    # 角色名 slug 也算「常见词」（名字有预训练语义）
    if (not raw) or s in _COMMON_TRIGGERS or s == nm:
        return _rare_trigger(name or raw)
    return s


def is_local_runner() -> bool:
    """空 LORA_TRAIN_ENDPOINT = 本地 ai-toolkit 子进程(Colab 单机默认)。"""
    return not (settings.LORA_TRAIN_ENDPOINT or "").strip()


def _resolve_low_vram() -> bool:
    """是否开 low_vram(把闲置专家挪 CPU 省显存)。auto=按显存：>48G 全 GPU 训(快、GPU 吃满)、≤48G 省显存。
    也可 LORA_TRAIN_LOW_VRAM=true/false 强制。"""
    v = str(settings.LORA_TRAIN_LOW_VRAM or "auto").strip().lower()
    if v in ("true", "1", "yes", "on"):
        return True
    if v in ("false", "0", "no", "off"):
        return False
    try:  # auto：按显存决定
        import torch
        gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        return gb <= 48     # >48G(A100-80/H100/大卡)→全 GPU 训；≤48G→挪 CPU 省显存
    except Exception:  # noqa: BLE001
        return True         # 探测不到显存 → 保守省显存


def count_images(dataset_dir: str) -> int:
    if not os.path.isdir(dataset_dir):
        return 0
    return len([x for x in os.listdir(dataset_dir) if x.lower().endswith(_IMG_EXTS)])


def build_aitk_config(name: str, dataset_dir: str, trigger: str, base: str,
                      steps: int, training_folder: str) -> dict:
    """生成 ai-toolkit **Wan2.2-T2V** 配置(照搬 notebook LW2；数值走 settings 可配，不写死)。

    arch=wan22_14b → MoE 双专家，一次出 high+low 两个 LoRA（给 t2v 文生视频锁人物）。
    图片即可训身份（图片教外观、动作由底模出）；★caption 只写【触发词】、不写外观（外观写进 caption
    会和「触发词→身份」绑定打架，训出来不像；外观留给出片时的画面提示词）。
    """
    dim = int(settings.LORA_TRAIN_NETWORK_DIM)
    res = int(settings.LORA_TRAIN_RESOLUTION)
    return {
        "job": "extension",
        "config": {
            "name": name,
            "process": [{
                "type": "sd_trainer",
                "training_folder": training_folder,
                "device": "cuda:0",
                "network": {"type": "lora", "linear": dim, "linear_alpha": max(1, dim // 2)},
                "save": {"dtype": "bf16", "save_every": 1000, "max_step_saves_to_keep": 2},
                "datasets": [{
                    "folder_path": dataset_dir,
                    "caption_ext": "txt",
                    "num_frames": 1,                            # 图片训身份(单帧)
                    # 多分辨率桶含 1024：脸/眼镜这类高频细节靠大桶才学得到（512 单桶时全身照里脸只剩 ~80-120px、糊掉）。
                    # 对齐官方 ai-toolkit wan22_14b 例子的 [512,768,1024]。显存吃紧可去掉 1024。
                    "resolution": sorted({res, int(res * 1.5), 1024}),
                    "cache_latents_to_disk": True,
                }],
                "train": {
                    "batch_size": int(settings.LORA_TRAIN_BATCH),
                    "steps": int(steps),
                    "gradient_accumulation_steps": 1,
                    "train_unet": True,
                    "train_text_encoder": False,
                    "gradient_checkpointing": True,
                    "optimizer": "adamw8bit",
                    "lr": 1e-4,
                    "dtype": "bf16",
                    "timestep_type": "sigmoid",
                    "switch_boundary_every": 10,    # 对齐官方/社区(原 1 每步切专家、更抖更慢);仍约 50/50 覆盖高低噪
                },
                # ★arch=wan22_14b → ai-toolkit 走 MoE 双专家、一次出 high+low 两个 LoRA(别用 is_flux)
                "model": {"name_or_path": base, "arch": "wan22_14b", "quantize": True,
                          "low_vram": _resolve_low_vram(),   # 大卡(>48G)全 GPU 训、不挪 CPU；小卡才省显存
                          "model_kwargs": {"train_high_noise": True, "train_low_noise": True}},
                # ★不生成训练中预览样图★：ai-toolkit 的 Wan2.2 采样路径调 diffusers encode_prompt 时把负向
                # prompt 传成 bool → ftfy.fix_text 崩(object of type 'bool' has no len())。角色 LoRA 不需要
                # 预览样图，直接不配 sample 段 → 跳过采样，训练照常出 high/low LoRA。
            }],
        },
    }


def _write_config(cfg: dict, dataset_dir: str) -> str:
    """写训练配置。优先 yaml(与 notebook 一致)；无 pyyaml 退 json(ai-toolkit 两者都吃)。"""
    try:
        import yaml  # Colab 上 ai-toolkit 依赖已装；本地缺也无妨(退 json)
        path = os.path.join(dataset_dir, "_train.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)
        return path
    except Exception:  # noqa: BLE001
        path = os.path.join(dataset_dir, "_train.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return path


def _tail(path: str, n: int) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()[-n:]
    except Exception:  # noqa: BLE001
        return ""


def _link_after_train(store, tid: str, trigger: str, lora_high: str, lora_low: str) -> None:
    """训练完成回写：① 绑定角色记下 trained_lora_id(反向链)；
    ② 项目若还没设 Wan-T2V 出片 LoRA，自动把这套 high/low 应用为本剧 t2v 角色 LoRA
    (单主角短剧直接生效；不覆盖已有手设；热生效、无需重启)。"""
    t = store.get_lora_training(tid) or {}
    cid = t.get("char_id")
    if cid:
        try:
            store.update_character(cid, trained_lora_id=tid)
        except Exception:  # noqa: BLE001
            pass
    pid = t.get("project_id")
    if pid:
        try:
            st = store.get_project_style(pid)
            if not (st.get("wan_t2v_lora_high") or "").strip():
                store.update_project_style(pid, wan_t2v_lora_high=lora_high,
                                           wan_t2v_lora_low=lora_low, trigger_word=trigger)
        except Exception:  # noqa: BLE001
            pass


def _do_train_local(store, tid: str, dataset_dir: str, trigger: str, name: str,
                    base: str, steps: int) -> None:
    """后台线程：跑 ai-toolkit → 拷贝产物到 loras → 更新 DB 状态。"""
    slug = _slug(trigger or name)
    job_name = f"{slug}_lora"
    # ★产物目录必须放在 dataset_dir **之外**：放里面的话 ai-toolkit 的图片 globber 会把这里的训练样图/
    #   检查点也当成训练图喂进去（污染数据集 → 训出来不像）。dataset 同级建 {tid}_out。
    training_folder = dataset_dir.rstrip("/\\") + "_out"
    log_path = os.path.join(dataset_dir, "_train.log")
    run_py = os.path.join(settings.AI_TOOLKIT_DIR, "run.py")
    try:
        # 每次训练前清干净产物目录 + 清掉历史遗留在 dataset 内的 _train_out（老版本放这、会被当训练图）
        shutil.rmtree(training_folder, ignore_errors=True)
        shutil.rmtree(os.path.join(dataset_dir, "_train_out"), ignore_errors=True)
        os.makedirs(training_folder, exist_ok=True)
        if not os.path.isfile(run_py):
            store.update_lora_training(
                tid, status="FAILED",
                message=f"ai-toolkit 未就绪（{run_py} 不存在）。Colab 请先跑 notebook L1 格安装，或在 .env 设 AI_TOOLKIT_DIR。")
            return
        cfg = build_aitk_config(job_name, dataset_dir, trigger, base, steps, training_folder)
        cfg_path = _write_config(cfg, dataset_dir)
        logger.info("LoRA 训练开始 tid=%s trigger=%s base=%s steps=%s cfg=%s",
                    tid, trigger, base, steps, cfg_path)
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.run([sys.executable, run_py, cfg_path], cwd=settings.AI_TOOLKIT_DIR,
                                  stdout=logf, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            store.update_lora_training(tid, status="FAILED",
                                       message=f"ai-toolkit 退出码 {proc.returncode}。日志尾部：\n{_tail(log_path, 800)}")
            return
        outs = sorted(glob.glob(os.path.join(training_folder, job_name, "*.safetensors")))
        if not outs:
            outs = sorted(glob.glob(os.path.join(training_folder, "**", "*.safetensors"), recursive=True))
        # Wan2.2 双专家：分别挑 high / low 两个产物，各拷一份到 loras/（t2v 出片高低噪各挂一个）
        os.makedirs(settings.COMFYUI_LORA_DIR, exist_ok=True)
        reg: dict[str, str] = {}
        for tag in ("high", "low"):
            tagged = [o for o in outs if tag in os.path.basename(o).lower()]
            # 优先「最终」产物(文件名无步数,如 char_lora_high_noise.safetensors);否则取步数最大的检查点
            src = next((o for o in tagged if not any(c.isdigit() for c in os.path.basename(o))), None) \
                or (tagged[-1] if tagged else None)
            if src:
                dst = os.path.join(settings.COMFYUI_LORA_DIR, f"{slug}_wan_t2v_{tag}.safetensors")
                shutil.copy(src, dst)
                reg[tag] = os.path.basename(dst)
                # ★把"存到哪"写进日志+心跳:训完用户能看到 LoRA 落到 char_loras 的确切路径(§5d 就从这找)
                logger.info("LoRA %s 已拷到: %s", tag, dst)
                try:
                    from mirage.app.pipeline import log_bus
                    log_bus.emit(f"[lora] {tag} 已存: {dst}")
                except Exception:  # noqa: BLE001
                    pass
        if not (reg.get("high") and reg.get("low")):
            store.update_lora_training(
                tid, status="FAILED",
                message=("训练结束但没找到 high/low 两个 LoRA 产物（看 _train.log；多半 arch/底模/ai-toolkit 版本不对）。"
                         f"产物：{[os.path.basename(o) for o in outs][:6]}"))
            return
        store.update_lora_training(
            tid, status="DONE", output_path=reg["high"], trigger_word=trigger,
            message=(f"训练完成 ✓ LoRA 已存到 {settings.COMFYUI_LORA_DIR}/（{reg['high']} / {reg['low']}）。"
                     f"跑笔记本 §5d 重起即自动挂上；§5d 没自动找到就重开一下 notebook（git pull 后浏览器里的旧格子不会自动刷新）。"))
        try:
            _link_after_train(store, tid, trigger, reg["high"], reg["low"])
        except Exception:  # noqa: BLE001
            logger.warning("训练完成后回写角色/项目失败 tid=%s", tid)
        logger.info("LoRA 训练完成 tid=%s → %s / %s", tid, reg["high"], reg["low"])
    except Exception as e:  # noqa: BLE001
        logger.exception("LoRA 训练异常 tid=%s", tid)
        try:
            store.update_lora_training(tid, status="FAILED", message=f"训练异常：{e}")
        except Exception:  # noqa: BLE001
            pass
    finally:
        with _RUNNING_LOCK:
            _RUNNING.pop(tid, None)


def dispatch_remote(store, tid: str, dataset_dir: str, trigger: str, name: str,
                    base: str, steps: int) -> dict:
    """远程训练服务派发(LORA_TRAIN_ENDPOINT 非空时)。最小实现：POST 任务描述、标 QUEUED。"""
    payload = {"training_id": tid, "trigger_word": trigger, "name": name,
               "base": base, "steps": steps, "dataset_dir": dataset_dir}
    try:
        import requests
        requests.post(settings.LORA_TRAIN_ENDPOINT.rstrip("/") + "/train",
                      json=payload, timeout=settings.REQUEST_TIMEOUT)
        return store.update_lora_training(tid, status="QUEUED", steps=steps, trigger_word=trigger,
                                          message="已派发到远程训练服务，排队中。")
    except Exception as e:  # noqa: BLE001
        return store.update_lora_training(tid, status="FAILED",
                                          message=f"派发远程训练服务失败：{e}（检查 LORA_TRAIN_ENDPOINT）")


def start_training(store, tid: str, dataset_dir: str, *, trigger: Optional[str] = None,
                   name: Optional[str] = None, base: Optional[str] = None,
                   steps: Optional[int] = None) -> dict:
    """开训入口(route 在 ≥门槛 后调用)。本地起线程或远程派发。返回更新后的训练 dict。"""
    t = store.get_lora_training(tid)
    if not t:
        raise ValueError(f"训练任务不存在: {tid}")
    trigger = (trigger or t.get("trigger_word") or _slug(t.get("name"))) or f"char_{tid[:6]}"
    name = name or t.get("name") or trigger
    base = base or settings.LORA_TRAIN_BASE
    steps = int(steps or t.get("steps") or settings.LORA_TRAIN_STEPS)

    if not is_local_runner():
        return dispatch_remote(store, tid, dataset_dir, trigger, name, base, steps)

    with _RUNNING_LOCK:
        if tid in _RUNNING and _RUNNING[tid].is_alive():
            return t  # 已在训，别重复开
        th = threading.Thread(target=_do_train_local,
                              args=(store, tid, dataset_dir, trigger, name, base, steps),
                              name=f"loratrain-{tid[:6]}", daemon=True)
        _RUNNING[tid] = th
        # 状态写入 + start() 一并纳入同一把锁：消除"已登记进 _RUNNING 但未 start"的
        # 竞态窗口(此间 is_alive()==False，并发/自举自动训会误判没在训而重复开训)。
        store.update_lora_training(
            tid, status="TRAINING", steps=steps, trigger_word=trigger,
            message=f"本地 ai-toolkit 训练中…（{steps} 步，约数十分钟；进度看任务目录 _train.log）")
        th.start()
    return store.get_lora_training(tid)
