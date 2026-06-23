import React, { useState, useEffect } from 'react'
import * as api from '../api'

/**
 * 登录 / 注册页（独立全屏，参考 OpenArt 的 auth 页）。Props：onSuccess、onBack。
 * 邮箱密码 + Google（后端配了才显示）。注册成功/登录成功 → onSuccess() 进 studio。
 */
export default function Login({ onSuccess, onBack }) {
  const [prov, setProv] = useState({ google: false, register_open: true })
  const [mode, setMode] = useState('login')
  const [f, setF] = useState({ email: '', pwd: '', name: '', err: '', busy: false })
  const set = (p) => setF((s) => ({ ...s, ...p }))
  useEffect(() => { api.authProviders().then(setProv).catch(() => {}) }, [])

  const submit = async () => {
    set({ err: '', busy: true })
    try {
      if (mode === 'register') await api.authRegister(f.email.trim(), f.pwd, f.name.trim())
      else await api.authLogin(f.email.trim(), f.pwd)
      onSuccess && onSuccess()
    } catch (e) { set({ err: String(e.message || e) }) } finally { set({ busy: false }) }
  }
  const google = async () => {
    try { window.location.href = await api.googleAuthUrl() } catch (e) { set({ err: String(e.message || e) }) }
  }

  return (
    <div style={S.page}>
      <div style={S.glow} />
      <button style={S.back} onClick={onBack}>← 返回首页</button>
      <div style={S.card}>
        <div style={S.brand}>蜃景<span style={{ color: '#a78bfa' }}> Mirage</span></div>
        <div style={S.title}>{mode === 'register' ? '创建账号' : '登录'}</div>
        <div style={S.subtitle}>{mode === 'register' ? '注册即送 100 积分，立即开始创作' : '欢迎回来，继续你的创作'}</div>

        {prov.google && (
          <button style={S.gbtn} onClick={google}>
            <span style={{ fontWeight: 900, fontSize: 16, color: '#4285F4' }}>G</span>&nbsp;&nbsp;用 Google 继续
          </button>
        )}
        {prov.google && <div style={S.or}><span style={S.orline} />或用邮箱<span style={S.orline} /></div>}

        {mode === 'register' && <input style={S.inp} placeholder="昵称（可选）" value={f.name} onChange={(e) => set({ name: e.target.value })} />}
        <input style={S.inp} placeholder="邮箱" value={f.email} onChange={(e) => set({ email: e.target.value })} />
        <input style={S.inp} type="password" placeholder="密码（≥6 位）" value={f.pwd}
               onChange={(e) => set({ pwd: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && submit()} />
        {f.err && <div style={S.err}>{f.err}</div>}
        <button style={S.submit} onClick={submit} disabled={f.busy}>
          {f.busy ? '…' : mode === 'register' ? '注册并开始创作' : '登录'}
        </button>

        {prov.register_open && (
          <div style={S.toggle}>
            {mode === 'login' ? '还没有账号？' : '已有账号？'}
            <span style={S.link} onClick={() => { set({ err: '' }); setMode(mode === 'login' ? 'register' : 'login') }}>
              {mode === 'login' ? '免费注册' : '去登录'}
            </span>
          </div>
        )}
      </div>
      <div style={S.legal}>登录即表示同意服务条款与隐私政策</div>
    </div>
  )
}

const S = {
  page: { position: 'relative', height: '100vh', overflowY: 'auto', overflowX: 'hidden', background: '#0a0a12', color: '#e2e8f0', fontFamily: 'system-ui,-apple-system,"Segoe UI",sans-serif', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' },
  glow: { position: 'absolute', top: '-20%', left: '50%', transform: 'translateX(-50%)', width: 900, height: 600, background: 'radial-gradient(circle, rgba(124,58,237,0.25), transparent 60%)', filter: 'blur(20px)', pointerEvents: 'none' },
  back: { position: 'absolute', top: 24, left: 24, height: 34, padding: '0 14px', borderRadius: 9, border: '1px solid rgba(148,163,184,0.2)', background: 'transparent', color: '#94a3b8', fontSize: 13, cursor: 'pointer' },
  card: { position: 'relative', width: 380, padding: '36px 34px', borderRadius: 18, background: 'rgba(20,20,32,0.85)', border: '1px solid rgba(148,163,184,0.18)', boxShadow: '0 24px 60px rgba(0,0,0,0.5)', backdropFilter: 'blur(12px)' },
  brand: { fontSize: 19, fontWeight: 800, textAlign: 'center', marginBottom: 18 },
  title: { fontSize: 24, fontWeight: 800, textAlign: 'center', color: '#f1f5f9' },
  subtitle: { fontSize: 13.5, color: '#94a3b8', textAlign: 'center', margin: '8px 0 24px' },
  gbtn: { width: '100%', height: 44, borderRadius: 11, border: '1px solid rgba(148,163,184,0.25)', background: '#fff', color: '#1f2937', fontWeight: 700, fontSize: 14, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' },
  or: { display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', fontSize: 12, margin: '18px 0' },
  orline: { flex: 1, height: 1, background: 'rgba(148,163,184,0.2)' },
  inp: { width: '100%', height: 44, padding: '0 14px', marginBottom: 12, borderRadius: 11, border: '1px solid rgba(148,163,184,0.25)', background: 'rgba(10,10,18,0.6)', color: '#e2e8f0', fontSize: 14.5, boxSizing: 'border-box', outline: 'none' },
  err: { color: '#f87171', fontSize: 12.5, marginBottom: 10 },
  submit: { width: '100%', height: 46, borderRadius: 11, border: 'none', background: 'linear-gradient(90deg,#7c3aed,#a855f7)', color: '#fff', fontWeight: 700, fontSize: 15, cursor: 'pointer', boxShadow: '0 8px 24px rgba(124,58,237,0.35)' },
  toggle: { textAlign: 'center', marginTop: 18, fontSize: 13, color: '#94a3b8' },
  link: { color: '#a78bfa', cursor: 'pointer', marginLeft: 5, fontWeight: 600 },
  legal: { position: 'relative', color: '#475569', fontSize: 11.5, marginTop: 22 },
}
