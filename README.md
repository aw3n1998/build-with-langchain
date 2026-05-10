# AI Agent 进阶开发全手册 (AgentLab)

## 🌟 项目综述
**AI Agent 进阶开发实验室 (AgentLab)** 是一个专为追求**生产环境稳定性**而设计的 AI 智能体平台。它基于 Python 异步协程架构，深度集成 LangChain 与 LangGraph，实现了从“简单问答”到“闭环执行”的质变。

本手册不仅记录了代码，更记录了在 Windows 环境下解决网络穿透、异步锁冲突、消息协议一致性等**核心工程问题**的底层逻辑。

---

## 🗺️ 1个月 AI 专家成长路线图 (Roadmap)

### 第一阶段：工程骨架与核心架构 (已完成 ✅)
- [x] **模块 01：Python 工程化补齐**：Pydantic V2 建模、Async/Await 异步调度。
- [x] **模块 02：持久化记忆 (Memory)**：手写异步 SQLite DAO，解决全链路异步冲突。
- [x] **模块 03：工具调用 (Tool Calling)**：LLM 消息时序协议、自动执行 Python REPL。
- [x] **模块 04：LangGraph 状态机**：构建自修复智能体，实现 Agent 决策闭环。

### 第二阶段：知识增强与多体协作 (进行中 🚀)
- [ ] **模块 05：企业级 RAG 系统 [待开始]**：集成 Chroma 向量数据库，攻克语义检索与 Rerank。
- [ ] **模块 06：多智能体 (Multi-Agent) 协同 [待开始]**：
    - **核心技术**：主从架构 (Router)、任务分发。
    - **进阶挑战**：**多 Agent 记忆协同**（如何让程序员 Agent 共享架构师 Agent 的上下文）。
- [ ] **模块 07：Agent 情感与拟人化 [待开始]**：
    - **核心技术**：System Prompt 调优、情感状态检测。
    - **进阶挑战**：构建带“脾气”和“性格”的 AI 助手。

### 第三阶段：生产落地与性能评估 (即将到来 🏁)
- [ ] **模块 08：可观测性 (Observability)**：集成 LangSmith 进行全链路 Trace 监控。
- [ ] **模块 09：RAG 评估框架 (Ragas)**：量化 AI 的幻觉率与回答准确度。
- [ ] **模块 10：面试冲刺与系统设计**：简历包装、百万级并发 AI 架构设计。

---

## 🏗️ 第一章：分层架构设计 (Architecture)

### 1.1 系统架构图
```mermaid
graph TD
    User([用户终端 CLI]) -- session_id --> Controller[main.py: 交互控制器]
    Controller --> Service[AIService: 核心业务引擎]
    
    subgraph "核心引擎层"
        Service --> StateMachine[LangGraph: 状态机图]
        StateMachine --> LLM[DeepSeek-V3: 思考大脑]
        StateMachine --> Tools[PythonREPL/Files: 执行手脚]
    end
    
    subgraph "基础设施层"
        Service --> DAO[AsyncSQLiteHistory: 异步持久化]
        DAO --> DB[(checkpoint.db / chat_history.db)]
        Service --> Config[pydantic-settings: 全局配置]
    end
    
    LLM -- 协议约束 --> Protocol[Error 400 校验器]
```

---

## 🛠️ 第二章：已完成模块深度解析 (Master Class)

### 模块 1：工程化骨架与 Windows 环境穿透
**操作细节：**
1.  **Pydantic V2 建模**：利用 Python 的类型提示实现强类型约束，对标 Java 的 Bean Validation。
    ```python
    class AIRequest(BaseModel):
        session_id: str = Field(..., description="会话ID") # 必填
        content: str = Field(..., min_length=1) # 最小长度为1
    ```
2.  **Windows 环境适配**：
    - **SSL 证书穿透**：针对 Windows 经常报 SSL 校验失败的问题，我们手动构造了 `httpx.AsyncClient(verify=False)`。
    - **终端乱码修复**：
        ```python
        if sys.platform == "win32":
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        ```

---

### 模块 2：深度持久化——手写异步 SQLite DAO
**操作细节：**
由于 LangChain 官方 `SQLChatMessageHistory` 内部存在同步调用，在异步 `ainvoke` 链路中会触发 `RuntimeError`。
**代码实现：**
```python
class AsyncSQLiteHistory(BaseChatMessageHistory):
    async def aget_messages(self) -> List[BaseMessage]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT message_json FROM agent_message_history WHERE session_id = ? ORDER BY id",
                (self.session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                # 关键：反序列化消息对象
                return messages_from_dict([json.loads(row[0]) for row in rows])
```

---

### 模块 3：Tool Calling 与消息时序协议
**操作细节：**
大模型对消息顺序有极其严格的要求。
**协议流程图：**
1.  **HumanMessage**: 用户提问。
2.  **AIMessage (with tool_calls)**: AI 决定调用工具（必须持久化，否则下一步会报错）。
3.  **ToolMessage**: 工具执行结果（必须携带唯一的 `tool_call_id`）。
4.  **Final AIMessage**: AI 根据结果给出的总结。

**核心代码演示：**
```python
# 必须按顺序保存，否则报 Error 400
await history.aadd_messages([ai_message_intent]) # 存入意图
observation = await tool.ainvoke(args) # 执行工具
await history.aadd_messages([ToolMessage(content=observation, tool_call_id=id)]) # 存入结果
```

---

### 模块 4：LangGraph 状态机——自修复 Agent
**操作细节：**
将 Agent 逻辑从“线”变成“圈”。
1.  **定义节点**：`agent` (思考) 和 `action` (执行)。
2.  **自修复逻辑**：在 `action` 节点捕获 Python 代码报错，直接发回给 `agent`。
3.  **持久化 Checkpoints**：引入 `AsyncSqliteSaver`，实现事务级快照。
```python
# 构建自修复循环
workflow.add_edge("action", "agent") # 执行完工具后强制复盘
```

---

## 📋 第三章：硬核 Troubleshooting (踩坑合集)
| 错误信息 | 根本原因 | 解决方案 |
| :--- | :--- | :--- |
| `ModuleNotFoundError: langgraph.checkpoint.sqlite` | 模块化拆分 | `pip install langgraph-checkpoint-sqlite` |
| `no such column: message_json` | 旧版 Schema 冲突 | 删除旧 `.db` 文件重试 |
| `Attempting to use async method...` | 异步环境下嵌套同步驱动 | 手写基于 `aiosqlite` 的异步 DAO |
| `Connection error (401)` | 配置格式错误 | 移除 API 地址中的多余空格，并使用 `.env` |

---

## 🚀 运行指南
1.  **准备环境**：`pip install langchain langchain-openai langgraph aiosqlite pydantic-settings langgraph-checkpoint-sqlite langchain-experimental`
2.  **配置密钥**：在根目录创建 `.env` 文件。
3.  **启动交互**：`python agent_lab/main.py [optional_session_id]`

---
*本手册由实战经验凝练而成，记录了从零到进阶架构的每一次蜕变。明天我们将开启模块 05：RAG 系统。*
