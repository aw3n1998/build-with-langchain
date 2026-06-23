import React, { useEffect, useRef, useState } from 'react'
import { listWorkers, connectWorkersWS } from '../api'

/**
 * GPU 算力仪表盘（弹层）—— worker 周期把自己的 GPU/状态/当前任务/显存 push 到后端，这里每 4s 轮询展示。
 * 支持多 worker（横向扩展）：每个 worker 一张卡，状态点(空闲绿/忙黄/错红/离线灰) + 队列。
 * Props：open、onClose。
 */
const SC = { idle: '#34d399', busy: '#eab308', error: '#f87171', offline: '#64748b' }
const SL = { idle: '空闲', busy: '忙', error: '错误', offline: '离线' }

export default function WorkerPanel({ open, onClose }) {
  const [data, setData] = useState({ workers: [], queue: [], dispatch_mode: '' })
  const [err, setErr] = useState('')
  const timer = useRef(null)
  useEffect(() => {
    if (!open) return
    let alive = true
    const tick = async () => {
      try { const d = await listWorkers(); if (alive) { setData(d); setErr('') } }
      catch (e) { if (alive) setErr(String(e.message || e)) }
    }
    tick()   // 首屏 + 兜底
    // WS 实时：连上即收 snapshot，之后 worker_update 按 id 合并（状态/进度 ~1s 内到，不再死等 4s）。
    const closeWs = connectWorkersWS(msg => {
      if (!alive) return
      if (msg.type === 'workers_snapshot') {
        setData({ workers: msg.workers || [], queue: msg.queue || [], dispatch_mode: msg.dispatch_mode || '' }); setErr('')
      } else if (msg.type === 'worker_update' && msg.worker) {
        setData(d => {
          const ws = (d.workers || []).slice()
          const i = ws.findIndex(w => w.id === msg.worker.id)
          if (i >= 0) ws[i] = { ...ws[i], ...msg.worker }; else ws.push(msg.worker)
          return { ...d, workers: ws }
        })
      } else if (msg.type === 'queue_update') {
        setData(d => ({ ...d, queue: msg.queue || [] }))
      }
    })
    timer.current = setInterval(tick, 10000)   // 慢轮询兜底：WS 断了仍刷新、并重算离线态
    return () => { alive = false; clearInterval(timer.current); closeWs() }
  }, [open])
  if (!open) return null
  const ws = data.workers || []
  const queue = data.queue || []
  const online = ws.filter(w => w.online).length
  return (
    <div onClick={onClose} style={S.scrim}>
      <div onClick={e => e.stopPropagation()} style={S.panel}>
        <div style={S.head}>
          <span style={{ fontSize: 16, fontWeight: 800 }}>GPU 算力 · Workers</span>
          <span style={S.modeBadge}>{data.dispatch_mode === 'worker' ? '拉取模式' : 'local · 直推'}</span>
          <span style={{ marginLeft: 'auto', fontSize: 12, color: '#94a3b8' }}>{online}/{ws.length} 在线 · 队列 {queue.length}</span>
          <button onClick={onClose} style={S.close}>✕</button>
        </div>
        {err && <div style={S.err}>连不上 worker 接口：{err}</div>}
        {ws.length === 0 ? (
          <div style={S.empty}>
            还没有 worker 连接。<br /><br />
            在 GPU 机上跑 <code style={S.code}>BACKEND_URL=… WORKER_TOKEN=… python colab/worker.py</code> 即可上线，多台横向扩展。<br />
            后端设 <code style={S.code}>DISPATCH_MODE=worker</code> 才会把出片任务派给 worker。
          </div>
        ) : (
          <div style={S.grid}>
            {ws.map(w => (
              <div key={w.id} style={S.card}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 9, height: 9, borderRadius: '50%', background: SC[w.display_state] || '#64748b', flexShrink: 0 }} />
                  <span style={{ fontWeight: 700, fontSize: 13.5, color: '#e2e8f0' }}>{w.gpu || w.id}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 11, color: SC[w.display_state], fontWeight: 600 }}>{SL[w.display_state] || w.display_state}</span>
                </div>
                <div style={S.meta}>{w.id}{w.hostname ? ' · ' + w.hostname : ''}</div>
                {w.current_task ? <div style={{ ...S.meta, color: '#a5b4fc' }}>▶ {w.current_task}{w.progress ? ' · ' + w.progress : ''}</div> : null}
                <div style={S.statRow}>
                  {w.vram ? <span style={S.tag}>显存 {w.vram}</span> : null}
                  <span style={S.tag}>✓ {w.done_count || 0}</span>
                  {(w.fail_count || 0) > 0 ? <span style={{ ...S.tag, color: '#fca5a5', borderColor: 'rgba(239,68,68,0.3)' }}>✗ {w.fail_count}</span> : null}
                  {w.last_seen_ago != null ? <span style={{ marginLeft: 'auto', fontSize: 10.5, color: '#64748b' }}>{w.last_seen_ago}s 前</span> : null}
                </div>
              </div>
            ))}
          </div>
        )}
        {queue.length > 0 && (
          <div style={S.queue}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>队列（{queue.length}）</div>
            {queue.slice(0, 12).map(t => (
              <div key={t.id} style={S.qrow}>
                <span style={{ width: 52, color: t.state === 'leased' ? '#eab308' : '#94a3b8' }}>{t.state === 'leased' ? '执行中' : '等待'}</span>
                <span style={{ width: 110 }}>{t.type}</span>
                <span style={{ color: '#64748b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.scene_id || t.project_id || t.id}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

const S = {
  scrim: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 3000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, backdropFilter: 'blur(3px)' },
  panel: { width: 640, maxWidth: '94vw', maxHeight: '86vh', overflowY: 'auto', background: '#141420', border: '1px solid rgba(148,163,184,0.18)', borderRadius: 16, padding: 20, color: '#e2e8f0', boxShadow: '0 24px 60px rgba(0,0,0,0.5)' },
  head: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 },
  modeBadge: { fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 6, background: 'rgba(99,102,241,0.16)', color: '#a5b4fc', border: '1px solid rgba(99,102,241,0.3)' },
  close: { width: 28, height: 28, borderRadius: 8, border: '1px solid rgba(148,163,184,0.2)', background: 'transparent', color: '#94a3b8', cursor: 'pointer', fontSize: 13 },
  err: { fontSize: 12, color: '#fca5a5', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, padding: '8px 10px', marginBottom: 12 },
  empty: { fontSize: 13, color: '#94a3b8', lineHeight: 1.9, padding: '24px 8px', textAlign: 'center' },
  code: { background: 'rgba(255,255,255,0.07)', borderRadius: 5, padding: '1px 6px', fontSize: 12, color: '#cbd5e1' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(260px,1fr))', gap: 12 },
  card: { border: '1px solid rgba(148,163,184,0.16)', borderRadius: 12, padding: 12, background: 'rgba(255,255,255,0.02)' },
  meta: { fontSize: 11.5, color: '#94a3b8', marginTop: 5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
  statRow: { display: 'flex', alignItems: 'center', gap: 6, marginTop: 9, flexWrap: 'wrap' },
  tag: { fontSize: 10.5, padding: '2px 7px', borderRadius: 6, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(148,163,184,0.18)', color: '#cbd5e1' },
  queue: { marginTop: 16, paddingTop: 12, borderTop: '1px solid rgba(148,163,184,0.12)' },
  qrow: { display: 'flex', gap: 10, fontSize: 11.5, padding: '3px 0', fontFamily: 'ui-monospace,monospace' },
}
