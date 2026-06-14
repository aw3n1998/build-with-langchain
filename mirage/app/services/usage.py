"""
用量/计费记账钩子（预留口子）。

现在：record_usage 是空操作——只为把"在哪记账"这件事的【调用点】钉死在代码里，
将来 toC 收费时只改这一个文件（落 usage 表 + 扣额度 + 校验），不必回头找散落的埋点。
"""

from __future__ import annotations

from mirage.app.core.logger import get_logger

logger = get_logger("services.usage")


def record_usage(user_id: str | None = "default", kind: str = "",
                 tokens: int = 0, gpu_seconds: float = 0.0, job_id: str | None = None) -> None:
    """记一笔用量（当前空操作，仅 debug 日志占位）。

    将来填实：写 usage(job_id,user_id,kind,tokens,gpu_seconds,cost,created_at) 表；
    chat/出图/出片提交前查额度，<=0 返回 402。
    """
    # TODO(toC): 落 usage 表 + 扣额度。当前不做任何事。
    logger.debug("[usage] (占位) user=%s kind=%s tokens=%s gpu=%.1fs job=%s",
                 user_id, kind, tokens, gpu_seconds, job_id)
    return None


def check_quota(user_id: str | None = "default") -> bool:
    """额度校验占位：当前恒为 True（不限）。将来 toC 时查余额。"""
    return True
