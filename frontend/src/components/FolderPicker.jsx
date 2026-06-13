import { useState, useEffect } from 'react'
import { fsList } from '../api'

/**
 * FolderPicker — 服务器端文件夹浏览选择器（模态）。
 * 浏览 /api/fs/list 返回的目录树，用户点进/返回上级，选定后回传绝对路径。
 */
export default function FolderPicker({ open, initial, onClose, onPick }) {
  const [path, setPath]   = useState('')
  const [dirs, setDirs]   = useState([])
  const [parent, setParent] = useState(null)
  const [err, setErr]     = useState('')
  const [loading, setLoading] = useState(false)

  const load = async (p) => {
    setLoading(true); setErr('')
    try {
      const data = await fsList(p)
      setPath(data.path || '')
      setDirs(data.dirs || [])
      setParent(data.parent)
    } catch (e) {
      setErr(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    // 打开时：有已选目录则从它的上一级进入，否则列盘符/根
    const start = initial ? initial.replace(/[\\/][^\\/]*$/, '') : ''
    load(start)
  }, [open, initial])

  if (!open) return null

  const baseName = (p) => p.replace(/[\\/]$/, '').split(/[\\/]/).pop() || p

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        position: 'relative', width: 560, maxWidth: '92vw', background: '#161616',
        border: '1px solid var(--border-strong)', borderRadius: 14,
        boxShadow: '0 20px 60px rgba(0,0,0,0.6)', overflow: 'hidden',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* 头部 */}
        <div style={{
          padding: '16px 20px', display: 'flex', alignItems: 'center',
          borderBottom: '1px solid var(--border)',
        }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>选择工作目录</span>
          <button onClick={onClose} style={{
            marginLeft: 'auto', width: 28, height: 28, borderRadius: 7,
            border: '1px solid var(--border-strong)', background: 'rgba(255,255,255,0.04)',
            color: 'rgba(255,255,255,0.7)', display: 'inline-flex', alignItems: 'center',
            justifyContent: 'center', fontSize: 15, cursor: 'pointer', fontFamily: 'inherit',
          }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.08)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.04)'}
          >×</button>
        </div>

        <div style={{ padding: '18px 20px' }}>
          {/* 当前路径 + 手动输入 */}
          <input
            value={path}
            onChange={e => setPath(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') load(path) }}
            placeholder="输入绝对路径回车跳转，或下方点选"
            style={{
              width: '100%', height: 32, padding: '0 10px', borderRadius: 7,
              border: '1px solid var(--border-strong)', background: 'rgba(255,255,255,0.04)',
              color: 'var(--text)', fontSize: 12.5,
              fontFamily: "'SF Mono',ui-monospace,monospace", outline: 'none',
              marginBottom: 14, boxSizing: 'border-box',
            }}
          />

          {err && <div style={{ fontSize: 12, color: 'rgba(239,68,68,0.85)', marginBottom: 14 }}>{err}</div>}

          {/* 目录列表 */}
          <div style={{
            overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 10,
            background: '#0d0d0d', minHeight: 200, maxHeight: 320,
          }}>
            {parent !== null && (
              <DirRow label=".. 返回上级" onClick={() => load(parent)} up />
            )}
            {loading ? (
              <div style={{ padding: 16, fontSize: 12.5, color: 'var(--text-sec)' }}>加载中…</div>
            ) : dirs.length === 0 ? (
              <div style={{ padding: 16, fontSize: 12.5, color: 'var(--text-sec)' }}>（无子目录）</div>
            ) : dirs.map(d => (
              <DirRow key={d} label={baseName(d)} onClick={() => load(d)} />
            ))}
          </div>

          {/* 底部操作 */}
          <div style={{ display: 'flex', gap: 10, marginTop: 16, justifyContent: 'flex-end' }}>
            <button onClick={() => onPick('')}
              style={{
                height: 34, padding: '0 14px', borderRadius: 8,
                border: '1px solid var(--border-strong)', background: 'rgba(255,255,255,0.04)',
                color: 'var(--text)', fontSize: 12.5, cursor: 'pointer', fontFamily: 'inherit',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.08)'}
              onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.04)'}
            >
              用默认目录
            </button>
            <button
              onClick={() => path && onPick(path)}
              disabled={!path}
              style={{
                height: 34, padding: '0 16px', borderRadius: 8, border: 'none',
                background: '#6366f1', color: '#fff', fontSize: 12.5, fontWeight: 600,
                fontFamily: 'inherit',
                opacity: path ? 1 : 0.5, cursor: path ? 'pointer' : 'not-allowed',
              }}
              onMouseEnter={e => { if (path) e.currentTarget.style.background = '#5254cc' }}
              onMouseLeave={e => { e.currentTarget.style.background = '#6366f1' }}
            >
              选定此目录
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function DirRow({ label, onClick, up }) {
  return (
    <div onClick={onClick} style={{
      height: 38, display: 'flex', alignItems: 'center', gap: 8, padding: '0 14px',
      fontSize: 12.5, color: up ? 'var(--text-sec)' : 'var(--text)',
      cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.05)',
    }}
      onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.03)'}
      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
    >
      {up ? (
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
      ) : (
        <>
          <span style={{ color: 'rgba(255,255,255,0.3)', fontFamily: "'SF Mono',ui-monospace,monospace" }}>/</span>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
        </>
      )}
    </div>
  )
}
