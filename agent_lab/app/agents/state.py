from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]

    # router 决定本轮要并行调用哪些子 Agent
    selected_agents: list[str]   # e.g. ["code", "file"] 或 ["general"]

    # 每个子 Agent 各自写自己的结果字段，互不干扰
    # 为什么不用一个 list 累加？因为 operator.add 会跨轮次叠加历史结果，
    # 而各自独立字段每轮被 router 重置为 ""，更清晰安全
    code_result:    str   # CodeAgent 的输出，未使用时为 ""
    file_result:    str   # FileAgent 的输出，未使用时为 ""
    general_result: str   # General 的输出，未使用时为 ""
