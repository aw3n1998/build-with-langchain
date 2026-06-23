import React from 'react'
import ReactDOM from 'react-dom/client'
import AppGate from './components/AppGate'   // 鉴权门：未登录看官网、登录进创作台（AUTH 关时直进，零回归）
import { DialogProvider } from './components/Dialog'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <DialogProvider>
      <AppGate />
    </DialogProvider>
  </React.StrictMode>
)
