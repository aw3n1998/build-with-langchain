"""
GPU 长任务管理器 —— 把出图/出片这类「几分钟、走 SSH」的任务从 HTTP 连接里解耦出来。

解决今天暴露的三个问题：
  1) 长任务占着 SSE 连接：浏览器断开/网络抖动就可能整轮卡死、进度丢失。
  2) 同一台 GPU 上多个任务被同时触发，在一条 SSH 连接上互相抢、互相拖慢。
  3) 刷新/重连后看不到正在跑的任务进度。

做法（进程内、轻量，不引入 Celery/Redis）：
  - 单 worker 串行消费队列 → GPU 任务一次只跑一个（单飞），杜绝并发抢连接；
    后到的任务排队，前端显示"排队中"。
  - 每个任务把事件（tool_call/tool_result/image/video/done/error）缓冲在内存。
  - 提交即返回 job_id；前端通过 SSE 连到 /jobs/{id}/events?since=N 回放+实时跟随。
    断线后带 since 重连即可续看，任务本身在后台继续，不受浏览器影响。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import AsyncIterator, Callable, Optional

from mirage.app.core.logger import get_logger

logger = get_logger("job_manager")

# 事件工厂：一个无参函数，返回 async generator，逐个 yield 事件 dict
EventFactory = Callable[[], AsyncIterator[dict]]

_MAX_JOBS = 80          # 内存里最多保留多少个历史任务（超出按时间淘汰）

# 任务硬超时（秒）：超过即判失败并继续下一个，防止一个跑飞的任务把单飞队列卡死。
# 按任务类型给宽裕值（共享 GPU 慢是常态，宁可宽不可误杀）。
_TIMEOUTS = {
    "generate": 45 * 60,        # 单分镜出图（FLUX 多候选 ~4min，留足重试与排队余量）
    "render": 120 * 60,         # 出片（Wan 单段 ~5min × 接续段数；LTX 快得多）
    "batch_generate": 4 * 3600, # 整片批量出图
    "batch_finish": 6 * 3600,   # 整片批量出片 + 合成
    "one_click": 8 * 3600,      # 一键全自动：拆分镜 + 批量出图 + 选图 + 批量出片 + 合成（最长链）
    "continuation": 8 * 3600,   # 尾帧续接：逐镜 i2v(默认 40 步,慢)，整集链下来很长
    "chat": 20 * 60,            # 一轮 agent 对话（LLM + 工具）
}
_DEFAULT_TIMEOUT = 3600


class Job:
    def __init__(self, job_id: str, kind: str, meta: Optional[dict] = None):
        self.id = job_id
        self.kind = kind                 # generate | render | batch_* | chat
        self.status = "queued"           # queued | running | done | error
        self.events: list[dict] = []
        self.error: Optional[str] = None
        self.meta = meta or {}           # 业务元数据（如 session_id），用于推送归属
        self.created_at = time.time()
        self.task: Optional[asyncio.Task] = None   # 执行任务句柄（chat 与 gpu 都有，可取消）
        self.cancel_requested = False    # 还在排队（无 task）时收到的取消，由 worker 跳过
        self._cond = asyncio.Condition()

    @property
    def terminal(self) -> bool:
        return self.status in ("done", "error")

    async def _emit(self, ev: dict):
        async with self._cond:
            self.events.append(ev)
            self._cond.notify_all()

    async def _set_status(self, status: str, error: Optional[str] = None):
        async with self._cond:
            self.status = status
            if error:
                self.error = error
            self._cond.notify_all()

    async def stream(self, since: int = 0) -> AsyncIterator[dict]:
        """从第 since 个事件开始回放已缓冲事件，再实时跟随，直到任务终态。

        支持断线重连：客户端记录已收事件数 N，重连时传 since=N，不重不漏。
        """
        # 钳位到合法范围：若客户端 since 飘到超过事件总数（如计入了 SSE 层附加的
        # 收尾事件），不钳位会导致终态任务返回空流且无 done，前端无限重连。
        i = max(0, min(since, len(self.events)))
        while True:
            async with self._cond:
                while i >= len(self.events) and not self.terminal:
                    await self._cond.wait()
                pending = self.events[i:]
                i = len(self.events)
                done = self.terminal and i >= len(self.events)
            for ev in pending:
                yield ev
            if done:
                # 终态重连且无可回放事件时补发收尾，确保客户端总能拿到终止信号
                if not pending:
                    yield {"type": "error", "content": self.error} if self.error \
                        else {"type": "done"}
                return


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._queue: Optional[asyncio.Queue] = None
        self._worker: Optional[asyncio.Task] = None
        self._current: Optional[Job] = None
        # 状态推送订阅者（WebSocket 连接各持一个队列）：任务状态一变就广播
        self._subscribers: set[asyncio.Queue] = set()

    # ── 状态推送（WebSocket 用）──────────────────────────────────
    def _snapshot(self, job: Job) -> dict:
        return {"type": "job_update", "job_id": job.id, "kind": job.kind,
                "status": job.status, "session_id": job.meta.get("session_id"),
                "error": job.error}

    def _notify(self, job: Job) -> None:
        msg = self._snapshot(job)
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except Exception:  # noqa: BLE001 - 满/坏的订阅者直接丢弃
                self._subscribers.discard(q)

    def subscribe(self) -> asyncio.Queue:
        """订阅任务状态变化；连接断开后必须 unsubscribe。订阅瞬间先收到全部未完任务快照。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        for job in self._jobs.values():
            if not job.terminal:
                q.put_nowait(self._snapshot(job))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _ensure_worker(self):
        if self._worker is None:
            self._queue = asyncio.Queue()
            self._worker = asyncio.create_task(self._run_worker())

    async def _execute(self, job: Job, factory: EventFactory):
        """统一执行一个任务：状态流转 + 超时 + 取消 + 异常兜底（GPU 队列与 chat 通道共用）。"""
        await job._set_status("running")
        self._notify(job)
        await job._emit({"type": "status", "status": "running"})
        logger.info("[job] 开始 %s", job.id)
        timeout = _TIMEOUTS.get(job.kind, _DEFAULT_TIMEOUT)
        try:
            async def _consume():
                async for ev in factory():
                    await job._emit(ev)

            await asyncio.wait_for(_consume(), timeout=timeout)
            await job._emit({"type": "done"})
            await job._set_status("done")
            self._notify(job)
            logger.info("[job] 完成 %s", job.id)
        except asyncio.CancelledError:
            msg = "已停止"
            await job._emit({"type": "error", "content": msg})
            await job._set_status("error", error=msg)
            self._notify(job)
            logger.info("[job] 已取消 %s", job.id)
        except asyncio.TimeoutError:
            msg = f"任务超过 {timeout // 60} 分钟仍未完成，已强制终止（可重试）"
            await job._emit({"type": "error", "content": msg})
            await job._set_status("error", error=msg)
            self._notify(job)
            logger.error("[job] 超时 %s（%ss）", job.id, timeout)
            # 超时只停了本地协程，远程 GPU 推理仍在跑 → 杀掉远程进程释放显卡，
            # 避免僵尸进程占卡堆积（与用户主动取消的清理一致）。
            if job.kind in ("generate", "render", "batch_generate", "batch_finish", "one_click", "continuation"):
                try:
                    from mirage.app.pipeline.gpu_client import get_gpu_client
                    await asyncio.to_thread(get_gpu_client().kill_inference)
                except Exception:  # noqa: BLE001
                    logger.warning("[job] 超时后远程推理清理失败（不影响超时处理）")
                try:   # ★ComfyUI 出片(默认链)：kill_inference 杀不到它 → 中断+卸显存，防僵尸占卡
                    from mirage.app.pipeline.comfy_http import interrupt as _comfy_interrupt
                    await asyncio.to_thread(_comfy_interrupt)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            await job._emit({"type": "error", "content": msg})
            await job._set_status("error", error=msg)
            self._notify(job)
            logger.exception("[job] 失败 %s", job.id)

    async def _run_worker(self):
        assert self._queue is not None
        while True:
            job, factory = await self._queue.get()
            self._current = job
            try:
                if job.cancel_requested:
                    # 排队期间已被取消 → 不下发到 GPU，直接收尾（这正是省算力的关键）
                    await job._emit({"type": "error", "content": "已停止"})
                    await job._set_status("error", error="已停止")
                    self._notify(job)
                else:
                    # 包成 task 以支持运行中取消（取消会在下一个 await 点抛 CancelledError，
                    # 批量任务因此停在当前分镜、不再下发后续分镜）
                    job.task = asyncio.create_task(self._execute(job, factory))
                    await job.task
            except asyncio.CancelledError:
                pass   # _execute 已自行处理并落终态
            finally:
                self._current = None
                self._queue.task_done()

    def _prune(self):
        if len(self._jobs) <= _MAX_JOBS:
            return
        # 淘汰最老的、已终态的任务
        olds = sorted(
            (j for j in self._jobs.values() if j.terminal),
            key=lambda j: j.created_at,
        )
        for j in olds[: len(self._jobs) - _MAX_JOBS]:
            self._jobs.pop(j.id, None)

    def submit(self, kind: str, factory: EventFactory, lane: str = "gpu",
               meta: dict | None = None) -> str:
        """提交任务，立即返回 job_id。

        lane="gpu"：进单飞队列串行执行（GPU 一次只跑一个）。
        lane="chat"：立即并发执行（LLM 对话互不阻塞，且可被 cancel 真取消）——
                     这让对话回合脱离 HTTP 连接：切会话/断网都不影响回合在后台完成。
        """
        job = Job(kind + "_" + uuid.uuid4().hex[:8], kind, meta=meta)
        self._jobs[job.id] = job
        self._notify(job)
        if lane == "chat":
            job.task = asyncio.create_task(self._execute(job, factory))
        else:
            self._ensure_worker()
            assert self._queue is not None
            busy = self._current is not None or not self._queue.empty()
            if busy:
                job.events.append({"type": "queued"})
            self._queue.put_nowait((job, factory))
        self._prune()
        logger.info("[job] 提交 %s（lane=%s）", job.id, lane)
        return job.id

    def cancel(self, job_id: str) -> bool:
        """取消任务。

        - 运行中：取消其 task → 在下一个 await 点抛 CancelledError，落「已停止」终态。
          对批量任务（多分镜）尤其有效：停在当前分镜，不再下发后续分镜，省下其余 GPU 算力。
        - 仍在排队（未轮到）：标记 cancel_requested，worker 取到时直接跳过、不下发 GPU。
        注：已下发到 GPU 的那一段远程进程无法即时杀死，但后续步骤全部止损。
        """
        job = self._jobs.get(job_id)
        if not job or job.terminal:
            return False
        job.cancel_requested = True
        if job.task is not None:
            job.task.cancel()
        # 已下发到 GPU 的 ComfyUI 渲染：本地取消协程不会停它 → 中断+卸显存，防僵尸占卡。
        if job.kind in ("generate", "render", "batch_generate", "batch_finish", "one_click", "continuation"):
            try:
                from mirage.app.pipeline.comfy_http import interrupt as _comfy_interrupt
                _comfy_interrupt()
            except Exception:  # noqa: BLE001
                pass
        return True

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list_active(self, project_id: Optional[str] = None,
                    session_id: Optional[str] = None) -> list[dict]:
        """列出未完成（排队/运行中）的任务，供刷新后前端重连。可按项目/会话过滤。"""
        out = []
        for j in self._jobs.values():
            if j.terminal:
                continue
            if project_id and j.meta.get("project_id") != project_id:
                continue
            if session_id and j.meta.get("session_id") != session_id:
                continue
            out.append({"job_id": j.id, "kind": j.kind, "status": j.status,
                        "scene_id": j.meta.get("scene_id")})
        return out


# 全局单例
job_manager = JobManager()
