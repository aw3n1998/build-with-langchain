import { useState, useEffect, useCallback, useRef } from 'react'
import SettingsPanel  from './components/SettingsPanel'
import FolderPicker   from './components/FolderPicker'
import FloatingAssistant from './components/FloatingAssistant'
import { getStatus, chatSubmit, resumeSubmit, cancelJob, getHistory, getSessionHistory, deleteSession,
         pipelineGenerate, pipelineSelect, pipelineRender, streamJobEvents, listProjects,
         getContextUsage, compactContext, getAgents, connectJobsWS,
         initWorkspace, projectCreate, projectRename, projectDelete } from './api'
import { ProductionPanel } from './components/MessageBubble'
import { Icon } from './components/icons'
import ProjectSidebar from './components/ProjectSidebar'
import Account from './components/Account'
import { useDialog } from './components/Dialog'
import useIsMobile from './components/mobile/useIsMobile'
import MobileShell from './components/mobile/MobileShell'

// 每个会话独立的工作目录（互不影响）
function loadWorkspaceMap() {
  try { return JSON.parse(localStorage.getItem('agentlab_workspaces') || '{}') } catch { return {} }
}
// 会话工作目录：优先本会话的；没有则回退「上次用过的工作目录」（避免新会话/刷新后工作台空白、像"数据没了"）
function getSessionWorkspace(sid) {
  return loadWorkspaceMap()[sid] || localStorage.getItem('agentlab_last_workspace') || ''
}
function setSessionWorkspace(sid, path) {
  const m = loadWorkspaceMap()
  if (path) m[sid] = path; else delete m[sid]
  localStorage.setItem('agentlab_workspaces', JSON.stringify(m))
  if (path) { try { localStorage.setItem('agentlab_last_workspace', path) } catch {} }  // 记成全局"上次用过"
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

const studioHdrBtn = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  height: 32, padding: '0 13px', borderRadius: 8, border: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.05)', color: 'var(--text)', fontSize: 12.5, fontWeight: 500,
  cursor: 'pointer', whiteSpace: 'nowrap', transition: 'background .14s, border-color .14s',
}
// 仅图标的方形按钮（重命名/删除）：与 studioHdrBtn 等高，正方形留白
const studioHdrIcon = { ...studioHdrBtn, width: 32, padding: 0, justifyContent: 'center' }
// 全局顶栏（OpenArt 风格 studio chrome）
const topBar = { display: 'flex', alignItems: 'center', gap: 18, height: 52, padding: '0 18px', flexShrink: 0,
  borderBottom: '1px solid rgba(255,255,255,0.07)', background: 'var(--bg)' }
const brandStyle = { fontSize: 16, fontWeight: 700, letterSpacing: '0.02em',
  background: 'linear-gradient(135deg,#a5b4fc,#818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }
const navItem = (active) => ({ fontSize: 13.5, fontWeight: 500, cursor: 'pointer', color: active ? 'var(--text)' : 'var(--text-muted)' })

export default function App() {
  const dialog = useDialog()
  const [sessionId, setSessionId]         = useState(loadSessionId)
  const [messages, setMessages]           = useState([])
  const [isStreaming, setIsStreaming]      = useState(false)
  const [ragStatus, setRagStatus]         = useState({ rag_connected: false, chunk_count: 0, model: '' })
  const [assistantOpen, setAssistantOpen] = useState(false)   // 浮动小助手开合
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
  const [panelProjectId, setPanelProjectId] = useState(null)
  const [hasProject, setHasProject]       = useState(false)
  const [heroNovel, setHeroNovel]         = useState('')   // 首页 Hero 的小说输入（OpenArt 式 prompt-first 入口）
  const [allProjects, setAllProjects]     = useState([])   // 工作目录下全部项目（供面板里切换）
  // 有任务（对话/出图/出片）在跑的会话集合：侧边栏据此显示绿点
  const [runningSessions, setRunningSessions] = useState(() => new Set())

  // 流取消令牌：切换/新建会话时 +1，旧流的所有写入立即失效并退出循环。
  // 对话回合本身在后台任务里跑（job_manager chat 通道），切走只是不再"看"，
  // 回合照常完成并落库，切回来从历史里看到完整结果。
  const streamToken = useRef(0)
  const activeJobRef = useRef(null)   // 当前回合的 job_id（停止按钮用）
  const cancelActiveStream = useCallback(() => {
    streamToken.current += 1
    setIsStreaming(false)
  }, [])

  /** 「停止生成」：真取消后台 chat 任务 + 停止本地跟随 */
  const stopGenerating = useCallback(async () => {
    const jid = activeJobRef.current
    cancelActiveStream()
    setMessages(prev => prev.map(m => m.streaming
      ? { ...m, streaming: false, content: (m.content || '') + '\n\n（已停止生成）' } : m))
    if (jid) { try { await cancelJob(jid) } catch {} }
  }, [cancelActiveStream])

  const fetchSessions = useCallback(async () => {
    try {
      const data = await getHistory()
      setSessions(data || [])
    } catch (err) {
      console.error('Failed to fetch historical sessions:', err)
    }
  }, [])

  // 当前会话的实时引用：异步回调里用它校验"结果是否还属于当前会话"，防止切会话后旧数据串台
  const sessionIdRef = useRef(sessionId)
  useEffect(() => { sessionIdRef.current = sessionId }, [sessionId])

  // 真实上下文窗口用量（定义在使用它的回调之前，避免 TDZ）
  const refreshContext = useCallback(async (sid) => {
    const target = sid || sessionIdRef.current
    try {
      const u = await getContextUsage(target)
      if (sessionIdRef.current === target) setCtxUsage(u)  // 已切走则丢弃，避免进度条串台
    } catch {}
  }, [])

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

  // 任务状态 WebSocket：后端推送，不轮询。
  // - 维护"哪些会话有任务在跑"（侧边栏绿点）；
  // - 当前会话的后台任务完成、而本地没在跟流（比如切走又切回）→ 自动刷新历史，结果直接出现。
  useEffect(() => {
    const close = connectJobsWS((msg) => {
      if (msg.type !== 'job_update' || !msg.session_id) return
      const sid = msg.session_id
      const active = msg.status === 'queued' || msg.status === 'running'
      setRunningSessions(prev => {
        const next = new Set(prev)
        if (active) next.add(sid); else next.delete(sid)
        return next
      })
      // 终态推送：属于当前会话且本地没有流在跟（切走过/刷新过）→ 拉最新历史
      if (!active && sid === sessionIdRef.current) {
        setIsStreaming(cur => {
          if (!cur) {
            getSessionHistory(sid).then(d => {
              if (sessionIdRef.current === sid && d?.messages?.length) setMessages(d.messages)
            }).catch(() => {})
            refreshContext(sid)
          }
          return cur
        })
      }
    })
    return close
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 工作目录变化时探测最新项目：有项目就点亮底部「制作面板」按钮
  useEffect(() => {
    let alive = true
    setHasProject(false); setPanelProjectId(null)
    // 即使没显式选工作目录(workspace='')也加载【默认工作目录】的剧集——否则刷新后列表空,
    // 但一点「新建剧集」(refreshProjects 无此守卫)旧剧集又全冒出来 = "刷新不自动加载"的真因。
    listProjects(workspace).then(d => {
      if (!alive) return
      const ps = d?.projects || []
      setAllProjects(ps)
      const latest = ps[0]
      if (latest) { setPanelProjectId(latest.project_id); setHasProject(true) }
    }).catch(() => {})
    return () => { alive = false }
  }, [workspace])

  // 剧集（项目）自助管理：新建 / 改名 / 删除（不绕 agent）
  const refreshProjects = useCallback(async () => {
    try { const d = await listProjects(workspace); const ps = d?.projects || []; setAllProjects(ps); return ps }
    catch { return [] }
  }, [workspace])
  const newProject = useCallback(async () => {
    const title = await dialog.prompt('新剧集名称', '新剧集', { title: '新建剧集', confirmText: '创建' })
    if (title == null) return
    try {
      const r = await projectCreate(title || '新剧集', workspace)
      await refreshProjects(); setHasProject(true); setPanelProjectId(r.project_id)
    } catch (e) { dialog.alert('新建失败：' + String(e.message || e)) }
  }, [workspace, refreshProjects, dialog])

  // 首页 Hero「一键开始」：把小说预填进制作面板（usePersistedState 同键 agentlab.panel.sbNovel），
  // 自动建剧集并打开 → 面板挂载即带着小说，用户点「✨ 一键全自动出片」直接出片。空文本 = 纯新建。
  const startFromNovel = useCallback(async (novelText) => {
    const text = (novelText || '').trim()
    const auto = text ? text.replace(/\s+/g, ' ').slice(0, 16) : '新剧集'
    try {
      const r = await projectCreate(auto, workspace)
      // 把小说预填进【这个新剧集】的拆分镜输入（per-project 同键 sbNovel.<pid>，面板 key=pid 挂载即读到）
      try { if (text) localStorage.setItem('agentlab.panel.sbNovel.' + r.project_id, JSON.stringify(text)) } catch { /* 隐私模式忽略 */ }
      // 自动跑信号旗（仅带小说时）：面板挂载后读到即自动触发「一键全自动出片」，读后即清；空文本=只建剧集不出片。
      try { if (text) localStorage.setItem('agentlab.panel.autorun.' + r.project_id, '1') } catch { /* 隐私模式忽略 */ }
      await refreshProjects(); setHasProject(true); setPanelProjectId(r.project_id); setHeroNovel('')
    } catch (e) { dialog.alert('新建失败：' + String(e.message || e)) }
  }, [workspace, refreshProjects, dialog])

  const renameProject = useCallback(async () => {
    if (!panelProjectId) return
    const cur = allProjects.find(p => p.project_id === panelProjectId)
    const title = await dialog.prompt('改名为', cur?.title || '', { title: '剧集改名' })
    if (title == null) return
    try { await projectRename(panelProjectId, title, workspace); await refreshProjects() }
    catch (e) { dialog.alert('改名失败：' + String(e.message || e)) }
  }, [panelProjectId, allProjects, workspace, refreshProjects, dialog])
  const removeProject = useCallback(async () => {
    if (!panelProjectId) return
    const cur = allProjects.find(p => p.project_id === panelProjectId)
    const ok = await dialog.confirm(`删除整个剧集「${cur?.title || panelProjectId}」？`, {
      message: '含全部分镜与候选图，不可恢复。', danger: true, confirmText: '删除',
    })
    if (!ok) return
    try {
      await projectDelete(panelProjectId, workspace)
      const ps = await refreshProjects()
      setPanelProjectId(ps.length ? ps[0].project_id : null)
      setHasProject(ps.length > 0)
    } catch (e) { dialog.alert('删除失败：' + String(e.message || e)) }
  }, [panelProjectId, allProjects, workspace, refreshProjects, dialog])

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
    // 取消契约：捕获当前令牌；用户切走会话后令牌变化，本流停止一切写入并退出
    //（for-await 的 break 会关闭底层 reader，连接随之中断；后台任务不受影响）。
    const myToken = streamToken.current
    // 参数卡先暂存，等本轮文字全部流完后再统一追加到对话最下面，
    // 否则卡片会被夹在"弹出参数卡"与后续总结文字之间。
    const pendingCards = []
    for await (const data of gen) {
      if (streamToken.current !== myToken) return 'cancelled'
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
      } else if (data.type === 'queued') {
        // 后台任务排队中（前面有 GPU 任务在跑，单飞队列）
        setMessages(prev => prev.map(m => m.id === aiMsgId
          ? { ...m, content: '前面有 GPU 任务在跑，排队中…（轮到就自动开始）' } : m))
      } else if (data.type === 'status') {
        if (data.status === 'running') {
          setMessages(prev => prev.map(m => m.id === aiMsgId
            ? (/排队中/.test(m.content) ? { ...m, content: '处理中…' } : m) : m))
        }
      } else if (data.type === 'production') {
        // 制作面板：拆完分镜后的确定性控制台，暂存到 turn 末尾追加；
        // 同时点亮底部常驻入口并指向该项目（小白即使没注意聊天卡片，也能从底部按钮进）
        setPanelProjectId(data.project_id)
        setHasProject(true)
        pendingCards.push({
          id: genId(), role: 'production', streaming: false,
          project_id: data.project_id,
        })
      } else if (data.type === 'param_form') {
        // 出图参数卡：暂存，turn 结束时追加到最下面
        pendingCards.push({
          id: genId(), role: 'param_form', streaming: false,
          params: {
            scene_id: data.scene_id, image_prompt: data.image_prompt || '',
            n: data.n, steps: data.steps, guidance: data.guidance,
            width: data.width, height: data.height, seed: data.seed,
            offload: data.offload,
          },
          submitted: false,
        })
      } else if (data.type === 'image') {
        // 候选图：追加到当前消息的图片墙
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId
            ? { ...m, images: [...(m.images || []), { assetId: data.asset_id, sceneId: data.scene_id, url: data.url, name: data.name }] }
            : m)
        )
      } else if (data.type === 'video_param_form') {
        // 出视频参数卡（多模型 + schema 驱动）。暂存到 turn 末尾再追加，兼容老事件（无 fields）。
        pendingCards.push({
          id: genId(), role: 'video_param_form', streaming: false, submitted: false,
          params: {
            scene_id: data.scene_id,
            motion_prompt: data.motion_prompt || '',
            model: data.model || '',
            models: data.models || [],
            fields: data.fields || null,
            // 老事件的扁平字段（向后兼容，card 在无 fields 时据此回退）
            size: data.size, frame_num: data.frame_num, sample_steps: data.sample_steps,
          },
        })
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
    if (streamToken.current !== myToken) return 'cancelled'
    // 本轮文字流完，参数卡统一追加到最下面
    if (pendingCards.length) {
      setMessages(prev => [...prev, ...pendingCards])
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
      // 回合提交为后台任务：切会话/断网不影响其完成，落库后可从历史恢复
      const jobId = await chatSubmit(sessionId, content.trim(), { agent, workspace })
      activeJobRef.current = jobId
      const result = await consumeStream(
        streamJobEvents(jobId),
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
      const jobId = await resumeSubmit(sid, ag, approved)
      activeJobRef.current = jobId
      const result = await consumeStream(
        streamJobEvents(jobId),
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
      // 提交为后台任务（单飞队列），再跟随其事件流；断线会自动重连续看
      const jobId = await pipelineGenerate({ ...params, workspace, session_id: sessionId })
      await consumeStream(streamJobEvents(jobId), aiMsgId, sessionId, 'video')
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
      id: aiMsgId, role: 'assistant', content: '出视频中（模型加载 + 采样，约 2-5 分钟）…',
      streaming: true, agentLabel: 'video',
    }])
    setIsStreaming(true)
    try {
      const jobId = await pipelineRender({ ...params, workspace, session_id: sessionId })
      await consumeStream(streamJobEvents(jobId), aiMsgId, sessionId, 'video')
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
      // 只有后端确认选图成功才在图片墙打勾——否则会出现"勾了但其实没选上"的假象，
      // 用户以为选好了点出视频才发现分镜状态不对。
      if (res.success) {
        setMessages(prev => prev.map(m => {
          if (!m.images) return m
          return { ...m, images: m.images.map(img =>
            img.assetId === assetId ? { ...img, selected: true }
              : (img.sceneId === sceneId ? { ...img, selected: false } : img)) }
        }))
      }
      // 选图确认消息：每个分镜只保留一条（重复点选/换选 = 原地替换，不再叠加刷屏）
      const selMsgId = `sel-${sceneId}`
      setMessages(prev => [...prev.filter(m => m.id !== selMsgId), {
        id: selMsgId, role: 'assistant', streaming: false,
        content: res.success
          ? `已选定候选图 \`${assetId}\`，分镜进入待出视频。\n<MSG_SPLIT><pcAction>{"label":"出视频","userInput":"出视频"}</pcAction>`
          : (res.message || '选图失败，请重试（后端未确认）。'),
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
    sessionIdRef.current = sid               // 同步更新引用（useEffect 要等下一帧，来不及）
    setSessionId(sid)
    setWorkspace(getSessionWorkspace(sid))   // 切到该会话自己的工作目录
  }

  // 对话进行中也允许新建/切换会话：取消当前流的 UI 写入（后台 GPU 任务照常跑，切回可见）
  const startNewChat = () => {
    cancelActiveStream()
    persistSession(`sid-${genId()}`)
    setMessages([])
    setPendingInterrupt(null)
  }

  const handleSelectSession = useCallback(async (sid) => {
    cancelActiveStream()
    setAssistantOpen(true)   // 选中历史会话 → 打开小助手查看
    try {
      persistSession(sid)
      const data = await getSessionHistory(sid)
      if (sessionIdRef.current === sid) {     // 异步期间又切走了就丢弃
        setMessages(data.messages || [])
        setPendingInterrupt(null)
      }
    } catch (err) {
      console.error("Failed to load session history:", err)
    }
  }, [cancelActiveStream])

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

  const openSettings = () => setShowSettings(v => !v)

  // Settings 保存后刷新显示的模型名
  const handleSettingsSaved = () => {
    setDisplayModel(getDisplayModel(ragStatus.model || ''))
  }

  // ── 手机端自适应：窄屏渲染短剧工作台移动壳(复用全部真功能 handler) ──
  const isMobile = useIsMobile()
  if (isMobile) {
    return (
      <MobileShell
        allProjects={allProjects} panelProjectId={panelProjectId} setPanelProjectId={setPanelProjectId}
        newProject={newProject} workspace={workspace} saveWorkspace={saveWorkspace} sessionId={sessionId}
        messages={messages} sendMessage={sendMessage} isStreaming={isStreaming} stopGenerating={stopGenerating}
        handleResume={handleResume} handleGenerate={handleGenerate} handleSelectImage={handleSelectImage}
        handleRenderVideo={handleRenderVideo} agent={agent} setAgent={setAgent} agentList={agentList}
        ragStatus={ragStatus} onSettingsSaved={handleSettingsSaved}
      />
    )
  }

  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      background: 'var(--bg)', position: 'relative', overflow: 'hidden',
      width: '100%'
    }}>
      {/* 全局顶栏（OpenArt 风格 studio chrome）：品牌 + 导航 + 账号/积分（Account 在开发态自动隐藏）*/}
      <div style={topBar}>
        <span style={brandStyle}>蜃景 Mirage</span>
        <span style={navItem(true)}>创作</span>
        <span style={navItem(false)} onClick={() => setAssistantOpen(true)} title="AI 助手">助手</span>
        <div style={{ marginLeft: 'auto' }}><Account /></div>
      </div>
      {/* 主体：左栏剧集 + 主区 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'row', minHeight: 0, width: '100%', overflow: 'hidden' }}>
      {/* 左栏：剧集列表（短剧工作台是唯一主视图；AI 助手退为右下角浮动小助手）*/}
      <ProjectSidebar
        projects={allProjects}
        currentProjectId={panelProjectId}
        onSelect={setPanelProjectId}
        onNew={newProject}
        onToChat={() => setAssistantOpen(true)}
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
        {/* 🎬 短剧工作台：唯一主视图 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', minWidth: 0, overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, minHeight: 56, padding: '0 20px',
                          borderBottom: '1px solid rgba(255,255,255,0.07)', background: 'var(--bg)', flexWrap: 'wrap' }}>
              {/* 当前剧集名（切换/新建由左栏剧集列表负责，顶栏只对「当前剧集」做操作，避免多处重复入口）*/}
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 9, marginRight: 4, minWidth: 0 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                               width: 28, height: 28, borderRadius: 8, color: '#fff', flexShrink: 0,
                               background: 'linear-gradient(135deg,#6366f1,#4338ca)' }}>
                  <Icon.Clapper size={16} />
                </span>
                <span title={(allProjects.find(p => p.project_id === panelProjectId)?.title) || ''}
                  style={{ fontSize: 15, fontWeight: 600, letterSpacing: '0.01em',
                           color: panelProjectId ? 'var(--text)' : 'var(--text-muted)',
                           maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {(allProjects.find(p => p.project_id === panelProjectId)?.title) || '选择或新建剧集'}
                </span>
              </span>
              {panelProjectId && <button onClick={renameProject} style={studioHdrIcon} title="给当前剧集改名"><Icon.Pencil /></button>}
              {panelProjectId && <button onClick={removeProject} style={{ ...studioHdrIcon, color: 'rgba(248,113,113,1)', borderColor: 'rgba(239,68,68,0.3)' }} title="删除当前剧集"><Icon.Trash /></button>}
              <button onClick={() => setShowFolderPicker(true)} style={studioHdrBtn} title={workspace || '默认工作目录'}><Icon.Folder />工作目录</button>
              <button onClick={openSettings} style={{ ...studioHdrIcon, marginLeft: 'auto' }} title="设置">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82 2 2 0 1 1-2.83 2.83 1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51 2 2 0 0 1-4 0 1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33 2 2 0 1 1-2.83-2.83 1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1 2 2 0 0 1 0-4 1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82 2 2 0 1 1 2.83-2.83 1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51 2 2 0 0 1 4 0 1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33 2 2 0 1 1 2.83 2.83 1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1 2 2 0 0 1 0 4 1.65 1.65 0 0 0-1.51 1Z"/></svg>
              </button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '18px 22px' }}>
              {panelProjectId ? (
                <ProductionPanel key={panelProjectId} message={{ project_id: panelProjectId }} workspace={workspace} sessionId={sessionId} />
              ) : (
                <div style={{ maxWidth: 600, margin: '46px auto', textAlign: 'center', color: 'var(--text-sec)' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                 width: 54, height: 54, borderRadius: 16, marginBottom: 16, color: 'rgba(190,192,255,0.9)',
                                 background: 'rgba(99,102,241,0.10)', border: '1px solid rgba(99,102,241,0.22)' }}>
                    <Icon.Clapper size={26} stroke={1.5} />
                  </span>
                  <div style={{ fontSize: 23, fontWeight: 800, color: 'var(--text)', marginBottom: 8, letterSpacing: '-0.01em' }}>把小说，一键变短剧</div>
                  <p style={{ fontSize: 13, lineHeight: 1.8, color: 'var(--text-sec)', margin: '0 0 18px' }}>
                    粘贴小说 / 剧情，AI 自动拆镜 · 出片续接 · 克隆配音 · 对口型 · 同步音效，合成竖屏成片。</p>
                  <textarea value={heroNovel} onChange={e => setHeroNovel(e.target.value)} rows={5}
                    placeholder="把这一集的小说 / 剧情粘进来，AI 帮你拆成整套分镜…"
                    style={{ width: '100%', resize: 'vertical', minHeight: 112, padding: '13px 15px', boxSizing: 'border-box',
                             borderRadius: 12, border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.03)',
                             color: 'var(--text)', fontSize: 14, lineHeight: 1.6, fontFamily: 'inherit', outline: 'none' }} />
                  <div style={{ display: 'flex', gap: 10, justifyContent: 'center', marginTop: 14, flexWrap: 'wrap' }}>
                    <button onClick={() => startFromNovel(heroNovel)} style={{
                      height: 44, padding: '0 26px', borderRadius: 11, border: 'none', cursor: 'pointer',
                      background: 'linear-gradient(135deg,#6366f1,#4338ca)', color: '#fff', fontWeight: 700, fontSize: 14.5,
                      display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: 'inherit',
                      boxShadow: '0 6px 20px rgba(99,102,241,0.32)' }}>
                      <Icon.Wand size={16} />{heroNovel.trim() ? '新建剧集并拆镜 →' : '新建空白剧集 →'}
                    </button>
                    <button onClick={() => setShowFolderPicker(true)} style={{ ...studioHdrBtn, height: 44, padding: '0 18px', fontSize: 13 }}>
                      <Icon.Folder />工作目录</button>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 14, lineHeight: 1.7 }}>
                    提交后进工作台，小说已自动带入「AI 拆分镜」——点 <b style={{ color: 'var(--text-sec)' }}>✨ 一键全自动出片</b> 即可一路到底。</div>
                </div>
              )}
            </div>
        </div>

        <SettingsPanel
          open={showSettings}
          onClose={() => setShowSettings(false)}
          onSaved={handleSettingsSaved}
          videoOnly={ragStatus.video_agent_only !== false}
        />

        <FolderPicker
          open={showFolderPicker}
          initial={workspace}
          onClose={() => setShowFolderPicker(false)}
          onPick={saveWorkspace}
        />

        {/* 右下角可拖动的可爱小助手（纯文字问答 + 久坐/友好主动互动）*/}
        <FloatingAssistant
          open={assistantOpen}
          onOpenChange={setAssistantOpen}
          messages={messages}
          onSend={sendMessage}
          isStreaming={isStreaming}
          onStop={stopGenerating}
          onResume={handleResume}
          onNewChat={startNewChat}
          sessions={sessions}
          sessionId={sessionId}
          onSelectSession={handleSelectSession}
        />
      </div>
      </div>
    </div>
  )
}
