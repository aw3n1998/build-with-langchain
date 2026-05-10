# Omni-Intelligence Platform (OIP) - 工业级 AI Agent 平台深度开发全手册

## 🌟 项目综述
**Omni-Intelligence Platform (OIP)** 是一个专为追求**生产环境稳定性**而设计的 AI 智能体平台。它基于 Python 异步协程架构，深度集成 LangChain 与 LangGraph，实现了从“简单问答”到“闭环执行”的质变。

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

### 1.2 核心模块职责映射
| 模块路径 | 职责描述 | Java 对标 |
| :--- | :--- | :--- |
| `oip/app/schemas/` | 定义 AIRequest/Response/State 的数据模型 | **DTO / POJO / Entity** |
| `oip/app/core/` | 基础组件：异步 DAO 实现、全局环境配置 | **Repository / Configuration** |
| `oip/app/services/` | 封装业务逻辑、工具定义、状态机编排 | **Service Layer** |
| `oip/main.py` | 负责 CLI 循环输入、Session 生命周期管理 | **Controller / Main Entry** |

---

## 🛠️ 第二章：已完成模块深度解析 (Master Class)

### 模块 1：工程化骨架与 Windows 环境穿透
**目标：** 解决 Windows 下开发 AI 应用的“冷启动”问题。

*   **Pydantic V2 建模**
    利用 Python 的类型提示（Type Hints）实现强类型约束。
    ```python
    class AIRequest(BaseSchema):
        # 强制要求在构造时传入，且必须非空。对标 Java 的 @NotNull
        session_id: str = Field(..., description="会话ID")
        content: str = Field(..., min_length=1)
    ```
*   **Windows 核弹级调优**
    - **SSL 问题**：由于 Windows 证书链导致 `Connection Error`。方案：注入自定义 `httpx.AsyncClient(verify=False)`。
    - **乱码问题**：强制重定向 `sys.stdout` 为 UTF-8，否则控制台输出中文会变火星文。

---

### 模块 2：深度持久化——手写异步 SQLite DAO
**目标：** 解决 LangChain 官方组件导致的异步阻塞冲突。

*   **痛点重现：** 
    官方 `SQLChatMessageHistory` 底层是同步的。在 `asyncio` 链路中调用会抛出：`Attempting to use an async method when sync mode is turned on`。
*   **硬核重构方案：**
    引入 `aiosqlite`，手写继承自 `BaseChatMessageHistory` 的异步类。
    ```python
    class AsyncSQLiteHistory(BaseChatMessageHistory):
        async def aget_messages(self) -> List[BaseMessage]:
            # 全链路异步查询。对标 Java 的 R2DBC 异步驱动
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT ...") as cursor:
                    # 序列化/反序列化逻辑
                    return messages_from_dict([json.loads(row[0]) for row in await cursor.fetchall()])
    ```

---

### 模块 3：Tool Calling 与消息时序协议 (Error 400 终结者)
**目标：** 解决 `insufficient tool messages following tool_calls` 协议错误。

*   **底层逻辑：** 
    LLM 协议（OpenAI/DeepSeek）是一个严格的状态机。消息序列必须是：`[Human] -> [AI Tool Call] -> [Tool Message] -> [Final Response]`。
*   **重构点：** 
    我们在 `AIService` 中手动拦截 `tool_calls`，确保 AI 的“调用意图”和“执行结果”按照原子顺序入库，绝对不能跳过任何一环发给下一次请求。

---

### 模块 4：LangGraph 状态机——自修复 Agent
**目标：** 实现具备“自我反思”和“纠错”能力的智能体。

*   **节点设计 (Nodes)**：
    - `agent`: 模型决策节点。
    - `action`: 工具执行节点（内置 `PythonREPL`）。
*   **自修复闭环 (Reflection Loop)**：
    如果 AI 编写的 Python 代码报错（Traceback），系统会自动捕获并将其作为 Observation 发回给 `agent`。AI 会在下一轮循环中自动修正代码。
    ```python
    # 连线逻辑：干完活必须回思考节点复盘
    workflow.add_edge("action", "agent") 
    ```
*   **断点续传：** 引入 `AsyncSqliteSaver` (Checkpoint)，状态机会为每一步动作打下“快照”，支持进程重启后的断点恢复。

---

## 📋 第三章：硬核 Troubleshooting (踩坑合集)
| 错误信息 | 根本原因 (Root Cause) | 解决方案 (The Cure) |
| :--- | :--- | :--- |
| `ModuleNotFoundError: langgraph.checkpoint.sqlite` | LangGraph 0.2 模块化拆分 | 安装 `langgraph-checkpoint-sqlite` |
| `no such column: message_json` | 同名数据库 Schema 冲突 | 删除旧 `chat_history.db` 并重启 |
| `Attempting to use async method...` | 异步链路嵌套同步数据库驱动 | 弃用官方组件，手写基于 `aiosqlite` 的 DAO |
| `Connection error (401)` | DeepSeek API 地址带了空格 | 清理 `config.py` 中的多余空格，提取到 `.env` |

---

## 📈 第四章：Java 程序员进阶 AI 路线图
| Python AI 概念 | Java 生态对标 | 核心掌握点 |
| :--- | :--- | :--- |
| **TypedDict / Pydantic** | **Lombok / JSR303** | 数据结构化与契约安全 |
| **async/await** | **CompletableFuture / WebFlux** | 突破 LLM 网络 IO 瓶颈 |
| **Runnable 接口** | **FunctionalInterface / Pipeline** | LangChain 的生命灵魂 |
| **StateGraph** | **BPMN / Activiti** | 复杂 Agent 的精准控制 |

---

## 🚀 运行指南
1.  **准备环境**：`pip install langchain langchain-openai langgraph aiosqlite pydantic-settings langgraph-checkpoint-sqlite`
2.  **配置密钥**：在根目录创建 `.env` 文件。
3.  **启动交互**：`python oip/main.py [optional_session_id]`

---
*本手册记录了从零到生产级架构的每一次蜕变。明天我们将开启模块 05：RAG 系统。*
