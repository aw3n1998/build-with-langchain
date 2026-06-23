"""
GPU 实时日志总线 —— 把远程命令（FLUX/Wan/LTX）的 stdout/stderr 逐行送到当前任务的事件流。

为什么用 contextvar：出片/出图的阻塞调用走 `asyncio.to_thread`，而 to_thread 会复制当前
contextvar 上下文到工作线程。于是「事件生成器设好 sink → to_thread 里的 gpu.run 取到同一个
sink → 逐行 put」就能把远程日志实时传回异步侧 yield 成 {type:'log'} 事件。
"""

from __future__ import annotations

import contextvars
import queue
from typing import Optional

_sink: contextvars.ContextVar[Optional["queue.Queue"]] = contextvars.ContextVar(
    "gpu_log_sink", default=None
)


def set_sink(q: "queue.Queue"):
    """设置当前上下文的日志队列，返回 token 供 reset。"""
    return _sink.set(q)


def reset_sink(token) -> None:
    _sink.reset(token)


def emit(line: str) -> None:
    """gpu.run 每读到一行就调用本函数；无 sink（如本地测试）时静默丢弃。"""
    q = _sink.get()
    if q is None:
        return
    try:
        q.put_nowait(line)
    except queue.Full:
        # 满了丢最旧一条再放（实时日志只看尾部，丢早期无所谓）
        try:
            q.get_nowait()
            q.put_nowait(line)
        except queue.Empty:
            pass
