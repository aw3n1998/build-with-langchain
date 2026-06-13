import { Icon } from './icons'

/**
 * TopBar — 顶部导航栏
 *
 * 左：Logo 方块 + "蜃景" + 分隔点 + 模型名
 * 右：新建对话图标 / Knowledge Base 按钮 / 设置图标
 */
export default function TopBar({ model, ragStatus, onKnowledgeClick, showKnowledge, onNewChat, onSettingsClick }) {
  return (
    <header style={{
      height: 44,
      flexShrink: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 18px',
      borderBottom: '1px solid rgba(255,255,255,0.07)',
      background: 'rgba(13,13,13,0.82)',
      backdropFilter: 'blur(14px)',
    }}>
      {/* ── 左：品牌标识 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* Logo 方块 */}
        <div style={{
          width: 20, height: 20, borderRadius: 7,
          background: 'linear-gradient(135deg,#6366f1,#4338ca)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#fff', flexShrink: 0,
        }}>
          <Icon.Clapper size={12} />
        </div>

        <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: '-0.01em', color: 'rgba(255,255,255,0.87)' }}>
          蜃景
        </span>

        <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: 12 }}>·</span>

        <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,0.52)', fontFamily: "'SF Mono',ui-monospace,monospace" }}>
          {model}
        </span>
      </div>

      {/* ── 右：操作区 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {/* 新建对话 */}
        <IconBtn title="新建对话" onClick={onNewChat}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>
            <path d="m15 5 4 4"/>
          </svg>
        </IconBtn>

        {/* Knowledge Base 按钮 */}
        <button
          onClick={onKnowledgeClick}
          style={{
            height: 30, padding: '0 11px',
            fontSize: 11.5,
            color: showKnowledge ? '#a5a8ff' : 'rgba(255,255,255,0.7)',
            background: showKnowledge ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.04)',
            border: `1px solid ${showKnowledge ? 'rgba(99,102,241,0.5)' : 'rgba(255,255,255,0.13)'}`,
            borderRadius: 7,
            cursor: 'pointer',
            display: 'inline-flex', alignItems: 'center', gap: 7,
            fontFamily: 'inherit',
            transition: 'all 0.15s',
          }}
          onMouseEnter={e => {
            if (!showKnowledge) e.currentTarget.style.background = 'rgba(255,255,255,0.08)'
          }}
          onMouseLeave={e => {
            if (!showKnowledge) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
          }}
        >
          {/* 连接状态绿点 */}
          <span style={{
            width: 5, height: 5, borderRadius: '50%', flexShrink: 0,
            background: ragStatus.rag_connected ? '#34d399' : '#ef4444',
          }} />
          Knowledge Base
          {ragStatus.rag_connected && ragStatus.chunk_count > 0 && (
            <span style={{
              fontSize: 9.5,
              padding: '1px 5px', borderRadius: 4,
              background: 'rgba(255,255,255,0.1)',
            }}>
              {ragStatus.chunk_count}
            </span>
          )}
        </button>

        {/* 设置 */}
        <IconBtn title="Settings" onClick={onSettingsClick}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
          </svg>
        </IconBtn>
      </div>
    </header>
  )
}

function IconBtn({ children, title, onClick }) {
  return (
    <button
      title={title}
      onClick={onClick}
      style={{
        width: 30, height: 30,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        borderRadius: 7,
        border: '1px solid rgba(255,255,255,0.13)',
        background: 'rgba(255,255,255,0.04)',
        color: 'rgba(255,255,255,0.7)', cursor: 'pointer',
        fontFamily: 'inherit',
        transition: 'all 0.15s',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = 'rgba(255,255,255,0.08)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
      }}
    >
      {children}
    </button>
  )
}
