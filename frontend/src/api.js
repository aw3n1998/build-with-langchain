/**
 * API 层 —— 封装所有后端接口调用。
 *
 * 后端端点从 localStorage 读取（key: agentlab_endpoint），
 * 默认 /api 走 Vite proxy → localhost:8000。
 *
 * 各 Agent 的 LLM 配置存于 localStorage key: agentlab_agent_configs，
 * 格式：{ supervisor: {model, api_base, api_key}, code: {...}, ... }
 */

function getBase() {
  // 三态统一(预留口子)：localStorage 自定义 > 后端 index.html 注入的 window.API_BASE(生产embed) > /api(开发走 Vite proxy)
  return localStorage.getItem('agentlab_endpoint') || (typeof window !== 'undefined' && window.API_BASE) || '/api'
}

function getAgentConfigs() {
  try {
    return JSON.parse(localStorage.getItem('agentlab_agent_configs') || 'null')
  } catch {
    return null
  }
}

// ── 应用状态（当前模型 / 模式）────────────────────────────────

export async function getStatus() {
  const r = await fetch(`${getBase()}/status`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// ── SSE 流式对话 ─────────────────────────────────────────────

/**
 * 异步生成器：逐 token yield SSE 消息对象。
 *
 * @param {string} sessionId  会话 ID
 * @param {string} content    用户消息
 * @param {object} options
 * @param {string} options.agent  路由目标（supervisor/code/file/batch/general）
 *
 * agent_configs 自动从 localStorage 读取，按每次请求随 body 发给后端。
 */
/** 复用的 SSE 解析：把 fetch Response 解析成事件对象的 async generator */
async function* parseSSE(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6))
        yield data
        if (data.type === 'done' || data.type === 'error') return
      } catch (err) {
        // 格式错误行：跳过，但记一笔便于排查后端 SSE 输出异常（之前是静默吞，没法 debug）
        console.warn('[SSE] 解析失败，已跳过该行:', line, err)
      }
    }
  }
}

// ── 对话改后台任务：提交即返回 job_id（回合在服务端独立完成，切会话/断网不丢）──
export async function chatSubmit(sessionId, content, { agent = 'supervisor', workspace = null } = {}) {
  const agentConfigs = getAgentConfigs()
  const body = { session_id: sessionId, content, agent }
  if (agentConfigs) body.agent_configs = agentConfigs
  if (workspace) body.workspace = workspace
  const r = await fetch(`${getBase()}/chat/submit`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()).job_id
}

export async function resumeSubmit(sessionId, agent, approved) {
  const r = await fetch(`${getBase()}/chat/resume_submit`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, agent, approved }),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()).job_id
}

/**
 * 任务状态 WebSocket：连接即收到所有未完任务快照，状态一变后端实时推送。
 * 断线自动重连。返回 close 函数。
 */
export function connectJobsWS(onMsg) {
  let ws = null
  let closed = false
  const url = (() => {
    const base = getBase()                       // '/api' 或 'http://host:8000/api'
    if (base.startsWith('http')) return base.replace(/^http/, 'ws') + '/ws/jobs'
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}${base}/ws/jobs`
  })()
  const connect = () => {
    if (closed) return
    try { ws = new WebSocket(url) } catch { setTimeout(connect, 3000); return }
    ws.onmessage = e => { try { onMsg(JSON.parse(e.data)) } catch {} }
    ws.onclose = () => { if (!closed) setTimeout(connect, 3000) }
    ws.onerror = () => { try { ws.close() } catch {} }
  }
  connect()
  return () => { closed = true; try { ws?.close() } catch {} }
}

// 停止生成：chat 回合可真取消；GPU 任务会返回 cancelled=false（不可中断）
export async function cancelJob(jobId) {
  const r = await fetch(`${getBase()}/pipeline/jobs/${jobId}/cancel`, { method: 'POST' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export async function* streamChat(sessionId, content, { agent = 'supervisor', workspace = null } = {}) {
  const agentConfigs = getAgentConfigs()
  const body = { session_id: sessionId, content, agent }
  if (agentConfigs) body.agent_configs = agentConfigs
  if (workspace) body.workspace = workspace

  const response = await fetch(`${getBase()}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  yield* parseSSE(response)
}

// ── 工作目录浏览 ─────────────────────────────────────────────
export async function fsList(path = '') {
  const r = await fetch(`${getBase()}/fs/list?path=${encodeURIComponent(path)}`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// ── GPU 长任务：提交即返回 job_id，再用 streamJobEvents 跟随 ─────
// 出图/出片改为后台单飞任务（不再占着连接，断线可重连续看）。
async function submitJob(path, params) {
  const r = await fetch(`${getBase()}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()).job_id
}

// params 需带 workspace（由调用方按当前会话传入）；返回 job_id
export async function pipelineGenerate(params) {
  return submitJob('/pipeline/generate', params)
}

/**
 * 跟随某个 GPU 任务的事件流（回放 + 实时），断线自动带 since 重连续看，
 * 直到收到 done/error。任务在后台独立运行，浏览器断开也不影响其完成。
 */
export async function* streamJobEvents(jobId) {
  let since = 0
  while (true) {
    let terminal = false
    let resp
    try {
      resp = await fetch(`${getBase()}/pipeline/jobs/${jobId}/events?since=${since}`)
    } catch {
      await new Promise(r => setTimeout(r, 1500))   // 连接失败，稍后重连
      continue
    }
    if (resp.status === 404) throw new Error('任务不存在或已过期')
    if (!resp.ok) { await new Promise(r => setTimeout(r, 1500)); continue }
    try {
      for await (const ev of parseSSE(resp)) {
        since += 1
        if (ev.type === 'done' || ev.type === 'error') { terminal = true; yield ev; return }
        yield ev
      }
    } catch {
      // 流中途断开：带 since 重连续看
    }
    if (terminal) return
    await new Promise(r => setTimeout(r, 1500))
  }
}

// ── 选定工作目录时立即初始化 .agent 结构 ─────────────────────
export async function initWorkspace(path) {
  const r = await fetch(`${getBase()}/workspace/init?path=${encodeURIComponent(path)}`, { method: 'POST' })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// ── 可用 Agent 列表（动态，注册即出现）────────────────────────
export async function getAgents() {
  const r = await fetch(`${getBase()}/agents`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// ── 出视频参数卡确认后出片：提交为后台任务，返回 job_id ────────
export async function pipelineRender(params) {
  return submitJob('/pipeline/render', params)
}

// ── 一键转规格（放大到 4K 等）：提交后台任务，返回 job_id；事件里 type==='video' 的 url 即高清版 ──
export async function pipelineUpscale(params) {
  return submitJob('/pipeline/upscale', params)
}

// ── 视频一键换脸：上传一张源脸 → 换到该成片里(产物独立新文件)。返回 job_id，用 streamJobEvents 跟随。
// ⚠️ 合规红线：仅用于你有权使用的脸(原创/AI 生成/本人授权);换可识别真人=deepfake,平台 ToS 与法律禁止。
export async function pipelineFaceswap(faceFile, { sceneId = '', kind = 'scene', projectId = '', workspace = null, sessionId = '' } = {}) {
  const form = new FormData()
  form.append('scene_id', sceneId)
  form.append('kind', kind)
  form.append('project_id', projectId)
  form.append('workspace', workspace || '')
  form.append('session_id', sessionId || '')
  form.append('file', faceFile)
  const r = await fetch(`${getBase()}/pipeline/faceswap`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()).job_id
}

// ── 制作面板：项目状态 + 一键批量出图 / 出片合成 ─────────────────
export async function getProject(projectId, workspace = null) {
  const q = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  const r = await fetch(`${getBase()}/pipeline/project/${projectId}${q}`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
export async function batchGenerate(params) { return submitJob('/pipeline/batch_generate', params) }
export async function batchFinish(params) { return submitJob('/pipeline/batch_finish', params) }
// 单个分镜独立出图 / 出片
export async function sceneGenerate(params) { return submitJob('/pipeline/scene_generate', params) }
export async function sceneRender(params) { return submitJob('/pipeline/scene_render', params) }
export async function sceneAppend(params) { return submitJob('/pipeline/scene_append', params) }
// 列出某项目在跑/排队的任务（刷新后面板重连用）
export async function listActiveJobs(projectId) {
  const r = await fetch(`${getBase()}/pipeline/jobs?project_id=${encodeURIComponent(projectId)}`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
// 删除产物（候选图 / 分镜成片 / 整集成片）
export async function deleteCandidate(assetId, workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/delete_candidate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asset_id: assetId, workspace }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
export async function deleteSceneVideo(sceneId, workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/delete_scene_video`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId, workspace }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
export async function sceneUndoAppend(sceneId, workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/scene_undo_append`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId, workspace }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
export async function deleteEpisode(projectId, workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/delete_episode`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, workspace }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// 小说 → 自动拆分镜（LLM 当导演一次拆 N 镜入库）
// 带上 Settings 里的导演模型(agent_configs)→ 让前端选 grok/OpenRouter 真去拆分镜(空=后端走 .env)
export async function autoStoryboard(projectId, novelText, scenes, replace, workspace = null) {
  const body = { project_id: projectId, novel_text: novelText, scenes, replace, workspace }
  const agentConfigs = getAgentConfigs()
  if (agentConfigs) body.agent_configs = agentConfigs
  const r = await fetch(`${getBase()}/pipeline/auto_storyboard`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
// 一键 AI 分析小说 → 自动填角色(+空 LoRA)/风格/分镜
// opts.targetSec 非空 → 后端按目标秒数自算分镜数(覆盖 scenes)；opts.coherence 控制少而长/快切
export async function autoFill(projectId, novelText, scenes, replace, workspace = null, opts = {}) {
  const body = { project_id: projectId, novel_text: novelText, scenes, replace, workspace }
  if (opts.targetSec != null) body.target_sec = opts.targetSec
  if (opts.coherence != null) body.coherence = opts.coherence
  const agentConfigs = getAgentConfigs()
  if (agentConfigs) body.agent_configs = agentConfigs   // 角色/风格/分镜 全部 AI 分析都走它(导演模型)
  const r = await fetch(`${getBase()}/pipeline/auto_fill`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// 自动选图（与手动 pipelineSelect 并存的双模式）：strategy=first/best。即时返回 {selected,skipped,empty}
export async function autoSelect(projectId, strategy = 'first', workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/auto_select`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, strategy, workspace }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// 一键全自动：小说 → ~目标时长成片（AI 按秒数自算镜数/段数；自动或手动选图）。返回 job_id，用 streamJobEvents 跟随。
// params: { project_id, novel_text, target_sec, coherence, select_mode:'auto'|'manual', select_strategy:'first'|'best', replace, lightning, model, size, workspace, session_id }
export async function oneClick(params) {
  const body = { ...params }
  const agentConfigs = getAgentConfigs()
  if (agentConfigs) body.agent_configs = agentConfigs
  return submitJob('/pipeline/one_click', body)
}

// PuLID 锁脸：给某角色上传 1 张参考脸 → 存盘并写入 characters.ref_image_path（出图时自动锁脸）
export async function uploadCharacterFace(charId, projectId, file, workspace = null) {
  const form = new FormData()
  form.append('char_id', charId)
  form.append('project_id', projectId)
  form.append('workspace', workspace || '')
  form.append('file', file)
  const r = await fetch(`${getBase()}/pipeline/character_face`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
// 可复用模板库（per-workspace）：action=list/add/delete；kind=style/motion/prompt
export async function templatesApi(action, fields = {}, workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/templates`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, workspace, ...fields }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
// 角色/声音圣经：action=list/add/update/delete
export async function characters(projectId, action, fields = {}, workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/characters`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, action, workspace, ...fields }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// 人物 LoRA 训练（界面框架；实际训练待 Colab 接入）
export async function loraCreate(projectId, name, triggerWord, charId, workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/lora_create`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, name, trigger_word: triggerWord, char_id: charId, workspace }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`); return r.json()
}
export async function loraAction(projectId, action, trainingId = null, workspace = null, extra = {}) {
  const r = await fetch(`${getBase()}/pipeline/lora_trainings`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, action, training_id: trainingId, workspace, ...extra }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`); return r.json()
}
export async function loraUploadImage(trainingId, file, workspace = null, characterId = '') {
  const fd = new FormData()
  fd.append('training_id', trainingId); fd.append('workspace', workspace || ''); fd.append('file', file)
  if (characterId) fd.append('character_id', characterId)   // 给了角色 → 后端按该角色「触发词,外貌」写同名 .txt caption
  const r = await fetch(`${getBase()}/pipeline/lora_upload_image`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error(`status ${r.status}`); return r.json()
}
// PuLID 单脸自举：上传 1 张参考脸（存 _ref/，不计入训练图数）
export async function loraUploadRef(trainingId, file, workspace = null) {
  const fd = new FormData()
  fd.append('training_id', trainingId); fd.append('workspace', workspace || ''); fd.append('file', file)
  const r = await fetch(`${getBase()}/pipeline/lora_upload_ref`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error(`status ${r.status}`); return r.json()
}

// 更新分镜提示词/旁白（AI 写的提示词可见可改）
export async function updateScenePrompts(sceneId, fields, workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/scene_prompts`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId, workspace, ...fields }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// AI 据画面 + 一句中文意图（可空），把动作拆成 N 段递进的英文运镜提示词（尾帧接续用）
export async function suggestSegmentPrompts(sceneId, segments, intent = '', workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/suggest_segment_prompts`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId, segments, intent, workspace }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()  // { scene_id, prompts: [...] }
}

// 据现有成片末帧推荐「下一段」运镜提示词（配了视觉模型则真看末帧图）。防抽卡。
export async function suggestContinuation(sceneId, lang = 'zh', workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/suggest_continuation`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId, lang, workspace }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()  // { scene_id, prompt, saw_frame }
}

// 已有分镜图直接上传当候选（跳过 GPU 生图）
export async function uploadCandidate(sceneId, file, workspace = null) {
  const form = new FormData()
  form.append('scene_id', sceneId)
  form.append('workspace', workspace || '')
  form.append('file', file)
  const r = await fetch(`${getBase()}/pipeline/upload_candidate`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// 上传一段视频 → 拼到该镜成片末尾 → 从其尾帧 AI 续写。返回 job_id，用 streamJobEvents 跟随。
// opts: { model, motionPrompt, size, count }（count=AI 续写段数，0=只拼接不续写）
export async function uploadContinueVideo(sceneId, file, opts = {}, workspace = null) {
  const { model = '', motionPrompt = '', size = '', count = 1 } = opts
  const form = new FormData()
  form.append('scene_id', sceneId)
  form.append('workspace', workspace || '')
  form.append('model', model)
  form.append('motion_prompt', motionPrompt)
  form.append('size', size)
  form.append('count', String(count))
  form.append('file', file)
  const r = await fetch(`${getBase()}/pipeline/upload_continue_video`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return (await r.json()).job_id
}

export async function listProjects(workspace = null) {
  const q = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  const r = await fetch(`${getBase()}/pipeline/projects${q}`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// ── 剧集（项目）管理 + 每集风格 + 分镜 增/删（面板自助，不绕 agent）──
async function _post(path, body) {
  const r = await fetch(`${getBase()}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
export const projectCreate = (title, workspace = null) => _post('/pipeline/project_create', { title, workspace })
export const projectRename = (projectId, title, workspace = null) => _post('/pipeline/project_rename', { project_id: projectId, title, workspace })
export const projectDelete = (projectId, workspace = null) => _post('/pipeline/project_delete', { project_id: projectId, workspace })
// fields 全空=只读返回风格；带字段=写入。返回 { project_id, style:{...} }
export const projectStyle = (projectId, fields = {}, workspace = null) => _post('/pipeline/project_style', { project_id: projectId, workspace, ...fields })
// 列 ComfyUI 实际可用 LoRA + 当前工作目录(对话/全局)出图配置。返回 { loras:[...], model:{trigger_word,flux_lora,negative_prompt} }
export async function listLoras(workspace = null) {
  const q = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  const r = await fetch(`${getBase()}/pipeline/loras${q}`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
export const sceneAdd = (projectId, fields = {}, workspace = null) => _post('/pipeline/scene_add', { project_id: projectId, workspace, ...fields })
export const sceneDelete = (sceneId, workspace = null) => _post('/pipeline/scene_delete', { scene_id: sceneId, workspace })

// ── 可用视频模型 + 各自参数 schema（注册即出现）──────────────
export async function getVideoProviders() {
  const r = await fetch(`${getBase()}/video/providers`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// ── 可用出图模型 + 各自参数 schema（公开模型名；ComfyUI 透明顶替后端，不作为单独条目出现）──
export async function getImageProviders() {
  const r = await fetch(`${getBase()}/image/providers`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// ── 上下文窗口用量（真实 token / 触发压缩阈值）────────────────
export async function getContextUsage(sessionId) {
  const r = await fetch(`${getBase()}/context/${sessionId}`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// 手动触发真实上下文压缩
export async function compactContext(sessionId) {
  const r = await fetch(`${getBase()}/context/${sessionId}/compact`, { method: 'POST' })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// ── 点击候选图=选图 ──────────────────────────────────────────
export async function pipelineSelect(sceneId, assetId, workspace = null) {
  const r = await fetch(`${getBase()}/pipeline/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId, asset_id: assetId, workspace }),
  })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// 把后端相对 URL（/api/file?...）补成走当前 base 的可访问地址
export function fileUrl(relUrl) {
  if (!relUrl) return relUrl
  const base = getBase()
  // 后端给的是 /api/file?path=...；base 默认 /api → 去掉重复前缀
  if (base === '/api') return relUrl
  return relUrl.replace(/^\/api/, base)
}

/**
 * 恢复 HITL 暂停的对话（SSE 流式）。
 *
 * @param {string} sessionId   会话 ID（与原 streamChat 一致）
 * @param {string} agent       agent 名称（目前仅 supervisor 支持）
 * @param {boolean} approved   true=继续执行，false=取消
 */
export async function* resumeChat(sessionId, agent, approved) {
  const response = await fetch(`${getBase()}/chat/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, agent, approved }),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  yield* parseSSE(response)
}

// ── 历史会话管理 ─────────────────────────────────────────────

export async function getHistory() {
  const r = await fetch(`${getBase()}/history`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

export async function getSessionHistory(sessionId) {
  const r = await fetch(`${getBase()}/history/${sessionId}`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

export async function deleteSession(sessionId) {
  const r = await fetch(`${getBase()}/history/${sessionId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}
