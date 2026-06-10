import { useState, useEffect, useCallback } from 'react'
import TopBar         from './components/TopBar'
import ChatWindow     from './components/ChatWindow'
import InputBar       from './components/InputBar'
import KnowledgePanel from './components/KnowledgePanel'
import SettingsPanel  from './components/SettingsPanel'
import HistorySidebar from './components/HistorySidebar'
import FolderPicker   from './components/FolderPicker'
import { getStatus, streamChat, resumeChat, getHistory, getSessionHistory, deleteSession,
         pipelineGenerate, pipelineSelect, pipelineRender, getContextUsage, compactContext, getAgents,
         initWorkspace } from './api'

// 每个会话独立的工作目录（互不影响）
function loadWorkspaceMap() {
  try { return JSON.parse(localStorage.getItem('agentlab_workspaces') || '{}') } catch { return {} }
}
function getSessionWorkspace(sid) { return loadWorkspaceMap()[sid] || '' }
function setSessionWorkspace(sid, path) {
  const m = loadWorkspaceMap()
  if (path) m[sid] = path; else delete m[sid]
  localStorage.setItem('agentlab_workspaces', JSON.stringify(m))
}

function genId() {
  return Math.random().toString(36).slice(2, 10)
}

/** 从 localStorage 读 Supervisor 模型名，用于 TopBar 显示 */
function getDisplayModel(fallback) {
  try {
    const cfg = JSON.parse(localStorage.getItem('agentlab_agent_configs') || 'null')
    return cfg?.supervisor?.model || fallback
  } catch {
    return fallback
  }
}

function loadSessionId() {
  // 跨刷新保持同一会话，避免每次刷新都新建导致历史里出现"重复"会话
  let sid = localStorage.getItem('agentlab_session_id')
  if (!sid) {
    sid = `sid-${genId()}`
    localStorage.setItem('agentlab_session_id', sid)
  }
  return sid
}

export default function App() {
  const [sessionId, setSessionId]         = useState(loadSessionId)
  const [messages, setMessages]           = useState([])
  const [isStreaming, setIsStreaming]      = useState(false)
  const [ragStatus, setRagStatus]         = useState({ rag_connected: false, chunk_count: 0, model: '' })
  const [showKnowledge, setShowKnowledge] = useState(false)
  const [showSettings,  setShowSettings]  = useState(false)
  const [agent, setAgent]                 = useState('supervisor')
  // HITL：当后端暂停等待确认时记录上下文，用于 resume 请求
  const [pendingInterrupt, setPendingInterrupt] = useState(null)
  // { sessionId, agent, node, msgId }   msgId = interrupt 消息在 messages 里的 id
  // displayModel 只用于 TopBar 标签显示，不影响实际请求（api.js 直接读 localStorage）
  const [displayModel, setDisplayModel]   = useState(() => getDisplayModel(''))
  const [sessions, setSessions]           = useState([])
  const [workspace, setWorkspace]         = useState(() => getSessionWorkspace(loadSessionId()))
  const [showFolderPicker, setShowFolderPicker] = useState(false)
  const [ctxUsage, setCtxUsage]           = useState(null)  // 真实上下文窗口用量
  const [agentList, setAgentList]         = useState([])    // 动态 Agent 列表（注册即出现）

  const fetchSessions = useCallback(async () => {
    try {
      const data = await getHistory()
      setSessions(data || [])
    } catch (err) {
      console.error('Failed to fetch historical sessions:', err)
    }
  }, [])

  // 真实上下文窗口用量（定义在使用它的回调之前，避免 TDZ）
  const refreshContext = useCallback(async (sid) => {
    try { setCtxUsage(await getContextUsage(sid || sessionId)) } catch {}
  }, [sessionId])

  // 启动 + 定期刷新 RAG 状态
  useEffect(() => {
    const refresh = async () => {
      try { setRagStatus(await getStatus()) } catch {}
    }
    refresh()
    const id = setInterval(refresh, 15000)
    return () => clearInterval(id)
  }, [])

  // 加载历史会话列表
  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  // 拉取动态 Agent 列表（注册了新 Agent 自动出现，无需改前端）
  useEffect(() => {
    getAgents().then(setAgentList).catch(() => {})
  }, [])

  // 刷新后恢复当前会话的历史消息（sessionId 已持久化，消息也要回来）
  useEffect(() => {
    (async () => {
      try {
        const data = await getSessionHistory(sessionId)
        if (data?.messages?.length) setMessages(data.messages)
      } catch {}
    })()
    // 仅在首次挂载执行；切换会话由 handleSelectSession 处理
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** 统一消费 SSE 事件流（sendMessage / handleResume 共用） */
  const consumeStream = useCallback(async (gen, aiMsgId, currentSessionId, currentAgent) => {
    for await (const data of gen) {
      if (data.type === 'chunk') {
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId ? { ...m, content: m.content + data.content } : m)
        )
      } else if (data.type === 'tool_call') {
        // 工具被调用：追加一个"执行中"步骤
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId
            ? { ...m, steps: [...(m.steps || []), { name: data.name, args: data.args, done: false }] }
            : m)
        )
      } else if (data.type === 'tool_result') {
        // 工具返回：把最近一个同名未完成步骤标记为完成并记录结果
        setMessages(prev =>
          prev.map(m => {
            if (m.id !== aiMsgId) return m
            const steps = [...(m.steps || [])]
            for (let i = steps.length - 1; i >= 0; i--) {
              if (steps[i].name === data.name && !steps[i].done) {
                steps[i] = { ...steps[i], done: true, result: data.content }
                break
              }
            }
            return { ...m, steps }
          })
        )
      } else if (data.type === 'param_form') {
        // 出图参数卡：插入一张可编辑参数表单卡片
        setMessages(prev => [...prev, {
          id: genId(), role: 'param_form', streaming: false,
          params: {
            scene_id: data.scene_id, image_prompt: data.image_prompt || '',
            n: data.n, steps: data.steps, guidance: data.guidance,
            width: data.width, height: data.height, seed: data.seed,
            offload: data.offload,
          },
          submitted: false,
        }])
      } else if (data.type === 'image') {
        // 候选图：追加到当前消息的图片墙
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId
            ? { ...m, images: [...(m.images || []), { assetId: data.asset_id, sceneId: data.scene_id, url: data.url, name: data.name }] }
            : m)
        )
      } else if (data.type === 'video_param_form') {
        // 出视频参数卡
        setMessages(prev => [...prev, {
          id: genId(), role: 'video_param_form', streaming: false, submitted: false,
          params: {
            scene_id: data.scene_id, motion_prompt: data.motion_prompt || '',
            size: data.size, frame_num: data.frame_num, sample_steps: data.sample_steps,
          },
        }])
      } else if (data.type === 'video') {
        // 成片：内嵌播放器
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId
            ? { ...m, video: { sceneId: data.scene_id, url: data.url, name: data.name } }
            : m)
        )
      } else if (data.type === 'interrupt') {
        // 把 AI 消息标为"已完成"（可能内容为空），再插入一条 interrupt 确认卡片
        setMessages(prev => {
          const withDone = prev.map(m =>
            m.id === aiMsgId ? { ...m, streaming: false } : m
          )
          const interruptMsgId = genId()
          const interruptMsg = {
            id: interruptMsgId,
            role: 'interrupt',
            node: data.node,
            content: data.content,
            streaming: false,
          }
          // 记录 pendingInterrupt（在 setState 外设置，避免闭包问题）
          setPendingInterrupt({ sessionId: currentSessionId, agent: currentAgent,
                                node: data.node, msgId: interruptMsgId })
          return [...withDone, interruptMsg]
        })
        setIsStreaming(false)
        return 'interrupted'   // 告知调用方流已暂停
      } else if (data.type === 'error') {
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId ? { ...m, content: `Error: ${data.content}` } : m)
        )
        break
      }
    }
    return 'done'
  }, [])

  const sendMessage = useCallback(async (content) => {
    if (!content.trim() || isStreaming) return

    const userMsg = { id: genId(), role: 'user',      content: content.trim(), streaming: false }
    const aiMsgId = genId()
    const aiMsg   = { id: aiMsgId,  role: 'assistant', content: '',             streaming: true,
                      agentLabel: agent }

    setMessages(prev => [...prev, userMsg, aiMsg])
    setIsStreaming(true)

    try {
      const result = await consumeStream(
        streamChat(sessionId, content.trim(), { agent, workspace }),
        aiMsgId, sessionId, agent,
      )
      if (result !== 'interrupted') {
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId ? { ...m, streaming: false } : m)
        )
      }
    } catch {
      setMessages(prev =>
        prev.map(m => m.id === aiMsgId
          ? { ...m, content: 'Request failed. Is the backend running?', streaming: false } : m)
      )
    } finally {
      // 无论是正常结束还是 interrupt 暂停，都关闭 streaming 状态
      // interrupt 卡片的交互按钮需要 isStreaming=false 才能响应
      setIsStreaming(false)
      try { setRagStatus(await getStatus()) } catch {}
      try { await fetchSessions() } catch {}
      refreshContext(sessionId)   // 更新上下文窗口进度
    }
  }, [sessionId, isStreaming, agent, workspace, consumeStream, fetchSessions, refreshContext])

  /** HITL：用户点击"确认"或"取消"后调用 */
  const handleResume = useCallback(async (approved) => {
    if (!pendingInterrupt) return
    const { sessionId: sid, agent: ag, msgId } = pendingInterrupt

    // 把 interrupt 卡片标为"已决策"，追加新的 AI 回复占位
    const aiMsgId = genId()
    const aiMsg   = { id: aiMsgId, role: 'assistant', content: '', streaming: true, agentLabel: ag }
    setMessages(prev => [
      ...prev.map(m => m.id === msgId ? { ...m, resolved: approved } : m),
      aiMsg,
    ])
    setPendingInterrupt(null)
    setIsStreaming(true)

    try {
      const result = await consumeStream(
        resumeChat(sid, ag, approved),
        aiMsgId, sid, ag,
      )
      if (result !== 'interrupted') {
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId ? { ...m, streaming: false } : m)
        )
      }
    } catch {
      setMessages(prev =>
        prev.map(m => m.id === aiMsgId
          ? { ...m, content: 'Resume failed.', streaming: false } : m)
      )
    } finally {
      setIsStreaming(false)
      try { setRagStatus(await getStatus()) } catch {}
      try { await fetchSessions() } catch {}
    }
  }, [pendingInterrupt, consumeStream, fetchSessions])

  /** 参数卡点「出图」：用确认后的参数真正跑 FLUX，结果流入新的 AI 消息 */
  const handleGenerate = useCallback(async (paramMsgId, params) => {
    if (isStreaming) return
    // 标记该参数卡已提交（禁用按钮）
    setMessages(prev => prev.map(m => m.id === paramMsgId ? { ...m, submitted: true } : m))
    const aiMsgId = genId()
    setMessages(prev => [...prev, {
      id: aiMsgId, role: 'assistant', content: '出图中（首次加载 FLUX 约 1-2 分钟）…',
      streaming: true, agentLabel: 'video',
    }])
    setIsStreaming(true)
    try {
      await consumeStream(pipelineGenerate({ ...params, workspace, session_id: sessionId }), aiMsgId, sessionId, 'video')
      setMessages(prev => prev.map(m => m.id === aiMsgId
        ? { ...m, content: m.content.replace(/^出图中.*?…/, '').trim(), streaming: false } : m))
    } catch {
      setMessages(prev => prev.map(m => m.id === aiMsgId
        ? { ...m, content: '出图请求失败，请确认后端/ GPU 状态。', streaming: false } : m))
    } finally {
      setIsStreaming(false)
      refreshContext(sessionId)
    }
  }, [isStreaming, consumeStream, sessionId, workspace, refreshContext])

  /** 出视频参数卡点「出视频」：用确认后的参数跑 Wan2.2，结果流入新的 AI 消息 */
  const handleRenderVideo = useCallback(async (paramMsgId, params) => {
    if (isStreaming) return
    setMessages(prev => prev.map(m => m.id === paramMsgId ? { ...m, submitted: true } : m))
    const aiMsgId = genId()
    setMessages(prev => [...prev, {
      id: aiMsgId, role: 'assistant', content: '出视频中（Wan2.2 加载 + 采样，约 2-5 分钟）…',
      streaming: true, agentLabel: 'video',
    }])
    setIsStreaming(true)
    try {
      await consumeStream(
        pipelineRender({ ...params, workspace, session_id: sessionId }),
        aiMsgId, sessionId, 'video')
      setMessages(prev => prev.map(m => m.id === aiMsgId
        ? { ...m, content: m.content.replace(/^出视频中.*?…/, '').trim(), streaming: false } : m))
    } catch {
      setMessages(prev => prev.map(m => m.id === aiMsgId
        ? { ...m, content: '出视频请求失败，请确认后端/ GPU 状态。', streaming: false } : m))
    } finally {
      setIsStreaming(false)
      refreshContext(sessionId)
    }
  }, [isStreaming, consumeStream, sessionId, workspace, refreshContext])

  /** 点击候选图=选图（HITL）：调后端推进状态，并在图片墙上打勾 */
  const handleSelectImage = useCallback(async (sceneId, assetId) => {
    try {
      const res = await pipelineSelect(sceneId, assetId, workspace)
      setMessages(prev => prev.map(m => {
        if (!m.images) return m
        return { ...m, images: m.images.map(img =>
          img.assetId === assetId ? { ...img, selected: true }
            : (m.images.some(x => x.assetId === assetId) ? { ...img, selected: false } : img)) }
      }))
      // 追加一条系统提示
      setMessages(prev => [...prev, {
        id: genId(), role: 'assistant', streaming: false,
        content: res.success
          ? `已选定候选图 \`${assetId}\`，分镜进入待出视频。下一步可让我「出视频」。`
          : res.message,
      }])
    } catch (e) {
      console.error('select failed', e)
    }
  }, [workspace])

  const saveWorkspace = (path) => {
    setWorkspace(path)
    setSessionWorkspace(sessionId, path)   // 只存到当前会话，互不影响
    setShowFolderPicker(false)
    if (path) initWorkspace(path).catch(() => {})   // 立即在该目录建好 .agent
  }

  // slash 命令：/clear 清空当前视图
  const handleClearChat = useCallback(() => { setMessages([]) }, [])

  // slash 命令：/compact 立即真实压缩上下文
  const handleCompact = useCallback(async () => {
    setMessages(prev => [...prev, { id: genId(), role: 'assistant', streaming: false,
      content: '正在压缩上下文…' }])
    try {
      const r = await compactContext(sessionId)
      setMessages(prev => prev.map((m, i) => i === prev.length - 1
        ? { ...m, content: r.success
            ? `${r.message}（${r.before.tokens} → ${r.after.tokens} tokens）`
            : `ℹ️ ${r.message}` }
        : m))
      refreshContext(sessionId)
    } catch (e) {
      setMessages(prev => prev.map((m, i) => i === prev.length - 1
        ? { ...m, content: '压缩失败：' + e } : m))
    }
  }, [sessionId, refreshContext])

  // 进入/切换会话时拉取真实上下文用量
  useEffect(() => { refreshContext(sessionId) }, [sessionId, refreshContext])

  const persistSession = (sid) => {
    localStorage.setItem('agentlab_session_id', sid)
    setSessionId(sid)
    setWorkspace(getSessionWorkspace(sid))   // 切到该会话自己的工作目录
  }

  const startNewChat = () => {
    if (isStreaming) return
    persistSession(`sid-${genId()}`)
    setMessages([])
  }

  const handleSelectSession = useCallback(async (sid) => {
    if (isStreaming) return
    try {
      persistSession(sid)
      const data = await getSessionHistory(sid)
      setMessages(data.messages || [])
      setPendingInterrupt(null)
    } catch (err) {
      console.error("Failed to load session history:", err)
    }
  }, [isStreaming])

  const handleDeleteSession = useCallback(async (sid) => {
    try {
      await deleteSession(sid)
      await fetchSessions()
      if (sid === sessionId) {
        persistSession(`sid-${genId()}`)
        setMessages([])
        setPendingInterrupt(null)
      }
    } catch (err) {
      console.error("Failed to delete session:", err)
    }
  }, [sessionId, fetchSessions])

  // 同一时间只开一个面板
  const openKnowledge = () => { setShowKnowledge(v => !v); setShowSettings(false) }
  const openSettings  = () => { setShowSettings(v => !v);  setShowKnowledge(false) }

  // Settings 保存后刷新 TopBar 显示的模型名
  const handleSettingsSaved = () => {
    setDisplayModel(getDisplayModel(ragStatus.model || ''))
  }

  const topBarModel = displayModel || ragStatus.model || 'claude-haiku-4.5'

  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'row',
      background: 'var(--bg)', position: 'relative', overflow: 'hidden',
      width: '100%'
    }}>
      {/* 历史侧边栏 */}
      <HistorySidebar
        currentSessionId={sessionId}
        sessions={sessions}
        onSelectSession={handleSelectSession}
        onNewChat={startNewChat}
        onDeleteSession={handleDeleteSession}
      />

      {/* 主对话区 */}
      <div style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minWidth: 0,
        position: 'relative',
        overflow: 'hidden'
      }}>
        <TopBar
          model={topBarModel}
          ragStatus={ragStatus}
          onKnowledgeClick={openKnowledge}
          showKnowledge={showKnowledge}
          onNewChat={startNewChat}
          onSettingsClick={openSettings}
        />

        <ChatWindow messages={messages} onResume={handleResume} onSend={sendMessage}
                    onGenerate={handleGenerate} onSelectImage={handleSelectImage}
                    onRenderVideo={handleRenderVideo} />

        {/* 工作目录条：出图/出视频的落地根 */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '6px 24px', fontSize: 12, color: 'var(--text-muted)',
          borderTop: '1px solid var(--border)', background: 'var(--bg)',
        }}>
          <span>工作目录：</span>
          <span style={{
            fontFamily: 'monospace', color: workspace ? 'rgba(134,239,172,0.9)' : 'var(--text-dim)',
            maxWidth: 480, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {workspace || '（默认 agent_workspace）'}
          </span>
          <button onClick={() => setShowFolderPicker(true)} style={{
            marginLeft: 'auto', height: 24, padding: '0 12px', borderRadius: 6,
            border: '1px solid var(--border)', background: 'rgba(255,255,255,0.05)',
            color: 'rgba(255,255,255,0.7)', fontSize: 12, cursor: 'pointer',
          }}>更改</button>
          {/* 上下文窗口真实用量进度条 */}
          <ContextBar usage={ctxUsage} onCompact={handleCompact} />
        </div>

        <InputBar
          key={sessionId}
          onSend={sendMessage}
          disabled={isStreaming}
          agent={agent}
          onAgentChange={setAgent}
          onNewChat={startNewChat}
          onClearChat={handleClearChat}
          onOpenWorkspace={() => setShowFolderPicker(true)}
          onCompact={handleCompact}
          agents={agentList}
        />

        <KnowledgePanel
          open={showKnowledge}
          onClose={() => setShowKnowledge(false)}
          onStatusChange={setRagStatus}
        />

        <SettingsPanel
          open={showSettings}
          onClose={() => setShowSettings(false)}
          onSaved={handleSettingsSaved}
        />

        <FolderPicker
          open={showFolderPicker}
          initial={workspace}
          onClose={() => setShowFolderPicker(false)}
          onPick={saveWorkspace}
        />
      </div>
    </div>
  )
}

/** 上下文窗口真实用量进度条：到达触发线会自动压缩；可点手动压缩 */
function ContextBar({ usage, onCompact }) {
  if (!usage || !usage.window) return null
  const { tokens, window, trigger_tokens, will_compact } = usage
  const pct = Math.min(100, (tokens / window) * 100)
  const triggerPct = Math.min(100, (trigger_tokens / window) * 100)
  const color = will_compact ? 'rgba(239,68,68,0.9)'
    : pct > triggerPct * 0.8 ? 'rgba(234,179,8,0.9)' : 'rgba(99,102,241,0.85)'
  const k = (n) => n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n)
  return (
    <div title={`上下文 ${tokens}/${window} tokens；达 ${trigger_tokens} 触发压缩`}
      style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 14, minWidth: 200 }}>
      <span style={{ fontSize: 11, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>上下文</span>
      <div style={{ position: 'relative', flex: 1, height: 6, borderRadius: 3,
                    background: 'rgba(255,255,255,0.08)', overflow: 'hidden', minWidth: 90 }}>
        <div style={{ position: 'absolute', inset: 0, width: `${pct}%`, background: color,
                      transition: 'width 0.3s' }} />
        {/* 压缩触发线标记 */}
        <div style={{ position: 'absolute', top: -1, bottom: -1, left: `${triggerPct}%`,
                      width: 2, background: 'rgba(239,68,68,0.6)' }} />
      </div>
      <span style={{ fontSize: 11, color: 'var(--text-dim)', fontFamily: 'monospace',
                     whiteSpace: 'nowrap' }}>{k(tokens)}/{k(window)}</span>
      <button onClick={onCompact} title="立即压缩上下文" style={{
        height: 20, padding: '0 8px', borderRadius: 5, border: '1px solid var(--border)',
        background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)', fontSize: 11,
        cursor: 'pointer', whiteSpace: 'nowrap',
      }}>压缩</button>
    </div>
  )
}
