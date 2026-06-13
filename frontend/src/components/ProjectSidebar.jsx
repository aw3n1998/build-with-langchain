import { useState } from 'react'
import { Icon } from './icons'

/**
 * ProjectSidebar —— 工作台（studio）模式的左侧「剧集列表」。
 *
 * 为什么有它：studio 模式下用户面对的是「项目（剧集）」而非聊天会话，
 * 用聊天会话侧栏(HistorySidebar)语义错配（点了没用）。这里把左栏换成剧集列表：
 * 点一条 = 打开该剧集（setPanelProjectId）。新建在顶部，删除/改名收敛在顶栏对「当前剧集」操作。
 *
 * 视觉按短剧工作台设计稿逐像素对齐：纯 #0d0d0d、单行 40px 剧集条、镜数右对齐、
 * 选中态左侧 3px 紫条 + 浅底，底部「AI 助手」为中性灰按钮。
 */
export default function ProjectSidebar({ projects = [], currentProjectId, onSelect, onNew, onToChat }) {
  const [newHover, setNewHover] = useState(false)
  const [chatHover, setChatHover] = useState(false)
  return (
    <aside style={{
      width: 260, flexShrink: 0, height: '100%',
      borderRight: '1px solid rgba(255,255,255,0.07)', background: '#0d0d0d',
      display: 'flex', flexDirection: 'column',
    }}>
      {/* 顶部 Logo */}
      <div style={{ padding: '16px 16px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
                       width: 22, height: 22, borderRadius: 7, color: '#fff', flexShrink: 0,
                       background: 'linear-gradient(135deg,#6366f1,#4338ca)' }}>
          <Icon.Clapper size={13} />
        </span>
        <span style={{ fontSize: 13.5, fontWeight: 600, color: 'rgba(255,255,255,0.87)' }}>短剧工作台</span>
      </div>

      {/* 新建剧集 */}
      <div style={{ padding: '0 12px 12px' }}>
        <button onClick={onNew}
          onMouseEnter={() => setNewHover(true)} onMouseLeave={() => setNewHover(false)}
          style={{
            width: '100%', height: 34, borderRadius: 8,
            border: `1px dashed ${newHover ? 'rgba(99,102,241,0.6)' : 'rgba(255,255,255,0.2)'}`,
            background: 'transparent', color: newHover ? '#a5a8ff' : 'rgba(255,255,255,0.52)',
            fontSize: 12.5, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            gap: 7, cursor: 'pointer', fontFamily: 'inherit', transition: 'all .14s', outline: 'none',
          }}>
          <Icon.Plus size={13} />新建剧集
        </button>
      </div>

      {/* 剧集列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
        {projects.length === 0 ? (
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.30)', textAlign: 'center',
                        padding: '32px 8px', lineHeight: 1.8 }}>
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
      <div style={{ padding: 12, borderTop: '1px solid rgba(255,255,255,0.07)' }}>
        <button onClick={onToChat}
          onMouseEnter={() => setChatHover(true)} onMouseLeave={() => setChatHover(false)}
          style={{ width: '100%', height: 34, borderRadius: 8, border: '1px solid rgba(255,255,255,0.13)',
                   background: chatHover ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.04)',
                   color: 'rgba(255,255,255,0.87)', fontSize: 12.5, display: 'inline-flex',
                   alignItems: 'center', justifyContent: 'center', gap: 8, cursor: 'pointer',
                   fontFamily: 'inherit', transition: 'background .14s', outline: 'none' }}>
          <Icon.Chat size={14} />AI 助手 · 会话历史
        </button>
      </div>
    </aside>
  )
}

function ProjectItem({ project, isActive, onClick }) {
  const [hovered, setHovered] = useState(false)
  const scenes = project.scenes ?? 0
  return (
    <div onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{
        position: 'relative', height: 40, display: 'flex', alignItems: 'center',
        padding: '0 12px', borderRadius: 8, cursor: 'pointer', userSelect: 'none',
        background: isActive ? 'rgba(255,255,255,0.05)' : hovered ? 'rgba(255,255,255,0.02)' : 'transparent',
        transition: 'background .14s',
      }}>
      {isActive && (
        <div style={{ position: 'absolute', left: 0, top: 9, bottom: 9, width: 3,
                      borderRadius: '0 2px 2px 0', background: '#6366f1' }} />
      )}
      <span style={{ fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis',
                     whiteSpace: 'nowrap',
                     color: isActive ? 'rgba(255,255,255,0.87)' : 'rgba(255,255,255,0.52)' }}>
        {project.title || '(无题)'}
      </span>
      <span style={{ marginLeft: 'auto', fontSize: 11, flexShrink: 0,
                     color: scenes ? 'rgba(255,255,255,0.30)' : 'rgba(255,255,255,0.18)' }}>
        {scenes} 镜
      </span>
    </div>
  )
}
