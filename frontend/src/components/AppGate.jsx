import React, { useState, useEffect } from 'react'
import App from '../App'
import Landing from './Landing'
import Login from './Login'
import * as api from '../api'

/**
 * 顶层路由门 —— 官网(未登录可见) → 登录页 → studio(创作台 App)。
 * - 有有效令牌 / Google 回调带回令牌 → 直接进 studio。
 * - 没令牌 → 官网 Landing；点「登录」或「开始创作」→ 登录页（AUTH 开时）/ 直进 studio（AUTH 关，开发态）。
 */
export default function AppGate() {
  const [view, setView] = useState('loading')   // loading | landing | login | app
  const [authEnabled, setAuthEnabled] = useState(false)

  useEffect(() => {
    (async () => {
      const fromOAuth = api.applyOAuthRedirect()   // Google 回调把 token 落到 localStorage
      let prov = { auth_enabled: false }
      try { prov = await api.authProviders() } catch { /* 后端没起也先给官网 */ }
      setAuthEnabled(!!prov.auth_enabled)
      // 有令牌（含刚 OAuth 回来）→ 校验后进 studio
      if (fromOAuth || (api.getToken && api.getToken())) {
        try { const me = await api.authMe(); if (me && me.user) { setView('app'); return } } catch { /* 令牌失效 → 落官网 */ }
      }
      setView('landing')
    })()
  }, [])

  if (view === 'loading') return <div style={{ minHeight: '100vh', background: '#0a0a12' }} />
  if (view === 'app') return <App />
  if (view === 'login') return <Login onSuccess={() => setView('app')} onBack={() => setView('landing')} />
  return (
    <Landing
      authEnabled={authEnabled}
      onLogin={() => setView('login')}
      onStart={() => setView(authEnabled ? 'login' : 'app')}   /* 开发态(AUTH 关)：直进创作台 */
    />
  )
}
