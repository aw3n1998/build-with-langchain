import { useState } from 'react'
import { Icon } from './icons'

/**
 * ProjectSidebar —— 工作台（studio）模式的左侧「剧集列表」。
 *
 * 为什么有它：studio 模式下用户面对的是「项目（剧集）」而非聊天会话，
 * 用聊天会话侧栏(HistorySidebar)语义错配（点了没用）。这里把左栏换成剧集列表：
 * 点一条 = 打开该剧集（setPanelProjectId）。新建在顶部，删除/改名收敛在顶栏对「当前剧集」操作。
 * 视觉与 HistorySidebar 对齐（260 宽 / 同款条目），切换模式时左栏观感一致。
 */
export default function ProjectSidebar({ projects = [], currentProjectId, onSelect, onNew, onToChat }) {
  return (
    <aside style={{
      width: 260, background: 'rgba(13, 13, 13, 0.95)', backdropFilter: 'blur(20px)',
      borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column',
      height: '100%', flexShrink: 0, zIndex: 30,
    }}>
      {/* 顶部 Logo + 新建剧集 */}
      <div style={{ padding: '16px 14px 12px 14px', display: 'flex', flexDirection: 'column', gap: 12, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                         width: 22, height: 22, borderRadius: 6, color: '#fff',
                         background: 'linear-gradient(135deg, #6366f1, #4338ca)', flexShrink: 0 }}>
            <Icon.Clapper size={13} />
          </span>
          <span style={{ fontSize: 14, fontWeight: 600, letterSpacing: '-0.01em', color: 'rgba(255,255,255,0.9)' }}>短剧工作台</span>
        </div>

        <button onClick={onNew}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            height: 36, borderRadius: 8, border: '1px dashed var(--border-strong)',
            background: 'rgba(255,255,255,0.02)', color: 'rgba(255,255,255,0.85)',
            fontSize: 12, fontWeight: 500, cursor: 'pointer', transition: 'all 0.15s ease', width: '100%', outline: 'none',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(99,102,241,0.08)'; e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--accent)' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; e.currentTarget.style.borderColor = 'var(--border-strong)'; e.currentTarget.style.color = 'rgba(255,255,255,0.85)' }}>
          <Icon.Plus size={13} />新建剧集
        </button>
      </div>

      {/* 剧集列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 10px 16px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
                      letterSpacing: '0.05em', padding: '10px 8px 6px 8px', flexShrink: 0 }}>
          剧集 · EPISODES
        </div>

        {projects.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', padding: '32px 8px', lineHeight: 1.8 }}>
            还没有剧集<br />点上方「新建剧集」开始
          </div>
        ) : (
          projects.map(p => (
            <ProjectItem key={p.project_id} project={p}
              isActive={p.project_id === currentProjectId}
              onClick={() => onSelect(p.project_id)} />
          ))
        )}
      </div>

      {/* 底部：切到 AI 助手 */}
      <div style={{ padding: '10px 14px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
        <button onClick={onToChat}
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, width: '100%',
                   height: 32, borderRadius: 8, border: '1px solid rgba(99,102,241,0.35)',
                   background: 'rgba(99,102,241,0.10)', color: 'rgba(190,192,255,1)',
                   fontSize: 12, fontWeight: 500, cursor: 'pointer', outline: 'none' }}>
          <Icon.Chat size={14} />AI 助手 · 会话历史
        </button>
      </div>
    </aside>
  )
}

function ProjectItem({ project, isActive, onClick }) {
  const [hovered, setHovered] = useState(false)
  return (
    <div onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{
        position: 'relative', display: 'flex', flexDirection: 'column', gap: 3,
        padding: '10px 12px', borderRadius: 8, cursor: 'pointer',
        background: isActive ? 'rgba(255,255,255,0.05)' : hovered ? 'rgba(255,255,255,0.02)' : 'transparent',
        border: isActive ? '1px solid rgba(255,255,255,0.08)' : '1px solid transparent',
        transition: 'all 0.15s ease', userSelect: 'none', overflow: 'hidden',
      }}>
      {isActive && (
        <div style={{ position: 'absolute', left: 0, top: '25%', bottom: '25%', width: 3,
                      borderRadius: '0 2px 2px 0', background: 'var(--accent)' }} />
      )}
      <div style={{ fontSize: 13, fontWeight: isActive ? 500 : 400,
                    color: isActive ? 'rgba(255,255,255,0.95)' : 'var(--text-sec)',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', lineHeight: 1.2 }}>
        {project.title || '(无题)'}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{project.scenes ?? 0} 镜</div>
    </div>
  )
}
