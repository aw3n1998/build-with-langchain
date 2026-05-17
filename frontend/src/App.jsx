import { useState, useEffect, useCallback } from 'react'
import TopBar         from './components/TopBar'
import ChatWindow     from './components/ChatWindow'
import InputBar       from './components/InputBar'
import KnowledgePanel from './components/KnowledgePanel'
import SettingsPanel  from './components/SettingsPanel'
import { getStatus, streamChat, resumeChat } from './api'

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

export default function App() {
  const [sessionId] = useState(() => `sid-${genId()}`)
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

  // 启动 + 定期刷新 RAG 状态
  useEffect(() => {
    const refresh = async () => {
      try { setRagStatus(await getStatus()) } catch {}
    }
    refresh()
    const id = setInterval(refresh, 15000)
    return () => clearInterval(id)
  }, [])

  /** 统一消费 SSE 事件流（sendMessage / handleResume 共用） */
  const consumeStream = useCallback(async (gen, aiMsgId, currentSessionId, currentAgent) => {
    for await (const data of gen) {
      if (data.type === 'chunk') {
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId ? { ...m, content: m.content + data.content } : m)
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
        streamChat(sessionId, content.trim(), { agent }),
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
    }
  }, [sessionId, isStreaming, agent, consumeStream])

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
    }
  }, [pendingInterrupt, consumeStream])

  const startNewChat = () => {
    if (isStreaming) return
    setMessages([])
  }

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
      height: '100%', display: 'flex', flexDirection: 'column',
      background: 'var(--bg)', position: 'relative', overflow: 'hidden',
    }}>
      <TopBar
        model={topBarModel}
        ragStatus={ragStatus}
        onKnowledgeClick={openKnowledge}
        showKnowledge={showKnowledge}
        onNewChat={startNewChat}
        onSettingsClick={openSettings}
      />

      <ChatWindow messages={messages} onResume={handleResume} />

      <InputBar
        onSend={sendMessage}
        disabled={isStreaming}
        agent={agent}
        onAgentChange={setAgent}
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
    </div>
  )
}
