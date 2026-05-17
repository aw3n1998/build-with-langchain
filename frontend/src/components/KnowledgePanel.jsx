import { useState } from 'react'
import { ingestFile, ingestText, getStatus } from '../api'

/**
 * KnowledgePanel — 知识库导入面板
 *
 * 从右侧滑出的抽屉，由 TopBar 的 "Knowledge Base" 按钮触发。
 * 支持文件上传（PDF / TXT / DOCX）和文本粘贴导入。
 */
export default function KnowledgePanel({ open, onClose, onStatusChange }) {
  const [tab, setTab] = useState('file')        // 'file' | 'text'
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null) // { ok: bool, msg: string }

  const [fileProjectId, setFileProjectId] = useState('default')
  const [textContent, setTextContent]     = useState('')
  const [sourceName, setSourceName]       = useState('')
  const [textProjectId, setTextProjectId] = useState('default')

  const refreshStatus = async () => {
    try { onStatusChange(await getStatus()) } catch {}
  }

  const handleFileChange = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setBusy(true)
    setFeedback(null)
    try {
      const res = await ingestFile(file, fileProjectId)
      setFeedback({ ok: res.success, msg: res.message })
      await refreshStatus()
    } catch (err) {
      setFeedback({ ok: false, msg: `Upload failed: ${err.message}` })
    } finally {
      setBusy(false)
      e.target.value = ''
    }
  }

  const handleTextImport = async () => {
    if (!textContent.trim()) return
    setBusy(true)
    setFeedback(null)
    try {
      const res = await ingestText(textContent, sourceName || 'inline', textProjectId)
      setFeedback({ ok: res.success, msg: res.message })
      if (res.success) setTextContent('')
      await refreshStatus()
    } catch (err) {
      setFeedback({ ok: false, msg: `Import failed: ${err.message}` })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {/* 遮罩 */}
      {open && (
        <div
          onClick={onClose}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.45)',
            zIndex: 40,
            backdropFilter: 'blur(2px)',
          }}
        />
      )}

      {/* 抽屉面板 */}
      <div style={{
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        width: 320,
        background: '#111111',
        borderLeft: '1px solid var(--border)',
        zIndex: 50,
        display: 'flex',
        flexDirection: 'column',
        transform: open ? 'translateX(0)' : 'translateX(100%)',
        transition: 'transform 0.22s cubic-bezier(0.4,0,0.2,1)',
        boxShadow: open ? '-8px 0 32px rgba(0,0,0,0.5)' : 'none',
      }}>
        {/* 头部 */}
        <div style={{
          height: 52,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          <div>
            <p style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>
              Knowledge Base
            </p>
            <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>
              Import documents for RAG retrieval
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 28, height: 28,
              borderRadius: 7, border: 'none',
              background: 'transparent',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16,
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = 'rgba(255,255,255,0.08)'
              e.currentTarget.style.color = 'rgba(255,255,255,0.7)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = 'transparent'
              e.currentTarget.style.color = 'var(--text-muted)'
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>

        {/* Tab 切换 */}
        <div style={{
          display: 'flex',
          gap: 2,
          padding: '12px 14px 0',
          flexShrink: 0,
        }}>
          {[
            { id: 'file', label: 'Upload File' },
            { id: 'text', label: 'Paste Text'  },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => { setTab(t.id); setFeedback(null) }}
              style={{
                flex: 1,
                height: 30,
                borderRadius: 7,
                border: 'none',
                fontSize: 12,
                fontWeight: 500,
                cursor: 'pointer',
                transition: 'all 0.15s',
                background: tab === t.id ? 'rgba(255,255,255,0.08)' : 'transparent',
                color: tab === t.id ? 'rgba(255,255,255,0.8)' : 'var(--text-muted)',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* 内容区（可滚动） */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 14 }}>
          {tab === 'file' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Project ID */}
              <Field label="Project ID">
                <TextInput
                  value={fileProjectId}
                  onChange={setFileProjectId}
                  placeholder="default"
                />
              </Field>

              {/* 上传区 */}
              <label style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: 110,
                borderRadius: 10,
                border: `1.5px dashed ${busy ? 'var(--border)' : 'var(--border-strong)'}`,
                cursor: busy ? 'not-allowed' : 'pointer',
                color: busy ? 'var(--text-dim)' : 'var(--text-muted)',
                transition: 'all 0.15s',
                gap: 6,
              }}
                onMouseEnter={e => {
                  if (!busy) e.currentTarget.style.borderColor = 'rgba(99,102,241,0.5)'
                }}
                onMouseLeave={e => {
                  if (!busy) e.currentTarget.style.borderColor = 'var(--border-strong)'
                }}
              >
                {busy ? (
                  <>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" strokeWidth="1.5"
                         style={{ animation: 'spin 1s linear infinite' }}>
                      <circle cx="12" cy="12" r="10" strokeOpacity="0.25"/>
                      <path d="M12 2a10 10 0 0110 10" strokeLinecap="round"/>
                    </svg>
                    <span style={{ fontSize: 12 }}>Uploading...</span>
                  </>
                ) : (
                  <>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                      <polyline points="17 8 12 3 7 8"/>
                      <line x1="12" y1="3" x2="12" y2="15"/>
                    </svg>
                    <span style={{ fontSize: 12, fontWeight: 500 }}>Click to upload</span>
                    <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>PDF · TXT · DOCX</span>
                  </>
                )}
                <input
                  type="file"
                  accept=".txt,.pdf,.docx"
                  style={{ display: 'none' }}
                  onChange={handleFileChange}
                  disabled={busy}
                />
              </label>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <Field label="Source name">
                <TextInput value={sourceName} onChange={setSourceName} placeholder="inline" />
              </Field>
              <Field label="Project ID">
                <TextInput value={textProjectId} onChange={setTextProjectId} placeholder="default" />
              </Field>
              <Field label="Content">
                <textarea
                  value={textContent}
                  onChange={e => setTextContent(e.target.value)}
                  rows={8}
                  placeholder="Paste text to import..."
                  style={{
                    width: '100%',
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid var(--border-strong)',
                    borderRadius: 8,
                    padding: '8px 10px',
                    fontSize: 13,
                    color: 'var(--text)',
                    resize: 'vertical',
                    outline: 'none',
                    fontFamily: 'inherit',
                    lineHeight: 1.6,
                    boxSizing: 'border-box',
                  }}
                />
              </Field>

              <button
                onClick={handleTextImport}
                disabled={busy || !textContent.trim()}
                style={{
                  height: 34,
                  borderRadius: 8,
                  border: 'none',
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: busy || !textContent.trim() ? 'not-allowed' : 'pointer',
                  background: busy || !textContent.trim()
                    ? 'rgba(255,255,255,0.06)'
                    : 'var(--accent)',
                  color: busy || !textContent.trim() ? 'var(--text-dim)' : '#fff',
                  transition: 'all 0.15s',
                }}
              >
                {busy ? 'Importing...' : 'Import Text'}
              </button>
            </div>
          )}

          {/* 操作反馈 */}
          {feedback && (
            <div style={{
              marginTop: 12,
              padding: '10px 12px',
              borderRadius: 8,
              fontSize: 12,
              lineHeight: 1.6,
              background: feedback.ok ? 'rgba(52,211,153,0.08)' : 'rgba(239,68,68,0.08)',
              border: `1px solid ${feedback.ok ? 'rgba(52,211,153,0.25)' : 'rgba(239,68,68,0.25)'}`,
              color: feedback.ok ? '#34d399' : '#f87171',
            }}>
              {feedback.msg}
            </div>
          )}
        </div>

        {/* 底部提示 */}
        <div style={{
          padding: '12px 16px',
          borderTop: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          <p style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.6 }}>
            After importing, ask questions in the chat. The agent will automatically retrieve relevant context.
          </p>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
      `}</style>
    </>
  )
}

/* ── 子组件 ──────────────────────────── */

function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <label style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500 }}>
        {label}
      </label>
      {children}
    </div>
  )
}

function TextInput({ value, onChange, placeholder }) {
  return (
    <input
      type="text"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid var(--border-strong)',
        borderRadius: 8,
        padding: '7px 10px',
        fontSize: 13,
        color: 'var(--text)',
        outline: 'none',
        width: '100%',
        fontFamily: 'inherit',
        boxSizing: 'border-box',
      }}
    />
  )
}
