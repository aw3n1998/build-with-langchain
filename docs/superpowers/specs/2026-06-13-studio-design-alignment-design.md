# 「蜃景 / Mirage」全组件视觉对齐 + 品牌改名 — 设计规格

日期：2026-06-13
状态：待评审

## 目标

两件事，一起做：

1. **视觉对齐**：把 `frontend/` 现有 React 组件按 **短剧工作台 mockup** 逐像素对齐。
2. **品牌改名**：把项目名从 **AgentLab** 彻底改成 **Mirage / 蜃景**（前端显示 + 后端包与目录 + 文档）。

- **参考稿**：`frontend/design-reference/new_template_extracted.html`（用户最新导出，与既有 `studio_template_extracted.html` 内容一致，仅导出外壳不同）。注意：mockup 里仍写 `AgentLab` / `AGENTLAB`，实现时一律换成 `蜃景` / `MIRAGE`（见下「品牌改名」）。
- **已对齐的参照组件**：`ProjectSidebar.jsx`（上一提交已逐像素对齐，作为「对齐到位」的标杆）。

## 品牌改名 Mirage / 蜃景

中文品牌字确认为 **蜃景**（shèn jǐng，海市蜃楼/蜃景）。命名约定：

| 场景 | 用法 |
|---|---|
| 中文 UI 品牌字 | **蜃景**（聊天侧栏/顶栏原 `AgentLab` → `蜃景`；`给 AgentLab 发消息` → `给 蜃景 发消息`） |
| 拉丁大写标签 | **MIRAGE**（AI 回复上方的 mono 标签 `AGENTLAB` → `MIRAGE`） |
| 代码/标识符/包名/标题 | `mirage` / `Mirage`（Python 包、`package.json` name、页面 `<title>`、`langgraph.json` 等） |
| studio 侧栏功能标签 | **保留「短剧工作台」**不动（它是功能描述，不是品牌字） |
| localStorage key | **不动**（`agentlab_*` 保持原样：内部不可见标识，不做迁移，避免老用户丢会话/设置） |

改名分层（已与用户确认的范围）：

- **前端显示文案**：并入下面各组件的视觉对齐一起做（同一处既改样式又改字）。
- **后端包与目录**：Python 包 `agent_lab/` → `mirage/`；同步更新所有 `import agent_lab` / `from agent_lab...`、`langgraph.json`、`Dockerfile`、`docker-compose.yml`、`scripts/`、`tests/`。默认工作目录 `agent_workspace` → `mirage_workspace`，**加回退**：若 `~/mirage_workspace` 不存在而 `~/agent_workspace` 存在则沿用旧目录，避免老数据找不到。
- **文档与 README**：`README.md`、`docs/`、`comfyui_workflows/` 里的品牌提及。

> 注：后端包重命名是大面积机械改动（330+ 处 import），单独成阶段并 `python -c "import mirage"` / 跑测试验证。前端改名跟视觉对齐合并。

## 不在范围内（硬约束）

- **视觉对齐只改样式，不动功能逻辑。** 所有 props、回调、状态机、API 调用、流式消费、HITL resume、出图/出片/选图链路、localStorage 持久化、WebSocket 任务状态，全部保持不变。
- **改名只改名字字符串与包/目录路径，不改行为。** localStorage key 保持 `agentlab_*` 不变。
- 不做无关重构、不改 `api.js` 行为逻辑（仅其中的品牌显示字/默认目录名按约定改）。
- 不引入新依赖。沿用现有「inline style + CSS 变量 token」写法（与 mockup 和 ProjectSidebar 一致），不改成 Tailwind 类。

## 设计 token（已就位，无需改）

`index.css` 现有 token 与 mockup 完全一致：

| token | 值 |
|---|---|
| `--bg` | `#0d0d0d` |
| `--card` | `#161616` |
| `--border` | `rgba(255,255,255,0.07)` |
| `--border-strong` | `rgba(255,255,255,0.13)` |
| `--text` | `rgba(255,255,255,0.87)` |
| `--text-sec` | `rgba(255,255,255,0.52)` |
| `--text-muted` | `rgba(255,255,255,0.30)` |
| `--text-dim` | `rgba(255,255,255,0.18)` |
| `--accent` | `#6366f1` |
| `--accent-hover` | `#5254cc` |

mockup 额外用到的强调色（按需在组件内联使用，不必新增 token）：
青 `#00bdb0`（出图/出片参数卡、③一键出片）、青亮 `#5fe8de`/`#5fe8de`、绿 `#34d399`、紫 `#c084fc`、黄 `#eab308`、红 `#f87171`、暖橙 `#ffb454`、淡紫文字 `#a5a8ff`、代码绿 `#86efac`。

圆角约定：按钮 6–8、图标方钮 7、大按钮 8、卡片 12、消息气泡 `14 14 4 14`、候选图 9。

## 已确认的判断项（评审中拍板）

1. **AI 助手消息去卡片框** —— `AssistantMessage` 不再包 `#161616` 卡片，改为「裸」渲染：紫色 `MIRAGE` 标签（`#6366f1`，SF Mono，`10px/700/letter-spacing:1px`）+ 正文（`13.5px/line-height:1.65`）直接踩 `#0d0d0d` 背景；工具步骤盒、候选图墙、RAG 标签、快捷回复作为子元素跟在下面。
2. **InterruptCard 简洁化 + 保留已决策反馈** —— pending 态用 mockup 中性卡（`border rgba(255,255,255,0.13)`、`bg #161616`、`radius 12`、`padding 15/17`）+ 绿「确认执行」(`#34d399`/`#04201a`) / 红「取消」(`border rgba(239,68,68,0.4)`,`bg rgba(239,68,68,0.1)`,`#f87171`)；去掉 HITL 大写标签与黄/警告三态外框；**保留** resolved 后的「已确认执行 / 已取消」状态行。

---

## 逐组件规格

### A. 全局 / 共享

**`index.css`**
- 新增 keyframes：
  - `@keyframes al-spin { to { transform: rotate(360deg); } }`（出图中转圈）
  - `@keyframes al-glow { 0%,100%{box-shadow:0 0 0 0 rgba(52,211,153,0.5);} 50%{box-shadow:0 0 0 5px rgba(52,211,153,0);} }`（会话进行中绿点呼吸）
- 现有 `blink`、滚动条样式保留。

### B. 聊天消息（`MessageBubble.jsx`）

**`UserMessage`**：右对齐纯文字 → 靛蓝气泡。
`align-self:flex-end; max-width:72%; background:rgba(99,102,241,0.14); border:1px solid rgba(99,102,241,0.25); border-radius:14px 14px 4px 14px; padding:11px 15px; font-size:13.5px; line-height:1.55`。保留 `white-space:pre-wrap`。

**`AssistantMessage`**（判断项 1）：去掉外层 `var(--card)` 卡片。
- `MIRAGE` 标签（原 `AGENTLAB` 文案改成 `MIRAGE`）：`#6366f1`，`font-family:'SF Mono',ui-monospace,monospace`，`font-size:10px; font-weight:700; letter-spacing:1px; margin-bottom:9px`。
- 正文容器仍用 `.prose-content`（Markdown 渲染不变），保证 `font-size:13.5px; line-height:1.65`。
- RAG 来源标签：靛蓝 pill —— `background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.25); color:#a5a8ff; SF Mono; font-size:10.5px; padding:3px 8px; border-radius:5px`；序号前缀 `#01` 形式。去掉「顶部分隔线 + 灰底」旧样式。
- MSG_SPLIT 快捷回复（纯文字类）：mockup 中性灰按钮 `height:28px; padding:0 12px; border-radius:8px; border rgba(255,255,255,0.13); bg rgba(255,255,255,0.04); color rgba(255,255,255,0.87); font 12px`，hover `bg rgba(255,255,255,0.08)`。
- `PcActionButton` 的语义色（add=蓝、含 userInput=紫 等）保留逻辑；仅把「纯快捷回复」对齐到中性灰。

**`ToolSteps`**：中性灰盒 → 靛蓝盒。
外框 `border:1px solid rgba(99,102,241,0.2); background:rgba(99,102,241,0.06); border-radius:10px; padding:12px 14px`；行 `font-size:12px; gap:7px`，状态符 `✓`=`#34d399`，名称色 `rgba(255,255,255,0.52)`。`s.result` 展开块沿用现有逻辑，配色随盒调和。

**`ImageWall`**：逻辑（放大灯箱 / 选图回调 / 禁用态）全部不动；样式对齐 —— 瓦片 `border-radius:9px; aspect-ratio:3/4`，选中 `2px solid #34d399`，右上「选中」标签 `padding:2px 7px; border-radius:5px; background:#34d399; color:#04201a; font-size:9.5px; font-weight:700`。栅格保持 `repeat(auto-fill,minmax(...))` 自适应（聊天区窄，沿用现值即可）。

**`ParamCard`（param_form）** + **`VideoParamCard`（video_param_form）**：靛蓝主题 → 青色主题。
- 外框 `border:1px solid rgba(0,189,176,0.3); background:rgba(0,189,176,0.05); border-radius:12px; padding:15px 17px`。
- 标题：去掉大写「出图参数 · 确认后生成」，改 mockup 形式 —— 图标 `stroke #00bdb0` + 标题文字 `出图参数卡 param_form` / `出视频参数卡 video_param_form`，`color:#5fe8de; font-size:12.5px; font-weight:600`（非大写）。video 卡右侧保留「预计 ≈ …s」`#5fe8de`。
- 内部 input/select/textarea：`border:1px solid rgba(0,189,176,0.25)`，其余沿用 `inputStyle`。
- 主按钮「出图 / 出视频」：`background:#00bdb0; color:#04201e; font-weight:600`，hover `opacity:.88`。
- 字段、校验、提交禁用（`submitted`/`stale`）逻辑不变。

**`InterruptCard`**（判断项 2）：见上「已确认的判断项 2」。`onResume(true/false)` 调用不变；保留 `resolved` 三态判断，但 pending 外观中性化、resolved 仍显示状态行。

### C. 短剧制作面板（`ProductionPanel` in `MessageBubble.jsx`）— 最大块

> 同一组件三处复用：studio 主视图（App.jsx）、聊天 `production` 消息卡、底部抽屉。对齐以 studio 主视图为准。

- **外层包裹**：去掉现有靛蓝卡（`border rgba(99,102,241,0.3); bg rgba(99,102,241,0.05)`），改为「裸」布局，由所在容器留白；内部各区块用 `#161616` 子卡（`border:1px solid rgba(255,255,255,0.07); border-radius:12px`）。
- **meta 头**：标题 + 彩色统计 —— `总数`(白) · `已出图 #eab308` · `已选 #c084fc` · `已出片 #34d399`，`font-size:12`；右侧刷新按钮 `Icon.Refresh`，方钮 30×30 `border-radius:7`。
- **Tab 栏**：`display:flex; gap:26px; border-bottom:1px solid rgba(255,255,255,0.07)`；每个 tab `padding-bottom:11px; margin-bottom:-1px`，active `border-bottom:2px solid #6366f1; color rgba(255,255,255,0.87); font-weight:650`，非 active `color rgba(255,255,255,0.52)`；图标 `opacity` 1/0.7。四个 tab：脚本 / 角色 & LoRA / 分镜制作 / 导出（保留现有 key：script/cast/shots/export）。
- **分镜卡（scene cards）**：`#161616` 卡；状态徽章 —— 已出片 `bg rgba(52,211,153,0.12) border rgba(52,211,153,0.35) #34d399`、待选图 `紫 #c084fc`、出图中 `黄 #eab308` + `al-spin` 转圈 + 「已运行 Ns」、待出图 `灰`。徽章 `height:22px; padding:0 9px; border-radius:6px; font-size:11px`，圆点 `5×5`。
- **全局控制条**：`① 一键全部出图` 靛蓝实心 `#6366f1`；`③ 一键出片并合成` 青色实心 `#00bdb0/#04201e`；尺寸/张数/模型/段数 select 沿用 `inputStyle`；预计秒数 `#5fe8de`。「更多参数」折叠箭头 `al`-style 旋转沿用现有交互。
- **候选图墙 / 提示词编辑器**：与 B 段 `ImageWall` 同款瓦片样式；提示词编辑器折叠区 `bg rgba(99,102,241,0.06) border rgba(99,102,241,0.2)`。
- **GPU 实时日志**：底部条 `background:#0a0a0a`，可折叠，标题行 `SF Mono 11px`，状态 `● 出图中 Ns` `#eab308`；日志行配色按级别 —— info `#34d399`、tool `#6cb6ff`、error `#f87171`、warn `#eab308`，`font-family:'SF Mono'; font-size:11px; line-height:1.7`。滚动/尾部 N 条逻辑不变。
- 共享样式常量按需调整：`panelBtn`（主操作）、`miniAct`（出图紫/出片青）、`inputStyle`、`miniBtn` —— 仅调色与圆角，签名不变。

### D. 其余组件

**`TopBar.jsx`**：品牌字 `AgentLab` → `蜃景`；logo 方块 `border-radius:6 → 7` + 用 `Icon.Clapper`（与侧栏统一）；高度 44；模型名 `SF Mono`；Knowledge Base 按钮内含绿点 + 计数徽章（`142` 形式，值来自现有 `ragStatus.chunk_count`）`font-size:9.5px; padding:1px 5px; border-radius:4px; bg rgba(255,255,255,0.1)`；图标方钮 base `bg rgba(255,255,255,0.04)`。active（KB/设置打开）态靛蓝高亮（`border rgba(99,102,241,0.5); bg rgba(99,102,241,0.15); #a5a8ff`）。

**`HistorySidebar.jsx`**：品牌字 `AgentLab` → `蜃景`；logo → `Icon.Clapper` 嵌 22×22 渐变方块；背景改纯 `#0d0d0d`（去 `rgba(13,13,13,0.95)` + backdrop-blur）；会话条 48px，进行中绿点 `7×7` 用 `al-glow`；New Chat 虚线按钮 `height:34; border:1px dashed rgba(255,255,255,0.2)`，hover `border rgba(99,102,241,0.6); #a5a8ff`；会话计数/时间 `N 条 · MM/DD HH:mm`。删除按钮 hover 显隐逻辑保留。（「History Threads」分组标签：mockup 无 → 去掉。）

**`InputBar.jsx`**：agent pill 按钮 `border-radius:6 → 13`（全圆 pill）、`height:24 → 25`、`padding:0 9px`、`font 11px`；think 按钮 `border-radius:6 → 7`、`height 25`；中间分隔 `width:1px;height:18px;bg rgba(255,255,255,0.1)`（已有）；命令提示行 `font-family:'SF Mono'`；占位符与底部提示用中文（`给 蜃景 发消息…  Enter 发送 · Shift+Enter 换行`）；发送按钮 `#6366f1/#fff; height:30; padding:0 18; radius:8`，hover `#5254cc`。active pill 配色 `border rgba(99,102,241,0.5); bg rgba(99,102,241,0.15); #a5a8ff`，非 active `border rgba(255,255,255,0.13); bg rgba(255,255,255,0.04); rgba(255,255,255,0.52)`。slash 菜单等增强逻辑保留。

**`SettingsPanel.jsx`**：抽屉宽 `360 → min(420px,92vw)`；头部 `齿轮图标 + Settings`；扁平化为 mockup 结构 —— Backend Endpoint 输入（值绿 `#86efac` SF Mono）；`Supervisor · 对话/导演模型` 区块（`#161616` 内卡）含预设按钮行（DS Chat / DS R1 / GPT mini / GPT-4o，active 靛蓝）+ Model Name / API Base URL / API Key（带眼睛切换按钮）；底部 `Reset all`（中性）/`Save changes`（靛蓝）等宽两按钮。保留现有保存/读取 localStorage 与 `onSaved` 逻辑、各 agent 配置项数据。（注：若现有功能字段多于 mockup，保留字段、套用 mockup 视觉，不删功能。）

**`KnowledgePanel.jsx`**：抽屉宽 320；顶部 `Upload File / Paste Text` 等宽切换（active 靛蓝）；Project ID 输入；上传区 `border:1.5px dashed rgba(255,255,255,0.18); border-radius:10px; padding:32px 16px; text-align:center` + 上传图标 + 中文「拖拽上传 PDF / TXT / DOCX」。上传/粘贴/状态反馈逻辑不变。

**`FolderPicker.jsx`**：遮罩 `rgba(0,0,0,0.55) + backdrop-filter:blur(2px)`；卡 `width:560; bg #161616; border rgba(255,255,255,0.13); radius:14; box-shadow:0 20px 60px rgba(0,0,0,0.6)`；路径输入 SF Mono；目录列表项 38px + `/` 前缀灰 + hover；底部「用默认目录」(中性) /「选定此目录」(靛蓝)。浏览/选定逻辑不变。

**`App.jsx`**（含内联的 studio 顶栏与聊天 ContextBar）：
- studio 顶栏：`min-height:56; padding:0 20px; gap:12`；剧集名 `15px/600`；改名/删除方钮 32×32 `radius:8`（删除红色调）；`工作目录` 中性按钮；右侧 `AI 助手` 主按钮 `#6366f1/#fff; radius:8`，hover `#5254cc`。
- 聊天底部 ContextBar：`工作台` 按钮（靛蓝调）、`工作目录：` + 绿色等宽路径（`rgba(134,239,172,0.9)` SF Mono）、`更改`、`制作面板`（有项目时靛蓝点亮）、上下文进度条（`ContextBar` 子组件，配色对齐 `#6366f1`/黄/红阈值，保留压缩逻辑）。
- 两套侧栏切换、抽屉、面板开合逻辑全部不变。

**`Sidebar.jsx`**：删除。已确认全仓库无 import（仅自身定义），是早期 Tailwind 版遗留。

**`icons.jsx`**：按需补齐 mockup 用到但缺失的图标（核对 `Clapper/Plus/Chat/Pencil/Trash/Folder/Script/Users/Layers/Download/Refresh/Wand/Settings/Eye/Mic/...`）；已有图标 viewBox/stroke 对齐 mockup（`stroke-width:1.7` 主、`2` 箭头）。

## 验证

- 前端：`npm run build`（或 `vite build`）通过，无新增告警/报错。
- 后端改名：`python -c "import mirage"` 通过；`langgraph.json` 指向的图能加载；现有 `tests/` 全跑通（改名只动路径不动行为，测试应不变绿）。全仓库 `grep -ri "agent_lab\|agentlab\|AgentLab"` 仅剩刻意保留处（localStorage `agentlab_*` key、历史 changelog/commit 不动）。
- 本地 `vite` 起后人工核对：studio 默认视图、四个 tab、出图中转圈、GPU 日志配色；切到 chat 视图核对裸 AI 消息、用户气泡、青色参数卡、HITL 卡 pending/已决策两态；三个抽屉 + FolderPicker 弹窗；品牌字均显示「蜃景 / MIRAGE」。
- 回归：出图/选图/出片/HITL resume/新建-切换-删除会话/工作目录切换 等功能路径手测无回归。

## 实施顺序（建议）

**阶段一 · 视觉对齐 + 前端改名**（同一批 commit）
1. `index.css`（keyframes）+ 删 `Sidebar.jsx`（低风险打底）。
2. `MessageBubble.jsx` 聊天卡：UserMessage / AssistantMessage（标签 `MIRAGE`）/ ToolSteps / ImageWall / ParamCard / VideoParamCard / InterruptCard。
3. `MessageBubble.jsx` 的 `ProductionPanel`（最大块）。
4. `TopBar` / `HistorySidebar` / `InputBar`（品牌字 → 蜃景）。
5. `SettingsPanel` / `KnowledgePanel` / `FolderPicker`。
6. `App.jsx` 内联顶栏与 ContextBar；`icons.jsx` 补齐；`index.html` `<title>`、`package.json` name、`vite.config.js` 里的品牌字。
7. 前端构建 + 人工核对。

**阶段二 · 后端包与目录改名**（单独 commit，机械改 + 验证）
8. `git mv agent_lab mirage`；全量更新 `import agent_lab`/`from agent_lab` → `mirage`。
9. `langgraph.json`、`Dockerfile`、`docker-compose.yml`、`requirements*`、`scripts/`、`tests/` 中的模块路径与品牌字。
10. 默认工作目录 `agent_workspace` → `mirage_workspace`（带旧目录回退）。
11. `python -c "import mirage"` + 跑测试验证。

**阶段三 · 文档**（单独 commit）
12. `README.md`、`docs/`、`comfyui_workflows/README.md` 等品牌提及；`design-reference/*.html` 是导出产物，保持原样不动。
