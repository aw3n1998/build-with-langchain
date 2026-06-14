import { useState } from 'react'
import MobileStudio from './MobileStudio'
import ChatWindow from '../ChatWindow'
import SettingsPanel from '../SettingsPanel'
import FolderPicker from '../FolderPicker'

/* ── 极简内联图标(避免新增 lucide 依赖) ── */
const P = {
  menu: 'M4 6h16M4 12h16M4 18h16',
  plus: 'M5 12h14M12 5v14',
  x: 'M18 6 6 18M6 6l12 12',
  folder: 'M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z',
}
function I({ d, size = 22, color = 'currentColor', sw = 1.8 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">
      {d.split('M').filter(Boolean).map((seg, i) => <path key={i} d={'M' + seg} />)}
    </svg>
  )
}
function Clapper({ size = 17, color = 'var(--accent)' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.2 6 3 11l-.9-2.4c-.3-.8.1-1.7.9-2l11.3-4.2c.8-.3 1.7.1 2 .9z" />
      <path d="m6.2 5.3 3.1 3.9M12.4 3.4l3.1 4M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  )
}
function Sparkles({ size = 16, color = '#fff' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.14a.5.5 0 0 1 .96 0L14.06 8.5A2 2 0 0 0 15.5 9.94l6.14 1.58a.5.5 0 0 1 0 .96L15.5 14.06a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0z" />
    </svg>
  )
}
function Gear({ size = 20, color = 'var(--text-secondary)' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82 2 2 0 1 1-2.83 2.83 1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51 2 2 0 0 1-4 0 1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33 2 2 0 1 1-2.83-2.83 1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1 2 2 0 0 1 0-4 1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82 2 2 0 1 1 2.83-2.83 1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51 2 2 0 0 1 4 0 1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33 2 2 0 1 1 2.83 2.83 1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1 2 2 0 0 1 0 4 1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

/**
 * MobileShell —— 短剧工作台手机端自适应外壳。
 * 复刻设计的顶栏 + 左侧剧集抽屉 + 底部 AI 助手 Sheet + 双 FAB;
 * 内容与对话复用桌面端已验证的真功能组件,保证即装即用、行为一致。
 */
export default function MobileShell(props) {
  const {
    allProjects = [], panelProjectId, setPanelProjectId, newProject,
    workspace, saveWorkspace, sessionId,
    messages, sendMessage, isStreaming, stopGenerating,
    handleResume, handleGenerate, handleSelectImage, handleRenderVideo,
    agent, setAgent, agentList, ragStatus,
    onSettingsSaved,
  } = props

  const [drawer, setDrawer] = useState(false)
  const [assistant, setAssistant] = useState(false)
  const [settings, setSettings] = useState(false)
  const [folder, setFolder] = useState(false)

  const cur = allProjects.find(p => p.project_id === panelProjectId)
  const epName = cur?.title || '选择或新建剧集'
  const videoOnly = ragStatus?.video_agent_only !== false

  return (
    <div style={{
      position: 'fixed', inset: 0, display: 'flex', flexDirection: 'column',
      background: 'var(--bg)', color: 'var(--text-primary)',
      fontFamily: 'var(--font-sans)', overflow: 'hidden',
    }}>
      {/* ── 顶栏 ── */}
      <header style={{
        flex: 'none', height: 'var(--topbar-h)', paddingTop: 'var(--safe-top)',
        boxSizing: 'content-box', display: 'flex', alignItems: 'center',
        padding: '0 6px', borderBottom: '1px solid var(--border)',
      }}>
        <button aria-label="剧集列表" onClick={() => setDrawer(true)} style={iconBtn}>
          <I d={P.menu} />
        </button>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      gap: 7, minWidth: 0 }}>
          <Clapper />
          <span style={{ fontSize: 16, fontWeight: 600, overflow: 'hidden',
                         textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                         color: cur ? 'var(--text-primary)' : 'var(--text-muted)' }}>{epName}</span>
        </div>
        <button aria-label="AI 助手" onClick={() => setAssistant(true)}
                style={{ ...iconBtn, width: 44 }}>
          <span style={{ width: 30, height: 30, borderRadius: '50%', background: 'var(--logo-grad)',
                         display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
            <Sparkles />
          </span>
        </button>
      </header>

      {/* ── 内容区:移动原生工作室(4 Tab,接真数据) ── */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', WebkitOverflowScrolling: 'touch',
                    padding: `12px var(--gutter) calc(var(--safe-bottom) + 88px)` }}>
        {panelProjectId ? (
          <MobileStudio projectId={panelProjectId} workspace={workspace} sessionId={sessionId} />
        ) : (
          <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '64px 16px' }}>
            <div style={{ width: 56, height: 56, borderRadius: 16, margin: '0 auto 16px',
                          background: 'var(--accent-soft)', border: '1px solid var(--accent-border)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Clapper size={26} />
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>开始做一部短剧</div>
            <p style={{ fontSize: 13, lineHeight: 1.8 }}>点下方「新建剧集」建一个,再用「AI 助手」把小说一键拆成分镜。</p>
            <button onClick={newProject} style={{ ...solidBtn, margin: '16px auto 0' }}>
              <I d={P.plus} size={16} color="#fff" /> 新建剧集
            </button>
          </div>
        )}
      </div>

      {/* ── 左下设置 FAB ── */}
      <button aria-label="设置" onClick={() => setSettings(true)} style={{
        position: 'absolute', left: 16, bottom: 'calc(var(--safe-bottom) + 16px)',
        width: 48, height: 48, borderRadius: 'var(--r-pill)', background: 'var(--surface-raised)',
        border: '1px solid var(--border-strong)', color: 'var(--text-secondary)',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
      }}><Gear /></button>

      {/* ── 右下 AI 助手 FAB ── */}
      <button aria-label="AI 助手" onClick={() => setAssistant(true)} style={{
        position: 'absolute', right: 16, bottom: 'calc(var(--safe-bottom) + 16px)',
        width: 56, height: 56, borderRadius: 'var(--r-pill)', background: 'var(--logo-grad)',
        border: 'none', boxShadow: 'var(--shadow-fab)', color: '#fff',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
      }}><Sparkles size={24} /></button>

      {/* ── 剧集抽屉(左滑) ── */}
      <Overlay open={drawer} onClose={() => setDrawer(false)}>
        <div onClick={e => e.stopPropagation()} style={{
          position: 'absolute', top: 0, bottom: 0, left: 0, width: 300, maxWidth: '86vw',
          background: 'var(--surface-card)', borderRight: '1px solid var(--border-strong)',
          transform: drawer ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform var(--dur-slow) var(--ease-out)',
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ padding: 'calc(var(--safe-top) + 12px) 16px 14px', borderBottom: '1px solid var(--border)',
                        display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 30, height: 30, borderRadius: 8, background: 'var(--logo-grad)',
                           display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
              <Clapper size={16} color="#fff" />
            </span>
            <div style={{ lineHeight: 1.2 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>蜃景 Mirage</div>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>短剧工作台</div>
            </div>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)',
                          padding: '4px 8px 10px', textTransform: 'uppercase', letterSpacing: '.05em' }}>剧集</div>
            {allProjects.length === 0 && (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', padding: '24px 8px' }}>
                还没有剧集<br />点下方「新建剧集」开始
              </div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {allProjects.map(p => {
                const active = p.project_id === panelProjectId
                return (
                  <button key={p.project_id} onClick={() => { setPanelProjectId(p.project_id); setDrawer(false) }}
                    style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 10,
                             padding: '12px 12px 12px 14px', width: '100%', textAlign: 'left',
                             background: active ? 'var(--surface-raised)' : 'transparent',
                             border: 'none', borderRadius: 'var(--r-btn)', cursor: 'pointer' }}>
                    {active && <span style={{ position: 'absolute', left: 0, top: 10, bottom: 10, width: 3,
                                              borderRadius: 3, background: 'var(--purple)' }} />}
                    <Clapper size={18} color={active ? 'var(--purple)' : 'var(--text-muted)'} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: active ? 600 : 500,
                                    color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.title || '(无题)'}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{p.scenes ?? 0} 镜</div>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
          <div style={{ padding: 12, borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button onClick={() => { setDrawer(false); newProject() }} style={ghostBtn}>
              <I d={P.plus} size={16} /> 新建剧集
            </button>
            <button onClick={() => { setDrawer(false); setFolder(true) }} style={ghostBtn}>
              <I d={P.folder} size={16} /> 工作目录
            </button>
          </div>
        </div>
      </Overlay>

      {/* ── 底部 AI 助手 Sheet:复用真聊天 ── */}
      <Sheet open={assistant} title="AI 助手" onClose={() => setAssistant(false)} maxHeight="88%">
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
          <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <ChatWindow messages={messages} onResume={handleResume} onSend={sendMessage}
                        onGenerate={handleGenerate} onSelectImage={handleSelectImage}
                        onRenderVideo={handleRenderVideo} workspace={workspace} sessionId={sessionId} compact />
          </div>
          <MobileInput onSend={sendMessage} disabled={isStreaming} onStop={stopGenerating} />

        </div>
      </Sheet>

      {/* ── 复用桌面端面板(本身即覆盖层) ── */}
      <SettingsPanel open={settings} onClose={() => setSettings(false)} onSaved={onSettingsSaved} videoOnly={videoOnly} />
      <FolderPicker open={folder} initial={workspace} onClose={() => setFolder(false)} onPick={saveWorkspace} />
    </div>
  )
}

/* ── 通用覆盖层 + 底部 Sheet ── */
function Overlay({ open, onClose, children }) {
  return (
    <div onClick={onClose} style={{
      position: 'absolute', inset: 0, zIndex: 60, pointerEvents: open ? 'auto' : 'none',
    }}>
      <div style={{ position: 'absolute', inset: 0, background: 'var(--scrim)',
                    opacity: open ? 1 : 0, transition: 'opacity var(--dur-base)' }} />
      {children}
    </div>
  )
}
function Sheet({ open, title, onClose, children, maxHeight = '86%' }) {
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 50, pointerEvents: open ? 'auto' : 'none' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'var(--scrim)',
                                      opacity: open ? 1 : 0, transition: 'opacity var(--dur-base) var(--ease-out)' }} />
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, maxHeight, height: maxHeight,
                    display: 'flex', flexDirection: 'column', background: 'var(--surface-card)',
                    borderTop: '1px solid var(--border-strong)', borderTopLeftRadius: 18, borderTopRightRadius: 18,
                    boxShadow: 'var(--shadow-sheet)', transform: open ? 'translateY(0)' : 'translateY(100%)',
                    transition: 'transform var(--dur-slow) var(--ease-out)' }}>
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 8 }}>
          <span style={{ width: 36, height: 4, borderRadius: 2, background: 'var(--border-strong)' }} />
        </div>
        {title && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '10px 16px 12px', borderBottom: '1px solid var(--border)' }}>
            <span style={{ fontSize: 16, fontWeight: 600 }}>{title}</span>
            <button aria-label="关闭" onClick={onClose} style={{ ...iconBtn, width: 32, height: 32 }}>
              <I d={P.x} size={18} color="var(--text-secondary)" />
            </button>
          </div>
        )}
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', WebkitOverflowScrolling: 'touch',
                      display: 'flex', flexDirection: 'column' }}>{children}</div>
      </div>
    </div>
  )
}

/* 底部输入条:textarea + 发送(Enter 发送 / Shift+Enter 换行),流式时显示停止 */
function MobileInput({ onSend, disabled, onStop }) {
  const [text, setText] = useState('')
  const submit = () => {
    const t = text.trim()
    if (!t || disabled) return
    onSend(t); setText('')
  }
  return (
    <div style={{ flex: 'none', borderTop: '1px solid var(--border)',
                  padding: `8px 12px calc(var(--safe-bottom) + 8px)`, background: 'var(--surface-card)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, background: 'var(--surface-sunken)',
                    border: '1px solid var(--border-strong)', borderRadius: 'var(--r-btn)', padding: '4px 4px 4px 12px' }}>
        <textarea value={text} onChange={e => setText(e.target.value)} placeholder="给 AI 助手发消息…"
          rows={1} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', resize: 'none',
                   color: 'var(--text-primary)', fontSize: 14, fontFamily: 'var(--font-sans)',
                   lineHeight: 1.5, maxHeight: 120, padding: '8px 0' }} />
        {disabled ? (
          <button aria-label="停止" onClick={onStop} style={{ ...sendBtn, background: 'var(--surface-raised)', color: 'var(--text-secondary)' }}>
            <span style={{ width: 12, height: 12, borderRadius: 2, background: 'currentColor' }} />
          </button>
        ) : (
          <button aria-label="发送" onClick={submit} style={sendBtn}>
            <I d="M12 19V5M5 12l7-7 7 7" size={18} color="#fff" />
          </button>
        )}
      </div>
    </div>
  )
}

const sendBtn = {
  width: 40, height: 40, flex: 'none', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  background: 'var(--logo-grad)', color: '#fff', border: 'none', borderRadius: 'var(--r-btn)', cursor: 'pointer',
}
const iconBtn = {
  width: 44, height: 44, flex: 'none', display: 'inline-flex', alignItems: 'center',
  justifyContent: 'center', background: 'transparent', border: 'none', color: 'var(--text-primary)',
  borderRadius: 'var(--r-btn)', cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
}
const ghostBtn = {
  width: '100%', height: 40, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  gap: 7, background: 'transparent', border: '1px solid var(--border-strong)', color: 'var(--text-primary)',
  borderRadius: 'var(--r-btn)', fontSize: 13, fontFamily: 'inherit', cursor: 'pointer',
}
const solidBtn = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 7, height: 44,
  padding: '0 18px', background: 'var(--accent)', border: 'none', color: '#fff', fontWeight: 600,
  fontSize: 14, borderRadius: 'var(--r-btn)', fontFamily: 'inherit', cursor: 'pointer',
}
