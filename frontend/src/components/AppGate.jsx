import React, { useState, useEffect } from 'react'
import App from '../App'
import Landing from './Landing'
import * as api from '../api'

/**
 * 鉴权门 —— 「未登录可看官网，登录了才能创作」。
 * - 后端 AUTH_ENABLED=false：authMe 返回内置 dev 用户 → 直接进创作台 App（开发态不变）。
 * - AUTH_ENABLED=true 且未登录：显示官网 Landing；登录/Google 成功后 onLoggedIn 重新校验 → 进 App。
 * 启动时先处理 Google 回调（URL 里的 oauth_token）。
 */
export default function AppGate() {
  const [view, setView] = useState('loading')   // loading / app / landing

  const check = async () => {
    try {
      const me = await api.authMe()
      setView(me && me.user ? 'app' : 'landing')
    } catch {
      setView('landing')
    }
  }
  useEffect(() => { api.applyOAuthRedirect(); check() }, [])

  if (view === 'loading') return <div style={{ minHeight: '100vh', background: '#0b1020' }} />
  if (view === 'landing') return <Landing onLoggedIn={check} />
  return <App />
}
