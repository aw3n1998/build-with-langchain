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
  return localStorage.getItem('agentlab_endpoint') || '/api'
}

function getAgentConfigs() {
  try {
    return JSON.parse(localStorage.getItem('agentlab_agent_configs') || 'null')
  } catch {
    return null
  }
}

// ── RAG 状态 ─────────────────────────────────────────────────

export async function getStatus() {
  const r = await fetch(`${getBase()}/rag/status`)
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

// ── 知识库导入 ────────────────────────────────────────────────

export async function ingestText(content, sourceName = 'inline', projectId = 'default') {
  const body = new URLSearchParams({ content, source_name: sourceName, project_id: projectId })
  const r = await fetch(`${getBase()}/rag/ingest/text`, { method: 'POST', body })
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

export async function ingestFile(file, projectId = 'default') {
  const form = new FormData()
  form.append('file', file)
  form.append('project_id', projectId)
  const r = await fetch(`${getBase()}/rag/ingest/file`, { method: 'POST', body: form })
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
      } catch {
        // 忽略格式错误行
      }
    }
  }
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

// ── 参数卡确认后出图（SSE：tool_call / tool_result / image）─────
// params 需带 workspace（由调用方按当前会话传入）
export async function* pipelineGenerate(params) {
  const body = { ...params }
  const response = await fetch(`${getBase()}/pipeline/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  yield* parseSSE(response)
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

// ── 出视频参数卡确认后出片（SSE：tool_result / video）────────
export async function* pipelineRender(params) {
  const response = await fetch(`${getBase()}/pipeline/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  yield* parseSSE(response)
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
