# LoRA 修复 + NSFW Master FLUX — 设计规格（子项目 C+D）

日期：2026-06-14
状态：已确认（用户拍板：LoRA 名称内联编辑、NSFW 默认 `lodestones/Chroma`、可配置检查点槽位）
所属：短剧工作台演进 6 项需求的第二个子项目。前序 A+B（去 RAG + 浮动小助手）已完成。

## 目标

1. **C — LoRA 修复**：(a) 新建/管理人物 LoRA 时能填**名称 + 触发词**（现在写死「新角色LoRA」、触发词空，且名称不可改）；(b) **删除可用且删干净**（现在只删 DB 行、磁盘参考图残留，且无确认）。
2. **D — NSFW Master FLUX**：新增一个**可配置检查点**的出图模型「NSFW Master FLUX」，A100 推荐 `lodestones/Chroma`；不做内容过滤；人物 LoRA 照常叠加。

---

## C — LoRA 修复

### 后端（`mirage/app/...`）
- `store.update_lora_training`：可更新字段集合加入 `name`（现为 `status/output_path/message/image_count/steps/trigger_word/char_id`，缺 `name` → 改不了名）。
- `routes.pipeline_lora_trainings`：`LoraActionRequest` 加可选 `name`/`trigger_word`；新增 `action == "update"` 分支 → `store.update_lora_training(training_id, name=..., trigger_word=...)`，返回更新后的列表。（沿用现有 `_ws_store(req.workspace)` 工作目录作用域。）
- `store.delete_lora_training`：删 DB 行后**同时删磁盘** `lora_train/{tid}` 目录（用 `_lora_dir` 同源路径；`shutil.rmtree(..., ignore_errors=True)`）。把磁盘清理放在 store 还是 route 层均可——放 route（`pipeline_lora_trainings` 的 delete 分支）更稳（store 不碰文件系统、保持纯数据层）。**采用 route 层清理**：delete 分支先 `delete_lora_training` 再 rmtree `_lora_dir(tid)`。

### 前端（`MessageBubble.jsx` cast tab + `api.js`）
- LoRA 卡片：`{t.name}` 的只读 `<strong>` → **可内联编辑的 name 输入**（`defaultValue={t.name}`，`onBlur` 改了才存）+ 新增**触发词输入**（`defaultValue={t.trigger_word}`，onBlur 存），与角色卡片同款交互。保存调用新增 `loraOp('update', t.id, {name, trigger_word})`。
- `loraOp`/`loraAction`：扩展支持 `update` 动作并透传 `name`/`trigger_word`（api.js `loraAction` 加可选字段）。
- 删除按钮：点前 `await dialog.confirm('删除这个 LoRA 训练？', { message:'参考图也会一并删除，不可恢复。', danger:true, confirmText:'删除' })`，确认后才 `loraOp('delete', t.id)`。
- `newLora` 不变（建默认名），建完直接在卡片内联改名即可。

### 验证（实机，本地有后端可测）
- 建 LoRA → 改名 + 填触发词（onBlur）→ 刷新仍在 ✓；传图 → 删除（确认框）→ 列表消失 + 磁盘 `lora_train/{tid}` 目录已清 ✓。

---

## D — NSFW Master FLUX

> 关键发现：`gpu_client.generate_candidates` **已支持 `base` 检查点覆盖**（L325/342，远程命令已带 `--base`），故无需改 gpu_client / 远程脚本，只加一个 provider + 配置。

### 后端
- `config.py` + `.env.example`：新增 `GPU_FLUX_NSFW_BASE`（NSFW 底模检查点路径/HF repo，默认空）+ 可选 `GPU_FLUX_NSFW_LORA`。注释写清推荐：
  - **首选 `lodestones/Chroma`**（开放无审查 FLUX 系，A100 友好；注意架构与 FLUX-dev 有别，现有 FLUX-dev 人物 LoRA 可能要按 Chroma 重训）。
  - **要现有人物 LoRA 直接生效** → 指向 FLUX.1-dev 系无审查合并检查点。
- 新增 `image_providers/nsfw_flux.py`：`class NsfwFluxImageProvider(FluxSshImageProvider)`，覆盖 `name="nsfw-flux"`、`display_name="NSFW Master FLUX"`；`generate()` 透传 `base=settings.GPU_FLUX_NSFW_BASE`（LoRA 仍取 `params.flux_lora`，未设时回退 `GPU_FLUX_NSFW_LORA`）。`param_schema` 继承 FLUX 那套。
- `image_providers/__init__.py`：**仅当 `settings.GPU_FLUX_NSFW_BASE` 非空才注册**（没配就不出现在下拉，避免选了报错）。
- 不加任何内容过滤（FLUX/Chroma 本就无内置审查；保持不加）。

### 前端
- 零改动：`getImageProviders()` 自动把「NSFW Master FLUX」加进 ProductionPanel 的「出图模型」下拉；选它即用 NSFW 底模出图，人物 LoRA 照常注入。

### 验证（无 GPU，构建+接线层面）
- `import mirage` + provider 注册逻辑：设了 `GPU_FLUX_NSFW_BASE` 时 `image_provider_registry.has('nsfw-flux')` 为真、`list_providers()` 含它；未设时不含。`/api`（出图模型列表）相应返回。实际出图需用户接好 A100 + 下好 Chroma 后自测。

---

## 非目标
- 不在本子项目做 E（一键分析小说）/ F（技能模板库）。
- D 不替用户下载/部署模型；不验证 Chroma 在远程脚本里的实际加载（远程侧由用户自测，槽位与接线已就绪）。

## 实施顺序
1. **C 后端**：store `update_lora_training` 加 name；routes 加 `update` 动作 + delete 清磁盘。验证 import。
2. **C 前端**：LoRA 卡片名称/触发词内联编辑 + 删除确认；api.js `loraAction` 支持 update。build。
3. **C 实机测**：建/改名/传图/删 全流程。
4. **D 后端**：config + `.env.example` NSFW 变量（Chroma 推荐注释）+ `nsfw_flux.py` provider + 条件注册。验证 import + 注册逻辑。
5. 收尾：构建 + 提交。
