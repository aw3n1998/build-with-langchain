"""
对外开放 API（/api/v1）—— 给第三方对接"小说→短剧"能力的稳定版本边界（预留口子）。

设计：
- 独立 router，前缀 /api/v1，与内部面板 API(/api/*) 分开，便于将来独立演进/文档/限流。
- 所有端点过 require_api_key（没配 PUBLIC_API_KEYS 时默认放行，单用户无感）。
- 现仅放"证明链路通"的最小端点 + 占位（建项目 / 自动拆分镜 / 查任务 / webhook 登记）。
  真正完整的对外能力（出图/出片批量、产物下载、配额）等 toC 真要做时在这里补，
  内部面板 API 完全不受影响。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mirage.app.core.auth import require_api_key

router = APIRouter(prefix="/api/v1", tags=["public-api-v1"])


def _store(workspace: str | None):
    from mirage.app.pipeline.runtime import set_workspace
    from mirage.app.pipeline.store import get_store
    set_workspace(workspace or None)
    return get_store()


@router.get("/metadata")
async def public_metadata(user_id: str = Depends(require_api_key)):
    """对外 API 自描述（也用于第三方自检 key 是否有效）。"""
    return {
        "name": "Mirage Public API",
        "version": "v1",
        "user_id": user_id,                 # 占位：未接账号体系时为 'default' 或 key 本身
        "capabilities": ["create_project", "auto_storyboard", "job_status"],
        "note": "更多能力(批量出图/出片/下载/配额)将在此版本下逐步开放。",
    }


class PubProjectCreate(BaseModel):
    title: str = "新短剧"
    workspace: str | None = None            # TODO(toC): 改为按 user_id 自动隔离，不让外部传任意目录


@router.post("/projects")
async def public_create_project(req: PubProjectCreate, user_id: str = Depends(require_api_key)):
    """第三方建项目。返回 project_id。"""
    p = _store(req.workspace).create_project(req.title or "新短剧")
    return {"project_id": p["id"], "title": p["title"], "owner": user_id}


class PubStoryboard(BaseModel):
    novel_text: str
    scenes: int = 8
    style: str = ""
    workspace: str | None = None


@router.post("/projects/{project_id}/storyboard")
async def public_storyboard(project_id: str, req: PubStoryboard,
                            user_id: str = Depends(require_api_key)):
    """第三方：小说 → 自动拆分镜并入库（复用内部导演式拆分镜）。"""
    from mirage.app.pipeline.storyboard import breakdown_storyboard
    store = _store(req.workspace)
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    n = max(1, min(int(req.scenes or 8), 40))
    scenes = await breakdown_storyboard(req.novel_text or "", n, style=req.style or "")
    created = []
    for i, sc in enumerate(scenes, 1):
        row = store.add_scene(project_id, i, narration=sc["narration"], image_prompt=sc["image_prompt"],
                              motion_prompt=sc["motion_prompt"], title=sc["title"], subtitle=sc["subtitle"])
        if sc.get("lipsync"):
            store.set_scene_lipsync(row["id"], True)
        created.append(row["id"])
    return {"project_id": project_id, "scene_ids": created, "count": len(created)}


@router.get("/jobs/{job_id}")
async def public_job_status(job_id: str, user_id: str = Depends(require_api_key)):
    """第三方轮询异步任务状态（出图/出片是异步作业）。"""
    from mirage.app.services.job_manager import job_manager
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job_id": job_id, "status": getattr(job, "status", "unknown"),
            "kind": getattr(job, "kind", ""), "error": getattr(job, "error", None)}


class PubWebhook(BaseModel):
    url: str


@router.post("/jobs/{job_id}/register-webhook")
async def public_register_webhook(job_id: str, req: PubWebhook,
                                  user_id: str = Depends(require_api_key)):
    """占位：登记任务完成回调 URL（当前只登记、不触发；真正回调调度等 toC 接入再实现）。"""
    # TODO(toC/webhook): 持久化 (job_id -> url)，job 终态时 httpx.post(url, json=result)，超时 settings.WEBHOOK_TIMEOUT
    return {"registered": True, "job_id": job_id, "note": "回调调度尚未实现(占位)。"}
