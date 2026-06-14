"""
节点内工具调用的流式埋点 —— 让"所有 agent"的工具调用都能在前端可见。

有些节点（general / shell）在节点内部直接执行工具，工具消息不进图状态，
默认 updates 流看不到。用 LangGraph 的 get_stream_writer 主动发自定义事件，
ai_service 监听 "custom" 流模式转发给前端（tool_call / tool_result）。

不在流式上下文里调用是安全的（get_stream_writer 取不到则静默跳过）。
"""

from __future__ import annotations


def _writer():
    try:
        from langgraph.config import get_stream_writer
        return get_stream_writer()
    except Exception:
        return None


def emit_tool_call(name: str, args: dict | None = None) -> None:
    w = _writer()
    if w is None:
        return
    try:
        w({"kind": "tool_call", "name": name, "args": args or {}})
    except Exception:
        pass


def emit_tool_result(name: str, content) -> None:
    w = _writer()
    if w is None:
        return
    try:
        w({"kind": "tool_result", "name": name, "content": str(content)})
    except Exception:
        pass
