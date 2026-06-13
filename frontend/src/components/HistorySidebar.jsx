import { useState } from 'react'

/**
 * HistorySidebar — 历史会话侧边栏
 *
 * 显示在最左侧，包含新建对话按钮、历史会话列表（显示标题、更新时间、消息数量）
 * 鼠标悬停在历史项上时，会淡入垃圾桶图标，允许删除会话。
 */
export default function HistorySidebar({
  runningSessions,
  currentSessionId,
  sessions = [],
  onSelectSession,
  onNewChat,
  onDeleteSession
}) {
  return (
    <aside style={{
      width: 260,
      background: 'rgba(13, 13, 13, 0.95)',
      backdropFilter: 'blur(20px)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      flexShrink: 0,
      transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
      zIndex: 30,
    }}>
      {/* ── 顶部 Logo 和新建会话 ── */}
      <div style={{
        padding: '16px 14px 12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* Logo 装饰 */}
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
            Mirage
          </span>
        </div>
        
        <button
          onClick={onNewChat}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            height: 36,
            borderRadius: 8,
            border: '1px dashed var(--border-strong)',
            background: 'rgba(255,255,255,0.02)',
            color: 'rgba(255,255,255,0.85)',
            fontSize: 12,
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'all 0.15s ease',
            width: '100%',
            outline: 'none',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'rgba(99, 102, 241, 0.08)'
            e.currentTarget.style.borderColor = 'var(--accent)'
            e.currentTarget.style.color = 'var(--accent)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'rgba(255,255,255,0.02)'
            e.currentTarget.style.borderColor = 'var(--border-strong)'
            e.currentTarget.style.color = 'rgba(255,255,255,0.85)'
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New Chat
        </button>
      </div>

      {/* ── 中间滚动列表 ── */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '0 10px 16px 10px',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
      }}>
        <div style={{
          fontSize: 10,
          fontWeight: 600,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          padding: '10px 8px 6px 8px',
          flexShrink: 0,
        }}>
          History Threads
        </div>

        {sessions.length === 0 ? (
          <div style={{
            fontSize: 12,
            color: 'var(--text-muted)',
            textAlign: 'center',
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
                const month = d.getMonth() + 1;
                const date = d.getDate();
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
        display: 'flex',
        alignItems: 'center',
        padding: '10px 12px',
        borderRadius: 8,
        cursor: 'pointer',
        background: isActive
          ? 'rgba(255, 255, 255, 0.05)'
          : hovered
          ? 'rgba(255, 255, 255, 0.02)'
          : 'transparent',
        border: isActive
          ? '1px solid rgba(255, 255, 255, 0.08)'
          : '1px solid transparent',
        transition: 'all 0.15s ease',
        userSelect: 'none',
        overflow: 'hidden',
      }}
    >
      {/* Active left indicator decoration */}
      {isActive && (
        <div style={{
          position: 'absolute',
          left: 0,
          top: '25%',
          bottom: '25%',
          width: 3,
          borderRadius: '0 2px 2px 0',
          background: 'var(--accent)',
        }} />
      )}

      {/* Content Area */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 3,
        flex: 1,
        minWidth: 0,
        paddingRight: hovered ? 22 : 0,
        transition: 'padding-right 0.15s ease',
      }}>
        {/* Title */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontSize: 13,
          fontWeight: isActive ? 500 : 400,
          color: isActive ? 'rgba(255, 255, 255, 0.95)' : 'var(--text-sec)',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          lineHeight: '1.2',
        }}>
          {running && (
            <span title="该会话有任务进行中" style={{
              width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
              background: 'rgba(34,197,94,1)',
              boxShadow: '0 0 6px rgba(34,197,94,0.8)',
              animation: 'blink 1.6s ease-in-out infinite',
            }} />
          )}
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {session.title || 'New Chat'}
          </span>
        </div>

        {/* Subtitle/Meta info */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 11,
          color: 'var(--text-muted)',
        }}>
          <span>{session.message_count || 0} 条</span>
          {timeStr && (
            <>
              <span>·</span>
              <span style={{ fontSize: 10 }}>{timeStr}</span>
            </>
          )}
        </div>
      </div>

      {/* Delete button (visible on hover) */}
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
          color: deleteHovered ? '#ef4444' : 'var(--text-muted)',
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
