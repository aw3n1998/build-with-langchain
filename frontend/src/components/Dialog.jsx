import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

/**
 * Dialog —— 应用内统一弹框，替代原生 window.alert / confirm / prompt。
 *
 * 用法：把 <DialogProvider> 包在应用最外层；组件里 `const dialog = useDialog()`，
 * 然后 `await dialog.alert(msg)` / `await dialog.confirm(msg, {danger})` /
 * `await dialog.prompt(label, defaultValue)`。三者都返回 Promise，保持原来的命令式写法。
 *
 * 视觉按短剧工作台设计稿：#161616 卡片 + 半透明遮罩 + 模糊，靛蓝主操作、红色危险操作。
 */
const DialogContext = createContext(null)

export function useDialog() {
  const ctx = useContext(DialogContext)
  if (!ctx) throw new Error('useDialog must be used within <DialogProvider>')
  return ctx
}

export function DialogProvider({ children }) {
  // 同一时刻只展示一个弹框（这些都是用户主动触发的串行操作）。
  const [dlg, setDlg] = useState(null)   // { type, title, message, defaultValue, placeholder, confirmText, cancelText, danger, resolve }
  const resolveRef = useRef(null)

  const close = useCallback((value) => {
    const r = resolveRef.current
    resolveRef.current = null
    setDlg(null)
    if (r) r(value)
  }, [])

  const open = useCallback((cfg) => new Promise((resolve) => {
    resolveRef.current = resolve
    setDlg(cfg)
  }), [])

  const api = useMemo(() => ({
    alert: (message, opts = {}) =>
      open({ type: 'alert', message, title: opts.title || '提示', confirmText: opts.confirmText || '知道了' }),
    confirm: (message, opts = {}) =>
      open({
        type: 'confirm', message, title: opts.title || '确认',
        confirmText: opts.confirmText || '确认', cancelText: opts.cancelText || '取消',
        danger: !!opts.danger,
      }),
    prompt: (label, defaultValue = '', opts = {}) =>
      open({
        type: 'prompt', message: label, title: opts.title || '输入',
        defaultValue, placeholder: opts.placeholder || '',
        confirmText: opts.confirmText || '确定', cancelText: opts.cancelText || '取消',
      }),
  }), [open])

  return (
    <DialogContext.Provider value={api}>
      {children}
      {dlg && <DialogModal dlg={dlg} onConfirm={close} onCancel={() => close(dlg.type === 'prompt' ? null : false)} />}
    </DialogContext.Provider>
  )
}

function DialogModal({ dlg, onConfirm, onCancel }) {
  const isPrompt = dlg.type === 'prompt'
  const isAlert = dlg.type === 'alert'
  const [value, setValue] = useState(dlg.defaultValue || '')
  const inputRef = useRef(null)

  // 进场自动聚焦：prompt 选中输入框文字，方便直接改写
  useEffect(() => {
    const t = setTimeout(() => {
      if (isPrompt && inputRef.current) { inputRef.current.focus(); inputRef.current.select() }
    }, 0)
    return () => clearTimeout(t)
  }, [isPrompt])

  // 键盘：Esc 取消；Enter 确认（prompt 在输入框内单独处理换行）
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onCancel() }
      else if (e.key === 'Enter' && !isPrompt) { e.preventDefault(); confirm() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPrompt])

  const confirm = () => onConfirm(isPrompt ? value : true)

  const confirmStyle = dlg.danger
    ? { border: 'none', background: 'rgba(239,68,68,0.9)', color: '#fff' }
    : { border: 'none', background: '#6366f1', color: '#fff' }

  return (
    <div onClick={onCancel} style={{
      position: 'fixed', inset: 0, zIndex: 3000,
      background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" style={{
        width: 'min(420px, 92vw)', background: '#161616',
        border: '1px solid rgba(255,255,255,0.13)', borderRadius: 14,
        boxShadow: '0 20px 60px rgba(0,0,0,0.6)', overflow: 'hidden',
      }}>
        <div style={{ padding: '18px 20px 16px' }}>
          <div style={{ fontSize: 14.5, fontWeight: 600, color: 'rgba(255,255,255,0.87)', marginBottom: dlg.message ? 8 : 0 }}>
            {dlg.title}
          </div>
          {dlg.message && (
            <div style={{ fontSize: 13, lineHeight: 1.6, color: 'rgba(255,255,255,0.7)', whiteSpace: 'pre-wrap' }}>
              {dlg.message}
            </div>
          )}
          {isPrompt && (
            <input
              ref={inputRef}
              value={value}
              placeholder={dlg.placeholder}
              onChange={e => setValue(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); confirm() } }}
              style={{
                width: '100%', height: 34, marginTop: 12, padding: '0 10px', boxSizing: 'border-box',
                borderRadius: 8, border: '1px solid rgba(255,255,255,0.13)',
                background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.87)',
                fontSize: 13, fontFamily: 'inherit', outline: 'none', colorScheme: 'dark',
              }}
              onFocus={e => e.target.style.borderColor = '#6366f1'}
              onBlur={e => e.target.style.borderColor = 'rgba(255,255,255,0.13)'}
            />
          )}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, padding: '0 20px 18px' }}>
          {!isAlert && (
            <button onClick={onCancel} style={{
              height: 34, padding: '0 14px', borderRadius: 8,
              border: '1px solid rgba(255,255,255,0.13)', background: 'rgba(255,255,255,0.04)',
              color: 'rgba(255,255,255,0.87)', fontSize: 12.5, cursor: 'pointer', fontFamily: 'inherit',
            }}>{dlg.cancelText}</button>
          )}
          <button onClick={confirm} autoFocus={!isPrompt} style={{
            height: 34, padding: '0 16px', borderRadius: 8, fontSize: 12.5, fontWeight: 600,
            cursor: 'pointer', fontFamily: 'inherit', ...confirmStyle,
          }}>{dlg.confirmText}</button>
        </div>
      </div>
    </div>
  )
}
