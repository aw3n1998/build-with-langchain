"""
Video Agent —— 小说转短剧视频的热插拔子 Agent。

这是把"headless / 解耦 / 人在回路（HITL）小说转视频架构"接进本框架的入口：
  - 复用与 general_agent 一致的 ReAct 子图结构（skill_retrieval → agent → tools）。
  - 工具来自 pipeline.pipeline_tools（建项目 / 加分镜 / 出图 / 选图 / 图生视频）。
  - 通过文件级 `register_agent(registry)` 挂钩被 AgentRegistry 自动发现，无需改 supervisor.py。

状态机（落在 SQLite，见 pipeline.store）：
  DRAFT → PENDING_FLUX_GEN → PENDING_HUMAN_SELECTION →(选图) PENDING_VIDEO_GEN → COMPLETED
HITL 卡点在 PENDING_HUMAN_SELECTION：出图后暂停，由人或上层 Agent 调 select_candidate 选图再继续。
"""

from typing import Annotated
from typing_extensions import TypedDict

from langchain_core.messages import ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from agent_lab.app.services.msg_utils import sanitize_messages
from agent_lab.app.services.skill_registry import SkillRegistry
from agent_lab.app.services.stream_events import emit_tool_call, emit_tool_result
from agent_lab.app.core.logger import get_logger

logger = get_logger("video_agent")

_PROMPT = SystemMessage(content=(
    "你是『小说转短剧视频』流水线助手。你的职责是把小说片段拆成分镜，"
    "再驱动远程 GPU 出图（FLUX）、选图（人在回路）、图生视频（Wan2.2），最终产出 mp4。\n"
    "标准流程：\n"
    "  0) 用户说『参考这个小说/这个文件夹里的小说』时，先用 list_workspace_files 找到小说文件，"
    "再用 read_text_file 读正文（长篇可分段读），据此构思分镜与提示词；\n"
    "  1) create_video_project 建项目；\n"
    "  2) add_scene 逐个加分镜（写好 image_prompt 与 motion_prompt）。角色触发词不要写死在提示词里——"
    "它由工作目录配置（.agent/config.json 的 trigger_word）决定，出图时会自动注入；"
    "用户提到某角色触发词/LoRA/风格时，调 configure_character 写入配置即可；\n"
    "  3) 【拆完所有分镜后，立刻调 open_production_panel(project_id)，不要询问用户『要不要打开面板』"
    "或『逐个出还是一起出』——直接开】。开完用一两句话告诉用户：在面板上"
    "「一键全部出图 → 每个分镜点选一张 → 一键出片并合成」即可，底部也有常驻的「制作面板」按钮可随时再打开。"
    "**你不要自己逐个出图/出片，也没有任何「参数卡」可弹**——机械步骤全部归面板；\n"
    "  4) 用户若想微调某个分镜（换提示词重新出图），你可以直接调 generate_candidates(scene_id, image_prompt=新提示词)；"
    "选图只能由用户在面板上点击完成，你不要用文字替用户选图，"
    "也不要凭记忆断言某分镜有没有图（要查先调 list_project_scenes）；\n"
    "  5) 随时用 list_project_scenes / project_status 查进度；用户找不到面板时，"
    "重新调一次 open_production_panel(project_id) 即可再弹一个。\n"
    "每步调用工具后，用简洁中文向用户汇报状态与下一步。遇到 GPU 未配置时，提示用户在 .env 填 GPU_SSH_* 配置。"
))


class VideoState(TypedDict):
    messages: Annotated[list, add_messages]
    active_tools: list[str]


def build_video_subgraph(llm, registry: SkillRegistry, checkpointer=None):
    """工厂：返回小说转视频 ReAct 子图（结构同 general_agent，工具偏向流水线工具）。"""

    # 流水线核心工具永远可用：语义检索只做补充。否则用户回一句「可以/好的」，
    # 检索拿这两个字去搜会返回不相干工具，agent 就会宣称"我没有出图工具"。
    _ESSENTIALS = [
        "create_video_project", "add_scene", "list_project_scenes", "project_status",
        "open_production_panel", "generate_candidates", "assemble_episode",
        "list_workspace_files", "read_text_file", "configure_character",
    ]

    async def skill_retrieval_node(state: VideoState) -> dict:
        query = next(
            m.content for m in reversed(state["messages"]) if m.type == "human"
        )
        retrieved = await registry.search(query, top_k=6)
        names = []
        for n in dict.fromkeys(_ESSENTIALS + [t.name for t in retrieved]):
            try:
                registry.get(n)
                names.append(n)
            except Exception:
                pass   # 未注册的名字直接跳过，避免 agent_node 取工具时崩
        logger.info("[VideoAgent] skill_retrieval → %s", names)
        return {"active_tools": names}

    async def agent_node(state: VideoState) -> dict:
        tools = [registry.get(n) for n in state["active_tools"]]
        llm_dynamic = llm.bind_tools(tools) if tools else llm
        response = await llm_dynamic.ainvoke([_PROMPT] + sanitize_messages(state["messages"]))
        return {"messages": [response]}

    async def tools_node(state: VideoState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            name = tc["name"]
            logger.info("[VideoAgent] 执行工具: %s", name)
            emit_tool_call(name, tc.get("args"))
            # 优先用本轮检索到的工具；召回里没有时回退到全局 registry，
            # 避免 LLM 调了未在 active_tools 中的工具就整图崩掉。
            try:
                tool = registry.get(name)
            except KeyError:
                tool = None
            if tool is None:
                msg = f"[工具不可用] 未找到工具 `{name}`，请改用已注册的流水线工具。"
                logger.warning("[VideoAgent] %s", msg)
                emit_tool_result(name, msg)
                results.append(ToolMessage(content=msg, tool_call_id=tc["id"]))
                continue
            try:
                result = await tool.ainvoke(tc["args"])
                emit_tool_result(name, result)
                results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
            except Exception as e:  # 工具执行失败（如 GPU 未开机）回灌给 LLM，而非中断整图
                err = f"[工具执行失败] {name}: {type(e).__name__}: {e}"
                logger.warning("[VideoAgent] %s", err)
                emit_tool_result(name, err)
                results.append(ToolMessage(content=err, tool_call_id=tc["id"]))
        return {"messages": results}

    def should_continue(state: VideoState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    g = StateGraph(VideoState)
    g.add_node("skill_retrieval", skill_retrieval_node)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)

    g.set_entry_point("skill_retrieval")
    g.add_edge("skill_retrieval", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")

    return g.compile(checkpointer=checkpointer)


def register_agent(registry) -> None:
    """AgentRegistry 自动发现挂钩：把 video_agent 注册为热插拔子 Agent。"""
    registry.register(
        name="video",
        builder=build_video_subgraph,
        description="小说转短剧视频流水线 Agent（拆分镜 / FLUX 出图 / HITL 选图 / Wan2.2 图生视频 / 出 mp4）",
        node_labels={"agent": "视频流水线 Agent", "tools": "流水线工具执行"},
        routing_keywords=[
            "视频", "短剧", "分镜", "出图", "图生视频", "成片", "mp4",
            "flux", "wan", "wan2.2", "ltx", "小说转视频", "选图", "运镜", "video",
            "合成", "拼接", "旁白", "字幕", "配音",
        ],
        user_facing_nodes={"agent"},
    )
