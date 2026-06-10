"""
上下文用量计量 —— 真实统计会话消息的 token 数，给压缩触发和前端进度条用。

token 估算：优先用 tiktoken(cl100k_base) 近似；不可用时退化为字符数估算
（中文约 1 token/字，英文约 1 token/4 字符）。统计的是**真实会话消息**，
不是模拟值。
"""

from __future__ import annotations

from agent_lab.app.core.config import settings

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001
    _ENC = None


def _text_of(m) -> str:
    """从各种消息形态里取文本内容。"""
    if isinstance(m, str):
        return m
    c = getattr(m, "content", None)
    if c is None and isinstance(m, dict):
        c = m.get("content", "")
    if isinstance(c, list):  # 多模态/分块内容
        return " ".join(
            (p.get("text", "") if isinstance(p, dict) else str(p)) for p in c
        )
    return c or ""


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENC is not None:
        try:
            return len(_ENC.encode(text))
        except Exception:  # noqa: BLE001
            pass
    # 退化估算：CJK 字符≈1 token，其余≈0.3 token
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return int(cjk + other * 0.3) + 1


def count_messages_tokens(messages) -> int:
    # 每条消息加 ~4 token 的角色/分隔开销
    return sum(count_tokens(_text_of(m)) + 4 for m in messages)


def usage(messages) -> dict:
    """返回真实上下文用量指标，供前端进度条与压缩判断。"""
    window = settings.CONTEXT_WINDOW
    trigger = int(window * settings.COMPACT_RATIO)
    tokens = count_messages_tokens(messages)
    return {
        "tokens": tokens,
        "window": window,
        "trigger_tokens": trigger,
        "ratio": round(tokens / window, 4) if window else 0,
        "message_count": len(messages),
        "will_compact": tokens >= trigger,
    }
