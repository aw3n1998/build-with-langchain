# 蜃景 Mirage —— AI Agent 工程化实战

> 从 LangChain 新手到具备工程化思维的 AI 开发者，完整记录每一步踩坑与突破。
> 技术栈：Python · LangChain · LangGraph · FastAPI · React · Pydantic V2 · aiosqlite · Milvus · FastEmbed

---

## 项目概览

蜃景 是一套**完整的 AI Agent 工程实战项目**，从零搭建多 Agent 协作系统，并最终交付一个真实可用的全栈 Web 应用。

**学习目标**：理解并实现企业级 AI Agent 系统的每一个核心模块，不停留在调用 API，而是理解底层机制。

**最终产物**：一个带完整 UI 的多 Agent 对话平台，支持 RAG 知识库、并行 Agent 路由、每个 Agent 独立配置 LLM。

---

## 全栈架构图

```
┌─────────────────────────────────────────────────────────┐
│                    浏览器 (React + Vite)                 │
│                                                         │
│  HistorySidebar ─ 历史会话侧边栏（新建/选择/删除会话）   │
│  TopBar ─ 显示当前模型、RAG 状态、侧栏开关及操作按钮     │
│  ChatWindow ─ 流式渲染 AI 消息（Markdown & 格式化表格）   │
│  InputBar ─ 发消息 + Agent 选择（5 种）                  │
│  KnowledgePanel ─ 抽屉面板：上传文件 / 粘贴文本           │
│  SettingsPanel ─ 抽屉面板：每个 Agent 独立配置 LLM        │
│                                                         │
│  api.js: fetch API / SSE 流式读取 / 历史会话管理          │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────────┐
│              FastAPI 后端（mirage/）                  │
│                                                         │
│  POST /api/chat        ← SSE 流式对话                   │
│  POST /api/rag/ingest  ← 文件/文本导入知识库             │
│  GET  /api/rag/status  ← Milvus 连接状态                │
│  GET  /api/health      ← 健康检查                       │
│                                                         │
│  AIService.astream_chat()                               │
│     ↓ 读 agent_configs（前端传入）                       │
│     ↓ 按配置构建各 Agent 的 LLM 实例                     │
│                                                         │
│  ┌─────────────────────────────────────────┐            │
│  │   Supervisor Graph（默认路由模式）        │            │
│  │                                         │            │
│  │   summarizer ← 长对话自动压缩（Compact）  │            │
│  │       ↓                                 │            │
│  │    router   ← LLM 识别意图，选多个 Agent  │            │
│  │   ↙   ↓   ↘   Send API 并行扇出          │            │
│  │ code file general ← 独立子图             │            │
│  │   ↘   ↓   ↙   全部完成后汇聚             │            │
│  │  aggregator ← LLM 整合多路结果           │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│  直连子 Agent 模式（跳过 Supervisor）：                   │
│    code / file / general / batch                        │
│                                                         │
│  AsyncSqliteSaver → langgraph_checkpoint.db             │
│  SkillRegistry    → FAISS 语义工具检索                   │
│  RAGPipeline      → Milvus 混合检索（BM25 + 向量 + RRF） │
└──────────────────────┬──────────────────────────────────┘
                       │ pymilvus
┌──────────────────────▼──────────────────────────────────┐
│                   Milvus（Docker）                       │
│        向量数据库，存储 RAG 知识库 chunk                  │
└─────────────────────────────────────────────────────────┘
```

---

## 快速启动

### 前置条件

- Python 3.11+
- Node.js 18+（前端）
- Docker Desktop（Milvus 向量数据库，可选，不启动则 RAG 降级运行）

### 1. 克隆与安装

```bash
git clone <repo>
cd build-with-langchain

# 安装 Python 依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 和 OPENAI_API_BASE（DeepSeek/OpenAI/其他）
```

### 2. 启动 Milvus（可选）

```bash
docker compose up -d
# 等待约 30 秒，确认 Docker Desktop 鲸鱼图标稳定
```

### 3. 启动后端

```bash
python mirage/main_api.py
# 监听 http://localhost:8000
# Swagger UI: http://localhost:8000/docs
```

### 4. 启动前端（开发模式）

```bash
cd frontend
npm install
npm run dev
# 浏览器访问 http://localhost:5173
```

### 5. 生产构建（前端打包到后端静态目录）

```bash
cd frontend
npm run build
# 构建产物输出到 mirage/static/
# 之后访问 http://localhost:8000 即可（后端托管前端）
```

### 6. CLI 模式（无前端，终端对话）

```bash
python mirage/main.py
```

### 7. LangGraph Studio 可视化调试

```bash
langgraph dev
# 浏览器访问 http://localhost:2024
```

---

## 前端功能说明

### Agent 选择器

InputBar 上方有 5 个 Agent 切换按钮：

| Agent | 说明 |
|-------|------|
| Supervisor | 默认模式，LLM 自动识别意图并行分发 |
| General | 直连通用问答 Agent（RAG + 工具），无路由开销 |
| Code | 直连代码执行 Agent |
| File | 直连文件处理 Agent |
| Batch | 批量并行任务（Map-Reduce 模式） |

### 知识库面板（Knowledge Base）

点击 TopBar 右侧书图标打开：
- **Upload File**：支持 .txt / .pdf / .docx，上传后自动分片入库
- **Paste Text**：直接粘贴文本内容，填写来源名称后导入

### 设置面板（Settings）

点击 TopBar 右侧设置图标打开，5 个可折叠 Agent 配置块：

```
▶ Supervisor  [deepseek-chat · api.deepseek.com]
▶ Code Agent  [gpt-4o · api.openai.com]
▶ File Agent  [— using Supervisor config —]
▶ General     [deepseek-reasoner · api.deepseek.com]
▶ Batch       [— using Supervisor config —]
```

每个 Agent 支持：
- **Preset chips**（同时填 model + api_base）：DeepSeek Chat / DeepSeek R1 / GPT mini / GPT-4o
- Model Name 输入
- API Base URL 输入
- API Key 输入（带显示/隐藏）
- 留空 = 跟随 `.env` 默认配置

顶部另有 **Backend Endpoint** 字段，支持连接远程部署的后端。

配置存储：`localStorage.agentlab_agent_configs`（JSON），每次发消息随请求体发给后端。

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
def build_code_subgraph(llm, registry, checkpointer=None):
    class CodeState(TypedDict):
        messages: Annotated[list, add_messages]
    g = StateGraph(CodeState)
    # ... 独立的 ReAct 循环
    return g.compile(checkpointer=checkpointer)

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
    "supervisor": "./mirage/app/agents/supervisor.py:graph"
  },
  "env": ".env"
}
```

模块级变量（`supervisor.py` 末尾）：

```python
graph = build_supervisor({"supervisor": _llm}, _registry).compile()
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
注册阶段：工具 description → FastEmbed Embedding → FAISS 向量索引
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

- 新依赖：`faiss-cpu` + `FastEmbedEmbeddings`（本地模型，无 API 费用）
- 日志输出：`[SkillRegistry] 查询: '帮我执行代码' → 检索到: ['execute_python_code'] | 相似度: [0.891]`

---

#### Chapter 15 — Map-Reduce：动态并行 Worker Agent（`app/agents/batch_agent.py`）

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

#### Chapter 16 — 上下文压缩 Compaction（`app/agents/supervisor.py`）

**问题：** 对话越来越长，传给 LLM 的 token 数量无限增长，最终触发 context limit 崩溃。

**方案：** 摘要压缩（和 Claude Code `/compact` 同款原理）

```
入口处自动检查消息数量：
  ≤ 阈值（20条）：直接跳过，零开销
  > 阈值         ：旧消息 → LLM 总结 → 替换原消息，保留最近 6 条保持连贯性
```

**实现位置：** `supervisor.py` 中的 `summarizer_node`，作为图的第一个节点：

```python
async def summarizer_node(state: SupervisorState) -> dict:
    messages = state["messages"]
    KEEP_RECENT = 6   # 始终保留最近 N 条，保持对话连贯
    TRIGGER_AT  = 20  # 消息总数超过此阈值才触发压缩

    if len(messages) <= TRIGGER_AT:
        return {}     # 不超过阈值：原样通过，不做任何处理

    to_compress = messages[:-KEEP_RECENT]
    recent      = messages[-KEEP_RECENT:]

    summary = await sup_llm.ainvoke([
        SystemMessage("请简洁总结以下对话的核心内容，保留：已完成的事项、重要决策、关键结论。"),
        *to_compress,
    ])
    return {
        "messages": [
            SystemMessage(content=f"【历史对话摘要】\n{summary.content}"),
            *recent,
        ]
    }

# 图入口改为 summarizer
g.set_entry_point("summarizer")
g.add_edge("summarizer", "router")
```

**效果：** 无论对话多长，传给 LLM 的 token 数始终可控；对用户无感知，体验不变。

---

#### Chapter 17 — RAG 知识库集成（`app/rag/`）

> 面试高频考点完整实现：分片 → Embedding → Milvus → 混合检索 → Agent 工具

##### RAG 完整工作流程图

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  【入库阶段】用户提供文档 → 向量化存入 Milvus
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用户说：「把 施工验收规范.txt 导入知识库」
   │
   ▼
[supervisor] 调用工具 ingest_document(file_path)
   │    （SkillRegistry embed 匹配工具描述，自动选中此工具）
   ▼
[RAGPipeline.ingest()]
   │
   ├─ Step 1: loader.load_file(file_path)
   │           支持 .txt / .pdf / .docx
   │           → list[Document]
   │
   ├─ Step 2: chunker.split_documents(docs, chunk_size=500, overlap=80)
   │           RecursiveCharacterTextSplitter
   │           分隔符优先级：\n\n → \n → 。！？ → ，→ 字符兜底
   │
   └─ Step 3: MilvusStore.add_documents(chunks, project_id)
               ├─ embedder.embed_documents([chunk.page_content, ...])
               │   模型：BAAI/bge-small-zh-v1.5（本地 ONNX，512维）
               ├─ collection.insert(rows) → 写入 Milvus（HNSW 索引）
               └─ BM25Retriever.build(chunks)  → 内存倒排索引


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  【出库阶段】用户提问 → 混合检索 → LLM 生成答案
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用户说：「防水层蓄水试验要多久？」
   ▼
[search_knowledge_base(query)] 工具执行
   ▼
[RAGPipeline.search(query, top_k=5)]
   ├────────────────────────┐
   ▼                        ▼
[向量检索]              [BM25 关键词检索]
Milvus HNSW → Top20     BM25Okapi → Top20
   └────────────┬───────────┘
                ▼
         [RRF 融合排序]
          score += 1 / (60 + rank)
          → 取 Top5 → 格式化字符串
                ▼
         [LLM] 基于原文生成答案 → 流式输出
```

##### 决策点一览（面试标准答案）

**分片策略：** `RecursiveCharacterTextSplitter`，分隔符优先级 `\n\n → \n → 。→ ，→ 字符`。固定大小分片会在句子中间截断，导致关键信息跨 chunk 检索失败。

**Embedding 模型：** `BAAI/bge-small-zh-v1.5`（FastEmbed 本地运行），专为中文优化，零 API 费用，512维向量。

**向量数据库：** Milvus，支持持久化、CRUD、多租户过滤（`project_id`），HNSW 索引 Recall > 99%。

**检索策略：** 混合检索（BM25 + 向量 + RRF）。工程规范含精确术语（`GB50205`），纯向量搜索准确率约 60%，混合检索提升至约 85%。

**RRF 融合公式：**
```
final_score = Σ 1 / (k + rank_i)    k = 60（学术界标准）
```
用排名而非原始分数，避免两路分数量纲不同（cosine 是 0-1，BM25 是 0-几十）的归一化问题。

##### Embedding 在项目中的两处使用

```
同一个 FastEmbedEmbeddings 实例，承担两个不同职责：

用途1：工具路由（SkillRegistry）
  注册时：工具 description → embed_documents() → FAISS 索引
  请求时：用户问题        → embed_query()     → 选 Top-K 工具

用途2：RAG 知识库（MilvusStore）
  入库时：chunk 原文 → embed_documents() → 写入 Milvus
  检索时：用户问题   → embed_query()     → HNSW 搜索
```

**核心文件：**

| 文件 | 职责 |
|------|------|
| `app/rag/loader.py` | 文档加载（txt/pdf/docx → Document） |
| `app/rag/chunker.py` | 分片（RecursiveCharacterTextSplitter，中文优化） |
| `app/rag/store.py` | Milvus 写入/检索（HNSW 索引，多租户） |
| `app/rag/retriever.py` | 混合检索（BM25 + 向量 + RRF 融合） |
| `app/rag/pipeline.py` | RAG 全链路管理器（单例，管理连接和 BM25 重建） |
| `app/rag/rag_tools.py` | LangChain 工具封装（search / ingest） |

---

#### Chapter 18 — FastAPI 接口层（`app/api/routes.py`）

**为什么选 FastAPI 不选 Flask？**

| | Flask | FastAPI（选用）|
|--|-------|--------------|
| async 支持 | 需要额外安装 quart | 原生，基于 Starlette/ASGI |
| 接口文档 | 需手写或装插件 | 根据 Pydantic Schema 自动生成 `/docs` |
| 类型校验 | 无 | Pydantic 自动校验请求体，字段缺失直接 422 |
| 性能 | WSGI，同步阻塞 | ASGI，IO 密集场景并发更高 |

**核心改造：`chat()` → `astream_chat()`**

```python
# 改成生成器，两种消费方式都支持
async def astream_chat(self, session_id, content, agent="supervisor", agent_configs=None):
    async for msg, _ in self._agent.astream(..., stream_mode="messages"):
        if isinstance(msg, AIMessageChunk) and msg.content:
            yield msg.content        # ← yield chunk，CLI/HTTP 都能用

async def chat(self, ...):           # CLI 继续用，向后兼容
    async for chunk in self.astream_chat(...):
        print(chunk, end="")
```

**SSE（Server-Sent Events）流式推送**

```
为什么用 SSE 不用 WebSocket？
  AI 回复是单向流（服务端 → 客户端），SSE 够用且更简单：
  - 基于 HTTP，无需额外握手，防火墙友好
  - 原生支持断线重连
  - WebSocket 适合双向通信（聊天室/协同编辑）

SSE 消息格式：
  data: {"type": "chunk", "content": "你好"}↵↵
  data: {"type": "chunk", "content": "，我"}↵↵
  data: {"type": "done",  "content": ""}↵↵
  data: {"type": "error", "content": "..."}↵↵
```

**接口一览**

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/api/chat` | SSE 流式对话，body: `{session_id, content, agent, agent_configs}` |
| `POST` | `/api/rag/ingest/file` | 上传文件导入知识库（multipart） |
| `POST` | `/api/rag/ingest/text` | 纯文本导入知识库 |
| `GET`  | `/api/rag/status` | 查询 Milvus 连接状态和 chunk 数量 |
| `GET`  | `/api/health` | 健康检查（Docker/K8S 探针用） |
| `GET`  | `/api/history` | 获取所有历史会话列表，包括标题、更新时间、消息数 |
| `GET`  | `/api/history/{session_id}` | 加载指定会话的完整历史消息列表（自动排除系统消息） |
| `DELETE`| `/api/history/{session_id}` | 物理删除指定的历史会话（同步删除主图及各子 Agent 的 SQLite Checkpoint） |
| `GET`  | `/docs` | Swagger UI，浏览器直接测试所有接口 |

---

### Phase 5 — 前端工程与多模型配置

> **新增阶段**：把 CLI 工具进化为完整的全栈 Web 应用，同时实现企业级多模型管理。

#### Chapter 19 — React 前端工程化（`frontend/`）

**技术选型：**

| 技术 | 选择 | 原因 |
|------|------|------|
| 框架 | React 18 | Hooks 模型与异步流式渲染天然契合 |
| 构建 | Vite | 极快热更新，开发体验好 |
| 样式 | CSS Variables | 设计 token 统一管理，主题切换方便 |
| 图标 | SVG inline | 无外部依赖，颜色可继承 |

**核心组件结构：**

```
src/
├── App.jsx              # 状态管理中枢，协调各组件
├── api.js               # API 层，封装 fetch + SSE 解析
└── components/
    ├── TopBar.jsx        # 顶部栏：模型名、RAG 状态、操作按钮
    ├── ChatWindow.jsx    # 消息列表，流式渲染中...动画
    ├── InputBar.jsx      # 输入框 + Agent 选择器
    ├── KnowledgePanel.jsx # 右侧抽屉：知识库管理
    └── SettingsPanel.jsx  # 右侧抽屉：LLM 配置
```

**SSE 流式读取（前端 async generator 模式）：**

```javascript
export async function* streamChat(sessionId, content, { agent = 'supervisor' } = {}) {
  const agentConfigs = JSON.parse(localStorage.getItem('agentlab_agent_configs') || 'null')
  const body = { session_id: sessionId, content, agent }
  if (agentConfigs) body.agent_configs = agentConfigs

  const response = await fetch(`${getBase()}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const data = JSON.parse(line.slice(6))
      yield data
      if (data.type === 'done' || data.type === 'error') return
    }
  }
}
```

**流式渲染原理（`ChatWindow` + `InputBar`）：**

```javascript
// App.jsx：逐 chunk 累加内容到对应消息 id
for await (const data of streamChat(sessionId, content.trim(), { agent })) {
  if (data.type === 'chunk') {
    setMessages(prev =>
      prev.map(m => m.id === aiMsgId
        ? { ...m, content: m.content + data.content }   // 累加
        : m)
    )
  }
}
```

**Vite 开发代理（`vite.config.js`）：**

```javascript
server: {
  proxy: {
    '/api': 'http://localhost:8000'
  }
}
```

开发时前端 `localhost:5173` 请求 `/api/...` 自动代理到后端 `localhost:8000`，不跨域。

---

#### Chapter 20 — 每 Agent 独立 LLM 配置

**核心需求：** Supervisor（路由/聚合）和每个子 Agent 可以各自使用不同的模型。典型场景：Supervisor 用 `deepseek-chat` 做路由决策（便宜快），Code Agent 用 `gpt-4o` 做代码生成（效果好）。

**数据结构设计：**

```python
# 后端 routes.py
class AgentLLMConfig(BaseModel):
    model:    str | None = None
    api_base: str | None = None
    api_key:  str | None = None

class ChatRequest(BaseModel):
    session_id:    str
    content:       str
    agent:         str = "supervisor"
    agent_configs: dict[str, AgentLLMConfig] | None = None
    # 键名：supervisor / code / file / general / batch
    # 缺失键 → 后端 .env 默认值
```

**后端 LLM 工厂（`ai_service.py`）：**

```python
def _make_llm_from_config(self, cfg) -> ChatOpenAI:
    """cfg 为 None / 全空时回退到 settings.py 默认值。"""
    return ChatOpenAI(
        api_key  = (cfg and cfg.api_key)  or settings.OPENAI_API_KEY,
        base_url = (cfg and cfg.api_base) or settings.OPENAI_API_BASE,
        model    = (cfg and cfg.model)    or settings.MODEL_NAME,
        ...
    )

def _build_llms_dict(self, agent_configs: dict | None) -> dict:
    """前端传来的 agent_configs → llms 字典。"""
    result = {"supervisor": self._llm}
    if not agent_configs:
        return result
    for name in ("supervisor", "code", "file", "general", "batch"):
        cfg = agent_configs.get(name)
        if cfg and any([cfg.model, cfg.api_base, cfg.api_key]):
            result[name] = self._make_llm_from_config(cfg)
        else:
            result[name] = self._llm
    return result
```

**Supervisor 多 LLM 支持（`supervisor.py`）：**

```python
def build_supervisor(llms: dict, registry: SkillRegistry):
    """
    llms 格式：{"supervisor": llm_sup, "code": llm_code, ...}
    缺失键自动回退到 llms["supervisor"]。
    """
    sup_llm     = llms["supervisor"]
    code_llm    = llms.get("code",    sup_llm)
    file_llm    = llms.get("file",    sup_llm)
    general_llm = llms.get("general", sup_llm)

    # router / aggregator / summarizer 用 sup_llm
    # code_agent 用 code_llm，file_agent 用 file_llm，general 用 general_llm
```

**缓存策略：**

| 场景 | 处理 |
|------|------|
| 无 `agent_configs`（或全为空） | 使用缓存的默认 supervisor / subagent，零重建开销 |
| 有 `agent_configs` | 按配置临时构建，不覆盖缓存，共享同一 SQLite DB 保持会话历史 |

`_is_default_config()` 判断是否全部使用默认配置：

```python
def _is_default_config(self, agent_configs: dict | None) -> bool:
    if not agent_configs:
        return True
    return all(
        not any([cfg.model, cfg.api_base, cfg.api_key])
        for cfg in agent_configs.values()
        if cfg is not None
    )
```

**前端配置存储：**

```json
// localStorage key: agentlab_agent_configs
{
  "supervisor": { "model": "deepseek-chat",     "api_base": "https://api.deepseek.com/v1", "api_key": "sk-..." },
  "code":       { "model": "gpt-4o",            "api_base": "https://api.openai.com/v1",   "api_key": "sk-..." },
  "file":       null,
  "general":    { "model": "deepseek-reasoner", "api_base": "https://api.deepseek.com/v1", "api_key": "sk-..." },
  "batch":      null
}
```

`null` 表示跟随 Supervisor 配置。每次发消息时，`api.js` 读取 localStorage 随请求体一起发给后端。

---

#### Chapter 21 — 直连子 Agent 模式

**问题：** 用户明确知道要做代码任务时，让请求经过 Supervisor 路由是浪费（额外一次 LLM 调用）。

**解决：** 前端提供 Agent 选择器，用户可直接指定目标 Agent，后端跳过 Supervisor 直接调用。

**后端路由逻辑（`ai_service.py`）：**

```python
async def astream_chat(self, session_id, content, agent="supervisor", agent_configs=None):
    thread_id = f"{agent}:{session_id}"
    config = {"configurable": {"thread_id": thread_id}}

    if agent == "supervisor":
        graph = await self._ensure_supervisor()           # 走 Supervisor 图
    elif agent == "batch":
        graph = await self._get_subagent("batch")
        result = await graph.ainvoke({...}, config=config)
        yield result["final_summary"]                     # Batch 不流式，一次性输出
        return
    else:
        graph = await self._get_subagent(agent)           # 直连 code/file/general

    async for msg, _ in graph.astream(
        {"messages": [("user", content)]},
        config=config, stream_mode="messages"
    ):
        if isinstance(msg, AIMessageChunk) and msg.content:
            yield msg.content
```

**关键细节：** `thread_id = f"{agent}:{session_id}"`，不同 Agent 模式有独立的会话历史，切换 Agent 不会混用历史消息。

---

#### Chapter 22 — 历史会话持久化与管理（History Sessions）

**核心需求：** 对话不能一刷新页面就消失，必须进行持久化，并且支持新建对话、在多个历史对话间平滑切换、以及物理删除历史对话。

**后端路由与数据库交互（`routes.py`）：**
- **获取会话列表：** `GET /api/history` 扫描 SQLite Checkpointer 数据库，过滤并提取以 `supervisor:` 开头的 `thread_id` 最新快照，以更新时间（`ts`）降序排列。
- **获取会话详情：** `GET /api/history/{session_id}` 读取对应 thread 快照的 `messages` 列表，自动过滤系统（`system`）消息，并格式化成前端标准 JSON。
- **物理删除会话：** `DELETE /api/history/{session_id}` 必须彻底物理清理 Checkpointer。**踩坑点：** 必须使用 `AsyncSqliteSaver.adelete_thread(thread_id)`，参数必须是 `thread_id: str`，传配置 dict 会导致静默不生效。

```python
@router.delete("/history/{session_id}")
async def delete_session(session_id: str):
    """物理删除指定的历史会话及所有关联子图的 Checkpoint"""
    await ai_service._ensure_supervisor()
    checkpointer = ai_service._agent.checkpointer
    
    # 删除 Supervisor 主图的 thread
    await checkpointer.adelete_thread(f"supervisor:{session_id}")
    
    # 同步删除各个子 Agent 的 thread 快照以完全释放 SQLite 数据库空间
    for ag in ["code", "file", "batch", "general", "shell"]:
        await checkpointer.adelete_thread(f"{ag}:{session_id}")
        
    return {"success": True}
```

**前端历史侧边栏（`HistorySidebar.jsx`）：**
- 采用极简高端的玻璃摩砂感（Glassmorphism）侧边栏设计，布局在屏幕最左侧。
- 鼠标悬浮列表项时淡入删除按钮，配合微动画提供一流的交互体验。
- 自动格式化显示消息条数和更新时间。

---

## 架构演进图

```
v1: CLI 单 Agent
   main.py → AIService.chat() → 单个 LangGraph ReAct 图

v2: Supervisor 多 Agent
   main.py → AIService → Supervisor 图 → Code / File / General 子图

v3: FastAPI 服务化
   main_api.py → FastAPI → SSE → AIService.astream_chat()

v4: RAG 集成
   FastAPI + RAGPipeline(Milvus) + SkillRegistry(FAISS)

v5: 全栈 Web 应用
   React 前端 + FastAPI 后端
   + 每 Agent 独立 LLM 配置
   + 直连子 Agent 模式
   + 知识库 Web UI
   + 设置面板 Web UI

v6: 历史会话持久化（当前）
   + Glassmorphic 历史侧边栏 (HistorySidebar)
   + SQLite Checkpointer 历史会话持久化
   + 历史会话详情懒加载 & 智能主子图物理删除
```

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
| DeepSeek 404 `/embeddings` | DeepSeek API 无 Embedding 端点 | 换 `FastEmbedEmbeddings`（本地模型，无需 API） |
| import 时 Embedding 崩溃 | `supervisor.py` 底部代码在 import 时同步执行 | 用 `try-except` 包裹，懒初始化 |
| Milvus `docker_engine` 管道找不到 | Docker Desktop 上下文未启动 | 先启动 Docker Desktop，等鲸鱼图标稳定再 `docker compose up -d` |
| BM25 重启后索引丢失 | BM25 是内存索引 | `pipeline.connect()` 时从 Milvus 全量重建 BM25 |
| Milvus `dimension mismatch` | Collection 维度与 Embedding 不一致 | `store.py` 中 `EMBEDDING_DIM=512` 与 BGE-small 对齐 |
| FastAPI SSE 在 Nginx 后不实时 | Nginx 默认缓冲响应 | 响应头加 `X-Accel-Buffering: no` |
| `@app.on_event` 警告 | FastAPI 新版废弃 on_event | 改用 `@asynccontextmanager lifespan` |
| multipart 上传报 422 | 未安装 `python-multipart` | `pip install python-multipart` |
| `build_code_subgraph` 无法传 checkpointer | 原函数内部直接 compile() | 改为接受 `checkpointer=None` 参数传给 `g.compile()` |
| 前端 CORS 报错 | 开发模式下跨域 | Vite 代理 `/api → localhost:8000`，生产模式后端托管前端静态文件 |

---

## 后续学习路线图

```
✅ 完成              第一阶段        第二阶段        第三阶段        第四阶段
──────────────────────────────────────────────────────────────────────────
Phase 1-5         Human-in-loop   微服务化       Docker        K8S 生产
（全栈跑通）        （人工审核节点）  （Agent 拆服务） （容器化）      （弹性扩缩容）
```

### 待完成

**✅ Human-in-the-loop 人工审核**（已完成）
- Supervisor 编译时设置 `interrupt_before=["code_agent"]`，路由到代码 Agent 前自动暂停
- 后端检测暂停：`await graph.aget_state(config)` → `state.next` 非空则 yield interrupt 事件
- 取消路径：`graph.aupdate_state(as_node="code_agent")` 注入"已取消"结果，跳过执行直接聚合
- 前端：InterruptCard 组件显示确认/取消按钮，确认后调用 `POST /api/chat/resume` 恢复 SSE 流

**微服务化**
- Supervisor 保持完整（编排层不拆），Worker Agent 拆成独立 HTTP 服务
- `CodeAgent :8001` / `FileAgent :8002` / `General :8003`
- Supervisor 节点函数改为 `httpx.AsyncClient().post(...)` 调用
- 替换 SQLite → PostgreSQL（多服务共享 Checkpoint）

**可观测性**
- LangSmith tracing：追踪每次 LLM 调用的输入输出、延迟、cost
- 结构化日志接入 ELK / Loki
- 告警：错误率异常自动通知

**K8S 部署**
- 各服务部署为 K8S Deployment
- HPA 自动弹性扩缩容
- NetworkPolicy 限制代码执行沙箱出站访问

---

## 文件结构

```
build-with-langchain/
├── mirage/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── supervisor.py      # 主路由图（Compaction + 并行扇出 + 聚合）
│   │   │   ├── code_agent.py      # 代码执行子图（ReAct + SkillRegistry）
│   │   │   ├── file_agent.py      # 文件处理子图
│   │   │   ├── general_agent.py   # 通用问答子图（RAG + 工具）
│   │   │   ├── batch_agent.py     # 批量并行图（Map-Reduce）
│   │   │   └── state.py           # SupervisorState TypedDict
│   │   ├── api/
│   │   │   └── routes.py          # FastAPI 路由（AgentLLMConfig / ChatRequest / SSE）
│   │   ├── core/
│   │   │   ├── config.py          # settings（读 .env）
│   │   │   └── logger.py          # get_logger 工厂
│   │   ├── rag/
│   │   │   ├── loader.py          # 文档加载
│   │   │   ├── chunker.py         # 分片
│   │   │   ├── store.py           # Milvus 写入/检索
│   │   │   ├── retriever.py       # 混合检索（BM25 + 向量 + RRF）
│   │   │   ├── pipeline.py        # RAG 全链路管理器
│   │   │   └── rag_tools.py       # LangChain 工具封装
│   │   └── services/
│   │       ├── ai_service.py      # AIService（LLM 工厂 + 图缓存 + 流式接口）
│   │       ├── tools.py           # 工具定义（code/file/general）
│   │       └── skill_registry.py  # FAISS 语义工具检索
│   ├── main.py                    # CLI 入口
│   ├── main_api.py                # FastAPI 服务入口
│   └── static/                    # 前端构建产物（npm run build 输出）
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # 状态管理中枢
│   │   ├── api.js                 # fetch API & SSE 流式处理器 & 历史会话 API 封装
│   │   └── components/
│   │       ├── TopBar.jsx
│   │       ├── ChatWindow.jsx
│   │       ├── InputBar.jsx       # Agent 选择器 + 发送框
│   │       ├── KnowledgePanel.jsx # 知识库管理抽屉
│   │       ├── SettingsPanel.jsx  # 每 Agent LLM 配置抽屉
│   │       └── HistorySidebar.jsx # 历史会话管理侧边栏 (新建/切换/删除会话)
│   ├── index.html
│   └── vite.config.js
├── docker-compose.yml             # Milvus 启动配置
├── langgraph.json                 # LangGraph Studio 配置
├── requirements.txt
├── .env.example
└── README.md
```
