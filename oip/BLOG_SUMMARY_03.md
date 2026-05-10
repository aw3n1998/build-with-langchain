# LangChain 实战：从零构建企业级 AI 平台 (OIP) - 记忆篇

## 让 AI 拥有“长久记忆”：不仅仅是存储
在 Java Web 开发中，我们习惯用 Session 或 Redis 来管理用户状态。在 AI 世界里，这被称为 **Memory (记忆)**。一个没有记忆的 AI 就像一个只有单次请求处理能力的接口，无法完成复杂的交互。

## 今日进度：集成对话历史管理
今天我为 OIP 平台增加了记忆模块，让它能够识别不同的 `session_id` 并维持对话上下文。

### 核心技术点
1. **MessagesPlaceholder**: 在 Prompt 模板中定义一个占位符。这就像在 Java 的 String 模板中预留一个集合位置，用来动态插入历史消息记录。
2. **InMemoryChatMessageHistory**: 实现了内存级的消息存储。对标 Java 中的 `ConcurrentHashMap<String, List<Message>>`。
3. **RunnableWithMessageHistory**: 这是 LangChain 的“高级装饰器”，它通过 **切面编程 (AOP)** 的思想，在请求进入 LLM 前自动注入历史，在 LLM 回复后自动保存历史。

## 架构升级：从单一链到状态链
原本的 OIP 只是简单的 `Prompt | LLM`，现在通过包装，它变成了具备“状态感应”的智能组件。这种解耦的设计模式，非常符合我们追求的“工业级”标准。

---
*项目仓库持续更新中... 下一篇：让 AI 走出“温室”——集成外部工具与 API (Tools)*
