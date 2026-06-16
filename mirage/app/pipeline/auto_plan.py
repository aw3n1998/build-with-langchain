"""自动决策层 —— 把「目标时长 / 选图 / 连贯参数」从手填变成算法自算。

服务于「一键全自动：小说 → ~1 分钟成片」。三个纯函数，互不依赖 GPU，可单测：
- estimate_storyboard：目标秒数 → 分镜数 / 每镜段数 / 每段帧数（Wan 合法 4k+1）。
- auto_select_all：把「逐镜手动点选候选图」这唯一人工卡点自动化（first / best 两策略）。
  与手动 /pipeline/select 并存，互不影响——「自动 + 手动」双模式。
- _best_asset：可选的「AI 视觉评分挑最佳」，未配置/失败自动回退第一张。

编排器 _one_click_events 放在 routes.py（紧邻 _batch_generate_events/_batch_finish_events，
复用其事件流），避免 auto_plan ↔ routes 循环 import。
"""

from __future__ import annotations

import math

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("pipeline.auto_plan")

_MAX_SCENES = 40        # 与 routes.py auto_storyboard/auto_fill 的上限一致
_MAX_SEGMENTS = 4       # 尾帧接续甜区：段越多末帧越糊（漂移累积），别无限大


def _to_4kp1(frames: int) -> int:
    """取到 Wan 合法的 4k+1 帧数（向上取整，最小 5）。81=4*20+1 已合法。"""
    f = max(5, int(frames or 0))
    if (f - 1) % 4 == 0:
        return f
    return ((f - 1) // 4 + 1) * 4 + 1


def estimate_storyboard(target_sec: float, *, fps: int = 0, coherence: bool = True,
                        sec_per_shot: float = 0.0) -> dict:
    """目标时长 → 拆几个镜 + 每镜几段 + 每段多少帧（让 AI 按秒数自算镜头）。

    连贯优先(coherence=True)→「少而长」：每镜默认拼成 2 个连续段（约 10s 长镜），
    切换点少 → 跨镜漂移点少 → 更连贯；coherence=False→「快切」：每镜单段约 5s。

    Args:
        target_sec: 目标成片时长（秒）。
        fps: 帧率；0=用 COMFYUI_FPS。
        coherence: True=少而长的连续长镜；False=多而短的快切。
        sec_per_shot: 手动指定每镜目标秒数；0=按 coherence 自动取。
    Returns:
        {n_shots, segments_per_shot, frames_per_segment, fps, sec_per_shot, est_total_sec}
    """
    fps = int(fps or settings.COMFYUI_FPS or 16)
    seg_frames = _to_4kp1(int(settings.COMFYUI_FRAMES or 81))
    single_seg_sec = seg_frames / fps                      # 单段时长，81@16 ≈ 5.06s
    if sec_per_shot and sec_per_shot > 0:
        sps = float(sec_per_shot)
    else:
        sps = single_seg_sec * (2 if coherence else 1)     # 连贯=双段长镜；快切=单段
    target = max(single_seg_sec, float(target_sec or 0))    # 至少出得了一个镜
    n_shots = max(1, min(round(target / sps), _MAX_SCENES))
    segments = max(1, min(math.ceil(sps / single_seg_sec), _MAX_SEGMENTS))
    sec_per_shot_actual = round(segments * single_seg_sec, 2)
    return {
        "n_shots": int(n_shots),
        "segments_per_shot": int(segments),
        "frames_per_segment": int(seg_frames),
        "fps": int(fps),
        "sec_per_shot": sec_per_shot_actual,
        "est_total_sec": round(n_shots * sec_per_shot_actual, 1),
    }


def _best_asset(assets: list[dict], scene: dict) -> dict | None:
    """可选「AI 视觉评分挑最佳」：逐张让视觉模型按构图/清晰/贴合度打 0-100，取最高。

    未配置视觉模型 / 任何失败 → 返回 None，调用方回退第一张。绝不抛异常。
    """
    try:
        from mirage.app.services.vision import suggest_from_image, vision_enabled
        if not vision_enabled():
            return None
    except Exception:  # noqa: BLE001
        return None
    want = (scene.get("image_prompt") or scene.get("title") or "").strip()[:400]
    sys = ("你是严格的选图评审。只输出一个 0-100 的整数分数，不要任何其它文字。"
           "评分依据：构图清晰、主体明确、无畸形/多手多脸、贴合画面描述。")
    best, best_score = None, -1.0
    for a in assets:
        path = a.get("storage_path") or ""
        out = suggest_from_image(path, sys, f"画面描述：{want}\n给这张候选图打分（只回数字）：")
        if not out:
            continue
        import re
        m = re.search(r"\d+(\.\d+)?", out)
        if not m:
            continue
        score = float(m.group(0))
        if score > best_score:
            best, best_score = a, score
    return best


def auto_select_all(project_id: str, *, strategy: str = "first",
                    workspace: str | None = None) -> dict:
    """自动选图：对每个「有候选且尚未选过」的分镜选定一张，推进到 PENDING_VIDEO_GEN。

    打通全自动的唯一人工卡点。复用 store.select_asset（= select_candidate 内核），
    所以 batch_finish 立刻能据 selected_asset_id 出片。手动 /pipeline/select 不受影响。

    Args:
        project_id: 项目 ID。
        strategy: "first"=选第 1 张（零依赖）；"best"=AI 视觉评分挑最佳（需 VISION_*，失败回退 first）。
        workspace: 工作目录（决定用哪个 DB）；与出图一致才查得到候选。
    Returns:
        {"selected": n, "skipped": 已选过的镜数, "empty": 无候选的镜数}
    """
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store
    set_workspace(workspace)
    store = get_store()
    st = store.status(project_id)
    selected = skipped = empty = 0
    for s in sorted(st["scenes"], key=lambda x: x["scene_number"]):
        if s.get("selected_asset_id"):
            skipped += 1
            continue
        assets = store.list_assets(s["id"], "IMAGE")   # 已按 created_at 排序
        if not assets:
            empty += 1
            continue
        pick = assets[0]
        if strategy == "best":
            pick = _best_asset(assets, s) or assets[0]
        try:
            store.select_asset(s["id"], pick["id"])
            selected += 1
        except Exception as e:  # noqa: BLE001 - 单镜失败不中断
            logger.warning("[auto_select] 分镜 %s 选图失败: %s", s["id"], e)
    logger.info("[auto_select] project=%s 选 %d 镜（跳过已选 %d，无候选 %d，策略=%s）",
                project_id, selected, skipped, empty, strategy)
    return {"selected": selected, "skipped": skipped, "empty": empty}
