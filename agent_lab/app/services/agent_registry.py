import importlib
import os
import glob
from typing import Callable, Dict, Set, Optional
from dataclasses import dataclass
from agent_lab.app.core.logger import get_logger

logger = get_logger("agent_registry")


@dataclass
class AgentMetadata:
    name: str
    builder: Callable
    description: str
    node_labels: Dict[str, str]
    routing_keywords: list = None
    user_facing_nodes: Set[str] = None  # 限定哪些节点的 LLM 输出可流给前端（None 表示全部）


class AgentRegistry:
    """
    热插拔 Agent 注册中心与自动发现引擎。
    """
    def __init__(self):
        self._agents: Dict[str, AgentMetadata] = {}

    def register(self, name: str, builder: Callable, description: str = "", node_labels: Dict[str, str] = None, routing_keywords: list = None, user_facing_nodes: Set[str] = None):
        """
        显式注册一个子 Agent 有向图。
        """
        self._agents[name] = AgentMetadata(
            name=name,
            builder=builder,
            description=description,
            node_labels=node_labels or {},
            routing_keywords=routing_keywords or [],
            user_facing_nodes=user_facing_nodes
        )
        logger.info(f"[AgentRegistry] 成功注册插拔式子 Agent: '{name}' | 描述: {description}")

    def get_agent(self, name: str) -> Optional[AgentMetadata]:
        return self._agents.get(name)

    def get_valid_agents(self) -> Set[str]:
        return set(self._agents.keys())

    def discover_and_register(self):
        """
        动态扫描 agent_lab/app/agents 目录下的所有 python 文件。
        如果文件中包含 `register_agent(registry)` 挂钩函数，则执行动态导入与加载注册。
        """
        logger.info("[AgentRegistry] 启动热插拔子 Agent 动态扫描流程...")

        # 1. 静态预注册核心系统级子 Agent，保证完美向下兼容，免去修改它们代码的风险
        try:
            from agent_lab.app.agents.code_agent import build_code_subgraph
            from agent_lab.app.agents.file_agent import build_file_subgraph
            from agent_lab.app.agents.batch_agent import build_batch_graph
            from agent_lab.app.agents.general_agent import build_general_subgraph
            from agent_lab.app.agents.shell_agent import build_shell_subgraph

            self.register("code", build_code_subgraph, "代码生成与执行 Agent", {"code_agent": "代码执行 Agent"})
            self.register("file", build_file_subgraph, "文件编辑与查看 Agent")
            self.register("batch", build_batch_graph, "批处理任务 Agent")
            self.register("general", build_general_subgraph, "通用问答与工具检索 Agent")
            self.register("shell", build_shell_subgraph, "命令行执行 Agent")
        except Exception as e:
            logger.error(f"[AgentRegistry] 核心 Agent 预注册失败: {e}")

        # 2. 扫描并自动加载 custom/plugins 文件夹或当前目录下的其他 py 插件
        agents_dir = os.path.dirname(os.path.abspath(__file__)) # services
        # 寻找 agents 目录
        agents_dir = os.path.join(os.path.dirname(agents_dir), "agents")
        if not os.path.exists(agents_dir):
            logger.warning(f"[AgentRegistry] 未找到 agents 目录: {agents_dir}")
            return

        pattern = os.path.join(agents_dir, "*.py")
        files = glob.glob(pattern)

        for filepath in files:
            filename = os.path.basename(filepath)
            # 避开系统保留或入口文件
            if filename in ("__init__.py", "state.py", "supervisor.py"):
                continue

            module_name = filename[:-3]  # 去除 .py 后缀
            import_path = f"agent_lab.app.agents.{module_name}"

            try:
                # 动态导入模块
                module = importlib.import_module(import_path)
                # 检测模块是否包含 register_agent 挂钩函数
                if hasattr(module, "register_agent"):
                    register_fn = getattr(module, "register_agent")
                    logger.info(f"[AgentRegistry] 发现热插拔组件 '{module_name}'，正在加载注册...")
                    register_fn(self)
            except Exception as e:
                logger.error(f"[AgentRegistry] 动态导入/注册模块 {import_path} 时发生异常: {e}", exc_info=True)


# 实例化单例并触发自动扫描注册
agent_registry = AgentRegistry()
agent_registry.discover_and_register()
