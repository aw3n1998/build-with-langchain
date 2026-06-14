/* 移动端「短剧工作台」设计系统基础组件 —— 忠实移植自 Claude Design 导出稿,
   全部走 index.css 的 --token,按压反馈、≥44px 触控、无 hover。 */
import { useState } from 'react'

/* ── 内联图标(lucide 子集,避免新增依赖) ── */
const PATHS = {
  menu: 'M4 6h16M4 12h16M4 18h16', plus: 'M5 12h14M12 5v14', x: 'M18 6 6 18M6 6l12 12',
  check: 'M20 6 9 17l-5-5', image: 'M3 3h18v18H3zM8.5 10a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM21 15l-5-5L5 21',
  film: 'M3 3h18v18H3zM7 3v18M17 3v18M3 7.5h4M3 12h18M3 16.5h4M17 7.5h4M17 16.5h4',
  download: 'M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3',
  upload: 'M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12',
  'rotate-cw': 'M21 12a9 9 0 1 1-3-6.7M21 3v6h-6', 'undo-2': 'M9 14 4 9l5-5M4 9h11a4 4 0 0 1 0 8h-1',
  'chevron-down': 'M6 9l6 6 6-6', 'chevron-up': 'M18 15l-6-6-6 6', 'chevron-right': 'M9 18l6-6-6-6',
  trash: 'M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2',
  wand: 'M15 4V2M15 16v-2M8 9h2M20 9h2M3 21l9-9M12.2 6.2 11 5', smartphone: 'M5 2h14v20H5zM12 18h0',
  play: 'M6 4l14 8-14 8z', folder: 'M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z',
}
export function MI({ name, size = 18, color = 'currentColor', sw = 1.8, fill = 'none' }) {
  const d = PATHS[name] || ''
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color}
         strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">
      {d.split('M').filter(Boolean).map((s, i) => <path key={i} d={'M' + s} />)}
    </svg>
  )
}
export function Sparkles({ size = 16, color = '#fff' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.14a.5.5 0 0 1 .96 0L14.06 8.5A2 2 0 0 0 15.5 9.94l6.14 1.58a.5.5 0 0 1 0 .96L15.5 14.06a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0z" />
    </svg>
  )
}

/* ── 按钮 ── */
export function Button({ children, variant = 'primary', size = 'md', full, disabled, icon, onClick, style = {} }) {
  const pal = {
    primary: { bg: 'var(--accent)', press: 'var(--accent-press)', fg: '#fff', bd: 'transparent' },
    teal:    { bg: 'var(--teal)', press: '#009a8f', fg: '#04221f', bd: 'transparent' },
    purple:  { bg: 'var(--purple)', press: '#a855e6', fg: '#23103a', bd: 'transparent' },
    ghost:   { bg: 'transparent', press: 'var(--neutral-soft)', fg: 'var(--text-primary)', bd: 'var(--border-strong)' },
    neutral: { bg: 'var(--surface-raised)', press: '#262626', fg: 'var(--text-primary)', bd: 'var(--border)' },
  }[variant] || {}
  const s = { sm: { h: 36, px: 12, fs: 13 }, md: { h: 44, px: 16, fs: 15 } }[size] || { h: 44, px: 16, fs: 15 }
  const [d, setD] = useState(false)
  return (
    <button disabled={disabled} onClick={onClick}
      onPointerDown={() => setD(true)} onPointerUp={() => setD(false)} onPointerLeave={() => setD(false)}
      style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 7,
        width: full ? '100%' : 'auto', height: s.h, padding: `0 ${s.px}px`, fontFamily: 'var(--font-sans)',
        fontSize: s.fs, fontWeight: 600, color: pal.fg, background: d && !disabled ? pal.press : pal.bg,
        border: `1px solid ${pal.bd}`, borderRadius: 'var(--r-btn)', cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1, transform: d && !disabled ? 'scale(0.97)' : 'scale(1)',
        transition: 'transform var(--dur-fast), background var(--dur-fast)', WebkitTapHighlightColor: 'transparent', ...style }}>
      {icon}{children}
    </button>
  )
}

export function Card({ children, tone = 'default', pad = 16, style = {} }) {
  const bg = tone === 'sunken' ? 'var(--surface-sunken)' : tone === 'code' ? 'var(--surface-code)' : 'var(--surface-card)'
  return <div style={{ background: bg, border: '1px solid var(--border)', borderRadius: 'var(--r-card)',
    padding: pad, fontFamily: 'var(--font-sans)', color: 'var(--text-primary)', ...style }}>{children}</div>
}

export function Chip({ children, tone = 'neutral', active, icon, onClick, style = {} }) {
  const c = { neutral: 'var(--text-secondary)', accent: 'var(--accent)', teal: 'var(--teal-bright)', purple: 'var(--purple)' }[tone] || 'var(--text-secondary)'
  const soft = { neutral: 'var(--neutral-soft)', accent: 'var(--accent-soft)', teal: 'var(--teal-soft)', purple: 'var(--purple-soft)' }[tone]
  return (
    <button onClick={onClick} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 32, padding: '0 12px',
      fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap',
      color: active ? c : 'var(--text-secondary)', background: active ? soft : 'var(--surface-card)',
      border: `1px solid ${active ? c : 'var(--border)'}`, borderRadius: 'var(--r-chip)', cursor: 'pointer',
      WebkitTapHighlightColor: 'transparent', ...style }}>{icon}{children}</button>
  )
}

export function StatChip({ label, value, tone = 'neutral' }) {
  const t = { neutral: { c: 'var(--text-secondary)', s: 'var(--neutral-soft)' }, yellow: { c: 'var(--yellow)', s: 'var(--yellow-soft)' },
    purple: { c: 'var(--purple)', s: 'var(--purple-soft)' }, green: { c: 'var(--green)', s: 'var(--green-soft)' } }[tone] || {}
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 28, padding: '0 10px',
      fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap',
      color: t.c, background: t.s, borderRadius: 'var(--r-chip)' }}>
      <span style={{ opacity: tone === 'neutral' ? 1 : 0.82 }}>{label}</span>
      <span style={{ fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </span>
  )
}

const SB = {
  pending:   { label: '待出图', c: 'var(--text-secondary)', s: 'var(--neutral-soft)', spin: false },
  drawing:   { label: '出图中', c: 'var(--yellow)', s: 'var(--yellow-soft)', spin: true },
  review:    { label: '待选图', c: 'var(--purple)', s: 'var(--purple-soft)', spin: false },
  done:      { label: '已出片', c: 'var(--green)', s: 'var(--green-soft)', spin: false },
  rendering: { label: '出片中', c: 'var(--teal-bright)', s: 'var(--teal-soft)', spin: true },
  failed:    { label: '失败',   c: 'var(--red)', s: 'var(--red-soft)', spin: false },
}
export function StatusBadge({ status = 'pending', label }) {
  const s = SB[status] || SB.pending
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 24, padding: '0 9px',
      fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 600, color: s.c, background: s.s, borderRadius: 'var(--r-tag)' }}>
      {s.spin
        ? <span style={{ width: 10, height: 10, borderRadius: '50%', border: `1.6px solid ${s.c}`, borderTopColor: 'transparent', animation: 'mirageSpin .7s linear infinite' }} />
        : <span style={{ width: 7, height: 7, borderRadius: '50%', background: s.c }} />}
      {label || s.label}
    </span>
  )
}

export function Switch({ checked, onChange, disabled }) {
  return (
    <button role="switch" aria-checked={checked} disabled={disabled} onClick={() => !disabled && onChange && onChange(!checked)}
      style={{ width: 46, height: 28, flex: 'none', borderRadius: 'var(--r-pill)', border: 'none', padding: 2,
        background: checked ? 'var(--accent)' : 'var(--surface-raised)', boxShadow: checked ? 'none' : 'inset 0 0 0 1px var(--border-strong)',
        cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1, display: 'inline-flex', alignItems: 'center',
        transition: 'background var(--dur-base)', WebkitTapHighlightColor: 'transparent' }}>
      <span style={{ width: 24, height: 24, borderRadius: '50%', background: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
        transform: checked ? 'translateX(18px)' : 'translateX(0)', transition: 'transform var(--dur-base)' }} />
    </button>
  )
}

export function CandidateImage({ src, selected, onClick, style = {} }) {
  const [d, setD] = useState(false)
  return (
    <button onClick={onClick} onPointerDown={() => setD(true)} onPointerUp={() => setD(false)} onPointerLeave={() => setD(false)}
      style={{ position: 'relative', aspectRatio: '3 / 4', width: '100%', padding: 0, border: 'none', borderRadius: 'var(--r-btn)',
        overflow: 'hidden', cursor: 'pointer', background: src ? '#000' : 'var(--surface-sunken)',
        boxShadow: selected ? '0 0 0 2px var(--green)' : 'inset 0 0 0 1px var(--border)',
        transform: d ? 'scale(0.98)' : 'scale(1)', transition: 'transform var(--dur-fast)', WebkitTapHighlightColor: 'transparent', ...style }}>
      {src
        ? <img src={src} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
        : <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-faint)' }}><MI name="image" size={22} /></span>}
      {selected && (
        <span style={{ position: 'absolute', top: 6, right: 6, display: 'inline-flex', alignItems: 'center', gap: 3, height: 20,
          padding: '0 7px', fontSize: 11, fontWeight: 600, color: '#04221f', background: 'var(--green)', borderRadius: 'var(--r-tag)' }}>
          <MI name="check" size={11} color="#04221f" sw={3.2} />选中
        </span>
      )}
    </button>
  )
}

export function SceneCard({ index, title, status = 'pending', onDelete, children }) {
  const edge = { pending: 'var(--border-strong)', drawing: 'var(--yellow)', review: 'var(--purple)',
    done: 'var(--green)', rendering: 'var(--teal)', failed: 'var(--red)' }[status] || 'var(--border-strong)'
  return (
    <div style={{ background: 'var(--surface-card)', border: '1px solid var(--border)', borderLeft: `2px solid ${edge}`,
      borderRadius: 'var(--r-card)', overflow: 'hidden', fontFamily: 'var(--font-sans)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 12px 12px 14px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', flex: 'none' }}>#{String(index).padStart(2, '0')}</span>
        <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</span>
        <StatusBadge status={status} />
        {onDelete && <button aria-label="删除" onClick={onDelete} style={{ width: 32, height: 32, flex: 'none', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: 'var(--red)', background: 'transparent', border: 'none', borderRadius: 'var(--r-btn)', cursor: 'pointer' }}><MI name="trash" size={17} /></button>}
      </div>
      {children && <div style={{ padding: '0 12px 12px 14px' }}>{children}</div>}
    </div>
  )
}

export function GpuLogBar({ state = 'idle', elapsed, lines = [], defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const m = { idle: { c: 'var(--text-secondary)', t: '空闲', spin: false }, drawing: { c: 'var(--yellow)', t: '出图中', spin: true },
    rendering: { c: 'var(--teal-bright)', t: '出片中', spin: true }, done: { c: 'var(--green)', t: '完成', spin: false },
    error: { c: 'var(--red)', t: '错误', spin: false } }[state] || { c: 'var(--text-secondary)', t: '空闲' }
  return (
    <div style={{ background: 'var(--surface-card)', border: '1px solid var(--border)', borderRadius: 'var(--r-card)', overflow: 'hidden', fontFamily: 'var(--font-mono)' }}>
      <button onClick={() => setOpen(o => !o)} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', height: 40, padding: '0 12px', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-primary)' }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', flex: 'none', background: m.c, boxShadow: m.spin ? `0 0 8px ${m.c}` : 'none' }} />
        <span style={{ fontSize: 12, color: m.c, fontWeight: 600 }}>{m.t}</span>
        {elapsed && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{elapsed}</span>}
        <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', display: 'inline-flex', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform var(--dur-base)' }}><MI name="chevron-up" size={14} /></span>
      </button>
      {open && (
        <div style={{ background: 'var(--surface-code)', borderTop: '1px solid var(--border)', padding: '10px 12px', maxHeight: 160, overflowY: 'auto', fontSize: 11.5, lineHeight: 1.7 }}>
          {lines.length === 0 && <div style={{ color: 'var(--text-muted)' }}>（暂无日志）</div>}
          {lines.map((l, i) => <div key={i} style={{ color: l.tone ? `var(--${l.tone})` : 'var(--text-secondary)' }}>{l.t}</div>)}
        </div>
      )}
    </div>
  )
}

export function TabRail({ tabs = [], value, onChange }) {
  return (
    <div className="no-scrollbar" style={{ display: 'flex', gap: 4, overflowX: 'auto', borderBottom: '1px solid var(--border)', WebkitOverflowScrolling: 'touch' }}>
      {tabs.map(t => {
        const active = t.id === value
        return (
          <button key={t.id} onClick={() => onChange(t.id)} style={{ position: 'relative', flex: 'none', height: 44, padding: '0 14px',
            fontFamily: 'var(--font-sans)', fontSize: 15, fontWeight: active ? 600 : 500, color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
            background: 'transparent', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap', WebkitTapHighlightColor: 'transparent' }}>
            {t.label}
            <span style={{ position: 'absolute', left: 12, right: 12, bottom: -1, height: 2, borderRadius: 2, background: active ? 'var(--accent)' : 'transparent' }} />
          </button>
        )
      })}
    </div>
  )
}

/* 字段输入 */
export function Field({ label, children }) {
  return <div style={{ marginBottom: 4 }}>{label && <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>{label}</div>}{children}</div>
}
export const fieldStyle = {
  width: '100%', background: 'var(--surface-sunken)', border: '1px solid var(--border)', borderRadius: 'var(--r-btn)',
  color: 'var(--text-primary)', fontFamily: 'var(--font-sans)', fontSize: 14, padding: '10px 12px', outline: 'none', boxSizing: 'border-box',
}

/* scene.state → 视觉状态 */
export function statusOf(s) {
  if (s.video) return 'done'
  if (s.state === 'FAILED') return 'failed'
  if (s.state === 'PENDING_FLUX_GEN') return 'drawing'
  if ((s.candidates && s.candidates.length) || s.state === 'PENDING_HUMAN_SELECTION' || s.state === 'PENDING_VIDEO_GEN') return 'review'
  return 'pending'
}
