import { useState } from 'react'
import { Icon } from './icons'

/**
 * HistorySidebar — 历史会话侧边栏（聊天视图左侧）
 *
 * 显示在最左侧，包含新建对话按钮、历史会话列表（标题、更新时间、消息数量）。
 * 鼠标悬停在历史项上时淡入垃圾桶图标，允许删除会话。
 *
 * 视觉按短剧工作台设计稿逐像素对齐：纯 #0d0d0d、48px 会话条、进行中绿点呼吸(al-glow)。
 */
export default function HistorySidebar({
  runningSessions,
  currentSessionId,
  sessions = [],
  onSelectSession,
  onNewChat,
  onDeleteSession
}) {
  const [newHover, setNewHover] = useState(false)

  return (
    <aside style={{
      width: 260,
      flexShrink: 0,
      height: '100%',
      borderRight: '1px solid rgba(255,255,255,0.07)',
      background: '#0d0d0d',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* 顶部 Logo */}
      <div style={{ padding: '16px 16px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: 22, height: 22, borderRadius: 7, color: '#fff', flexShrink: 0,
          background: 'linear-gradient(135deg,#6366f1,#4338ca)',
        }}>
          <Icon.Clapper size={13} />
        </span>
        <span style={{ fontSize: 13.5, fontWeight: 600, color: 'rgba(255,255,255,0.87)' }}>蜃景</span>
      </div>

      {/* 新建会话 */}
      <div style={{ padding: '0 12px 12px' }}>
        <button
          onClick={onNewChat}
          onMouseEnter={() => setNewHover(true)}
          onMouseLeave={() => setNewHover(false)}
          style={{
            width: '100%', height: 34, borderRadius: 8,
            border: `1px dashed ${newHover ? 'rgba(99,102,241,0.6)' : 'rgba(255,255,255,0.2)'}`,
            background: 'transparent', color: newHover ? '#a5a8ff' : 'rgba(255,255,255,0.52)',
            fontSize: 12.5, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            gap: 7, cursor: 'pointer', fontFamily: 'inherit', transition: 'all .14s', outline: 'none',
          }}
        >
          <Icon.Plus size={13} />New Chat
        </button>
      </div>

      {/* 会话列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
        {sessions.length === 0 ? (
          <div style={{
            fontSize: 12, color: 'rgba(255,255,255,0.30)', textAlign: 'center',
            padding: '32px 8px',
          }}>
            No history yet
          </div>
        ) : (
          sessions.map(s => {
            const isActive = s.session_id === currentSessionId;
            let timeStr = '';
            if (s.updated_at) {
              try {
                const d = new Date(s.updated_at);
                const month = String(d.getMonth() + 1).padStart(2, '0');
                const date = String(d.getDate()).padStart(2, '0');
                const hours = String(d.getHours()).padStart(2, '0');
                const minutes = String(d.getMinutes()).padStart(2, '0');
                timeStr = `${month}/${date} ${hours}:${minutes}`;
              } catch {
                timeStr = String(s.updated_at);
              }
            }

            return (
              <SessionItem
                key={s.session_id}
                session={s}
                isActive={isActive}
                running={runningSessions?.has?.(s.session_id)}
                timeStr={timeStr}
                onClick={() => onSelectSession(s.session_id)}
                onDelete={() => onDeleteSession(s.session_id)}
              />
            );
          })
        )}
      </div>
    </aside>
  );
}

function SessionItem({ session, isActive, running, timeStr, onClick, onDelete }) {
  const [hovered, setHovered] = useState(false);
  const [deleteHovered, setDeleteHovered] = useState(false);

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => {
        setHovered(false);
        setDeleteHovered(false);
      }}
      style={{
        position: 'relative',
        height: 48,
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '0 11px',
        borderRadius: 8,
        cursor: 'pointer',
        userSelect: 'none',
        background: isActive
          ? 'rgba(255,255,255,0.05)'
          : hovered
          ? 'rgba(255,255,255,0.04)'
          : 'transparent',
        transition: 'background .14s',
      }}
    >
      {/* 进行中绿点（呼吸） */}
      {running && (
        <span title="该会话有任务进行中" style={{
          width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
          background: '#34d399',
          animation: 'al-glow 1.6s ease-in-out infinite',
        }} />
      )}

      {/* 内容区 */}
      <div style={{
        minWidth: 0,
        flex: 1,
        paddingRight: hovered ? 22 : 0,
        transition: 'padding-right .14s ease',
      }}>
        {/* 标题 */}
        <div style={{
          fontSize: 12.5,
          color: isActive ? 'rgba(255,255,255,0.87)' : 'rgba(255,255,255,0.52)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {session.title || 'New Chat'}
        </div>

        {/* 副行：N 条 · MM/DD HH:mm */}
        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.30)' }}>
          {session.message_count || 0} 条{timeStr ? ` · ${timeStr}` : ''}
        </div>
      </div>

      {/* 删除按钮（悬停显隐） */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        onMouseEnter={() => setDeleteHovered(true)}
        onMouseLeave={() => setDeleteHovered(false)}
        style={{
          position: 'absolute',
          right: 8,
          top: '50%',
          transform: 'translateY(-50%)',
          width: 22,
          height: 22,
          borderRadius: 6,
          border: 'none',
          background: deleteHovered ? 'rgba(239, 68, 68, 0.15)' : 'transparent',
          color: deleteHovered ? '#ef4444' : 'rgba(255,255,255,0.30)',
          opacity: hovered ? 1 : 0,
          transition: 'all 0.15s ease',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          outline: 'none',
        }}
        title="Delete session"
      >
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          <line x1="10" y1="11" x2="10" y2="17" />
          <line x1="14" y1="11" x2="14" y2="17" />
        </svg>
      </button>
    </div>
  );
}
