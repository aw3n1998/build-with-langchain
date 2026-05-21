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

export async function* streamChat(sessionId, content, { agent = 'supervisor' } = {}) {
  const agentConfigs = getAgentConfigs()
  const body = { session_id: sessionId, content, agent }
  if (agentConfigs) body.agent_configs = agentConfigs

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
