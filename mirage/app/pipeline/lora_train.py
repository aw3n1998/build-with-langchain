"""人物 LoRA 训练执行器。

Colab 单机(后端 + ai-toolkit + ComfyUI 同机)→ 默认**本地子进程**训练：
    {sys.executable} {settings.AI_TOOLKIT_DIR}/run.py {config}
照搬 notebook colab_deploy.ipynb L1/L3/L4 已验证跑通的 ai-toolkit 配方
(sd_trainer / lora / is_flux / caption_ext=txt)。训练完把产物 safetensors
拷到 settings.COMFYUI_LORA_DIR —— ComfyUI 出图按文件名加载该 LoRA。

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


def is_local_runner() -> bool:
    """空 LORA_TRAIN_ENDPOINT = 本地 ai-toolkit 子进程(Colab 单机默认)。"""
    return not (settings.LORA_TRAIN_ENDPOINT or "").strip()


def count_images(dataset_dir: str) -> int:
    if not os.path.isdir(dataset_dir):
        return 0
    return len([x for x in os.listdir(dataset_dir) if x.lower().endswith(_IMG_EXTS)])


def build_aitk_config(name: str, dataset_dir: str, trigger: str, base: str,
                      steps: int, training_folder: str) -> dict:
    """生成 ai-toolkit 配置(照搬 notebook L3；数值走 settings 可配，不写死)。"""
    dim = int(settings.LORA_TRAIN_NETWORK_DIM)
    return {
        "job": "extension",
        "config": {
            "name": name,
            "process": [{
                "type": "sd_trainer",
                "training_folder": training_folder,
                "device": "cuda:0",
                "network": {"type": "lora", "linear": dim, "linear_alpha": max(1, dim // 2)},
                "save": {"dtype": "float16", "save_every": 500, "max_step_saves_to_keep": 2},
                "datasets": [{
                    "folder_path": dataset_dir,
                    "caption_ext": "txt",
                    "resolution": [int(settings.LORA_TRAIN_RESOLUTION)],
                    "cache_latents_to_disk": True,
                }],
                "train": {
                    "batch_size": int(settings.LORA_TRAIN_BATCH),
                    "steps": int(steps),
                    "gradient_accumulation_steps": 1,
                    "train_unet": True,
                    "train_text_encoder": False,
                    "optimizer": "adamw8bit",
                    "lr": 1e-4,
                    "lr_scheduler": "cosine",
                    "dtype": "bf16",
                    "gradient_checkpointing": True,
                },
                "model": {"name_or_path": base, "is_flux": True, "quantize": False},
                "sample": {"sample_every": 500, "prompts": [f"{trigger}, portrait, studio lighting"]},
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


def _link_after_train(store, tid: str, trigger: str, final: str) -> None:
    """训练完成回写：① 绑定角色记下 trained_lora_id(反向链)；
    ② 项目若还没设出图 LoRA，自动把这枚 LoRA 应用为本剧出图 LoRA(单主角短剧直接生效；
    不覆盖已有设置，避免抢用户手设的风格)。"""
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
            if not (st.get("flux_lora") or "").strip():
                store.update_project_style(pid, flux_lora=os.path.basename(final), trigger_word=trigger)
        except Exception:  # noqa: BLE001
            pass


def _do_train_local(store, tid: str, dataset_dir: str, trigger: str, name: str,
                    base: str, steps: int) -> None:
    """后台线程：跑 ai-toolkit → 拷贝产物到 loras → 更新 DB 状态。"""
    slug = _slug(trigger or name)
    job_name = f"{slug}_lora"
    training_folder = os.path.join(dataset_dir, "_train_out")
    log_path = os.path.join(dataset_dir, "_train.log")
    run_py = os.path.join(settings.AI_TOOLKIT_DIR, "run.py")
    try:
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
        if not outs:
            store.update_lora_training(tid, status="FAILED",
                                       message="训练结束但未找到 .safetensors 产物（看 _train.log）。")
            return
        os.makedirs(settings.COMFYUI_LORA_DIR, exist_ok=True)
        final = os.path.join(settings.COMFYUI_LORA_DIR, f"{slug}.safetensors")
        shutil.copy(outs[-1], final)
        store.update_lora_training(
            tid, status="DONE", output_path=final, trigger_word=trigger,
            message=f"训练完成 ✓ LoRA → {os.path.basename(final)}（出图按文件名加载，触发词「{trigger}」）")
        try:
            _link_after_train(store, tid, trigger, final)
        except Exception:  # noqa: BLE001
            logger.warning("训练完成后回写角色/项目失败 tid=%s", tid)
        logger.info("LoRA 训练完成 tid=%s → %s", tid, final)
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
