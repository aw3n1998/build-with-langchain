import { useState, useEffect } from 'react'

const ENDPOINT_KEY    = 'agentlab_endpoint'
const AGENT_CFG_KEY   = 'agentlab_agent_configs'

const AGENTS = [
  { id: 'supervisor', label: 'Supervisor',  desc: 'Router, aggregator & summarizer' },
  { id: 'code',       label: 'Code Agent',  desc: 'Falls back to Supervisor if unset' },
  { id: 'file',       label: 'File Agent',  desc: 'Falls back to Supervisor if unset' },
  { id: 'general',    label: 'General',     desc: 'Falls back to Supervisor if unset' },
  { id: 'shell',      label: 'Shell Agent', desc: 'Falls back to Supervisor if unset' },
  { id: 'batch',      label: 'Batch',       desc: 'Falls back to Supervisor if unset' },
]

const PRESETS = [
  { label: 'deepseek-chat',     base: 'https://api.deepseek.com/v1',  short: 'DS Chat' },
  { label: 'deepseek-reasoner', base: 'https://api.deepseek.com/v1',  short: 'DS R1' },
  { label: 'gpt-4o-mini',       base: 'https://api.openai.com/v1',    short: 'GPT mini' },
  { label: 'gpt-4o',            base: 'https://api.openai.com/v1',    short: 'GPT-4o' },
]

const EMPTY_CFG = () => ({ model: '', api_base: '', api_key: '' })

function cfgIsEmpty(c) {
  return !c || (!c.model && !c.api_base && !c.api_key)
}

function cfgSummary(c, agentId) {
  if (cfgIsEmpty(c)) return agentId === 'supervisor' ? 'using .env default' : 'using Supervisor'
  const parts = []
  if (c.model)    parts.push(c.model)
  if (c.api_base) parts.push(c.api_base.replace('https://', '').split('/')[0])
  if (c.api_key)  parts.push('key ••••')
  return parts.join(' · ')
}

/**
 * SettingsPanel — 每 Agent 独立 LLM 配置面板
 *
 * 右侧抽屉，由 TopBar 设置图标触发。
 * 顶部：Backend Endpoint（FastAPI 服务器地址）
 * 主体：5 个可折叠 Agent 配置块，每块含：
 *         preset chips + Model + API Base URL + API Key
 * 所有配置写 localStorage，下次发消息时即生效（per-request）。
 */
export default function SettingsPanel({ open, onClose, onSaved, videoOnly = false }) {
  // 视频专用模式：只暴露 supervisor 这一个 LLM 配置（视频 agent 用它的模型）；
  // code/file/general/shell/batch 在该模式下永不执行，配了也误导 —— 隐藏但保留状态/链路。
  const visibleAgents = videoOnly ? AGENTS.filter(a => a.id === 'supervisor') : AGENTS
  const [endpoint, setEndpoint] = useState('')
  // agentCfgs: { supervisor: {model,api_base,api_key}, code: {...}, ... }
  const [agentCfgs, setAgentCfgs] = useState(() =>
    Object.fromEntries(AGENTS.map(a => [a.id, EMPTY_CFG()]))
  )
  const [expanded, setExpanded] = useState({})  // { agentId: bool }
  const [showKey,  setShowKey]  = useState({})  // { agentId: bool }
  const [saved,    setSaved]    = useState(false)

  useEffect(() => {
    if (!open) return
    setEndpoint(localStorage.getItem(ENDPOINT_KEY) || '')
    const stored = JSON.parse(localStorage.getItem(AGENT_CFG_KEY) || 'null') || {}
    setAgentCfgs(
      Object.fromEntries(
        AGENTS.map(a => [a.id, stored[a.id] ? { ...EMPTY_CFG(), ...stored[a.id] } : EMPTY_CFG()])
      )
    )
    setSaved(false)
    setExpanded({})
    setShowKey({})
  }, [open])

  const updateField = (agentId, field, value) => {
    setAgentCfgs(prev => ({
      ...prev,
      [agentId]: { ...prev[agentId], [field]: value },
    }))
  }

  const applyPreset = (agentId, preset) => {
    setAgentCfgs(prev => ({
      ...prev,
      [agentId]: { ...prev[agentId], model: preset.label, api_base: preset.base },
    }))
  }

  const clearAgent = (agentId) => {
    setAgentCfgs(prev => ({ ...prev, [agentId]: EMPTY_CFG() }))
  }

  const handleSave = () => {
    // 写 endpoint
    if (endpoint.trim()) localStorage.setItem(ENDPOINT_KEY, endpoint.trim())
    else localStorage.removeItem(ENDPOINT_KEY)

    // 写 agent_configs（只保存非空的 agent）
    const toSave = {}
    for (const a of AGENTS) {
      const c = agentCfgs[a.id]
      if (!cfgIsEmpty(c)) toSave[a.id] = { ...c }
    }
    if (Object.keys(toSave).length > 0) {
      localStorage.setItem(AGENT_CFG_KEY, JSON.stringify(toSave))
    } else {
      localStorage.removeItem(AGENT_CFG_KEY)
    }

    onSaved?.()
    setSaved(true)
    setTimeout(() => setSaved(false), 1800)
  }

  const handleReset = () => {
    localStorage.removeItem(ENDPOINT_KEY)
    localStorage.removeItem(AGENT_CFG_KEY)
    setEndpoint('')
    setAgentCfgs(Object.fromEntries(AGENTS.map(a => [a.id, EMPTY_CFG()])))
    onSaved?.()
    setSaved(true)
    setTimeout(() => setSaved(false), 1800)
  }

  return (
    <>
      {open && (
        <div onClick={onClose} style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.5)', zIndex: 40,
          backdropFilter: 'blur(2px)',
        }} />
      )}

      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0,
        width: 'min(420px,92vw)',
        background: '#0d0d0d',
        borderLeft: '1px solid var(--border-strong)',
        zIndex: 50,
        display: 'flex', flexDirection: 'column',
        transform: open ? 'translateX(0)' : 'translateX(100%)',
        transition: 'transform 0.22s cubic-bezier(0.4,0,0.2,1)',
        boxShadow: open ? '-12px 0 40px rgba(0,0,0,0.5)' : 'none',
      }}>

        {/* 头部 */}
        <div style={{
          flexShrink: 0,
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '16px 20px',
          borderBottom: '1px solid var(--border)',
        }}>
          <GearIcon />
          <div>
            <p style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>
              Settings
            </p>
            <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>
              Per-agent LLM configuration
            </p>
          </div>
          <CloseBtn onClick={onClose} />
        </div>

        {/* 滚动内容区 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '18px 20px' }}>

          {/* ── Backend Endpoint ── */}
          <div style={{ marginBottom: 18 }}>
            <SectionLabel>Backend Endpoint</SectionLabel>
            <input
              type="text"
              value={endpoint}
              onChange={e => setEndpoint(e.target.value)}
              placeholder="http://localhost:8000/api  (blank = Vite proxy)"
              style={endpointInputStyle}
            />
            <p style={hintStyle}>FastAPI server address. Leave blank to use the default proxy.</p>
          </div>

          {/* ── Per-Agent 配置块 ── */}
          <div>
            <div style={{ marginBottom: 10 }}>
              <p style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
                          color: 'var(--text-dim)', textTransform: 'uppercase' }}>
                {videoOnly ? '模型配置' : 'Agent LLM Configuration'}
              </p>
              <p style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 3 }}>
                {videoOnly
                  ? '短剧的拆分镜 / 旁白 / 对话都用这个模型（留空走 .env 默认）。'
                  : 'Each agent can use a different model. Sub-agents fall back to Supervisor if not set.'}
              </p>
            </div>

            {visibleAgents.map(a => {
              const cfg = agentCfgs[a.id]
              const isOpen = !!expanded[a.id]
              const isEmpty = cfgIsEmpty(cfg)
              const summary = cfgSummary(cfg, a.id)
              const label = (videoOnly && a.id === 'supervisor') ? '对话 / 导演模型' : a.label

              return (
                <div key={a.id} style={{
                  border: '1px solid var(--border)',
                  borderRadius: 10,
                  background: '#161616',
                  marginBottom: 10,
                  overflow: 'hidden',
                }}>
                  {/* 折叠标题行 */}
                  <button
                    onClick={() => setExpanded(prev => ({ ...prev, [a.id]: !isOpen }))}
                    style={{
                      width: '100%', display: 'flex', alignItems: 'center',
                      padding: '11px 16px', gap: 8,
                      background: 'transparent',
                      border: 'none', cursor: 'pointer',
                      transition: 'background 0.12s',
                    }}
                  >
                    {/* 折叠箭头 */}
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
                         style={{ flexShrink: 0, color: 'var(--text-dim)',
                                  transform: isOpen ? 'rotate(90deg)' : 'rotate(0)',
                                  transition: 'transform 0.15s' }}>
                      <path d="M3 2l4 3-4 3" stroke="currentColor" strokeWidth="1.5"
                            strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>

                    <span style={{ fontSize: 12.5, fontWeight: 600,
                                   color: isEmpty ? 'var(--text-sec)' : 'var(--text)',
                                   flex: 1, textAlign: 'left' }}>
                      {label}
                    </span>

                    {/* 配置摘要 */}
                    <span style={{ fontSize: 10, color: 'var(--text-dim)',
                                   fontFamily: "'SF Mono',ui-monospace,monospace", maxWidth: 160,
                                   overflow: 'hidden', textOverflow: 'ellipsis',
                                   whiteSpace: 'nowrap' }}>
                      {summary}
                    </span>

                    {/* 非空时显示清除按钮 */}
                    {!isEmpty && (
                      <span
                        role="button"
                        onClick={e => { e.stopPropagation(); clearAgent(a.id) }}
                        style={{
                          fontSize: 10, color: 'var(--text-dim)',
                          padding: '1px 5px', borderRadius: 4,
                          border: '1px solid var(--border-strong)',
                          flexShrink: 0,
                          cursor: 'pointer',
                        }}
                      >
                        clear
                      </span>
                    )}
                  </button>

                  {/* 展开区域 */}
                  {isOpen && (
                    <div style={{
                      padding: '4px 16px 14px',
                      borderTop: '1px solid var(--border)',
                    }}>
                      {/* Preset chips */}
                      <p style={{ ...labelStyle, marginTop: 10, marginBottom: 8 }}>Preset</p>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 13 }}>
                        {PRESETS.map(p => {
                          const active = cfg.model === p.label && cfg.api_base === p.base
                          return (
                            <button
                              key={p.label}
                              onClick={() => applyPreset(a.id, p)}
                              title={`${p.label}\n${p.base}`}
                              style={{
                                height: 24, padding: '0 9px',
                                borderRadius: 6,
                                border: `1px solid ${active ? 'rgba(99,102,241,0.4)' : 'var(--border-strong)'}`,
                                background: active ? 'rgba(99,102,241,0.12)' : 'rgba(255,255,255,0.04)',
                                color: active ? '#a5a8ff' : 'var(--text-sec)',
                                fontSize: 11, cursor: 'pointer',
                                fontFamily: 'inherit',
                                transition: 'all 0.12s',
                              }}
                            >
                              {p.short}
                            </button>
                          )
                        })}
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                        <LabeledInput
                          label="Model Name"
                          value={cfg.model}
                          onChange={v => updateField(a.id, 'model', v)}
                          placeholder="e.g. deepseek-chat"
                        />
                        <LabeledInput
                          label="API Base URL"
                          value={cfg.api_base}
                          onChange={v => updateField(a.id, 'api_base', v)}
                          placeholder="https://api.deepseek.com/v1"
                        />
                        <div>
                          <p style={labelStyle}>API Key</p>
                          <div style={{ display: 'flex', gap: 7 }}>
                            <input
                              type={showKey[a.id] ? 'text' : 'password'}
                              value={cfg.api_key}
                              onChange={e => updateField(a.id, 'api_key', e.target.value)}
                              placeholder="sk-••••••••••••••••"
                              style={{ ...inputStyle, flex: 1, width: 'auto' }}
                            />
                            <button
                              onClick={() => setShowKey(prev => ({ ...prev, [a.id]: !prev[a.id] }))}
                              style={{
                                width: 32, flexShrink: 0,
                                borderRadius: 8,
                                border: '1px solid var(--border-strong)',
                                background: 'rgba(255,255,255,0.04)',
                                cursor: 'pointer',
                                color: 'var(--text-sec)', padding: 0,
                                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                              }}
                            >
                              {showKey[a.id] ? <EyeOffIcon /> : <EyeIcon />}
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* 底部操作 */}
        <div style={{
          padding: '12px 20px', flexShrink: 0,
          borderTop: '1px solid var(--border)',
          display: 'flex', gap: 10,
        }}>
          <button onClick={handleReset} style={secondaryBtnStyle}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = 'rgba(255,255,255,0.25)'
              e.currentTarget.style.background = 'rgba(255,255,255,0.08)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'var(--border-strong)'
              e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
            }}
          >
            Reset all
          </button>
          <button onClick={handleSave} style={{
            ...primaryBtnStyle,
            background: saved ? 'rgba(52,211,153,0.2)' : 'var(--accent)',
            color: saved ? '#34d399' : '#fff',
          }}>
            {saved ? 'Saved' : 'Save changes'}
          </button>
        </div>
      </div>
    </>
  )
}

/* ── 小组件 ──────────────────────────────────────────────── */

function SectionLabel({ children }) {
  return (
    <p style={{ ...labelStyle, marginBottom: 6 }}>{children}</p>
  )
}

function LabeledInput({ label, value, onChange, placeholder }) {
  return (
    <div>
      <p style={labelStyle}>{label}</p>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={inputStyle}
      />
    </div>
  )
}

function GearIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="rgba(255,255,255,0.7)" strokeWidth="1.7"
         strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82 2 2 0 1 1-2.83 2.83 1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51 2 2 0 0 1-4 0 1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33 2 2 0 1 1-2.83-2.83 1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1 2 2 0 0 1 0-4 1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82 2 2 0 1 1 2.83-2.83 1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51 2 2 0 0 1 4 0 1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33 2 2 0 1 1 2.83 2.83 1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1 2 2 0 0 1 0 4 1.65 1.65 0 0 0-1.51 1Z"/>
    </svg>
  )
}

function CloseBtn({ onClick }) {
  return (
    <button onClick={onClick} style={{
      marginLeft: 'auto',
      width: 28, height: 28, borderRadius: 7,
      border: '1px solid var(--border-strong)',
      background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.7)',
      cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
      transition: 'all 0.15s',
    }}
      onMouseEnter={e => {
        e.currentTarget.style.background = 'rgba(255,255,255,0.08)'
        e.currentTarget.style.color = 'rgba(255,255,255,0.87)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
        e.currentTarget.style.color = 'rgba(255,255,255,0.7)'
      }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M18 6L6 18M6 6l12 12"/>
      </svg>
    </button>
  )
}

function EyeIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  )
}

function EyeOffIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94"/>
      <path d="M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19"/>
      <line x1="1" y1="1" x2="23" y2="23"/>
    </svg>
  )
}

const inputStyle = {
  width: '100%', boxSizing: 'border-box',
  background: 'rgba(255,255,255,0.04)',
  border: '1px solid var(--border-strong)',
  borderRadius: 8, padding: '7px 10px',
  fontSize: 12, color: 'var(--text)',
  outline: 'none',
  fontFamily: "'SF Mono',ui-monospace,monospace",
}
const endpointInputStyle = {
  ...inputStyle,
  color: '#86efac',
}
const labelStyle = {
  fontSize: 10, fontWeight: 600, color: 'var(--text-muted)',
  textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4,
  display: 'block',
}
const hintStyle = {
  fontSize: 11, color: 'var(--text-dim)', marginTop: 5, lineHeight: 1.55,
}
const secondaryBtnStyle = {
  flex: 1, height: 34, borderRadius: 8,
  border: '1px solid var(--border-strong)',
  background: 'rgba(255,255,255,0.04)', color: 'var(--text)',
  fontSize: 12.5, cursor: 'pointer', transition: 'all 0.15s',
}
const primaryBtnStyle = {
  flex: 1, height: 34, borderRadius: 8, border: 'none',
  fontSize: 12.5, fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
}
