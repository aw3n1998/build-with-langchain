"""
消息历史清洗 —— 发给 LLM 前修复"不配对的工具调用"。

为什么需要：被中途打断的回合（进程被杀、出图卡死、后端重启）会在 LangGraph checkpoint 里
留下「带 tool_calls 的 AIMessage」但缺少对应的 ToolMessage。下一轮把整段历史发给
OpenAI 兼容接口时会被拒：
  "An assistant message with 'tool_calls' must be followed by tool messages
   responding to each 'tool_call_id'."
本函数在调用 LLM 前临时清洗（不改写已存的 checkpoint），把悬空的 tool_calls 去掉、
孤儿 ToolMessage 丢弃，保证发出去的消息序列合法。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage


def _is_tool_msg(m) -> bool:
    return isinstance(m, ToolMessage) or getattr(m, "type", None) == "tool"


def sanitize_messages(messages: list) -> list:
    """返回一个清洗后的新列表（不修改入参，也不影响已存 checkpoint）。

    规则：
      - 某条 AIMessage 的某个 tool_call 在后续没有对应 ToolMessage 回应 → 视为悬空；
        该 AIMessage 仅保留"有回应"的 tool_calls；若一个都没有，则保留其正文（无正文则整条丢弃）。
      - 没有对应有效 tool_call 的 ToolMessage（孤儿）→ 丢弃。
    """
    # 1) 哪些 tool_call_id 确实被 ToolMessage 回应过
    responded: set[str] = set()
    for m in messages:
        if _is_tool_msg(m):
            tcid = getattr(m, "tool_call_id", None)
            if tcid:
                responded.add(tcid)

    cleaned: list = []
    valid_ids: set[str] = set()
    for m in messages:
        tcs = getattr(m, "tool_calls", None)
        if tcs:  # 带工具调用的 AIMessage
            kept = [tc for tc in tcs if tc.get("id") in responded]
            content = getattr(m, "content", "") or ""
            if len(kept) == len(tcs):
                cleaned.append(m)  # 全部配对，原样保留
                valid_ids.update(tc.get("id") for tc in kept)
            elif kept:  # 部分配对：只保留有回应的
                cleaned.append(AIMessage(content=content, tool_calls=kept))
                valid_ids.update(tc.get("id") for tc in kept)
            elif str(content).strip():  # 全悬空但有正文：保留正文
                cleaned.append(AIMessage(content=content))
            # 否则整条丢弃
            continue
        if _is_tool_msg(m):  # ToolMessage：只留有对应有效调用的
            if getattr(m, "tool_call_id", None) in valid_ids:
                cleaned.append(m)
            continue
        cleaned.append(m)
    return cleaned
