import { useState, useRef, useEffect, useCallback } from 'react'

// 兜底列表（后端 /api/agents 未就绪时用）；正常走后端动态列表
const FALLBACK_AGENTS = [
  { id: 'supervisor', label: 'Supervisor', desc: 'Auto-route to best agent' },
  { id: 'general',   label: 'General',    desc: 'Q&A + RAG, no routing overhead' },
  { id: 'code',      label: 'Code',       desc: 'Code writing & execution' },
  { id: 'file',      label: 'File',       desc: 'File listing & reading' },
  { id: 'shell',     label: 'Shell',      desc: 'Run safe shell commands' },
  { id: 'batch',     label: 'Batch',      desc: 'Parallel map-reduce tasks' },
]

// Slash 命令（在输入框输入 / 唤起）：都是 agent/会话相关命令，不是内容命令
const SLASH_COMMANDS = [
  { cmd: '/new',       desc: '开始一个新会话', action: 'new' },
  { cmd: '/clear',     desc: '清空当前对话内容', action: 'clear' },
  { cmd: '/workspace', desc: '选择本会话的工作目录', action: 'workspace' },
  { cmd: '/compact',   desc: '立即压缩上下文（总结旧消息）', action: 'compact' },
  { cmd: '/agent',     desc: '切换 Agent（supervisor/general/code/file/shell/batch）', action: 'agent' },
  { cmd: '/think',     desc: '切换思考程度（标准/深度思考）', action: 'think' },
  { cmd: '/help',      desc: '查看可用命令', action: 'help' },
]

// 思考程度 → 模型映射
const THINK_LEVELS = [
  { id: 'standard', label: '标准',     model: 'deepseek-chat' },
  { id: 'deep',     label: '深度思考', model: 'deepseek-reasoner' },
]
// 回复/上下文长度档位
const LENGTH_LEVELS = [
  { id: 'short',  label: '短',  max_tokens: 2048 },
  { id: 'medium', label: '中',  max_tokens: 4096 },
  { id: 'long',   label: '长',  max_tokens: 8192 },
]

// 读取/写入 localStorage 里 supervisor 的 LLM 配置（api.js 发请求时会带上）
function readSupCfg() {
  try { return JSON.parse(localStorage.getItem('agentlab_agent_configs') || 'null') || {} }
  catch { return {} }
}
function writeSupCfg(patch) {
  const cfg = readSupCfg()
  cfg.supervisor = { ...(cfg.supervisor || {}), ...patch }
  localStorage.setItem('agentlab_agent_configs', JSON.stringify(cfg))
}

/**
 * InputBar — 底部输入栏
 *
 * - Agent 选择 pill（Supervisor / General / Code / File / Batch）
 * - Enter 发送，Shift+Enter 换行
 * - textarea 随内容自动增高（最高 160px）
 * - 流式回复期间禁用输入
 */
export default function InputBar({ onSend, disabled, agent, onAgentChange,
                                   onNewChat, onClearChat, onOpenWorkspace, onCompact,
                                   agents, onStop }) {
  const [value, setValue] = useState('')
  const [slashIdx, setSlashIdx] = useState(0)
  const textareaRef = useRef(null)
  const AGENTS = (agents && agents.length) ? agents : FALLBACK_AGENTS

  // slash 菜单：输入以 / 开头且无空格时显示匹配命令
  const showSlash = value.startsWith('/') && !value.includes(' ') && !value.includes('\n')
  const slashMatches = showSlash
    ? SLASH_COMMANDS.filter(c => c.cmd.startsWith(value.toLowerCase()))
    : []

  // 思考程度 / 长度：从已存配置反推当前档位
  const sup = readSupCfg().supervisor || {}
  const [think, setThink] = useState(
    () => (sup.model === 'deepseek-reasoner' ? 'deep' : 'standard'))
  const [length, setLength] = useState(() => {
    const mt = sup.max_tokens
    return mt >= 8192 ? 'long' : mt <= 2048 ? 'short' : 'medium'
  })

  const onThinkChange = (id) => {
    setThink(id)
    const lv = THINK_LEVELS.find(l => l.id === id)
    writeSupCfg({ model: lv.model })
  }
  const onLengthChange = (id) => {
    setLength(id)
    const lv = LENGTH_LEVELS.find(l => l.id === id)
    writeSupCfg({ max_tokens: lv.max_tokens })
  }
  const HELP_TEXT = SLASH_COMMANDS.map(c => `${c.cmd} — ${c.desc}`).join('\n')

  // 执行一条命令行（如 "/agent code" / "/new"）。返回 true 表示已作为命令处理。
  const runCommandLine = (line) => {
    const [cmd, ...rest] = line.trim().split(/\s+/)
    const arg = rest.join(' ')
    switch (cmd) {
      case '/new':       onNewChat?.(); return true
      case '/clear':     onClearChat?.(); return true
      case '/workspace': onOpenWorkspace?.(); return true
      case '/compact':   onCompact?.(); return true
      case '/help':      setValue('/'); textareaRef.current?.focus(); return true  // 展开命令菜单
      case '/agent':
        if (arg && AGENTS.some(a => a.id === arg)) onAgentChange?.(arg)
        return true
      case '/think':
        onThinkChange(arg === 'deep' || arg === '深度' ? 'deep' : 'standard'); return true
      default:
        return false
    }
  }

  // slash 菜单选中：无参命令直接执行；带参命令补全成 "/cmd " 等待输入
  const pickSlash = (c) => {
    if (c.action === 'agent' || c.action === 'think') {
      setValue(c.cmd + ' ')
      textareaRef.current?.focus()
    } else {
      runCommandLine(c.cmd)
      setValue('')
    }
  }

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [value])

  useEffect(() => { setSlashIdx(0) }, [value])

  const handleSend = useCallback(() => {
    if (!value.trim() || disabled) return
    // 以 / 开头的整行作为命令处理，不发给 LLM
    if (value.trim().startsWith('/') && runCommandLine(value)) {
      setValue('')
      if (textareaRef.current) textareaRef.current.style.height = 'auto'
      return
    }
    onSend(value)
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [value, disabled, onSend])

  const handleKeyDown = (e) => {
    // slash 菜单导航
    if (showSlash && slashMatches.length > 0) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setSlashIdx(i => (i + 1) % slashMatches.length); return }
      if (e.key === 'ArrowUp')   { e.preventDefault(); setSlashIdx(i => (i - 1 + slashMatches.length) % slashMatches.length); return }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault(); pickSlash(slashMatches[Math.min(slashIdx, slashMatches.length - 1)]); return
      }
    }
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

        {/* 思考程度 + 长度（命令改到输入框内 / 唤起）*/}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8,
        }}>
          <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>输入 <code style={{
            background: 'rgba(255,255,255,0.08)', padding: '1px 5px', borderRadius: 4,
          }}>/</code> 唤起命令</span>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: 'var(--text-dim)', flexShrink: 0 }}>思考</span>
          <select value={think} onChange={e => onThinkChange(e.target.value)} disabled={disabled}
            style={selStyle}>
            {THINK_LEVELS.map(l => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
          <span style={{ fontSize: 11, color: 'var(--text-dim)', flexShrink: 0 }}>长度</span>
          <select value={length} onChange={e => onLengthChange(e.target.value)} disabled={disabled}
            style={selStyle}>
            {LENGTH_LEVELS.map(l => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
        </div>

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

        {/* slash 命令菜单 */}
        {showSlash && slashMatches.length > 0 && (
          <div style={{
            background: 'var(--card)', border: '1px solid var(--border-strong)',
            borderRadius: 12, marginBottom: 6, overflow: 'hidden',
            boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
          }}>
            {slashMatches.map((c, i) => {
              const active = i === Math.min(slashIdx, slashMatches.length - 1)
              return (
                <div key={c.cmd} onMouseDown={e => { e.preventDefault(); pickSlash(c) }}
                  onMouseEnter={() => setSlashIdx(i)}
                  style={{
                    display: 'flex', alignItems: 'baseline', gap: 10, padding: '8px 14px',
                    cursor: 'pointer', background: active ? 'rgba(99,102,241,0.15)' : 'transparent',
                  }}>
                  <span style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 600,
                                 color: 'rgba(165,168,255,0.95)' }}>{c.cmd}</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{c.desc}</span>
                </div>
              )
            })}
          </div>
        )}

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
              onClick={disabled ? onStop : handleSend}
              disabled={!disabled && !canSend}
              title={disabled ? '停止生成' : ''}
              style={{
                height: 30, padding: '0 14px',
                borderRadius: 8, border: 'none',
                fontSize: 12, fontWeight: 600,
                cursor: (disabled || canSend) ? 'pointer' : 'not-allowed',
                display: 'flex', alignItems: 'center', gap: 6,
                transition: 'all 0.15s',
                background: disabled ? 'rgba(239,68,68,0.18)'
                  : canSend ? 'var(--accent)' : 'rgba(255,255,255,0.06)',
                color: disabled ? 'rgba(252,165,165,1)'
                  : canSend ? '#fff' : 'var(--text-dim)',
              }}
              onMouseEnter={e => {
                if (disabled) e.currentTarget.style.background = 'rgba(239,68,68,0.3)'
                else if (canSend) e.currentTarget.style.background = 'var(--accent-hover)'
              }}
              onMouseLeave={e => {
                if (disabled) e.currentTarget.style.background = 'rgba(239,68,68,0.18)'
                else if (canSend) e.currentTarget.style.background = 'var(--accent)'
              }}
            >
              {disabled ? (
                <>
                  <span style={{
                    width: 9, height: 9, borderRadius: 2,
                    background: 'currentColor', display: 'inline-block',
                  }} />
                  停止
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

const selStyle = {
  height: 24, borderRadius: 6, padding: '0 6px', flexShrink: 0,
  border: '1px solid var(--border-strong)', background: 'var(--card)',
  color: 'rgba(255,255,255,0.75)', fontSize: 11, cursor: 'pointer',
}
