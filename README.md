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

### Phase 4 — 知识检索与动态扩展

#### Chapter 14 — Skill 动态检索（RAG 应用于工具选择）

**问题：** 用户上传了大量 Skill，无法全部塞进 LLM 上下文（token 浪费 + 注意力稀释）。

**原理：** 和 RAG 完全一样，只是把"文档"换成了"工具描述"：

```
注册阶段：工具 description → OpenAI Embedding → FAISS 向量索引
检索阶段：用户问题        → Embedding        → 余弦相似度搜索 → Top-K 工具
```

**核心实现：** `app/services/skill_registry.py`

```python
class SkillRegistry:
    def register(self, tools: list[BaseTool]) -> None:
        texts = [f"{t.name}: {t.description}" for t in tools]
        vecs = np.array(self._embedder.embed_documents(texts), dtype=np.float32)
        faiss.normalize_L2(vecs)          # 归一化 → 内积 = 余弦相似度
        self._index.add(vecs)

    async def search(self, query: str, top_k: int = 3) -> list[BaseTool]:
        vec = np.array(await self._embedder.aembed_query(query), dtype=np.float32)
        faiss.normalize_L2(vec.reshape(1, -1))
        scores, indices = self._index.search(vec.reshape(1, -1), top_k)
        return [self._tools[self._names[i]] for i in indices[0]]
```

**图结构变化（每个子图加入 skill_retrieval 节点）：**

```
__start__
    ↓
skill_retrieval  ← embed(用户问题) → FAISS → Top-K 工具名写入 state
    ↓
agent            ← llm.bind_tools(仅检索到的K个工具)  动态绑定！
    ↓
tools            ← 从 state 中取工具执行
    ↓
agent → ... → __end__
```

- 新依赖：`faiss-cpu` + `OpenAIEmbeddings`（`langchain-openai` 已含）
- 日志输出：`[SkillRegistry] 查询: '帮我执行代码' → 检索到: ['execute_python_code'] | 相似度: [0.891]`

---

#### Chapter 15 — Map-Reduce：动态并行 Worker Agent

**问题：** 生成 100 张图片不能让同一个 Agent 串行处理，需要动态创建 N 个相同 Worker 并行执行。

**核心技术：** `Send` API + `operator.add` reducer（Map-Reduce 模式）

```python
import operator

class BatchState(TypedDict):
    subtasks: list[dict]
    # operator.add reducer：每个 worker 写入的列表自动拼接，不会互相覆盖
    results: Annotated[list[str], operator.add]
```

**图结构：**

```
planner    ← LLM 分析任务，动态决定拆几份（运行时决定，非硬编码）
    ↓  fan_out 返回 N 个 Send("worker", 子任务)
worker × N ← 相同节点函数，N 个实例完全并行，互不干扰
    ↓  operator.add 自动汇聚所有结果
merger     ← LangGraph 等全部 worker 完成后触发
```

**关键代码：**

```python
def fan_out(state: BatchState) -> list[Send]:
    # N 由 planner 运行时决定，不是固定数字
    return [Send("worker", {"subtask": task}) for task in state["subtasks"]]

async def worker_node(state: WorkerState) -> dict:
    result = await process(state["subtask"])
    return {"results": [result]}  # 列表包装，add reducer 汇聚

g.add_conditional_edges("planner", fan_out, ["worker"])
g.add_edge("worker", "merger")   # 所有 worker → merger，LangGraph 自动等待
```

**与 Supervisor 模式的区别：**

| | Supervisor 模式（Chapter 11） | Map-Reduce 模式（本章） |
|---|---|---|
| Worker 数量 | 固定（code/file/general 三种） | 运行时动态决定 |
| Worker 类型 | 不同节点（不同职责） | 相同节点（相同逻辑） |
| 结果汇聚 | 专属字段（code_result 等） | `operator.add` reducer |
| 适用场景 | 意图路由 | 批量并行任务 |

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

```
现在          第一阶段      第二阶段      第三阶段      第四阶段
─────────────────────────────────────────────────────────────
单体系统  →  加Compaction → 加FastAPI  → 拆微服务   → 上K8S
（能跑）     （能稳定跑）   （能对外用）  （能扩容）   （能生产）
```

---

### ✅ 已完成

| Module | 内容 | 文件 |
|--------|------|------|
| 14 | Skill 动态检索（FAISS + Embedding） | `app/services/skill_registry.py` |
| 15 | Map-Reduce 动态并行 Worker | `app/agents/batch_agent.py` |

---

### 第一阶段 — 稳定性（最紧迫）

**Module 16：上下文压缩 Compaction**

没有这个，对话超过一定长度就会 token 超限崩溃。

- **方案**：摘要压缩（Claude Code 同款）——旧消息交给 LLM 总结成一段话，替换原消息，保留最近 5 条保持连贯
- **实现位置**：`app/agents/supervisor.py`，在图入口前加 `summarizer` 节点
- **触发条件**：`messages` 超过 15 条自动触发

```python
async def maybe_summarize(state: SupervisorState) -> dict:
    if len(state["messages"]) <= 15:
        return {}
    summary = await llm.ainvoke([
        SystemMessage("简洁总结以下对话的核心内容和关键决策："),
        *state["messages"][:-5]
    ])
    return {"messages": [SystemMessage(f"【历史摘要】{summary.content}"),
                         *state["messages"][-5:]]}

g.add_node("summarizer", maybe_summarize)
g.set_entry_point("summarizer")
g.add_edge("summarizer", "router")
```

---

### 第二阶段 — 对外暴露

**Module 17：FastAPI 接口层**
- `ai_service.chat()` 包成 HTTP POST 接口
- SSE（Server-Sent Events）流式推送 AI 回复，前端实时显示
- 支持多用户并发（thread_id 隔离已有，直接复用）

**Module 18：Human-in-the-loop 人工审核**
- Agent 执行到危险节点（写文件、执行代码）时暂停，等用户确认再继续
- 实现：`graph.compile(interrupt_before=["code_agent"])` + `graph.update_state()`

---

### 第三阶段 — 微服务化

**Module 19：Agent 服务拆分**

Supervisor 保持完整（编排层不拆），只把 Worker Agent 拆成独立 HTTP 服务：

```
Supervisor Service（编排，不拆）
    ↓ HTTP 并行调用（asyncio 等待，LangGraph 并行聚合不变）
CodeAgent Service :8001   FileAgent Service :8002   General Service :8003
    ↓
PostgreSQL（替换 SQLite，多服务共享 Checkpoint）
```

- Worker 服务可独立扩容：CodeAgent 压力大就多起几个实例
- Supervisor 里只改节点函数：函数调用 → `httpx.AsyncClient().post(...)`
- LangGraph 的并行等待和聚合逻辑**零改动**

**Module 20：Docker 容器化**
- 每个服务写 `Dockerfile`
- `docker-compose` 本地一键启动所有服务
- 代码执行沙箱：每次执行启动独立容器，执行后销毁

---

### 第四阶段 — 生产级

**Module 21：可观测性**
- LangSmith tracing：追踪每次 LLM 调用的输入输出、延迟、cost
- 结构化日志接入 ELK / Loki
- 告警：错误率异常自动通知

**Module 22：K8S 部署**
- 各服务部署为 K8S Deployment
- 自动弹性扩缩容（HPA）
- NetworkPolicy 限制代码执行沙箱出站访问

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
