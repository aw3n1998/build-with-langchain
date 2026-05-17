import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'

export default function ChatWindow({ messages, onResume }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <main style={{ flex: 1, overflowY: 'auto' }}>
      {messages.length === 0 ? (
        <EmptyState />
      ) : (
        <div style={{
          maxWidth: 760,
          margin: '0 auto',
          padding: '40px 24px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}>
          {messages.map(msg => (
            <MessageBubble key={msg.id} message={msg} onResume={onResume} />
          ))}
          <div ref={bottomRef} />
        </div>
      )}
    </main>
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
        marginBottom: 20,
      }}>
        <div style={{
          width: 20, height: 20, borderRadius: 5,
          background: 'rgba(13,13,13,0.65)',
        }} />
      </div>

      <h2 style={{
        fontSize: 18,
        fontWeight: 600,
        color: 'rgba(255,255,255,0.85)',
        letterSpacing: '-0.01em',
        marginBottom: 8,
      }}>
        AgentLab
      </h2>

      <p style={{
        fontSize: 14,
        color: 'var(--text-muted)',
        maxWidth: 360,
        lineHeight: 1.7,
        marginBottom: 32,
      }}>
        An AI agent with knowledge base retrieval. Import documents from the top-right, then ask questions based on your content.
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
          { label: 'Hybrid retrieval',    desc: 'BM25 + vector search' },
          { label: 'Streaming responses', desc: 'Token-by-token output' },
          { label: 'Multi-agent',         desc: 'LangGraph supervisor' },
          { label: 'Document ingestion',  desc: 'PDF · TXT · DOCX' },
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
