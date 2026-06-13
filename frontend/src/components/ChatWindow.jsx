import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import { Icon } from './icons'

export default function ChatWindow({ messages, onResume, onSend, onGenerate, onSelectImage, onRenderVideo, workspace, sessionId, compact }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) {
    return compact ? <CompactEmpty /> : <EmptyState />
  }

  const list = (
    <div style={compact
      ? { padding: '12px 12px 16px', display: 'flex', flexDirection: 'column', gap: 12 }
      : { maxWidth: 760, margin: '0 auto', padding: '36px 24px 40px', display: 'flex', flexDirection: 'column', gap: 20 }}>
      {(() => {
        // 最后一条用户消息之后才算"当前回合"；之前的交互卡片（参数卡/选图）失效，不可再点
        let lastUserIdx = -1
        messages.forEach((m, i) => { if (m.role === 'user') lastUserIdx = i })
        return messages.map((msg, i) => (
          <MessageBubble key={msg.id} message={msg} onResume={onResume} onSend={onSend}
                         onGenerate={onGenerate} onSelectImage={onSelectImage}
                         onRenderVideo={onRenderVideo}
                         workspace={workspace} sessionId={sessionId}
                         stale={i < lastUserIdx} compact={compact} />
        ))
      })()}
      <div ref={bottomRef} />
    </div>
  )

  return <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>{list}</div>
}

/* 浮动小助手里的极简空态 */
function CompactEmpty() {
  return (
    <div style={{
      flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', textAlign: 'center', padding: '24px 18px', gap: 6,
    }}>
      <div style={{ fontSize: 26 }}>🎬</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.8)' }}>蜃景小助手</div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6, maxWidth: 240 }}>
        有啥想问的尽管说～比如「这场戏怎么拍」「这个参数啥意思」。<br />拆分镜、出图、出片去左边工作台面板做哦。
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '0 24px',
      textAlign: 'center',
    }}>
      {/* Logo */}
      <div style={{
        width: 48, height: 48, borderRadius: 14,
        background: 'linear-gradient(135deg, #6366f1, #4338ca)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        marginBottom: 20, color: '#fff',
      }}>
        <Icon.Clapper size={24} stroke={1.7} />
      </div>

      <h2 style={{
        fontSize: 18,
        fontWeight: 600,
        color: 'rgba(255,255,255,0.85)',
        letterSpacing: '-0.01em',
        marginBottom: 8,
      }}>
        蜃景 Mirage
      </h2>

      <p style={{
        fontSize: 14,
        color: 'var(--text-muted)',
        maxWidth: 360,
        lineHeight: 1.7,
        marginBottom: 32,
      }}>
        小说一键拆分镜、出图、出片的 AI 短剧工作台。把剧情发给我，或从右上角导入资料后再提问。
      </p>

      {/* 能力卡片 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 10,
        maxWidth: 440,
        width: '100%',
      }}>
        {[
          { label: '混合检索',  desc: 'BM25 + 向量' },
          { label: '流式输出',  desc: '逐字返回' },
          { label: '多 Agent', desc: 'LangGraph 协作' },
          { label: '文档导入',  desc: 'PDF · TXT · DOCX' },
        ].map(({ label, desc }) => (
          <div key={label} style={{
            background: 'var(--card)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: '12px 14px',
            textAlign: 'left',
          }}>
            <p style={{ fontSize: 13, fontWeight: 500, color: 'rgba(255,255,255,0.7)', marginBottom: 3 }}>
              {label}
            </p>
            <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>{desc}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
