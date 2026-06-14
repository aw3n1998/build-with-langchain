# 去 RAG + 可爱浮动小助手 — 设计规格

日期：2026-06-14
状态：待评审
所属：短剧工作台演进 6 项需求中的**第一个子项目（A+B）**。后续子项目：C+D（LoRA 修复+NSFW 模型）、E（一键分析小说自动填充）、F（可复用技能/模板库）。

## 目标

两件事，一起做：

1. **A — 去掉 RAG**：知识库（Milvus/向量检索）没用了，整条移除（前端 UI + 后端 pipeline + agent 工具注入），但保留状态端点里仍需要的 `model`/`video_agent_only`。
2. **B — 聊天改「可爱浮动小助手」**：短剧工作台成为**唯一主视图**；AI 助手退为右下角一个**可拖动的可爱小助手**，点开是**纯文字问答**面板，并**偶尔主动互动**（久坐提醒等）。

## 背景 / 约束

- 现在 chat 是整屏 `viewMode==='chat'` 视图；拆分镜/出图/出片/角色/导出 **已全部在工作台 ProductionPanel 具备**，所以聊天不再需要承担「干活」，降级为纯问答助手。
- **不破坏**现有流式/会话基础设施（`chatSubmit`/`streamJobEvents`/`consumeStream`/`sessionId`/HITL resume）——复用，只是换渲染容器并砍掉重 UI。
- localStorage key 仍保持 `agentlab_*` 不动（与既有约定一致）。
- 沿用 inline style + CSS 变量 token；不引依赖（拖动用原生 pointer 事件，不引 react-rnd）。

---

## A. 去掉 RAG

### 后端
- **删除**：`mirage/app/rag/`（`pipeline.py`/`store.py`/`retriever.py`/`chunker.py`/`loader.py`/`rag_tools.py`）。
- `mirage/app/services/ai_service.py`：移除 RAG 导入、`_rag_pipeline` 初始化、以及把 `rag_tools` 注册进工具表那行（`register(rag_tools)`）。`is_connected` 之类的引用一并清理。
- `mirage/app/api/routes.py`：删 `/api/rag/ingest/file`、`/api/rag/ingest/text` 两个端点及其 RAG 导入；**状态端点**保留但去掉 `rag_connected`/`chunk_count` 字段——重命名/精简为 `GET /api/status` 返回 `{ model, video_agent_only }`（路径从 `/api/rag/status` 改 `/api/status`）。
- 验证：`python -c "import mirage"` + `from mirage.app.agents.supervisor import graph` 仍解析（supervisor 少一个检索工具，不报错）；`rg -ri "rag" mirage --type py` 仅剩无关词。

### 前端
- **删除** `frontend/src/components/KnowledgePanel.jsx`。
- `TopBar.jsx`：移除「Knowledge Base」按钮（绿点 + 计数徽章那一坨）。
- `App.jsx`：移除 `showKnowledge` 状态、`openKnowledge`、`<KnowledgePanel/>` 挂载、以及对应 props 透传。`ragStatus` → 改名 `appStatus`（仅保留 `model`/`video_agent_only` 用途）。`getStatus` 改调 `/api/status`。
- `api.js`：移除 `ingestText`/`ingestFile`；`getStatus` 指向新端点。
- `ChatWindow` 空态里「混合检索 / 从右上角导入资料」等 RAG 文案——本子项目 B 会重做聊天容器，空态随之更新（不再提 RAG/知识库）。

---

## B-1. 工作台成为唯一主视图

- `App.jsx`：移除 `viewMode` 双视图与持久化、底部 ContextBar 的「工作台/AI 助手」切换、整屏 `ChatWindow`/`InputBar`/`TopBar(chat)`、以及作为主侧栏的整屏 `HistorySidebar`。
- 主体常驻：左 `ProjectSidebar` + 右 `ProductionPanel`（即现在 studio 分支的布局），顶栏保留 studio 顶栏（剧集名/改名/删除/工作目录）。
- 原 studio 顶栏右侧的「AI 助手」主按钮去掉（助手改为浮动小助手，不需要切视图）。
- 工作目录选择（FolderPicker）、设置（SettingsPanel）入口保留（设置入口移到 studio 顶栏或小助手面板，二选一——实现时取 studio 顶栏一个齿轮按钮）。

## B-2. 可爱浮动小助手 `FloatingAssistant.jsx`（核心新增）

一个常驻在工作台之上的浮层组件，三部分：

### 1) 吉祥物（mascot）
- 右下角默认位置的一个可爱小家伙：圆头 + 两只会眨眼的眼睛 + 蜃景靛蓝渐变身体，带一点短剧场记板小元素。
- **idle 动画**：轻微上下浮动（CSS keyframe，新增 `al-bob`）+ 周期眨眼（复用/新增 keyframe）。
- **可拖动**：原生 pointer 事件（pointerdown/move/up）拖到屏幕任意位置；位置存 localStorage（`agentlab_assistant_pos`），刷新保留；拖动与点击区分（移动超过阈值判为拖动，不触发点开）。
- 点击 → 切换聊天面板开合。

### 2) 聊天面板（点开后）
- 锚在 mascot 旁边弹出，约 `360px` 宽、`min(70vh, 520px)` 高的卡片（`#161616` + 边框 + 圆角 14 + 阴影），可关闭。
- **顶部**：小助手名字（如「蜃景小助手」）+ 新建会话按钮 + 会话历史小下拉（切换/列出近期会话，复用 `getHistory`/`getSessionHistory`）+ 关闭。
- **消息区**：复用流式逻辑，但**纯文字问答**渲染——只渲染 user 文字气泡 / assistant 文字（含 Markdown）/ 工具步骤 chips / 快捷回复 / HITL 确认卡；**不渲染** param_form / video_param_form / production / 候选图墙（这些属于工作台，不在小助手里堆）。
- **底部**：极简输入框（textarea + 发送 + 流式时停止）。**砍掉** agent 药丸、think 模式、slash 菜单（「简单会话」）。聊天默认走问答型 agent（supervisor）。
- 复用现有 `sendMessage`/`consumeStream`/`sessionId`/HITL `handleResume`（chat 状态仍可留在 `App.jsx`，以 props 传入小助手；或抽到 `useChat` hook——实现时择优，优先低风险留在 App）。

### 3) 偶尔主动互动（小性格）
- mascot 头顶冒一个**气泡说话**，可点掉、低频、不打扰。由一个轻量调度器驱动（`setInterval` 每 60s 检查 + localStorage 记时间戳，避免刷新刷屏）：
  - **久坐提醒**（明确要的）：连续操作累计约 `30min` 未休息 → 「忙挺久啦，起来动动、喝口水？☕」。点掉/休息后重置计时。
  - **零星友好语**：偶尔（低概率、间隔 ≥ 数分钟、仅在面板关闭时）轮播一句，如「需要帮忙就叫我~」「先在角色圣经设好人物，拆出来更统一哦」「记得给本集设个统一风格～」。
  - 气泡 ~10s 自动收起或点掉。
- 话术与节奏抽成顶部常量（`REST_AFTER_MIN=30`、`IDLE_TIP_MIN=8`、文案数组），便于调。
- 原则：可关、低频、温柔，绝不打断正在进行的操作。

### 状态与数据流
- chat 相关状态（`messages`/`sessionId`/`isStreaming`/`pendingInterrupt`/`sessions`）仍由 `App.jsx` 持有，传入 `FloatingAssistant`（与现状一致，仅渲染位置变化）。
- `FloatingAssistant` 自有状态：`open`（面板开合）、`pos`（拖动位置）、`bubble`（当前主动消息）、计时戳。
- 助手面板里渲染的「简化消息视图」用一个轻量渲染器（可在 `FloatingAssistant` 内联，或给 `ChatWindow`/`MessageBubble` 加一个 `compact` 开关跳过生产类卡片——实现时优先加 `compact` 开关复用 `MessageBubble`，避免重写 Markdown/步骤渲染）。

---

## 非目标（本子项目不做）
- 不做 E（一键分析小说自动填充）、不做 F（技能/模板库）、不动 LoRA（C）/不加 NSFW 模型（D）——后续子项目各自来。
- 小助手不承担生产（出图/出片/拆分镜）——那些在工作台面板。
- 不引拖拽/动画库；不做多吉祥物皮肤切换（先一个）。

## 验证
- 前端 `npm run build` 通过；本地 vite 实机：工作台为唯一主视图、无双视图切换；右下角小助手可拖动、点开能纯文字问答、久坐提醒能触发（可临时把 `REST_AFTER_MIN` 调小验证）；无 RAG 残留 UI。
- 后端 `import mirage` + graph 解析通过；`rg -ri "knowledge base|rag_tools|/rag/"` 无残留有效引用。
- 回归：新建/切换/删除会话、出图/出片/选图/HITL（在工作台面板里）手测无回归。

## 实施顺序（建议）
1. **A 后端**：删 `mirage/app/rag/` + ai_service 去注入 + routes 删端点/精简状态端点；验证 import/graph。
2. **A 前端**：删 KnowledgePanel + TopBar KB 按钮 + App/api 清理；build。
3. **B-1**：App.jsx 去 viewMode、改为工作台唯一主视图；build。
4. **B-2**：写 `FloatingAssistant.jsx`（mascot + 拖动 + 聊天面板 + 主动互动）；给 `MessageBubble` 加 `compact` 开关；接到 App 的 chat 状态；`index.css` 加 `al-bob`/眨眼 keyframe；build + 实机核对。
5. 收尾：构建 + 实机 + 回归。
