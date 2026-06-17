"""
Map-Reduce 模式演示：动态并行 Worker Agent

场景：用户要生成大量图片，planner 把任务拆分成 N 个子批次，
      每个子批次由独立的 worker 并行处理，最终汇聚所有结果。

关键技术：
  - Send API 动态创建 N 个 worker（数量由 planner 运行时决定）
  - operator.add reducer 自动把所有 worker 结果拼接成一个列表
  - 所有 worker 完成后 LangGraph 自动触发 merger
"""

import operator
import json
import asyncio
from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.types import Send
from mirage.app.core.logger import get_logger

logger = get_logger("batch_agent")


# ── State 设计 ────────────────────────────────────────────────

class BatchState(TypedDict):
    request: str                                   # 原始用户请求
    subtasks: list[dict]                           # planner 拆分的子任务列表
    results: Annotated[list[str], operator.add]    # ← add reducer：所有 worker 结果自动汇聚
    final_summary: str                             # merger 整理后的最终输出


class WorkerState(TypedDict):
    """
    每个 worker 实例收到的输入 State（通过 Send 传入）。
    worker 的返回值会被 merge 回父图的 BatchState，
    results 字段通过 operator.add 追加而非覆盖。
    """
    subtask: dict                                  # 本 worker 负责的子任务
    results: Annotated[list[str], operator.add]    # 与 BatchState 中的 reducer 一致


# ── Prompt ───────────────────────────────────────────────────

_PLANNER_PROMPT = SystemMessage(content=(
    "你是任务规划器。用户提交了一个批量任务，你需要将其拆分为多个并行子任务。\n\n"
    "输出严格的 JSON 数组，每个元素包含：\n"
    "  - batch_id: 批次编号（从1开始）\n"
    "  - description: 本批次的具体描述\n"
    "  - count: 本批次数量\n\n"
    "示例输出（不要包含任何其他文字）：\n"
    '[{"batch_id":1,"description":"生成第1-10张橘猫照片","count":10},'
    '{"batch_id":2,"description":"生成第11-20张黑猫照片","count":10}]'
))

_WORKER_PROMPT = SystemMessage(content=(
    "你是图片生成 Worker。收到子任务后，模拟执行并返回结果描述。\n"
    "输出格式：JSON 对象，包含 batch_id、generated_count、image_urls（模拟URL列表）。\n"
    "直接输出 JSON，不要包含其他文字。"
))

_MERGER_PROMPT = SystemMessage(content=(
    "所有并行 Worker 已完成任务，以下是各批次的结果。\n"
    "请整理成简洁的汇总报告，包括：总生成数量、各批次状态、整体结论。"
))


# ── 节点函数 ──────────────────────────────────────────────────

async def planner_node(state: BatchState, llm) -> dict:
    """
    规划节点：LLM 分析用户请求，决定拆分成几个子批次。
    子批次数量完全由 LLM 运行时决定，不是硬编码的。
    """
    logger.info("[Planner] 开始规划任务: %s", state["request"])

    response = await llm.ainvoke([
        _PLANNER_PROMPT,
        HumanMessage(content=f"用户请求：{state['request']}")
    ])

    try:
        subtasks = json.loads(response.content)
        logger.info("[Planner] 拆分为 %d 个子任务: %s",
                    len(subtasks), [t["description"] for t in subtasks])
    except json.JSONDecodeError:
        # 如果 LLM 输出格式不对，给一个保底方案
        subtasks = [{"batch_id": 1, "description": state["request"], "count": 1}]
        logger.warning("[Planner] JSON 解析失败，使用保底方案")

    return {"subtasks": subtasks}


def fan_out(state: BatchState) -> list[Send]:
    """
    扇出函数：为每个子任务创建一个 Send，LangGraph 并行执行所有 worker。
    这里的 worker 数量是运行时决定的——这就是"动态创建 Agent"的本质。
    """
    sends = [
        Send("worker", {"subtask": task, "results": []})
        for task in state["subtasks"]
    ]
    logger.info("[FanOut] 动态创建 %d 个并行 Worker", len(sends))
    return sends


async def worker_node(state: WorkerState, llm) -> dict:
    """
    Worker 节点：每个实例处理一个子任务，完全并行，互不干扰。
    返回的 results 通过 operator.add reducer 自动追加到主图的 results 列表。
    """
    task = state["subtask"]
    logger.info("[Worker-%s] 开始处理: %s", task["batch_id"], task["description"])

    response = await llm.ainvoke([
        _WORKER_PROMPT,
        HumanMessage(content=f"子任务：{json.dumps(task, ensure_ascii=False)}")
    ])

    logger.info("[Worker-%s] 完成", task["batch_id"])
    # 返回列表（单个元素），operator.add 会把所有 worker 的结果列表拼接在一起
    return {"results": [response.content]}


async def merger_node(state: BatchState, llm) -> dict:
    """
    汇聚节点：等所有 worker 完成后自动触发（LangGraph 保证）。
    state["results"] 此时已包含全部 worker 的结果（由 operator.add 汇聚）。
    """
    logger.info("[Merger] 收集到 %d 个 Worker 结果，开始整合", len(state["results"]))

    combined = "\n\n".join(
        f"=== 批次 {i+1} 结果 ===\n{r}"
        for i, r in enumerate(state["results"])
    )
    summary = await llm.ainvoke([
        _MERGER_PROMPT,
        HumanMessage(content=combined)
    ])

    return {"final_summary": summary.content}


# ── 图构建 ────────────────────────────────────────────────────

def build_batch_graph(llm, checkpointer=None):
    """
    构建 Map-Reduce 图：
      planner → (动态 N 个 worker 并行) → merger

    图结构：
      __start__
          ↓
       planner   ← LLM 决定拆几个子任务（运行时动态）
          ↓  fan_out 返回 N 个 Send
      worker × N  ← 相同节点，N 个实例并行执行
          ↓  operator.add 自动汇聚 results
        merger   ← LangGraph 等所有 worker 完成后触发
          ↓
        __end__
    """
    # 用 lambda 把 llm 注入节点函数（闭包传参）
    async def _planner(state):  return await planner_node(state, llm)
    async def _worker(state):   return await worker_node(state, llm)
    async def _merger(state):   return await merger_node(state, llm)

    g = StateGraph(BatchState)
    g.add_node("planner", _planner)
    g.add_node("worker",  _worker)
    g.add_node("merger",  _merger)

    g.set_entry_point("planner")
    g.add_conditional_edges("planner", fan_out, ["worker"])  # 动态扇出
    g.add_edge("worker", "merger")                           # 所有 worker → merger
    g.add_edge("merger", END)

    return g.compile(checkpointer=checkpointer)


# ── 快速验证入口 ──────────────────────────────────────────────

async def demo():
    """运行演示：生成100张猫的图片（模拟）。"""
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    from mirage.app.core.config import settings
    from langchain_openai import ChatOpenAI
    import httpx

    llm = ChatOpenAI(
        api_key=settings.OPENAI_API_KEY or "sk-no-llm-key-set",   # 占位兜底:无 key 不在构造时崩(真调用才报)
        base_url=settings.OPENAI_API_BASE,
        model=settings.MODEL_NAME,
        http_async_client=httpx.AsyncClient(verify=not settings.SKIP_SSL_VERIFY),
        max_retries=2,
    )

    graph = build_batch_graph(llm)

    print("\n=== Map-Reduce 动态并行 Agent 演示 ===\n")
    result = await graph.ainvoke({
        "request": "生成100张猫的照片，要求包含不同品种：橘猫、英短、布偶、暹罗、波斯猫",
        "subtasks": [],
        "results": [],
        "final_summary": "",
    })

    print("\n=== 最终汇总 ===")
    print(result["final_summary"])
    print(f"\n[共收到 {len(result['results'])} 个 Worker 结果]")


if __name__ == "__main__":
    asyncio.run(demo())
