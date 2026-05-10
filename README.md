# Omni-Intelligence Platform (OIP) - 工业级 AI Agent 平台深度开发全手册

## 🌟 项目综述
**Omni-Intelligence Platform (OIP)** 是一个专为追求**生产环境稳定性**而设计的 AI 智能体平台。它基于 Python 异步协程架构，深度集成 LangChain 与 LangGraph，实现了从“简单问答”到“闭环执行”的质变。

本手册不仅记录了代码，更记录了在 Windows 环境下解决网络穿透、异步锁冲突、消息协议一致性等**核心工程问题**的底层逻辑。

---

## 🏗️ 第一章：分层架构设计 (Architecture)
借鉴 Java Spring 的分层思想，OIP 拒绝了 AI 开发中常见的“面条式”代码，建立了严谨的解耦体系。

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

### 1.2 核心模块职责
| 模块路径 | 职责描述 | Java 对标 |
| :--- | :--- | :--- |
| `oip/app/schemas/` | 定义 AIRequest/Response/State 的数据模型 | **DTO / POJO / Entity** |
| `oip/app/core/` | 基础组件：异步 DAO 实现、全局环境配置 | **Repository / Configuration** |
| `oip/app/services/` | 封装业务逻辑、工具定义、状态机编排 | **Service Layer** |
| `oip/main.py` | 负责 CLI 循环输入、Session 生命周期管理 | **Controller / Main Entry** |

---

## 🛠️ 第二章：模块化开发全记录 (Step-by-Step)

### 模块 1：工程化骨架与环境穿透
**目标：** 解决 Windows 下开发 AI 应用的“冷启动”问题。

*   **核心操作 1：Pydantic V2 建模**
    利用 Python 的类型提示（Type Hints）实现强类型约束。
    ```python
    # 伪代码：强制数据校验
    class AIRequest(BaseSchema):
        session_id: str = Field(..., min_length=5) # 必须传且长度>5
        content: str = Field(..., max_length=1000)
    ```
*   **核心操作 2：Windows 核弹级调优**
    - **SSL 问题**：Windows 证书链经常导致 Connection Error。通过自定义 `httpx.AsyncClient(verify=False)` 强行穿透。
    - **乱码问题**：重定向 `sys.stdout`，将默认的 GBK 强制转为 UTF-8。

---

### 模块 2：深度持久化——手写异步 SQLite DAO
**目标：** 解决 LangChain 官方组件导致的 `RuntimeError: Attempting to use an async method when sync mode is turned on`。

*   **技术深度：**
    官方 `SQLChatMessageHistory` 底层是同步的。在一个纯异步的 AI 链路（`ainvoke`）中，同步数据库操作会阻塞事件循环并触发报错。
*   **重构方案：**
    引入 `aiosqlite`，手写继承自 `BaseChatMessageHistory` 的异步类。
    ```python
    # oip/app/core/history.py
    async def aadd_messages(self, messages: Sequence[BaseMessage]):
        async with aiosqlite.connect(self.db_path) as db:
            for m in messages:
                # 必须手动执行序列化，对标 Java 的 JSON 转换
                await db.execute("INSERT INTO ...", (self.sid, json.dumps(message_to_dict(m))))
            await db.commit()
    ```

---

### 模块 3：Tool Calling 与消息时序协议
**目标：** 让 AI 具备“行动力”，并攻克 OpenAI/DeepSeek 的 400 协议报错。

*   **关键点：** 
    LLM 协议规定：如果返回了 `tool_calls`，下一次请求的历史记录中**必须**紧跟对应的 `ToolMessage`。
*   **错误示范：** `User -> AI(call tool) -> [代码直接跑了没存] -> AI(final)` ❌
*   **正确实现：** 
    ```python
    # AIService.chat 核心逻辑
    await history.aadd_messages([ai_message_with_tool_call]) # 1. 存入 AI 的调用意图
    observation = await tool.ainvoke(args) # 2. 执行
    await history.aadd_messages([ToolMessage(content=observation)]) # 3. 存入执行结果
    # 4. 最后带上完整历史请求 LLM 总结
    ```

---

### 模块 4：LangGraph 状态机——从线性到循环
**目标：** 实现具备“自我反思”和“纠错”能力的智能体。

*   **节点定义 (Nodes)**：
    - `agent`: 调用 LLM 思考。
    - `action`: 使用 `PythonREPL` 执行代码。
*   **自修复循环逻辑**：
    如果 AI 写的代码报错（例如 `import` 了一个没装的库），系统会捕获错误并将其作为 `observation` 发回。AI 会在下一次循环中看到：“代码报错了，原因是...”，从而自动重写代码。
*   **断点续传 (SqliteSaver)**：
    引入 `AsyncSqliteSaver`，状态机会为每一步动作打下“快照”。
    ```python
    # 架构隐喻：事务检查点
    workflow.compile(checkpointer=AsyncSqliteSaver(connection))
    ```

---

## 📋 第三章：实战踩坑与硬核 Troubleshooting
记录本工程中所有 P0 级 Bug 的排查。

| 错误信息 | 根本原因 (Root Cause) | 解决方案 (The Cure) |
| :--- | :--- | :--- |
| `ImportError: AsyncSqliteSaver` | LangGraph 0.2+ 版本模块拆分 | 安装 `langgraph-checkpoint-sqlite` 插件包 |
| `no such column: message_json` | 旧版同步组件创建了错误的数据库 Schema | 执行 `Remove-Item chat_history.db` 并重启 |
| `Attempting to use async...` | 异步环境下嵌套了同步数据库驱动 | 采用“线程隔离 (to_thread)”或手写“异步 DAO” |
| `Connection error (401)` | DeepSeek API 地址与 Key 配置不匹配 | 提取到 `.env`，统一 Base 为 `https://api.deepseek.com/v1` |

---

## 📈 第四章：Java 程序员进阶 AI 路线图
| Python AI 概念 | Java 生态对标 | 核心掌握点 |
| :--- | :--- | :--- |
| **TypedDict / Pydantic** | **Lombok / JSR303** | 保证 AI 处理的数据“结构化” |
| **async/await** | **CompletableFuture / Loom** | 解决 LLM 长耗时任务的吞吐量瓶颈 |
| **Runnable 接口** | **FunctionalInterface / Pipe** | 理解 LangChain 所有的“管道”操作 |
| **StateGraph** | **BPMN / State Machine** | 掌握 Agent 的控制权，实现复杂业务闭环 |

---

## 🚀 运行指南
1.  **准备环境**：
    ```bash
    pip install langchain langchain-openai langgraph langgraph-checkpoint-sqlite aiosqlite pydantic-settings
    ```
2.  **配置密钥**：
    在根目录创建 `.env` 文件。
3.  **启动平台**：
    ```bash
    python oip/main.py [optional_session_id]
    ```

---
*本手册由实战经验凝练而成，记录了从“Demo”到“生产级架构”的每一次蜕变。*
