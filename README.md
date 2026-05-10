# AI Agent 进阶实战：我的从零到一进阶之路 (AgentLab)

你好！这份文档是我从一个 LangChain 小白进阶到具备工程化思维的 AI 开发者全过程的**实战复盘**。我抛弃了所有 Demo 级代码，带你看看一个真正能跑在生产环境的 AI 系统是如何诞生的。

---

## 📅 1个月 AI 专家成长路线图
- [x] **第一阶段：工程骨架与核心架构 (已完成 ✅)**
- [ ] **第二阶段：知识增强与多体协作 (明天开启 🚀)**
    - [ ] 模块 05：企业级 RAG 系统（向量数据库）
    - [ ] 模块 06：多 Agent 记忆协同（跨 Agent 共享上下文）
    - [ ] 模块 07：Agent 情感与拟人化（性格调优）
- [ ] **第三阶段：生产落地与性能评估 (即将到来 🏁)**

---

## 第一章：打地基 —— 拒绝 Demo，建立工程化骨架

当我开始写第一行代码时，我意识到 AI 应用如果不分层，后期就是噩梦。我借鉴了 Java Spring 的思想，第一步就是把规矩定好。

### 第 1 步：定义数据契约 (Schemas)
**重点：** 使用 Pydantic V2。如果 LLM 吐出的数据乱七八糟，这一层就是最后一道防线。
```python
# [重点代码] oip/app/schemas/base.py
class AIRequest(BaseModel):
    # 对标 Java 的 @NotNull，强制要求 Session 追踪
    session_id: str = Field(..., description="会话唯一ID")
    content: str = Field(..., min_length=1)
```

### 第 2 步：攻克 Windows 环境的“下马威”
**战记：** 程序一启动就报错？要么是 SSL 证书过期，要么是控制台打印中文变乱码。
*   **我的药方：**
    1.  手动构造一个**不校验 SSL** 的 `httpx.AsyncClient`。
    2.  强行把 `sys.stdout` 的编码改成 **UTF-8**。

---

## 第二章：记忆的决战 —— 手写异步 SQLite DAO

AI 不能是“鱼的记忆”。第二阶段我的目标是实现：**即便服务器重启，AI 依然记得我是谁。**

### 第 1 步：遭遇“同步/异步冲突”
**痛点：** 我尝试用 LangChain 官方的 `SQLChatMessageHistory`，结果一跑就报 `RuntimeError`。
**原因：** 官方组件是同步驱动的，在我的 `async` 链条里会发生死锁。

### 第 2 步：硬核重构 —— 手写异步持久化类
**重点：** 既然官方的不行，我就自己用 `aiosqlite` 撸一个。
```python
# [重点代码] oip/app/core/history.py
class AsyncSQLiteHistory(BaseChatMessageHistory):
    async def aget_messages(self) -> List[BaseMessage]:
        # 全链路异步，对标 Java 的 R2DBC
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT ...") as cursor:
                # 反序列化 JSON 字符串为 LangChain 消息对象
                return messages_from_dict([json.loads(row[0]) for row in rows])
```

---

## 第三章：赋予手脚 —— 工具调用与协议死斗

第三阶段，我给 AI 装上了 Python 执行器和文件读取器。

### 第 1 步：定义工具
**重点：** 使用 `@tool` 装饰器。记住，给 AI 看的注释（Docstring）必须写得像给领导汇报工作一样清晰。

### 第 2 步：攻克 Error 400 协议黑洞
**战记：** 调完工具发回给 AI 总结时，系统频繁报错。
**发现：** LLM 对消息顺序有洁癖。顺序必须是：`用户问 -> AI说要调工具 -> 存入工具执行结果 -> AI最终总结`。少存一步都不行！
*   **我的药方：** 在 `AIService.chat` 中手动接管消息存入流程，确保**意图**和**结果**原子性入库。

---

## 第四章：进化为大脑 —— LangGraph 状态机

这是目前最令我兴奋的部分：我把 Agent 从“复读机”变成了一个会“自我修正”的工程师。

### 第 1 步：从“链”到“图”
**重点：** 引入 LangGraph。
```python
# [重点代码] 核心循环逻辑
workflow.add_edge("action", "agent") # 执行完工具，强制回去“复盘”
```

### 第 2 步：实现“自修复”黑科技
**场景：** 我让 AI 统计文件行数，它写的代码引用错了变量。
**逻辑：** 程序捕获 Traceback 报错，直接喂给 AI。AI 看到后说：“哦，我写错了”，然后**自动改好代码重新跑**。这一刻，它才真正像个智能体。

---

## 📋 硬核避坑合集 (Troubleshooting)
| 我遇到的报错 | 它的根本原因 | 我是怎么修好的 |
| :--- | :--- | :--- |
| `ModuleNotFoundError: langgraph.checkpoint.sqlite` | 官方包拆分了 | `pip install langgraph-checkpoint-sqlite` |
| `insufficient tool messages` | 消息序列不完整 | 严格按照 [AI意图 -> 工具结果] 的顺序存入数据库 |
| `Attempting to use async method...` | 同步驱动阻塞 | 弃用官方同步组件，手写异步 DAO |

---

## 🚀 启动我的实验室
1.  **装依赖**：`pip install langchain langchain-openai langgraph aiosqlite pydantic-settings langgraph-checkpoint-sqlite`
2.  **设密钥**：在根目录新建 `.env`，写上你的 `OPENAI_API_KEY`。
3.  **开始聊**：`python agent_lab/main.py`

---
**这就是我目前的心路历程。明天，我们将一起攻克 RAG，让 AI 拥有属于它自己的“私人图书馆”！**
