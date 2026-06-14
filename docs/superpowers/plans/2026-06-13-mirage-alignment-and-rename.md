# 蜃景 / Mirage — 视觉对齐 + 品牌改名 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `frontend/` 全部组件逐像素对齐到短剧工作台 mockup，并把项目品牌从 AgentLab 彻底改成 蜃景 / Mirage（前端显示 + 后端包与目录 + 文档），功能逻辑零改动。

**Architecture:** 三阶段。阶段一前端视觉对齐与前端改名合并提交；阶段二后端 Python 包 `agent_lab`→`mirage` 机械重命名并验证；阶段三文档。沿用现有「inline style + CSS 变量 token」写法，不引入依赖、不改行为。

**Tech Stack:** React 18 + Vite + 纯 inline style/CSS 变量（无 Tailwind 类）；后端 Python（LangGraph / FastAPI）。

**源真规格（exact 像素值都在这）：** `docs/superpowers/specs/2026-06-13-studio-design-alignment-design.md`。本计划各任务引用其对应小节，不重复抄数值；改动时以规格为准。

**验证方式（本类工作无单测）：** 前端 = `cd frontend && npm run build` 通过 + 本地 `vite` 人工核对；后端改名 = `python -c "import mirage"` + `pytest` 现有用例不变绿 + 全仓 grep 残留。

---

## 阶段一 · 视觉对齐 + 前端改名

### Task 1: 打底 — keyframes + 删遗留 Sidebar

**Files:**
- Modify: `frontend/src/index.css`（追加 keyframes）
- Delete: `frontend/src/components/Sidebar.jsx`

- [ ] **Step 1: 在 `index.css` 的 `@keyframes blink` 旁追加**

```css
@keyframes al-spin { to { transform: rotate(360deg); } }
@keyframes al-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(52,211,153,0.5); }
  50%      { box-shadow: 0 0 0 5px rgba(52,211,153,0); }
}
```

- [ ] **Step 2: 删除 `frontend/src/components/Sidebar.jsx`**（已确认全仓无 import：`git mv` 不需要，直接 `git rm`）

Run: `cd frontend && rg -n "from.*Sidebar'|import Sidebar" src` → 期望无结果（确认无引用后删）

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: 成功，无新增报错。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/index.css && git rm frontend/src/components/Sidebar.jsx
git commit -m "style(frontend): 加 al-spin/al-glow keyframes; 删遗留 Sidebar.jsx"
```

---

### Task 2: MessageBubble — UserMessage 改靛蓝气泡

**Files:** Modify `frontend/src/components/MessageBubble.jsx`（`UserMessage`, 约 L55-70）
**规格：** B 段「`UserMessage`」。

- [ ] **Step 1:** 把右对齐纯文字改为气泡：外层 `display:flex; justify-content:flex-end`，气泡 `align-self/max-width:72%; background:rgba(99,102,241,0.14); border:1px solid rgba(99,102,241,0.25); border-radius:14px 14px 4px 14px; padding:11px 15px; font-size:13.5px; line-height:1.55; white-space:pre-wrap`。保留 `content` 渲染。
- [ ] **Step 2:** 构建：`cd frontend && npm run build` → 成功。
- [ ] **Step 3:** Commit：`git commit -am "style(chat): 用户消息改靛蓝气泡"`

---

### Task 3: MessageBubble — AssistantMessage 去卡片框 + MIRAGE 标签

**Files:** Modify `frontend/src/components/MessageBubble.jsx`（`AssistantMessage`, 约 L118-222）
**规格：** 判断项 1 + B 段「`AssistantMessage`」。

- [ ] **Step 1:** 去掉最外层 `var(--card)` 卡片 `<div>`，改为无背景/无边框/无 padding 的容器（保留为定位用的 `<div>` 或 fragment）。
- [ ] **Step 2:** 标签文案 `AGENTLAB` → `MIRAGE`；样式 `color:#6366f1; font-family:'SF Mono',ui-monospace,monospace; font-size:10px; font-weight:700; letter-spacing:1px; margin-bottom:9px`。
- [ ] **Step 3:** RAG 来源标签改靛蓝 pill（`bg rgba(99,102,241,0.1); border rgba(99,102,241,0.25); color:#a5a8ff; SF Mono; 10.5px; padding:3px 8px; radius:5px`，去掉顶部分隔线那套灰底）。
- [ ] **Step 4:** MSG_SPLIT 纯快捷回复按钮 → 中性灰（`height:28; padding:0 12; radius:8; border rgba(255,255,255,0.13); bg rgba(255,255,255,0.04); color rgba(255,255,255,0.87); 12px`，hover `bg rgba(255,255,255,0.08)`）。`PcActionButton` 语义色逻辑不动。
- [ ] **Step 5:** `ToolSteps`/`ImageWall`/`video` 子元素调用位置不变（样式在各自任务里改）。构建通过。
- [ ] **Step 6:** Commit：`git commit -am "style(chat): AI 消息去卡片框 + MIRAGE 标签 + 靛蓝 RAG pill"`

---

### Task 4: MessageBubble — ToolSteps 靛蓝盒

**Files:** Modify `frontend/src/components/MessageBubble.jsx`（`ToolSteps`, 约 L1781-1831）
**规格：** B 段「`ToolSteps`」。

- [ ] **Step 1:** 外框改 `border:1px solid rgba(99,102,241,0.2); background:rgba(99,102,241,0.06); border-radius:10px; padding:12px 14px`；行 `font-size:12px; gap:7px`，状态符 `✓`=`#34d399`，名称色 `rgba(255,255,255,0.52)`。`s.result` 展开逻辑保留，分隔线/底色随盒调和。
- [ ] **Step 2:** 构建通过。
- [ ] **Step 3:** Commit：`git commit -am "style(chat): 工具步骤盒改靛蓝"`

---

### Task 5: MessageBubble — ImageWall 瓦片对齐

**Files:** Modify `frontend/src/components/MessageBubble.jsx`（`ImageWall`, 约 L225-306）
**规格：** B 段「`ImageWall`」。**逻辑（放大灯箱/选图回调/禁用态）一律不动。**

- [ ] **Step 1:** 瓦片 `border-radius:9px`，选中边框 `2px solid #34d399`；右上角加「选中」标签（`padding:2px 7px; radius:5px; background:#34d399; color:#04201a; font-size:9.5px; font-weight:700`）替代/补充现有 ○/✓ 视觉（选图按钮交互保留）。栅格 `minmax` 自适应沿用。
- [ ] **Step 2:** 构建通过。
- [ ] **Step 3:** Commit：`git commit -am "style(chat): 候选图墙瓦片/选中标签对齐 mockup"`

---

### Task 6: MessageBubble — ParamCard + VideoParamCard 改青色

**Files:** Modify `frontend/src/components/MessageBubble.jsx`（`ParamCard` L309-391, `VideoParamCard` L441-615）
**规格：** B 段「`ParamCard` + `VideoParamCard`」。**字段/校验/`submitted`/`stale` 逻辑不动。**

- [ ] **Step 1:** 外框 `border:1px solid rgba(0,189,176,0.3); background:rgba(0,189,176,0.05); radius:12; padding:15px 17px`。
- [ ] **Step 2:** 标题去大写，改图标(`stroke #00bdb0`) + 文案 `出图参数卡 param_form` / `出视频参数卡 video_param_form`，`color:#5fe8de; 12.5px; 600`；video 卡右侧「预计 ≈ Ns」`#5fe8de`。
- [ ] **Step 3:** 内部 input/select/textarea 边框 `rgba(0,189,176,0.25)`；主按钮 `background:#00bdb0; color:#04201e; 600` hover `opacity:.88`。
- [ ] **Step 4:** 构建通过。
- [ ] **Step 5:** Commit：`git commit -am "style(chat): 出图/出视频参数卡改青色 param_form 主题"`

---

### Task 7: MessageBubble — InterruptCard 简洁化

**Files:** Modify `frontend/src/components/MessageBubble.jsx`（`InterruptCard`, 约 L1941-2039）
**规格：** 判断项 2 + D-N/A。**`onResume(true/false)` 与 `resolved` 三态判断保留。**

- [ ] **Step 1:** pending 外框中性：`border:1px solid rgba(255,255,255,0.13); background:#161616; radius:12; padding:15px 17px`；去掉 HITL 大写标签 + 警告图标 + 黄色外框；正文 `12.5px; line-height:1.6`。
- [ ] **Step 2:** 按钮：确认执行 `background:#34d399; color:#04201a`；取消 `border rgba(239,68,68,0.4); bg rgba(239,68,68,0.1); color:#f87171`。
- [ ] **Step 3:** 保留 resolved 后「已确认执行 / 已取消」状态行（配色 `#34d399`/`#f87171`）。
- [ ] **Step 4:** 构建通过。
- [ ] **Step 5:** Commit：`git commit -am "style(chat): HITL 确认卡简洁化, 保留已决策反馈"`

---

### Task 8: MessageBubble — ProductionPanel 对齐（最大块）

**Files:** Modify `frontend/src/components/MessageBubble.jsx`（`ProductionPanel` L643-1607 及共享样式 `panelBtn`/`miniAct`/`inputStyle`/`miniBtn` L1729-1778）
**规格：** C 段全部。**所有数据加载/出图/出片/选图/角色/LoRA/导出 等逻辑与 API 调用一律不动，仅改样式与文案。**

- [ ] **Step 1: 外层 + meta 头**：去掉外层靛蓝卡（`border rgba(99,102,241,0.3); bg rgba(99,102,241,0.05)`）改裸布局；meta 头彩色统计（已出图 `#eab308` · 已选 `#c084fc` · 已出片 `#34d399`），右侧刷新方钮 30×30 radius 7。
- [ ] **Step 2: Tab 栏**：`gap:26px; border-bottom 1px`，每 tab `padding-bottom:11; margin-bottom:-1`，active `border-bottom:2px #6366f1; color rgba(255,255,255,0.87); 650`，图标 opacity 1/0.7。key 不变（script/cast/shots/export）。
- [ ] **Step 3: 分镜卡状态徽章**：已出片绿/待选图紫/出图中黄(+`al-spin`+已运行Ns)/待出图灰；徽章 `height:22; padding:0 9; radius:6; 11px`，圆点 5×5。
- [ ] **Step 4: 全局控制条**：`① 一键全部出图` 靛蓝 `#6366f1`；`③ 一键出片并合成` 青 `#00bdb0/#04201e`；预计秒数 `#5fe8de`。
- [ ] **Step 5: GPU 日志**：底条 `background:#0a0a0a` 可折叠，标题 SF Mono 11px，状态 `● 出图中 Ns` `#eab308`；日志行配色 info `#34d399`/tool `#6cb6ff`/error `#f87171`/warn `#eab308`，SF Mono 11px line-height 1.7。滚动/尾部 N 条逻辑不动。
- [ ] **Step 6: 共享样式常量**：`panelBtn`/`miniAct`/`inputStyle`/`miniBtn` 仅调色与圆角，签名不变。
- [ ] **Step 7:** 构建通过。
- [ ] **Step 8:** Commit：`git commit -am "style(studio): ProductionPanel 逐像素对齐 mockup(meta/tab/状态徽章/全局条/GPU日志)"`

---

### Task 9: TopBar 对齐 + 品牌字

**Files:** Modify `frontend/src/components/TopBar.jsx`
**规格：** D 段「`TopBar.jsx`」。

- [ ] **Step 1:** 品牌字 `AgentLab` → `蜃景`；logo 方块 radius 6→7 + `Icon.Clapper`；模型名 SF Mono；KB 按钮含绿点 + 计数徽章（值用现有 `ragStatus.chunk_count`）；图标方钮 base `bg rgba(255,255,255,0.04)`；KB/设置 active 靛蓝高亮。回调/props 不变。
- [ ] **Step 2:** 构建通过。
- [ ] **Step 3:** Commit：`git commit -am "style(chat): TopBar 对齐 + 品牌字蜃景"`

---

### Task 10: HistorySidebar 对齐 + 品牌字

**Files:** Modify `frontend/src/components/HistorySidebar.jsx`
**规格：** D 段「`HistorySidebar.jsx`」。

- [ ] **Step 1:** 品牌字 `AgentLab` → `蜃景`；logo → `Icon.Clapper` 嵌 22×22 渐变方块；背景纯 `#0d0d0d`（去 backdrop-blur）；会话条 48px，进行中绿点 7×7 用 `animation:al-glow 1.6s ease-in-out infinite`；New Chat 虚线按钮 34px；去掉「History Threads」分组标签。删除按钮 hover 显隐与所有回调不变。
- [ ] **Step 2:** 构建通过。
- [ ] **Step 3:** Commit：`git commit -am "style(chat): HistorySidebar 对齐 + 品牌字蜃景"`

---

### Task 11: InputBar 对齐 + 占位符

**Files:** Modify `frontend/src/components/InputBar.jsx`
**规格：** D 段「`InputBar.jsx`」。

- [ ] **Step 1:** agent pill radius 6→13/height 24→25/padding 0 9/11px；think 按钮 radius 6→7/height 25；命令提示行 SF Mono；占位符与底部提示中文 `给 蜃景 发消息…  Enter 发送 · Shift+Enter 换行`；发送按钮 `#6366f1` radius 8 hover `#5254cc`；active/非 active pill 配色按规格。slash 菜单等逻辑不动。
- [ ] **Step 2:** 构建通过。
- [ ] **Step 3:** Commit：`git commit -am "style(chat): InputBar 药丸/think/发送对齐 + 占位符蜃景"`

---

### Task 12: SettingsPanel 对齐

**Files:** Modify `frontend/src/components/SettingsPanel.jsx`
**规格：** D 段「`SettingsPanel.jsx`」。**保存/读取 localStorage、`onSaved`、各 agent 配置字段全保留；功能字段多于 mockup 则保留字段套视觉。**

- [ ] **Step 1:** 抽屉宽 360→`min(420px,92vw)`；头部 齿轮 + Settings；Backend Endpoint 输入（值绿 `#86efac` SF Mono）；Supervisor 区块预设按钮行 + Model/URL/Key（眼睛切换）；底部 Reset all / Save changes 等宽。
- [ ] **Step 2:** 构建通过。
- [ ] **Step 3:** Commit：`git commit -am "style: SettingsPanel 对齐 mockup"`

---

### Task 13: KnowledgePanel + FolderPicker 对齐

**Files:** Modify `frontend/src/components/KnowledgePanel.jsx`, `frontend/src/components/FolderPicker.jsx`
**规格：** D 段对应两条。**上传/粘贴/状态/浏览/选定逻辑不动。**

- [ ] **Step 1:** KnowledgePanel：宽 320；Upload/Paste 等宽切换；上传区 `1.5px dashed rgba(255,255,255,0.18) radius:10 padding:32 16` + 图标 + 中文提示。
- [ ] **Step 2:** FolderPicker：遮罩 `rgba(0,0,0,0.55)+blur(2px)`；卡 560/`#161616`/radius 14/box-shadow；路径 SF Mono；列表项 38px + `/` 前缀；底部 用默认目录/选定此目录。
- [ ] **Step 3:** 构建通过。
- [ ] **Step 4:** Commit：`git commit -am "style: KnowledgePanel/FolderPicker 对齐 mockup"`

---

### Task 14: App.jsx 内联顶栏/ContextBar + 应用级品牌字

**Files:** Modify `frontend/src/App.jsx`, `frontend/index.html`, `frontend/package.json`, `frontend/vite.config.js`
**规格：** D 段「`App.jsx`」。

- [ ] **Step 1:** App.jsx studio 顶栏 min-height 56/gap 12，剧集名 15px/600，改名删除方钮 32×32 radius 8，`工作目录` 中性钮，右侧 `AI 助手` 主钮 `#6366f1` hover `#5254cc`；聊天底部 ContextBar（工作台钮靛蓝、绿路径、更改、制作面板、进度条）对齐。切换/抽屉逻辑不动。
- [ ] **Step 2:** `index.html` `<title>` → `蜃景 Mirage`（或 `蜃景`）；`package.json` `"name"` → `mirage`（或 `mirage-frontend`）；`vite.config.js` 里出现的品牌字 → mirage。检查 `frontend/previews/*.html` 品牌字一并改。
- [ ] **Step 3:** 构建通过；全前端残留检查 `cd frontend && rg -i "agentlab" src index.html package.json vite.config.js` → 仅剩 `agentlab_*` localStorage key（刻意保留）。
- [ ] **Step 4:** Commit：`git commit -am "style/chore(frontend): App 顶栏+ContextBar 对齐; 应用级品牌字改蜃景/mirage"`

---

### Task 15: icons.jsx 核对补齐

**Files:** Modify `frontend/src/components/icons.jsx`（按需）
**规格：** D 段「`icons.jsx`」。

- [ ] **Step 1:** 核对各任务用到的图标（`Clapper/Plus/Chat/Pencil/Trash/Folder/Script/Users/Layers/Download/Refresh/Wand/Settings/Eye/Mic` 等）是否齐全；缺的按 mockup SVG 补；stroke-width 主 1.7 / 箭头 2 对齐。
- [ ] **Step 2:** 构建通过。
- [ ] **Step 3:** Commit（若有改动）：`git commit -am "chore(icons): 补齐/对齐 mockup 图标"`

---

### Task 16: 阶段一人工核对（checkpoint）

- [ ] **Step 1:** `cd frontend && npm run build` 成功。
- [ ] **Step 2:** 本地起 `vite`，逐项核对（规格「验证」清单）：studio 默认视图四 tab/出图中转圈/GPU 日志配色；chat 裸 AI 消息/用户气泡/青色参数卡/HITL 两态；三抽屉 + FolderPicker；品牌字均显示 蜃景/MIRAGE。
- [ ] **Step 3:** 回归手测：出图/选图/出片/HITL resume/新建-切换-删除会话/工作目录切换。
- [ ] **Step 4:** 发现的视觉偏差就地修并补 commit。

---

## 阶段二 · 后端包与目录改名（单独提交）

### Task 17: git mv agent_lab → mirage + 更新 import

**Files:** `agent_lab/**` → `mirage/**`，全仓 `*.py` 的 import。

- [ ] **Step 1:** `git mv agent_lab mirage`。
- [ ] **Step 2:** 全量替换 import：`from agent_lab` → `from mirage`、`import agent_lab` → `import mirage`、字符串内 `agent_lab.` 模块路径同理。范围：`mirage/**`、`tests/**`、`scripts/**`、`colab/**`。先 `rg -l "agent_lab" --type py` 列清单再逐文件改（避免误伤 `agent_workspace`/`agentlab` 这类不同 token）。
- [ ] **Step 3:** Run `python -c "import mirage"` → 期望成功无 ImportError。
- [ ] **Step 4:** Commit：`git commit -am "refactor: Python 包 agent_lab → mirage(机械重命名, 仅路径)"`

### Task 18: 配置/容器/入口里的模块路径

**Files:** `langgraph.json`, `Dockerfile`, `docker-compose.yml`, `requirements*.txt/lock`, `seccomp-profile.json`, `.dockerignore`, `scripts/*`。

- [ ] **Step 1:** 改模块引用：如 `agent_lab.main_api:app` → `mirage.main_api:app`、`langgraph.json` graph 路径、Docker `COPY/CMD/WORKDIR`、`-m agent_lab...`。`rg -n "agent_lab" langgraph.json Dockerfile docker-compose.yml requirements* scripts` 逐处改。
- [ ] **Step 2:** Run `python -c "import mirage"`（+ 如可，`docker compose config` 校验 yaml）。
- [ ] **Step 3:** Commit：`git commit -am "chore: langgraph/Docker/scripts 模块路径 agent_lab → mirage"`

### Task 19: 默认工作目录 agent_workspace → mirage_workspace（带回退）

**Files:** 定义默认目录处（`rg -n "agent_workspace" --type py` 定位，多在 config / workspace 解析）+ 前端 `App.jsx` 显示用默认串。

- [ ] **Step 1:** 默认值改 `mirage_workspace`；加回退：解析默认目录时若 `~/mirage_workspace` 不存在而 `~/agent_workspace` 存在则用旧目录（避免老数据丢）。前端 `（默认 agent_workspace）` 提示文案 → `（默认 mirage_workspace）`。
- [ ] **Step 2:** Run `python -c "import mirage"` + 相关 workspace 解析的现有测试。
- [ ] **Step 3:** Commit：`git commit -am "chore: 默认工作目录 agent_workspace → mirage_workspace(带旧目录回退)"`

### Task 20: 后端改名验证（checkpoint）

- [ ] **Step 1:** `pytest -q`（或现有测试命令）→ 期望与改名前同样通过（改名不动行为）。失败逐个排查残留 `agent_lab` 路径。
- [ ] **Step 2:** `rg -i "agent_lab" --type py` → 期望无结果（除非注释里刻意保留历史说明）。

---

## 阶段三 · 文档（单独提交）

### Task 21: README/docs/comfyui 品牌字

**Files:** `README.md`, `docs/**`（不含本 spec/plan 与 `design-reference/*.html` 导出产物）, `comfyui_workflows/README.md`, `comfyui_workflows/*.json` 里的品牌串。

- [ ] **Step 1:** 品牌提及 AgentLab → 蜃景 / Mirage（按语境）；模块/命令路径 `agent_lab` → `mirage`。`design-reference/*.html` 是 mockup 导出产物，**保持原样**。
- [ ] **Step 2:** 全仓最终残留：`rg -i "agentlab|agent_lab"` → 仅剩刻意保留（`agentlab_*` localStorage key、本计划/规格里说明性引用、commit 历史）。
- [ ] **Step 3:** Commit：`git commit -am "docs: 品牌 AgentLab → 蜃景/Mirage"`

---

## Self-Review（写完已自查）

- **Spec coverage：** 规格 A–D 各组件 + 改名三层 + 验证，均有对应 Task（A→T1，B→T2-7，C→T8，D→T9-15，改名→T17-21，验证→T16/T20/T21）。
- **Placeholder：** 无 TBD；UI 任务以「改样式 + 构建 + commit」三步落地，exact 值在规格里引用（DRY，不重复抄）。
- **一致性：** key（script/cast/shots/export）、token、品牌约定（蜃景/MIRAGE/mirage）跨任务一致。
