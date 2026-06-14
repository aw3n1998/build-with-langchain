# 去 RAG + 可爱浮动小助手 — 实施计划（子项目 A+B）

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** 移除 RAG（前端+后端+工具注入），把短剧工作台变成唯一主视图，AI 助手改为可拖动的可爱浮动小助手（纯文字问答 + 久坐/友好主动互动）。

**Spec:** `docs/superpowers/specs/2026-06-14-rag-removal-floating-assistant-design.md`（源真）。
**验证:** 前端 `cd frontend && npm run build`；后端 `python -c "import mirage"` + `from mirage.app.agents.supervisor import graph`（带 `OPENAI_API_KEY=placeholder`）。

---

## 阶段 A · 去掉 RAG

### Task A1: 后端去 RAG
**Files:** del `mirage/app/rag/`；modify `mirage/app/services/ai_service.py`、`mirage/app/api/routes.py`

- [ ] **Step 1:** `git rm -r mirage/app/rag`
- [ ] **Step 2:** `ai_service.py`：删 import `init_pipeline`(L9)、`rag_tools`(L10)；删 `_rag_pipeline = init_pipeline(...)` + `connect()` + 相关日志(约 L36-46)；`all_tools` 那行(L106)去掉 `+ rag_tools`。若别处引用 `self._rag_pipeline`（routes 会改），确保无残留。
- [ ] **Step 3:** `routes.py`：删 `ingest_file`/`ingest_text`/`rag_status` 三个端点(约 L255-296)及 RAG 相关 import/注释；`StatusResponse` 去掉 `rag_connected`/`chunk_count`(L85-86)，新增/保留 `model`/`video_agent_only`；加一个 `GET /api/status` 返回 `{model, video_agent_only}`（沿用原 rag_status 里取 model/video_agent_only 的逻辑）。`IngestResponse` 若仅 RAG 用则一并删。
- [ ] **Step 4:** 验证 `OPENAI_API_KEY=placeholder python -c "from mirage.app.agents.supervisor import graph; print('ok')"`（解析到第三方缺失止于非 rag）；`rg -ri "rag" mirage --type py` 仅剩无关词。
- [ ] **Step 5:** commit `refactor(backend): 移除 RAG(pipeline/tools/endpoints), 状态端点精简为 /api/status`

### Task A2: 前端去 RAG
**Files:** del `frontend/src/components/KnowledgePanel.jsx`；modify `TopBar.jsx`、`App.jsx`、`api.js`

- [ ] **Step 1:** `git rm frontend/src/components/KnowledgePanel.jsx`
- [ ] **Step 2:** `TopBar.jsx`：删「Knowledge Base」按钮（绿点+计数徽章）；`onKnowledgeClick`/`showKnowledge` prop 去掉。
- [ ] **Step 3:** `App.jsx`：删 `import KnowledgePanel`、`showKnowledge` 状态、`openKnowledge`、`<KnowledgePanel/>`；`ragStatus`→`appStatus`（字段只用 model/video_agent_only）；`getStatus` 仍可用（指向 /api/status）。
- [ ] **Step 4:** `api.js`：删 `ingestText`/`ingestFile`；`getStatus` 改 `/api/status`。
- [ ] **Step 5:** `cd frontend && npm run build` 通过；commit `refactor(frontend): 移除知识库 UI(KnowledgePanel/TopBar 按钮/api)`

---

## 阶段 B · 工作台唯一主视图 + 浮动小助手

### Task B1: 工作台成为唯一主视图
**Files:** modify `frontend/src/App.jsx`（大改：去 viewMode）

- [ ] **Step 1:** 去掉 `viewMode` 状态/持久化、底部 ContextBar 的「工作台/AI 助手」切换、整屏 `<TopBar/ChatWindow/InputBar>` 的 chat 分支、作为主侧栏的 `<HistorySidebar/>`、studio 顶栏右侧「AI 助手」按钮。
- [ ] **Step 2:** 主体常驻 `ProjectSidebar` + studio 顶栏 + `ProductionPanel`/空态。设置入口：studio 顶栏加一个齿轮按钮开 `SettingsPanel`。FolderPicker 入口保留。
- [ ] **Step 3:** chat 状态（messages/sessionId/isStreaming/pendingInterrupt/sessions/sendMessage/handleResume/startNewChat/handleSelectSession/handleDeleteSession）**保留**在 App，供小助手用。
- [ ] **Step 4:** `npm run build` 通过（此时 chat 暂时无 UI 挂载点，下个 task 接上）。

### Task B2: MessageBubble compact 开关
**Files:** modify `frontend/src/components/MessageBubble.jsx`

- [ ] **Step 1:** `MessageBubble` 加可选 prop `compact`。compact 时：`production`/`param_form`/`video_param_form` 角色 → 渲染一行轻量占位（如「📋 该结果请在工作台面板查看」）而非完整卡；`AssistantMessage` 的候选图墙（ImageWall）不渲染。其余（user 气泡/assistant 文字/ToolSteps/快捷回复/InterruptCard）正常。不改非 compact 行为。
- [ ] **Step 2:** `npm run build` 通过。

### Task B3: FloatingAssistant 组件
**Files:** new `frontend/src/components/FloatingAssistant.jsx`；modify `frontend/src/App.jsx`、`frontend/src/index.css`

- [ ] **Step 1:** `index.css` 加 keyframe `al-bob`（轻微上下浮动）与 `al-blink2`（眨眼，或复用现有 blink）。
- [ ] **Step 2:** 写 `FloatingAssistant.jsx`：
  - props：`messages,onSend,isStreaming,onStop,onResume,onNewChat,sessions,onSelectSession,sessionId`。
  - mascot：SVG 可爱小家伙（圆头+眼睛+靛蓝渐变+场记板小元素），`al-bob` idle、周期眨眼。
  - 拖动：pointer 事件，位置存 `localStorage('agentlab_assistant_pos')`，移动阈值区分拖动/点击。
  - 面板：点开 360px 卡片（#161616/边框/圆角14/阴影），顶部 名字+新建会话+历史小下拉+关闭；消息区用 `<MessageBubble compact>`；底部极简输入（textarea+发送+停止）。
  - 主动互动：`setInterval(60s)` + localStorage 时间戳；`REST_AFTER_MIN=30` 久坐提醒、`IDLE_TIP_MIN=8` 友好语轮播（仅面板关闭时、低频）；头顶气泡 ~10s 自动收起、可点掉。文案/间隔为顶部常量。
- [ ] **Step 3:** `App.jsx` 挂载 `<FloatingAssistant .../>`（传 chat 状态/回调）。
- [ ] **Step 4:** `npm run build` 通过。

### Task B4: 实机核对 + 回归
- [ ] **Step 1:** vite 实机：工作台唯一主视图；小助手可拖动、点开纯文字问答、久坐提醒（临时调小 REST_AFTER_MIN 验证）；无 RAG UI。
- [ ] **Step 2:** 回归：新建/切换/删除会话、工作台出图/出片/选图/HITL、设置/工作目录入口。
- [ ] **Step 3:** commit `feat(frontend): 工作台唯一主视图 + 可爱浮动小助手(拖动/纯问答/久坐提醒)`

## Self-Review
- Spec 覆盖：A(后端 A1/前端 A2)、B-1(B1)、B-2(B2 compact + B3 组件)、验证(B4)。
- 无 placeholder；anchors 来自实际 grep（ai_service L9/10/38-44/106；routes L85-86/255-296）。
- 一致性：状态端点 /api/status 字段 model/video_agent_only 前后端一致；compact 开关复用 MessageBubble。
