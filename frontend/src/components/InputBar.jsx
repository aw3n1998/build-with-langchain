import { useState, useRef, useEffect, useCallback } from 'react'

const AGENTS = [
  { id: 'supervisor', label: 'Supervisor', desc: 'Auto-route to best agent' },
  { id: 'general',   label: 'General',    desc: 'Q&A + RAG, no routing overhead' },
  { id: 'code',      label: 'Code',       desc: 'Code writing & execution' },
  { id: 'file',      label: 'File',       desc: 'File listing & reading' },
  { id: 'shell',     label: 'Shell',      desc: 'Run safe shell commands' },
  { id: 'batch',     label: 'Batch',      desc: 'Parallel map-reduce tasks' },
]

/**
 * InputBar — 底部输入栏
 *
 * - Agent 选择 pill（Supervisor / General / Code / File / Batch）
 * - Enter 发送，Shift+Enter 换行
 * - textarea 随内容自动增高（最高 160px）
 * - 流式回复期间禁用输入
 */
export default function InputBar({ onSend, disabled, agent, onAgentChange }) {
  const [value, setValue] = useState('')
  const textareaRef = useRef(null)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [value])

  const handleSend = useCallback(() => {
    if (!value.trim() || disabled) return
    onSend(value)
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [value, disabled, onSend])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const canSend = value.trim().length > 0 && !disabled
  const activeAgent = AGENTS.find(a => a.id === agent) || AGENTS[0]

  return (
    <footer style={{
      flexShrink: 0,
      padding: '8px 20px 20px',
      background: 'transparent',
    }}>
      <div style={{ maxWidth: 760, margin: '0 auto' }}>

        {/* Agent 选择器 */}
        <div style={{
          display: 'flex', gap: 5,
          marginBottom: 8,
          overflowX: 'auto',
          paddingBottom: 2,
        }}>
          {AGENTS.map(a => {
            const active = a.id === agent
            return (
              <button
                key={a.id}
                onClick={() => onAgentChange?.(a.id)}
                disabled={disabled}
                title={a.desc}
                style={{
                  height: 24, padding: '0 10px',
                  borderRadius: 6,
                  border: `1px solid ${active ? 'rgba(99,102,241,0.55)' : 'var(--border-strong)'}`,
                  background: active ? 'rgba(99,102,241,0.18)' : 'transparent',
                  color: active ? 'rgba(255,255,255,0.85)' : 'var(--text-muted)',
                  fontSize: 11, fontWeight: active ? 500 : 400,
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  whiteSpace: 'nowrap',
                  transition: 'all 0.12s',
                  flexShrink: 0,
                  opacity: disabled ? 0.5 : 1,
                }}
                onMouseEnter={e => {
                  if (!disabled && !active) {
                    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.22)'
                    e.currentTarget.style.color = 'rgba(255,255,255,0.65)'
                  }
                }}
                onMouseLeave={e => {
                  if (!disabled && !active) {
                    e.currentTarget.style.borderColor = 'var(--border-strong)'
                    e.currentTarget.style.color = 'var(--text-muted)'
                  }
                }}
              >
                {a.label}
              </button>
            )
          })}
          {/* 当前 agent 描述 */}
          <span style={{
            fontSize: 11, color: 'var(--text-dim)',
            display: 'flex', alignItems: 'center',
            marginLeft: 4,
            whiteSpace: 'nowrap',
          }}>
            — {activeAgent.desc}
          </span>
        </div>

        {/* 输入卡片 */}
        <div style={{
          background: 'var(--card)',
          border: `1px solid ${disabled ? 'var(--border)' : 'var(--border-strong)'}`,
          borderRadius: 14,
          padding: '12px 14px 10px',
          transition: 'border-color 0.15s',
          boxShadow: '0 2px 12px rgba(0,0,0,0.3)',
        }}>
          <textarea
            ref={textareaRef}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            rows={1}
            placeholder={disabled ? 'Responding...' : 'Ask anything about your knowledge base...'}
            style={{
              width: '100%',
              background: 'transparent',
              border: 'none', outline: 'none',
              resize: 'none',
              fontSize: 14, lineHeight: 1.7,
              color: disabled ? 'var(--text-muted)' : 'var(--text)',
              caretColor: 'var(--accent)',
              maxHeight: 160,
              fontFamily: 'inherit',
              display: 'block',
            }}
          />

          {/* 底部工具栏 */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginTop: 8,
          }}>
            <span style={{
              fontSize: 11, color: 'var(--text-dim)',
              fontFamily: 'monospace', userSelect: 'none',
            }}>
              Return to send · Shift+Return for newline
            </span>

            <button
              onClick={handleSend}
              disabled={!canSend}
              style={{
                height: 30, padding: '0 14px',
                borderRadius: 8, border: 'none',
                fontSize: 12, fontWeight: 600,
                cursor: canSend ? 'pointer' : 'not-allowed',
                display: 'flex', alignItems: 'center', gap: 6,
                transition: 'all 0.15s',
                background: canSend ? 'var(--accent)' : 'rgba(255,255,255,0.06)',
                color: canSend ? '#fff' : 'var(--text-dim)',
              }}
              onMouseEnter={e => {
                if (canSend) e.currentTarget.style.background = 'var(--accent-hover)'
              }}
              onMouseLeave={e => {
                if (canSend) e.currentTarget.style.background = 'var(--accent)'
              }}
            >
              {disabled ? (
                <>
                  <span style={{
                    width: 10, height: 10, borderRadius: '50%',
                    border: '2px solid rgba(255,255,255,0.3)',
                    borderTopColor: 'rgba(255,255,255,0.8)',
                    display: 'inline-block',
                    animation: 'spin 0.7s linear infinite',
                  }} />
                  Thinking
                </>
              ) : (
                <>
                  Send
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M5 12h14M12 5l7 7-7 7"/>
                  </svg>
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
      `}</style>
    </footer>
  )
}
