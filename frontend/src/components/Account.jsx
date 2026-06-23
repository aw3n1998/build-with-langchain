import React, { useState, useEffect } from 'react'
import * as api from '../api'

/**
 * 账号入口（用户系统 + 充值/计费）。自包含组件——放进顶栏即可：
 *   import Account from './components/Account'
 *   <Account />
 * 门控关（后端 AUTH_ENABLED=false 且 BILLING_ENABLED=false）时本组件自动隐藏（开发态开放、无需登录）。
 * 依赖 api.js 的 authLogin/authRegister/authMe/billing* 等（已实现）。⚠ 未经构建验证，按需微调样式。
 */
export default function Account() {
  const [me, setMe] = useState(null)          // {user, auth_enabled, billing_enabled} | null
  const [needLogin, setNeedLogin] = useState(false)
  const [cfg, setCfg] = useState(null)
  const [ui, setUi] = useState({ open: false, mode: 'login', email: '', pwd: '', err: '', busy: false })
  const set = (p) => setUi((s) => ({ ...s, ...p }))

  const refresh = async () => {
    try { setMe(await api.authMe()); setNeedLogin(false) }
    catch { setMe(null); setNeedLogin(true) }
  }
  useEffect(() => { api.billingConfig().then(setCfg).catch(() => {}); refresh() }, [])

  const submit = async () => {
    set({ err: '', busy: true })
    try {
      if (ui.mode === 'register') await api.authRegister(ui.email.trim(), ui.pwd)
      else await api.authLogin(ui.email.trim(), ui.pwd)
      await refresh(); set({ open: false, email: '', pwd: '' })
    } catch (e) { set({ err: String(e.message || e) }) } finally { set({ busy: false }) }
  }
  const recharge = async () => {
    set({ busy: true })
    try { const r = await api.billingRecharge(100); if (r.pay_url) window.open(r.pay_url, '_blank'); await refresh() }
    catch (e) { set({ err: String(e.message || e) }) } finally { set({ busy: false }) }
  }
  const logout = () => { api.authLogout(); setMe(null); setNeedLogin(true) }

  const user = me?.user
  const authOn = me?.auth_enabled
  const billingOn = me?.billing_enabled ?? cfg?.enabled

  if (user && (authOn || billingOn)) {
    return (
      <div style={S.bar}>
        {billingOn && <span title="积分余额" style={{ color: '#a78bfa', fontWeight: 700 }}>💎 {user.balance}</span>}
        {billingOn && <button style={S.btn('#7c5cff')} onClick={recharge} disabled={ui.busy}>充值</button>}
        <span style={{ color: '#cbd5e1' }} title={user.email}>{user.display_name || user.email}</span>
        {authOn && <button style={S.btn('#64748b')} onClick={logout}>退出</button>}
        {ui.err && <span style={{ color: '#f87171', fontSize: 11 }}>{ui.err}</span>}
      </div>
    )
  }
  if (needLogin) {
    return (
      <>
        <button style={S.btn('#7c5cff')} onClick={() => set({ open: true })}>登录 / 注册</button>
        {ui.open && (
          <div style={S.mask} onClick={() => set({ open: false })}>
            <div style={S.modal} onClick={(e) => e.stopPropagation()}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                <button style={S.tab(ui.mode === 'login')} onClick={() => set({ mode: 'login', err: '' })}>登录</button>
                <button style={S.tab(ui.mode === 'register')} onClick={() => set({ mode: 'register', err: '' })}>注册</button>
              </div>
              <input style={S.inp} placeholder="邮箱" value={ui.email} onChange={(e) => set({ email: e.target.value })} />
              <input style={S.inp} placeholder="密码（≥6 位）" type="password" value={ui.pwd} onChange={(e) => set({ pwd: e.target.value })} />
              {ui.err && <div style={{ color: '#f87171', fontSize: 12, marginTop: 6 }}>{ui.err}</div>}
              <button style={{ ...S.btn('#7c5cff'), width: '100%', height: 36, marginTop: 10 }} onClick={submit} disabled={ui.busy}>
                {ui.busy ? '…' : ui.mode === 'register' ? '注册' : '登录'}
              </button>
              {ui.mode === 'register' && cfg?.signup_bonus > 0 && (
                <div style={{ color: '#94a3b8', fontSize: 11, marginTop: 8, textAlign: 'center' }}>注册即赠 {cfg.signup_bonus} 积分</div>
              )}
            </div>
          </div>
        )}
      </>
    )
  }
  return null
}

const S = {
  bar: { display: 'flex', alignItems: 'center', gap: 10, fontSize: 12.5 },
  btn: (c) => ({ height: 26, padding: '0 12px', borderRadius: 6, border: `1px solid ${c}99`, background: `${c}22`, color: '#e2e8f0', fontSize: 12, cursor: 'pointer' }),
  tab: (a) => ({ flex: 1, height: 30, borderRadius: 6, border: 'none', background: a ? '#7c5cff' : 'rgba(148,163,184,0.15)', color: a ? '#fff' : '#cbd5e1', cursor: 'pointer', fontSize: 13 }),
  inp: { width: '100%', height: 34, padding: '0 10px', marginTop: 8, borderRadius: 6, border: '1px solid rgba(148,163,184,0.3)', background: 'rgba(15,23,42,0.6)', color: '#e2e8f0', fontSize: 13, boxSizing: 'border-box' },
  mask: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 },
  modal: { width: 320, padding: 20, borderRadius: 12, background: '#1e293b', border: '1px solid rgba(148,163,184,0.25)' },
}
