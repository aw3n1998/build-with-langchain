/**
 * TopBar — 顶部导航栏
 *
 * 左：Logo 方块 + "AgentLab" + 分隔点 + 模型名
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
      padding: '0 16px',
      borderBottom: '1px solid var(--border)',
      background: 'rgba(13,13,13,0.95)',
      backdropFilter: 'blur(12px)',
    }}>
      {/* ── 左：品牌标识 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* Logo 方块 */}
        <div style={{
          width: 22, height: 22, borderRadius: 6,
          background: 'linear-gradient(135deg, #6366f1, #4338ca)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          <div style={{
            width: 9, height: 9, borderRadius: 2,
            background: 'rgba(13,13,13,0.7)',
          }} />
        </div>

        <span style={{ fontSize: 14, fontWeight: 600, letterSpacing: '-0.01em', color: 'rgba(255,255,255,0.9)' }}>
          AgentLab
        </span>

        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>·</span>

        <span style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
          {model}
        </span>
      </div>

      {/* ── 右：操作区 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {/* 新建对话 */}
        <IconBtn title="新建对话" onClick={onNewChat}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/>
          </svg>
        </IconBtn>

        {/* Knowledge Base 按钮 */}
        <button
          onClick={onKnowledgeClick}
          style={{
            height: 28, padding: '0 10px',
            fontSize: 12, fontWeight: 500,
            color: showKnowledge ? 'rgba(255,255,255,0.85)' : 'var(--text-sec)',
            background: showKnowledge ? 'rgba(99,102,241,0.15)' : 'transparent',
            border: `1px solid ${showKnowledge ? 'rgba(99,102,241,0.4)' : 'var(--border-strong)'}`,
            borderRadius: 7,
            cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
            transition: 'all 0.15s',
          }}
          onMouseEnter={e => {
            if (!showKnowledge) {
              e.currentTarget.style.borderColor = 'rgba(255,255,255,0.25)'
              e.currentTarget.style.color = 'rgba(255,255,255,0.75)'
            }
          }}
          onMouseLeave={e => {
            if (!showKnowledge) {
              e.currentTarget.style.borderColor = 'var(--border-strong)'
              e.currentTarget.style.color = 'var(--text-sec)'
            }
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
              fontSize: 10, color: 'var(--text-muted)',
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid var(--border)',
              borderRadius: 4, padding: '0 5px',
            }}>
              {ragStatus.chunk_count}
            </span>
          )}
        </button>

        {/* 设置 */}
        <IconBtn title="Settings" onClick={onSettingsClick}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        borderRadius: 7, border: 'none', background: 'transparent',
        color: 'var(--text-muted)', cursor: 'pointer',
        transition: 'all 0.15s',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = 'rgba(255,255,255,0.07)'
        e.currentTarget.style.color = 'rgba(255,255,255,0.75)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'transparent'
        e.currentTarget.style.color = 'var(--text-muted)'
      }}
    >
      {children}
    </button>
  )
}
