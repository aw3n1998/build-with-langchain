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
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 560, maxHeight: '70vh', background: 'var(--card)',
        border: '1px solid var(--border)', borderRadius: 12, padding: 18,
        display: 'flex', flexDirection: 'column', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>选择工作目录</span>
          <button onClick={onClose} style={{
            marginLeft: 'auto', background: 'none', border: 'none', color: 'var(--text-muted)',
            fontSize: 18, cursor: 'pointer',
          }}>×</button>
        </div>

        {/* 当前路径 + 手动输入 */}
        <input
          value={path}
          onChange={e => setPath(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') load(path) }}
          placeholder="输入绝对路径回车跳转，或下方点选"
          style={{
            width: '100%', height: 32, padding: '0 10px', borderRadius: 8,
            border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)',
            color: 'rgba(255,255,255,0.85)', fontSize: 12, fontFamily: 'monospace',
          }}
        />

        {err && <div style={{ fontSize: 12, color: 'rgba(239,68,68,0.85)' }}>{err}</div>}

        {/* 目录列表 */}
        <div style={{
          flex: 1, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8,
          minHeight: 200, maxHeight: 320,
        }}>
          {parent !== null && (
            <DirRow label=".. 返回上级" onClick={() => load(parent)} up />
          )}
          {loading ? (
            <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)' }}>加载中…</div>
          ) : dirs.length === 0 ? (
            <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)' }}>（无子目录）</div>
          ) : dirs.map(d => (
            <DirRow key={d} label={baseName(d)} onClick={() => load(d)} />
          ))}
        </div>

        {/* 底部操作 */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => onPick('')} style={btnStyle('rgba(255,255,255,0.06)', 'rgba(255,255,255,0.6)')}>
            用默认目录
          </button>
          <button
            onClick={() => path && onPick(path)}
            disabled={!path}
            style={{ ...btnStyle('rgba(99,102,241,0.18)', 'rgba(165,168,255,0.95)'), marginLeft: 'auto',
                     opacity: path ? 1 : 0.5, cursor: path ? 'pointer' : 'not-allowed' }}
          >
            ✓ 选定此目录
          </button>
        </div>
      </div>
    </div>
  )
}

function DirRow({ label, onClick, up }) {
  return (
    <div onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
      fontSize: 13, color: up ? 'var(--text-muted)' : 'rgba(255,255,255,0.8)',
      cursor: 'pointer', borderBottom: '1px solid var(--border)',
    }}
      onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.04)'}
      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
    >
      <span style={{ color: 'var(--text-dim)', fontFamily: 'monospace' }}>{up ? '..' : '/'}</span>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
    </div>
  )
}

function btnStyle(bg, color) {
  return {
    height: 32, padding: '0 16px', borderRadius: 8, border: '1px solid var(--border)',
    background: bg, color, fontSize: 13, fontWeight: 600, cursor: 'pointer',
  }
}
