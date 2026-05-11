# AgentLab —— AI Agent 工程化实战

> 从 LangChain 新手到具备工程化思维的 AI 开发者，完整记录每一步踩坑与突破。
> 技术栈：Python · LangChain · LangGraph · Pydantic V2 · aiosqlite · DeepSeek API

---

## 项目架构图

```
用户输入
   ↓
main.py（CLI 交互层）
   ↓
AIService.chat(session_id, content)
   ↓  AsyncSqliteSaver（LangGraph 原生持久化，按 thread_id 存储）
┌──────────────────────────────────────────┐
│  Supervisor Graph（主路由图）              │
│                                          │
│  router ← LLM 分析意图，选多个 Agent       │
│     ↓  Send API 并行扇出                  │
│  code_agent  file_agent  general         │
│  （子图隔离） （子图隔离） （主图节点）      │
│     ↓  全部完成后汇聚                     │
│  aggregator ← LLM 整合多路结果            │
└──────────────────────────────────────────┘
   ↓
流式输出回用户
```

LangGraph 图拓扑：

```
          __start__
              ↓
           router
        ↙    ↓    ↘      （Send API 并行扇出，可同时触发多个）
  code_agent file_agent general
        ↘    ↓    ↙      （全部完成后自动汇聚）
         aggregator
              ↓
           __end__
```

---

## 已完成学习内容

### Phase 1 — 工程基础

#### Chapter 1 — 数据合约：Pydantic V2 Schema

- 核心：用 `BaseModel` + 字段验证替代裸字典，在系统边界强制数据格式
- 关键代码：`app/schemas/base.py` 中的 `AIRequest`（含 UUID 自动生成、空白检测 validator）
- 踩坑：Pydantic V2 的 `model_config = ConfigDict(...)` 替换了 V1 的 `class Config`

```python
class AIRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str = Field(..., min_length=1)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content 不能为纯空白")
        return v
```

---

#### Chapter 2 — 异步消息历史（已被 LangGraph 取代，保留学习价值）

- 问题根源：LangChain 官方 `SQLChatMessageHistory` 是同步的，在 asyncio 环境下会死锁
- 解决方案：自己实现 `AsyncSQLiteHistory`（继承 `BaseChatMessageHistory`），用 `aiosqlite` 实现非阻塞 IO
- 架构模式：DAO 模式 —— `_ensure_table()` 懒加载建表、`aget_messages()` / `aadd_messages()` 读写分离
- **后续升级**：迁移到 LangGraph 原生 Checkpointer 后，此类已删除，但理解它的设计是理解 LangGraph 持久化的前提

---

#### Chapter 3 — 工具调用协议

- 工具定义：`@tool` 装饰器 + docstring = LLM 能理解的工具说明书
- 关键协议：消息顺序必须严格遵守 `User → AIMessage(tool_calls) → ToolMessage(s) → AIMessage(summary)`
- 踩坑：跳过中间任何一步会触发 API 报错 `insufficient tool messages`
- 实现的工具：`get_current_time` / `list_files` / `read_file_content` / `execute_python_code`

```python
@tool
def execute_python_code(code: str) -> str:
    """执行 Python 代码并返回输出结果。用于数据处理、计算等任务。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp_path = f.name
    result = subprocess.run(
        ["python", tmp_path], capture_output=True, text=True, timeout=10
    )
    return result.stdout or result.stderr
```

---

#### Chapter 4 — LangGraph 状态机基础

- 核心概念：State（共享黑板）、Node（处理函数）、Edge（固定跳转）、Conditional Edge（条件跳转）
- 图结构：`agent → (有工具调用?) → tools → agent` 的 ReAct 循环
- **自纠错原理**：工具执行失败时返回错误字符串，LLM 下一轮看到错误自动修正代码，无需手动 retry

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

g = StateGraph(AgentState)
g.add_node("agent", agent_node)
g.add_node("tools", tools_node)
g.set_entry_point("agent")
g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
g.add_edge("tools", "agent")
```

---

### Phase 2 — 工程质量提升

#### Chapter 5 — 依赖管理

- 问题：没有 `requirements.txt`，项目在新环境无法复现
- 解决：`pip freeze | grep ...` 提取版本，写入 `requirements.txt` + `.env.example`

---

#### Chapter 6 — 结构化日志

- 问题：`print` 无时间戳、无级别、无法过滤
- 解决：`app/core/logger.py` 的 `get_logger(name)` 工厂函数
- 格式：`HH:MM:SS [LEVEL] module: message`
- 原则：流式输出给用户的 chunk 保留 `print`，系统内部状态用 `logger`

```python
def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger
```

---

#### Chapter 7 — 单一职责重构

- 问题：`ai_service.py` 的 `chat()` 方法同时做了 7 件事
- 解决：拆分出 `_agent_node()` / `_tools_node()` / `_should_continue()` / `_build_agent()` 等私有方法
- 原则：每个方法只做一件事，方法名即注释

---

### Phase 3 — 多 Agent 协作

#### Chapter 8 — LangGraph 显式图构建 vs create_react_agent

- `create_react_agent`：预构建快捷方式，隐藏了图细节，适合生产快速开发
- 显式 `StateGraph`：手写 `add_node` / `add_conditional_edges`，可以看到每条边，适合学习和深度定制
- 决策：学习阶段用显式构建，理解每条边的含义后再考虑用 prebuilt

---

#### Chapter 9 — LangGraph 原生持久化

LangGraph 自带持久化，不需要额外数据库，按 `thread_id` 自动隔离会话：

```python
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

conn = await aiosqlite.connect("checkpoint.db")
memory = AsyncSqliteSaver(conn)
compiled = g.compile(checkpointer=memory)

# 调用时传 thread_id 即会话 ID，自动隔离
config = {"configurable": {"thread_id": session_id}}
await compiled.ainvoke({"messages": [("user", content)]}, config=config)
```

- `AsyncSqliteSaver` 存储整个 State 快照（含所有 messages），服务重启后历史自动恢复
- 这使得自定义 `history.py` 完全冗余，已删除
- 注意：需要单独安装 `pip install langgraph-checkpoint-sqlite`

---

#### Chapter 10 — Supervisor 多 Agent 模式

- 架构：主图（Supervisor）负责路由，子图（CodeAgent / FileAgent）负责专业执行
- 隔离原理：每个子图有独立的 State TypedDict（`CodeState` / `FileState`），与主图 `SupervisorState` 完全隔离
- 工具分组：`code_tools` / `file_tools` / `general_tools` 各自只注入对应 Agent，避免"工具噪声"

```python
# 子图工厂函数
def build_code_subgraph(llm):
    class CodeState(TypedDict):
        messages: Annotated[list, add_messages]
    g = StateGraph(CodeState)
    # ... 独立的 ReAct 循环
    return g.compile()

# 主图调用子图
result = await code_graph.ainvoke({"messages": state["messages"]})
final_msg = next((m for m in reversed(result["messages"]) if isinstance(m, AIMessage)), None)
```

---

#### Chapter 11 — Send API 并行执行（if-if 而非 if-else-if）

- 原 `if-else-if` 问题：条件边每次只走一条路径，无法同时处理多类需求
- `Send` API 解决：`fan_out` 函数返回 `list[Send]`，LangGraph 并行启动所有目标节点

```python
from langgraph.types import Send

def fan_out(state: SupervisorState) -> list[Send]:
    node_map = {"code": "code_agent", "file": "file_agent", "general": "general"}
    return [
        Send(node_map[agent], {"messages": state["messages"]})
        for agent in state["selected_agents"]
        if agent in node_map
    ]

g.add_conditional_edges("router", fan_out, ["code_agent", "file_agent", "general"])
```

- 状态隔离技巧：每个并行 Agent 写自己专属字段（`code_result` / `file_result` / `general_result`），router 每轮重置为 `""` 避免跨轮残留
- 汇聚：三条边同指 `aggregator`，LangGraph 自动等全部激活节点完成再触发

---

#### Chapter 12 — LangGraph Studio 可视化

配置文件放在项目根目录：

```json
{
  "dependencies": ["."],
  "graphs": {
    "supervisor": "./agent_lab/app/agents/supervisor.py:graph"
  },
  "env": ".env"
}
```

模块级变量（`supervisor.py` 末尾）：

```python
graph = build_supervisor(_llm).compile()
```

启动可视化：

```bash
langgraph dev
# 浏览器打开 http://localhost:2024
```

Studio 功能：节点执行动画、每步 State 快照、手动注入消息测试图流转

---

#### Chapter 13 — 沙箱隔离（概念）

- 当前实现：`execute_python_code` 用裸 `subprocess`，LLM 生成代码可访问任意文件/网络
- 工程实践：生产环境使用 **Docker + K8S** 做容器级隔离
  - 每次代码执行启动独立容器，执行完销毁
  - NetworkPolicy 限制出站访问
  - 文件系统只读挂载，仅 `/tmp` 可写
  - 资源配额限制（CPU/内存），防止恶意代码耗尽资源

---

## 踩坑记录

| 错误 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: langgraph.checkpoint.sqlite` | 官方包已拆分独立发布 | `pip install langgraph-checkpoint-sqlite` |
| `insufficient tool messages` | tool_calls 后缺少对应 ToolMessage | 严格按 AIMessage(tool_calls) → ToolMessage → AIMessage 顺序 |
| `SqliteSaver does not support async` | 在 async 上下文用了同步 Saver | 换 `AsyncSqliteSaver` + `aiosqlite.connect()` |
| `draw_ascii() ImportError` | 缺少 `grandalf` 渲染库 | `pip install grandalf` |
| 中文终端乱码（Windows） | stdout 默认编码非 UTF-8 | `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')` |
| SSL 证书报错（Windows） | 系统证书链问题 | `httpx.AsyncClient(verify=False)` 或更新证书 |

---

## 后续学习路线图

### Phase 4 — 知识增强

**Module 14：RAG 知识检索系统**
- 向量数据库（Chroma / FAISS）存储私有文档
- Embedding 模型将文本转为向量，用户提问 → 相似度检索 → 注入 prompt → LLM 回答
- 解决：LLM 不知道私有文档内容的核心问题

**Module 15：Human-in-the-loop（人工审核节点）**
- LangGraph `interrupt()` —— Agent 执行到关键节点时暂停，等人类确认后继续
- 场景：执行危险代码前、发送邮件前、写入数据库前
- 实现：`graph.compile(interrupt_before=["code_agent"])` + `graph.update_state()`

**Module 16：Agent 评估与测试**
- LangSmith tracing —— 追踪每次 LLM 调用的输入输出、延迟、cost
- 自动化评估：构建测试集，评估 Agent 路由准确率、工具调用成功率
- 回归测试：防止改动破坏已有能力

### Phase 5 — 生产化

**Module 17：FastAPI 接口层**
- 将 CLI 改造为 HTTP API，支持前端/移动端调用
- SSE（Server-Sent Events）流式推送 AI 回复
- 多用户并发会话管理

**Module 18：Docker 容器化**
- `Dockerfile` 打包应用
- 代码执行沙箱：每次执行启动独立容器，执行后销毁
- `docker-compose` 本地联调

**Module 19：K8S 部署 + 沙箱隔离**
- 主应用部署为 K8S Deployment
- 代码执行 Pod：按需创建、NetworkPolicy 限制出站、资源限额（CPU/内存）
- 健康检查 + 自动重启

**Module 20：可观测性**
- 结构化日志 → ELK / Loki
- 指标：请求量、延迟 P99、Agent 路由分布、工具调用成功率
- 告警：异常错误率自动通知

---

## 快速启动

```bash
git clone <repo>
cd build-with-langchain
pip install -r requirements.txt
cp .env.example .env     # 填入 API Key
python agent_lab/main.py

# LangGraph Studio 可视化
langgraph dev
```
