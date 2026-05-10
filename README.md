# Omni-Intelligence Platform (OIP) - 工业级 LangChain 实战全记录

本项目是一个基于 **Python 异步架构**、**LangChain** 与 **LangGraph** 驱动的生产级 AI 智能体平台。它不仅是一个聊天机器人，更是一个具备**长效数据库记忆**、**自动化工具执行**及**自我纠错能力**的智能系统。

---

## 🛠️ 项目核心演进全历程（保姆级操作记录）

### 1. 环境与工程化骨架 (Infrastructure)
**操作目标：** 建立类似 Java Spring 的分层架构，拒绝 Demo 式代码。

*   **步骤 1：定义契约 (DTO Layer)**
    使用 Pydantic V2 确保输入输出的严谨性。
    ```python
    # oip/app/schemas/base.py
    class AIRequest(BaseModel):
        session_id: str = Field(..., description="必填的会话ID")
        content: str = Field(..., min_length=1)
    ```
*   **步骤 2：环境隔离与配置中心**
    利用 `pydantic-settings` 自动加载 `.env`，解决敏感信息硬编码。
*   **步骤 3：攻克 Windows 环境顽疾**
    - **SSL 穿透**：注入自定义 `httpx.AsyncClient(verify=False)`。
    - **终端乱码**：重定向 `sys.stdout` 为 UTF-8 编码。

---

### 2. 突破“单轮对话”：异步数据库持久化 (Persistence)
**操作目标：** 解决 LangChain 官方组件在异步链路中的同步阻塞冲突。

*   **痛点：** 官方 `SQLChatMessageHistory` 在 `asyncio` 下会触发 `RuntimeError`。
*   **硬核重构：** 手写 **`AsyncSQLiteHistory`** 异步 DAO。
    ```python
    # 伪代码逻辑：异步 DAO 模式
    class AsyncSQLiteHistory(BaseChatMessageHistory):
        async def aget_messages(self):
            async with aiosqlite.connect(self.db_path) as db:
                # 纯异步查询数据库，不阻塞线程
                cursor = await db.execute("SELECT ... WHERE session_id=?", (self.sid,))
                return deserialize(await cursor.fetchall())
    ```
*   **结果：** 实现了真正的“重启不失忆”，支持通过 `thread_id` 找回历史。

---

### 3. 为 AI 装上手：Tool Calling 与闭环协议
**操作目标：** 让 AI 具备执行 Python 代码和查文件的能力。

*   **步骤 1：声明工具**
    使用 `@tool` 将 Python 函数转化为 LLM 可理解的描述。
*   **步骤 2：绑定工具**
    `model.bind_tools([get_time, execute_code])`。
*   **步骤 3：处理 Error 400 协议错误**
    - **深坑**：调用工具后直接二次请求会报 `insufficient tool messages`。
    - **修复**：严格遵循消息序列：`User -> Assistant(tool_call) -> ToolMessage -> Final Assistant`。每一环都必须持久化。

---

### 4. 智能体进化：LangGraph 状态机与自修复 (The Brain)
**操作目标：** 弃用线性链，改用图结构实现“反思”与“纠错”。

*   **架构设计：**
    ```mermaid
    graph LR
        START --> agent[模型思考节点]
        agent --> condition{是否调工具?}
        condition -- 是 --> action[工具执行节点]
        action --> agent
        condition -- 否 --> END
    ```
*   **黑科技：自修复循环 (Self-Correction)**
    如果在 `action` 节点执行代码报错，系统会捕捉 Traceback 喂回给 `agent`。
    ```python
    # 逻辑演示
    async def call_model(state):
        # 系统提示词：告诉 AI 报错了就要修正代码重跑
        return await model.ainvoke(state['messages'])
    ```
*   **断点续传：** 引入 `SqliteSaver` (Checkpoint)，让 AI 执行到一半掉线也能从当前节点恢复。

---

## 📈 Java 程序员技术对标
| 模块 | Java 生态对标 | 本项目意义 |
| :--- | :--- | :--- |
| **Pydantic** | Hibernate / JSR303 | 数据契约安全 |
| **LCEL** | Java Stream / 责任链 | 逻辑声明式编排 |
| **AsyncIO** | Netty / CompletableFuture | 高并发不阻塞 |
| **LangGraph** | Activiti / Flowable | 行为可控的状态机 |

---

## 🚀 快速启动
1.  **安装依赖**：`pip install langchain langchain-openai langgraph aiosqlite pydantic-settings`
2.  **配置环境**：在根目录创建 `.env` 并填入 `OPENAI_API_KEY`。
3.  **运行程序**：`python oip/main.py`

---
*本项目记录了 AI 工程化中所有的核心挑战，是一份可以从 0 复制到 1 的生产级实战手册。*
