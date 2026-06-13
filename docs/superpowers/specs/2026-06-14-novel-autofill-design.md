# 一键 AI 分析小说 → 自动填充全部 — 设计规格（子项目 E）

日期：2026-06-14
状态：已确认（用户拍板：新增大按钮+保留只拆分镜；「替换现有」开关每次自选 + 有内容弹确认）
所属：短剧工作台演进第三个子项目。前序 A+B、C+D 已完成。

## 目标
脚本 tab 一个按钮，把粘进来的小说/剧情交给 AI 一条龙分析并入库：**角色（含外貌+音色）→ 每角色建空 LoRA → 本集统一风格 → 分镜（标题/出图词/运镜/旁白/字幕/对口型/出场角色）**。跑完整个制作面板都填好。

## 背景
- 现有 `breakdown_storyboard(novel, n, style, characters)` 只**消费**角色/风格产分镜，不创建它们（`storyboard.py`）。
- store 已有：`add_character/list_characters/delete_character`、`get/update_project_style`、`add_scene/set_scene_lipsync/set_scene_voice`、`add_lora_training/list_lora_trainings`、`set_project_novel`。
- 现有路由 `/pipeline/auto_storyboard`（只拆分镜，保留）。

## 设计

### 后端 `mirage/app/pipeline/novel_analyze.py`（新增，照 storyboard.py 的 LLM+健壮JSON+保底 模式）
- `async extract_characters(novel_text, max_n=6) -> list[{name, appearance, voice}]`
  - system：抽主要角色（≤max_n）；每个写**明确年龄数字**+外貌特征（发型/脸型/穿着/标志）；从给定 edge-tts 音色表里**选一个最贴合的 voice id**（性别/气质匹配）。
  - 健壮 JSON（取第一个数组）+ 失败返回 `[]`。内置精简 VOICES（与前端一致的常用中/英文音色 id+标签）喂给 LLM。
- `async generate_style(novel_text) -> {style_prompt, negative_prompt, default_size}`
  - system：据题材/氛围定**全集统一画风**（写实/电影感/色调/景深/光线…一句话风格词）+ 负向词 + 默认尺寸（竖屏默认 `768x1024`）。
  - 失败返回稳妥默认 `{style_prompt:"电影感，写实，浅景深", negative_prompt:"低质,模糊,多手指", default_size:"768x1024"}`。

### 后端路由 `/pipeline/auto_fill`（新增）
`AutoFillRequest{ workspace, project_id, novel_text, scenes=8, replace=False }`。流程：
1. `chars = await extract_characters(novel)`。
2. `replace` 时先清空现有 characters（`delete_character` 逐个）；style 与 scenes 同理在各自步骤清。
3. 逐个 `add_character(pid, name, appearance, voice)`；并**按名去重建空 LoRA**：`existing = {t.name for t in list_lora_trainings(pid)}`，新角色名不在其中才 `add_lora_training(pid, name, "", char_id)`（**不删旧 LoRA**，保住已传参考图）。
4. `style = await generate_style(novel)` → `update_project_style(pid, **style)`。
5. `scenes = await breakdown_storyboard(novel, n, style=style.style_prompt, characters=list_characters(pid))`；`replace` 时先清空现有分镜；`add_scene` 循环（含 lipsync/音色，逻辑与 auto_storyboard 一致）。`set_project_novel`。
6. 返回 `{project_id, characters, style, scenes_count, lora_count}`。
- 沿用 `_ws_store(req.workspace)` 工作目录作用域；`n` 上限保护（≤40）；全程保底容错（任一步 LLM 失败走该步 fallback，不中断整体）。

### 前端（`MessageBubble.jsx` 脚本 tab + `api.js`）
- 脚本 tab 的小说区：保留现有「拆成 N 镜 + 开始拆分镜 + 替换现有分镜」。**新增**一个醒目主按钮「🪄 一键 AI 分析填充（角色+风格+LoRA+分镜）」+ 旁边「替换现有」复选框（每次自选）。
- 点按钮：若勾了替换且项目已有角色/风格/分镜 → 先 `dialog.confirm`（红色「将替换现有角色/风格/分镜，继续？」）。确认后调 `autoFill(pid, novel, n, replace, ws)`，跑完 `await load()` 刷新整面板，并 `setProgress` 汇报「已填：N 角色 / 风格 / M 分镜 / K LoRA」。
- `api.js` 加 `autoFill(projectId, novelText, scenes, replace, workspace)` → POST `/pipeline/auto_fill`。

## 非目标
- 不做 F（技能/模板库）。
- 不实跑 LLM 验证（占位 key）；用 mock LLM 输出验证编排/入库与 JSON 健壮解析。

## 验证
- `import mirage` + 路由可加载。
- mock `ai_service._llm.ainvoke` 返回样例 JSON → `extract_characters`/`generate_style` 解析正确；调 `/pipeline/auto_fill`（直接调 handler）→ store 里出现对应 角色/风格/分镜/LoRA；`replace` 行为正确；LoRA 去重不重复建。
- 前端 `npm run build` 通过。

## 实施顺序
1. 后端 `novel_analyze.py`（extract_characters + generate_style）。
2. 后端 `/pipeline/auto_fill` 路由（编排）。
3. mock-LLM 验证编排/解析/入库。
4. 前端按钮 + 替换开关 + 确认 + `api.autoFill`；build。
5. 提交。
