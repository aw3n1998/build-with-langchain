import { useEffect, useRef, useState } from 'react'
import ChatWindow from './ChatWindow'

/**
 * FloatingAssistant —— 可爱浮动小助手（替代整屏聊天）。
 *
 * - 右下角一个可拖动的小吉祥物（会眨眼、轻微上下浮动）。
 * - 点一下 → 旁边弹出纯文字问答面板（复用 ChatWindow 的 compact 模式）。
 * - 偶尔头顶冒气泡主动说话：久坐提醒 + 零星友好语（低频、可关、不打扰）。
 *
 * 重活（拆分镜/出图/出片/角色/导出）都在左边工作台面板，小助手只做问答。
 */

const POS_KEY  = 'agentlab_assistant_pos'
const REST_KEY = 'agentlab_assistant_lastrest'
const TIP_KEY  = 'agentlab_assistant_lasttip'

const REST_AFTER_MIN = 30   // 连续多久没歇 → 久坐提醒
const TIP_EVERY_MIN  = 12   // 友好语最短间隔
const MASCOT = 58           // 吉祥物尺寸
const PANEL_W = 360

const REST_LINES = [
  '忙挺久啦，起来动动、喝口水？☕',
  '盯屏幕有一会儿了，眼睛歇一歇～',
  '做得不错！要不要起来伸个懒腰？🙆',
]
const TIP_LINES = [
  '需要帮忙就叫我～',
  '先在「角色圣经」设好人物，拆出来更统一哦',
  '记得给本集设个统一风格，整集更连贯～',
  '出图不满意？多出几张挑挑看',
]
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)]

function loadPos() {
  try {
    const p = JSON.parse(localStorage.getItem(POS_KEY) || 'null')
    if (p && typeof p.left === 'number' && typeof p.top === 'number') return p
  } catch { /* ignore */ }
  return { left: window.innerWidth - MASCOT - 26, top: window.innerHeight - MASCOT - 30 }
}

export default function FloatingAssistant({
  open, onOpenChange,
  messages, onSend, isStreaming, onStop, onResume, onNewChat,
  sessions = [], sessionId, onSelectSession,
}) {
  const [pos, setPos] = useState(loadPos)
  const [bubble, setBubble] = useState(null)   // 主动说话气泡文字
  const [draft, setDraft] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const drag = useRef(null)                    // {dx, dy, moved}
  const bubbleTimer = useRef(null)

  // 拖动：pointer 事件；移动<5px 视为点击（切换面板）
  const onPointerDown = (e) => {
    e.preventDefault()
    drag.current = { dx: e.clientX - pos.left, dy: e.clientY - pos.top, moved: false, id: e.pointerId }
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e) => {
    if (!drag.current) return
    const left = e.clientX - drag.current.dx
    const top = e.clientY - drag.current.dy
    if (Math.abs(e.clientX - (drag.current.dx + pos.left)) > 4 || Math.abs(e.clientY - (drag.current.dy + pos.top)) > 4) drag.current.moved = true
    const clamp = (v, max) => Math.max(6, Math.min(v, max))
    setPos({ left: clamp(left, window.innerWidth - MASCOT - 6), top: clamp(top, window.innerHeight - MASCOT - 6) })
  }
  const onPointerUp = () => {
    if (!drag.current) return
    const wasClick = !drag.current.moved
    drag.current = null
    try { localStorage.setItem(POS_KEY, JSON.stringify(pos)) } catch { /* ignore */ }
    if (wasClick) { setBubble(null); onOpenChange(!open) }
  }

  const popBubble = (text) => {
    setBubble(text)
    clearTimeout(bubbleTimer.current)
    bubbleTimer.current = setTimeout(() => setBubble(null), 10000)
  }

  // 主动互动调度：每 60s 检查（面板开着 / 已有气泡 时不打扰）
  useEffect(() => {
    // 每次加载把计时重置为「现在」，避免一进来就提醒
    const now = Date.now()
    if (!localStorage.getItem(REST_KEY)) localStorage.setItem(REST_KEY, String(now))
    const id = setInterval(() => {
      if (open || bubble) return
      const t = Date.now()
      const lastRest = Number(localStorage.getItem(REST_KEY) || t)
      if (t - lastRest > REST_AFTER_MIN * 60000) {
        popBubble(pick(REST_LINES)); localStorage.setItem(REST_KEY, String(t)); return
      }
      const lastTip = Number(localStorage.getItem(TIP_KEY) || 0)
      if (t - lastTip > TIP_EVERY_MIN * 60000 && Math.random() < 0.25) {
        popBubble(pick(TIP_LINES)); localStorage.setItem(TIP_KEY, String(t))
      }
    }, 60000)
    return () => { clearInterval(id); clearTimeout(bubbleTimer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, bubble])

  const send = () => {
    const t = draft.trim()
    if (!t || isStreaming) return
    setDraft('')
    onSend(t)
  }

  // 面板位置：贴着吉祥物上方、右边缘对齐，clamp 进视口
  const panelH = Math.min(window.innerHeight - 40, 520)
  let right = window.innerWidth - (pos.left + MASCOT)
  let bottom = window.innerHeight - pos.top + 12
  right = Math.max(8, Math.min(right, window.innerWidth - PANEL_W - 8))
  bottom = Math.max(8, Math.min(bottom, window.innerHeight - panelH - 8))

  return (
    <>
      {/* 聊天面板 */}
      {open && (
        <div style={{
          position: 'fixed', right, bottom, width: PANEL_W, height: panelH, zIndex: 1400,
          display: 'flex', flexDirection: 'column', background: '#161616',
          border: '1px solid rgba(255,255,255,0.13)', borderRadius: 14,
          boxShadow: '0 20px 60px rgba(0,0,0,0.55)', overflow: 'hidden',
        }}>
          {/* 头部 */}
          <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '11px 12px',
                        borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
            <MascotFace size={22} />
            <span style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.87)' }}>蜃景小助手</span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, position: 'relative' }}>
              <HdrBtn title="新建会话" onClick={onNewChat}><PlusIcon /></HdrBtn>
              <HdrBtn title="历史会话" onClick={() => setShowHistory(v => !v)}><HistIcon /></HdrBtn>
              <HdrBtn title="收起" onClick={() => onOpenChange(false)}><span style={{ fontSize: 15, lineHeight: 1 }}>×</span></HdrBtn>
              {showHistory && (
                <div style={{ position: 'absolute', top: 32, right: 0, width: 230, maxHeight: 260, overflowY: 'auto',
                              background: '#0d0d0d', border: '1px solid rgba(255,255,255,0.13)', borderRadius: 10,
                              boxShadow: '0 12px 30px rgba(0,0,0,0.5)', padding: 6, zIndex: 5 }}>
                  {sessions.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 6px' }}>暂无历史会话</div>}
                  {sessions.map(s => (
                    <div key={s.session_id} onClick={() => { onSelectSession?.(s.session_id); setShowHistory(false) }}
                      style={{ padding: '7px 8px', borderRadius: 7, cursor: 'pointer', fontSize: 12,
                               background: s.session_id === sessionId ? 'rgba(255,255,255,0.05)' : 'transparent',
                               color: 'rgba(255,255,255,0.82)' }}
                      onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
                      onMouseLeave={e => e.currentTarget.style.background = s.session_id === sessionId ? 'rgba(255,255,255,0.05)' : 'transparent'}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.title || '新会话'}</div>
                      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{s.message_count ?? 0} 条</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* 消息区（复用 ChatWindow 的 compact 纯文字模式）*/}
          <ChatWindow messages={messages} onResume={onResume} onSend={onSend} compact />

          {/* 输入区（极简）*/}
          <div style={{ flexShrink: 0, borderTop: '1px solid rgba(255,255,255,0.07)', padding: 10,
                        display: 'flex', alignItems: 'flex-end', gap: 8 }}>
            <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
              placeholder="问问蜃景小助手…"
              rows={1}
              style={{
                flex: 1, resize: 'none', maxHeight: 110, minHeight: 36, padding: '8px 10px',
                borderRadius: 9, border: '1px solid rgba(255,255,255,0.13)', background: 'rgba(255,255,255,0.04)',
                color: 'rgba(255,255,255,0.87)', fontSize: 13, fontFamily: 'inherit', outline: 'none', lineHeight: 1.5,
              }}
            />
            {isStreaming ? (
              <button onClick={onStop} title="停止" style={sendBtn('rgba(239,68,68,0.9)')}>停</button>
            ) : (
              <button onClick={send} title="发送" style={sendBtn('#6366f1')}><SendIcon /></button>
            )}
          </div>
        </div>
      )}

      {/* 吉祥物 + 主动气泡 */}
      <div style={{ position: 'fixed', left: pos.left, top: pos.top, zIndex: 1401, touchAction: 'none' }}>
        {bubble && !open && (
          <div onClick={() => setBubble(null)} style={{
            position: 'absolute', bottom: MASCOT + 8, right: 0, width: 200, cursor: 'pointer',
            background: '#161616', border: '1px solid rgba(99,102,241,0.35)', borderRadius: 12,
            boxShadow: '0 10px 30px rgba(0,0,0,0.5)', padding: '9px 12px',
            fontSize: 12.5, lineHeight: 1.55, color: 'rgba(255,255,255,0.87)',
          }}>{bubble}</div>
        )}
        <div
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          title="蜃景小助手（拖我换位置 · 点我聊天）"
          style={{
            width: MASCOT, height: MASCOT, cursor: 'grab', userSelect: 'none',
            animation: 'al-bob 3.4s ease-in-out infinite',
            filter: 'drop-shadow(0 6px 14px rgba(99,102,241,0.4))',
          }}>
          <MascotFace size={MASCOT} active={open} />
        </div>
      </div>
    </>
  )
}

/* ── 吉祥物形象（圆头 + 渐变身体 + 会眨眼 + 小场记板帽）── */
function MascotFace({ size = 58, active = false }) {
  return (
    <svg width={size} height={size} viewBox="0 0 58 58" style={{ display: 'block' }}>
      <defs>
        <linearGradient id="mascotG" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6366f1" /><stop offset="1" stopColor="#4338ca" />
        </linearGradient>
      </defs>
      {/* 身体（圆角方）*/}
      <rect x="6" y="8" width="46" height="44" rx="16" fill="url(#mascotG)" />
      {/* 场记板小帽（顶部条纹）*/}
      <rect x="6" y="8" width="46" height="9" rx="4" fill="rgba(255,255,255,0.16)" />
      <path d="M12 8 L16 17 M20 8 L24 17 M28 8 L32 17 M36 8 L40 17 M44 8 L48 17" stroke="rgba(255,255,255,0.25)" strokeWidth="1.4" />
      {/* 眼睛（会眨）*/}
      <g fill="#fff" style={{ transformOrigin: '29px 32px', animation: 'al-blink-eye 4.6s infinite' }}>
        <ellipse cx="22" cy="32" rx="3.1" ry="4" />
        <ellipse cx="36" cy="32" rx="3.1" ry="4" />
      </g>
      {/* 腮红 + 嘴 */}
      <circle cx="17.5" cy="39" r="2.4" fill="rgba(255,255,255,0.18)" />
      <circle cx="40.5" cy="39" r="2.4" fill="rgba(255,255,255,0.18)" />
      <path d={active ? 'M25 40 q4 5 8 0' : 'M26 41 q3 3 6 0'} stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" />
    </svg>
  )
}

const sendBtn = (bg) => ({
  flexShrink: 0, width: 36, height: 36, borderRadius: 9, border: 'none', background: bg, color: '#fff',
  cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 600,
})
function HdrBtn({ children, onClick, title }) {
  return (
    <button onClick={onClick} title={title} style={{
      width: 26, height: 26, borderRadius: 7, border: '1px solid rgba(255,255,255,0.13)',
      background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.7)', cursor: 'pointer',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    }}>{children}</button>
  )
}
const SendIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 2 11 13" /><path d="M22 2 15 22l-4-9-9-4Z" /></svg>
)
const PlusIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M5 12h14" /><path d="M12 5v14" /></svg>
)
const HistIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v5h5" /><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" /><path d="M12 7v5l4 2" /></svg>
)
