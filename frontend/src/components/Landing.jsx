import React, { useState, useEffect } from 'react'
import * as api from '../api'

/**
 * 官网 / 落地页 —— 未登录可见（产品介绍 + 登录 CTA）。
 * 点「开始创作」要求登录：邮箱密码 或 Google（后端开了才显示）。登录成功 → onLoggedIn() 进创作台。
 * ⚠ 未经前端构建验证，按需微调文案/样式。
 */
export default function Landing({ onLoggedIn }) {
  const [prov, setProv] = useState({ local: true, google: false, register_open: true })
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState('login')
  const [f, setF] = useState({ email: '', pwd: '', err: '', busy: false })
  const set = (p) => setF((s) => ({ ...s, ...p }))

  useEffect(() => { api.authProviders().then(setProv).catch(() => {}) }, [])

  const submit = async () => {
    set({ err: '', busy: true })
    try {
      if (mode === 'register') await api.authRegister(f.email.trim(), f.pwd)
      else await api.authLogin(f.email.trim(), f.pwd)
      onLoggedIn && onLoggedIn()
    } catch (e) { set({ err: String(e.message || e) }) } finally { set({ busy: false }) }
  }
  const google = async () => {
    try { window.location.href = await api.googleAuthUrl() }
    catch (e) { set({ err: String(e.message || e) }); setOpen(true) }
  }

  const FEAT = [
    ['🎬', 'AI 一键拆镜', '小说/剧情 → 自动分镜，每镜自定时长、续接、对口型、音效，全由 AI 决定'],
    ['🎥', '文生 / 续接出片', 'Wan2.2 出片 + i2v 尾帧续接，人物与场景跨镜连贯一致'],
    ['🗣', '克隆配音 + 对口型', 'CosyVoice2 情感克隆配音，正脸说话镜自动 LatentSync 缝嘴'],
    ['🔊', '同步音效', 'MMAudio 按画面生成与动作同步的环境/动作音效，自动垫在人声之下'],
  ]

  return (
    <div style={S.page}>
      <header style={S.nav}>
        <div style={S.brand}>蜃景 <span style={{ color: '#a78bfa' }}>Mirage</span></div>
        <button style={S.cta} onClick={() => setOpen(true)}>登录 / 开始创作</button>
      </header>

      <section style={S.hero}>
        <h1 style={S.h1}>小说，一键变 AI 短剧</h1>
        <p style={S.sub}>从文本到成片，全自动一条龙：AI 拆镜 · 出片续接 · 克隆配音 · 对口型 · 同步音效 · 合成出片。开放 API，可接你的业务。</p>
        <button style={{ ...S.cta, height: 46, padding: '0 28px', fontSize: 15 }} onClick={() => setOpen(true)}>免费开始创作 →</button>
      </section>

      <section style={S.grid}>
        {FEAT.map(([i, t, d]) => (
          <div key={t} style={S.card}>
            <div style={{ fontSize: 26 }}>{i}</div>
            <div style={{ fontWeight: 700, margin: '10px 0 5px', color: '#e2e8f0' }}>{t}</div>
            <div style={{ color: '#94a3b8', fontSize: 13, lineHeight: 1.6 }}>{d}</div>
          </div>
        ))}
      </section>

      <footer style={S.foot}>© 蜃景 Mirage · 全自托管 AI 短剧流水线 · 开放 API 对接</footer>

      {open && (
        <div style={S.mask} onClick={() => setOpen(false)}>
          <div style={S.modal} onClick={(e) => e.stopPropagation()}>
            <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 16, color: '#e2e8f0' }}>{mode === 'register' ? '注册' : '登录'}</div>
            {prov.google && <button style={S.gbtn} onClick={google}>用 Google 继续</button>}
            {prov.google && <div style={S.or}>或用邮箱</div>}
            <input style={S.inp} placeholder="邮箱" value={f.email} onChange={(e) => set({ email: e.target.value })} />
            <input style={S.inp} placeholder="密码（≥6 位）" type="password" value={f.pwd} onChange={(e) => set({ pwd: e.target.value })} />
            {f.err && <div style={{ color: '#f87171', fontSize: 12, marginTop: 8 }}>{f.err}</div>}
            <button style={{ ...S.cta, width: '100%', height: 40, marginTop: 14 }} onClick={submit} disabled={f.busy}>
              {f.busy ? '…' : mode === 'register' ? '注册并开始' : '登录'}
            </button>
            {prov.register_open && (
              <div style={{ textAlign: 'center', marginTop: 14, fontSize: 12.5, color: '#94a3b8' }}>
                {mode === 'login' ? '还没有账号？' : '已有账号？'}
                <span style={{ color: '#a78bfa', cursor: 'pointer', marginLeft: 4 }}
                      onClick={() => { set({ err: '' }); setMode(mode === 'login' ? 'register' : 'login') }}>
                  {mode === 'login' ? '注册' : '登录'}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const S = {
  page: { minHeight: '100vh', background: 'radial-gradient(1200px 600px at 50% -10%, #1e1b4b, #0b1020 60%)', color: '#e2e8f0', fontFamily: 'system-ui, -apple-system, sans-serif' },
  nav: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '18px 28px', maxWidth: 1100, margin: '0 auto' },
  brand: { fontSize: 20, fontWeight: 800, letterSpacing: 1 },
  cta: { height: 36, padding: '0 18px', borderRadius: 9, border: 'none', background: 'linear-gradient(90deg,#7c5cff,#a78bfa)', color: '#fff', fontWeight: 700, fontSize: 13.5, cursor: 'pointer' },
  hero: { textAlign: 'center', padding: '70px 20px 50px', maxWidth: 820, margin: '0 auto' },
  h1: { fontSize: 44, fontWeight: 900, lineHeight: 1.15, margin: 0 },
  sub: { color: '#94a3b8', fontSize: 16, lineHeight: 1.7, margin: '20px auto 30px', maxWidth: 640 },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 16, maxWidth: 1000, margin: '10px auto 60px', padding: '0 20px' },
  card: { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(148,163,184,0.15)', borderRadius: 14, padding: 20 },
  foot: { textAlign: 'center', color: '#64748b', fontSize: 12.5, padding: '30px 20px 40px' },
  mask: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 },
  modal: { width: 340, padding: 26, borderRadius: 16, background: '#161a2e', border: '1px solid rgba(148,163,184,0.2)' },
  gbtn: { width: '100%', height: 40, borderRadius: 9, border: '1px solid rgba(148,163,184,0.3)', background: '#fff', color: '#1f2937', fontWeight: 700, fontSize: 13.5, cursor: 'pointer' },
  or: { textAlign: 'center', color: '#64748b', fontSize: 12, margin: '12px 0' },
  inp: { width: '100%', height: 38, padding: '0 12px', marginTop: 10, borderRadius: 9, border: '1px solid rgba(148,163,184,0.3)', background: 'rgba(15,23,42,0.6)', color: '#e2e8f0', fontSize: 14, boxSizing: 'border-box' },
}
