# AgentLab —— AI Agent 工程化实战

> 从 LangChain 新手到具备工程化思维的 AI 开发者，完整记录每一步踩坑与突破。
> 技术栈：Python · LangChain · LangGraph · Pydantic V2 · aiosqlite · DeepSeek API · Milvus · FastEmbed

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
          summarizer   ← 自动检查消息长度，超阈值压缩历史（Compaction）
              ↓
           router      ← LLM 分析意图，并行选多个 Agent
        ↙    ↓    ↘      （Send API 并行扇出）
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

#### Chapter 17 — RAG 知识库集成（`app/rag/`）

> 面试高频考点完整实现：分片 → Embedding → Milvus → 混合检索 → Agent 工具

---

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
   │             Document.page_content = "施工验收是确保..."
   │             Document.metadata    = {source: "规范.txt", file_type: "txt"}
   │
   ├─ Step 2: chunker.split_documents(docs, chunk_size=500, overlap=80)
   │           RecursiveCharacterTextSplitter
   │           分隔符优先级：\n\n → \n → 。！？ → ，→ 字符兜底
   │           → [chunk1, chunk2, ..., chunkN]  每个仍是 Document
   │             metadata 原样继承：{source, file_type, ...}
   │
   └─ Step 3: MilvusStore.add_documents(chunks, project_id)
               │
               ├─ 3a: embedder.embed_documents([chunk.page_content, ...])
               │       模型：BAAI/bge-small-zh-v1.5（本地 ONNX，512维）
               │       → [[0.12, -0.34, ...], ...]  每个 chunk 一条 512 维向量
               │
               ├─ 3b: 组装行数据
               │       {id: UUID,
               │        embedding: [512 个 float],
               │        content:   chunk 原文,
               │        source:    "规范.txt",
               │        project_id: "proj_001",
               │        chunk_index: 0, 1, 2...}
               │
               ├─ 3c: collection.insert(rows) → 写入 Milvus
               │       HNSW 索引自动更新（M=16, efConstruction=200）
               │
               └─ 3d: BM25Retriever.build(chunks)
                       按字符分词：["施","工","验","收","是","确"...]
                       BM25Okapi 计算 TF-IDF 分数，构建倒排索引（内存）


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  【出库阶段】用户提问 → 混合检索 → LLM 生成答案
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用户说：「防水层蓄水试验要多久？」
   │
   ▼
[supervisor] SkillRegistry.search(query)
   │  embedder.embed_query("防水层蓄水试验要多久？")
   │  → 512维向量 → FAISS 余弦相似度 → 命中 search_knowledge_base
   │
   ▼
[search_knowledge_base(query)] 工具执行
   │
   ▼
[RAGPipeline.search(query, top_k=5)]
   │
   ├─────────────────────────────────────────┐
   │                                         │
   ▼                                         ▼
[路1: 向量检索]                          [路2: BM25 关键词检索]
embedder.embed_query(query)             tokenize("防水层蓄水...")
→ 512维查询向量                         → ["防","水","层","蓄"...]
→ Milvus HNSW 搜索                     → BM25Okapi.get_scores()
   metric: COSINE, ef=50               → 按 TF-IDF 打分排序
→ 返回 Top20 docs + cosine_score       → 返回 Top20 docs + bm25_score
   │                                         │
   └──────────────┬──────────────────────────┘
                  ▼
         [RRF 融合排序]
          公式：score += 1 / (60 + rank)
          对每个文档，把两路的排名转成分数累加

          例：某 chunk 在向量排 rank=1，BM25 排 rank=2
              RRF = 1/(60+1) + 1/(60+2) = 0.0164 + 0.0161 = 0.0325

          按 RRF 分降序 → 取 Top5
                  │
                  ▼
         格式化为字符串：
         【知识库检索结果】
         [1] 来源：施工验收规范.txt（相关度 0.0325）
             防水层施工须进行蓄水试验，蓄水时间不少于24小时，无渗漏为合格。
         [2] 来源：...
                  │
                  ▼
         [LLM] 读取检索结果 + 用户问题
         → 生成最终答案（基于原文，附来源）
         → 流式输出给用户
```

---

##### 决策点一览（面试标准答案）

**决策点1：分片策略**

选 `RecursiveCharacterTextSplitter`（递归字符分片），不用固定大小分片。

**用真实文档说明为什么：**

输入文档（节选）：
```
第一章 施工验收管理规范

1.1 验收流程概述

施工验收是确保工程质量的关键环节，主要包括以下步骤：首先由施工单位自检，
填写自检报告并上传系统。自检通过后，由质检人员进行现场验收检查。检查发现
问题时，在系统中创建整改单，注明问题描述、整改要求和完成期限。施工单位完
成整改后，上传整改结果并申请复验。复验通过后，由项目经理确认归档，验收流
程结束。

1.2 质量标准

混凝土强度等级须符合设计要求，现场取样检测合格率须达到100%。钢筋绑扎间距
偏差不得超过±10mm，焊接质量须满足GB50205标准。防水层施工须进行蓄水试验，
蓄水时间不少于24小时，无渗漏为合格。
```

**❌ 固定大小分片（chunk_size=100，无分隔符）结果：**

```
Chunk1:「第一章 施工验收管理规范  1.1 验收流程概述  施工验收是确保工程质量的关键
         环节，主要包括以下步骤：首先由施工单位自检，填写自检报告并上传系统。
         自检通过后，由质检人员进行现场验收检查。检查发现问题」
         ↑ 在"检查发现问题"后面硬截断，下半句跑到 Chunk2 去了

Chunk2:「时，在系统中创建整改单，注明问题描述、整改要求和完成期限。施工单位完
         成整改后，上传整改结果并申请复验。复验通过后，由项目经理确认归档，验
         收流程结束。  1.2 质量标准  混凝土强度等级须符合设计要求」
         ↑ 开头"时"是上一句的残余，语义破碎

Chunk3:「，现场取样检测合格率须达到100%。钢筋绑扎间距偏差不得超过±10mm，焊接
         质量须满足GB50205标准。防水层施工须进行蓄水试验，蓄水时间不少于...」
         ↑ 开头逗号，"混凝土强度等级须符合设计要求" 被切掉了
```

问题：用户问"混凝土强度等级的要求"，这句话被分到两个 chunk，两个 chunk 检索出来都不完整。

---

**✅ 递归字符分片（chunk_size=150, overlap=30）结果：**

```
Chunk1（24字）:
「第一章 施工验收管理规范

 1.1 验收流程概述」
  ↑ 发现这段只有标题，不超过 150，但下一段加上就超了，所以在 \n\n 处切断

Chunk2（148字）:
「施工验收是确保工程质量的关键环节，主要包括以下步骤：首先由施工单位自检，
 填写自检报告并上传系统。自检通过后，由质检人员进行现场验收检查。检查发现
 问题时，在系统中创建整改单，注明问题描述、整改要求和完成期限。施工单位完
 成整改后，上传整改结果并申请复验。复验通过后，由项目经理确认归档...」
  ↑ 完整段落，在句号处切断，没有截断任何一句话

Chunk3（110字）:
「1.2 质量标准

 混凝土强度等级须符合设计要求，现场取样检测合格率须达到100%。钢筋绑扎间
 距偏差不得超过±10mm，焊接质量须满足GB50205标准。防水层施工须进行蓄水试
 验，蓄水时间不少于24小时，无渗漏为合格。」
  ↑ 1.2 的内容完整，包含标题和全部标准，检索"GB50205"能命中完整上下文
```

**分隔符优先级（RecursiveCharacterTextSplitter 从左到右依次尝试）：**

```
\n\n  →  \n  →  。  →  ！  →  ？  →  ；  →  ，  →  空格  →  字符（兜底）

优先在段落边界切（\n\n），其次句子边界（。），最后才按字符截断
```

**overlap 的作用（实际内容示例）：**

```
chunk_size=150, overlap=30

Chunk2 末尾：「...施工单位完成整改后，上传整改结果并申请复验。」
Chunk3 开头：「施工单位完成整改后，上传整改结果并申请复验。复验通过后...」
              ↑ 这22字在两个 chunk 里都有

作用：如果用户问"申请复验之后做什么"，这个知识点刚好跨了 chunk 边界，
      有 overlap 的话两个 chunk 都能检索到完整的上下文。
```

生产参数：`chunk_size=500, overlap=80`（overlap 约占 16%）

**决策点2：Embedding 模型**

选 `BAAI/bge-small-zh-v1.5`（FastEmbed 本地运行），不用 OpenAI Embeddings API。

| 对比 | OpenAI text-embedding-3-small | BGE-small-zh-v1.5（选用）|
|------|------------------------------|------------------------|
| 运行方式 | 远程 API 调用 | 本地 ONNX，CPU 推理 |
| 中文效果 | 通用多语言 | 专为中文优化，工程术语更准 |
| 成本 | 按量计费 | 零 API 费用 |
| 首次使用 | 无需准备 | 下载模型 ~50MB |
| 输出维度 | 1536 维 | 512 维 |

`chunk_size=500` 字符 ≈ 333 tokens，在 BGE-small 512 token 上限内，安全。

**决策点3：向量数据库**

选 Milvus，不用 FAISS 或 ChromaDB。

| 对比 | FAISS | ChromaDB | Milvus（选用）|
|------|-------|----------|--------------|
| 持久化 | ❌ 内存 | ✅ | ✅ |
| CRUD | ❌ | ✅ | ✅ |
| 多租户过滤 | ❌ | 有限 | ✅ `project_id` 标量过滤 |
| 数据规模 | 百万级 | 百万级 | 十亿级 |
| 部署 | 纯内存库 | pip 安装 | Docker |
| 适用 | 离线/研究 | 原型验证 | **生产 SaaS** ✅ |

索引选 HNSW（`M=16, efConstruction=200, ef=50`），Recall > 99%，检索速度比暴力搜索快100倍以上。

Collection Schema 设计：

```
id          VARCHAR(64)      主键，UUID
embedding   FLOAT_VECTOR(512) 向量数据，BGE-small 输出
content     VARCHAR(65535)   chunk 原文
source      VARCHAR(256)     来源文件名（溯源用）
project_id  VARCHAR(64)      项目 ID（多租户过滤用）
chunk_index INT64            chunk 序号（定位用）
```

**决策点4：检索策略**

选混合检索（BM25 + 向量 + RRF），不用纯向量。

核心原因：工程规范有大量精确术语（`GB50205`、`±10mm`、`24小时`）。纯向量搜 `GB50205` 时，BGE 对 `GB50205` 和 `GB50206` 的向量距离几乎相同，会检索出错。BM25 精确匹配关键词，弥补向量的短板。

RRF（Reciprocal Rank Fusion）融合公式：

```
final_score = Σ  1 / (k + rank_i)    k = 60（学术界标准）

两路都靠前：1/(60+1) + 1/(60+1) = 0.0328   → 排名最高
只有向量靠前：1/(60+1) + 1/(60+20) = 0.0262 → 排名居中
```

用排名而非原始分数，避免两路分数量纲不同（cosine 是 0-1，BM25 是 0-几十）的归一化问题。

实际效果：
- 纯向量 + 固定分片：工程规范检索准确率约 60%
- 混合检索 + 递归分片：准确率提升至约 85%

---

##### Embedding 在项目中的两处使用

同一个 `FastEmbedEmbeddings` 实例，在项目中承担两个完全不同的职责：

```
embedder = FastEmbedEmbeddings(model_name="BAAI/bge-small-zh-v1.5")

用途1：工具路由（SkillRegistry）
  注册时：工具 description → embed_documents() → 512维向量 → FAISS 索引
  请求时：用户问题        → embed_query()     → 512维向量 → 余弦相似度 → 选工具

用途2：RAG 知识库（MilvusStore）
  入库时：chunk 原文 → embed_documents() → 512维向量 → 写入 Milvus
  检索时：用户问题   → embed_query()     → 512维向量 → HNSW 搜索 → 返回 chunk
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
| `demo_rag_01_chunking.py` | 分片效果可视化 Demo |
| `demo_rag_02_vectorstore.py` | Milvus 写入/检索可视化 Demo |
| `demo_rag_03_retrieval.py` | 纯向量 vs 混合检索对比 Demo |

**启动知识库：**

```bash
# 1. 启动 Milvus（需要 Docker Desktop 运行）
docker compose up -d

# 2. 启动 app（RAG 自动连接，Milvus 不可用时自动降级不报错）
python agent_lab/main.py

# 3. 在对话中导入文档
# 用户：「帮我把 D:/规范/施工验收规范.txt 导入知识库」

# 4. 直接提问
# 用户：「防水层蓄水试验要多久？」
# Agent 自动调 search_knowledge_base → 检索 → 基于原文回答
```

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

    summary = await llm.ainvoke([
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
| import 时 Embedding 崩溃 | `supervisor.py` 底部代码在 import 时同步执行 | 用 `try-except` 包裹，`_ensure_initialized()` 懒加载 |
| Milvus `docker_engine` 管道找不到 | Docker Desktop 上下文为 `desktop-linux` 但引擎未启动 | 先启动 Docker Desktop，等鲸鱼图标稳定再执行 `docker compose up -d` |
| BM25 重启后索引丢失 | BM25 是内存索引，重启后为空 | `pipeline.connect()` 时自动从 Milvus 查询全量 chunk 重建 BM25 |
| Milvus `dimension mismatch` | Collection 维度与 Embedding 输出维度不一致 | `store.py` 中 `EMBEDDING_DIM=512` 与 BGE-small 输出维度对齐 |

---

## 后续学习路线图

```
✅ 完成         第一阶段      第二阶段      第三阶段      第四阶段
──────────────────────────────────────────────────────────────────
单体+Compaction → 加FastAPI  → 拆微服务   → Docker    → 上K8S
（能稳定跑）      （能对外用）  （能扩容）    （容器化）   （能生产）
```

---

### ✅ 已完成

| Module | 内容 | 文件 |
|--------|------|------|
| 14 | Skill 动态检索（FAISS + Embedding） | `app/services/skill_registry.py` |
| 15 | Map-Reduce 动态并行 Worker | `app/agents/batch_agent.py` |
| 16 | 上下文压缩 Compaction（summarizer 节点） | `app/agents/supervisor.py` |
| 17 | RAG 知识库集成（分片/Embedding/Milvus/混合检索） | `app/rag/` |

---

### 第一阶段 — 对外暴露

**Module 17：FastAPI 接口层**
- `ai_service.chat()` 包成 HTTP POST 接口
- SSE（Server-Sent Events）流式推送 AI 回复，前端实时显示
- 支持多用户并发（thread_id 隔离已有，直接复用）

**Module 18：Human-in-the-loop 人工审核**
- Agent 执行到危险节点（写文件、执行代码）时暂停，等用户确认再继续
- 实现：`graph.compile(interrupt_before=["code_agent"])` + `graph.update_state()`

---

### 第二阶段 — 微服务化

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
