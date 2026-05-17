import ReactMarkdown from 'react-markdown'

/**
 * MessageBubble — 消息渲染
 *
 * 用户消息：右对齐纯文字，无背景
 * AI 消息：全宽深色卡片，含 AGENTLAB 标签 + Markdown + 来源标签
 */
export default function MessageBubble({ message, onResume }) {
  if (message.role === 'user') {
    return <UserMessage content={message.content} />
  }
  if (message.role === 'interrupt') {
    return <InterruptCard message={message} onResume={onResume} />
  }
  return <AssistantMessage message={message} />
}

/* ── 用户消息 ──────────────────────────────────────── */
function UserMessage({ content }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '4px 0' }}>
      <p style={{
        maxWidth: '72%',
        fontSize: 14,
        lineHeight: 1.7,
        color: 'rgba(255,255,255,0.82)',
        textAlign: 'right',
        whiteSpace: 'pre-wrap',
      }}>
        {content}
      </p>
    </div>
  )
}

/* ── AI 消息卡片 ────────────────────────────────────── */
function AssistantMessage({ message }) {
  const sources = extractSources(message.content)

  return (
    <div style={{
      background: 'var(--card)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: '16px 20px',
    }}>
      {/* AGENTLAB 标签 */}
      <p style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        color: 'var(--text-dim)',
        marginBottom: 12,
      }}>
        AGENTLAB
      </p>

      {/* Markdown 内容 */}
      <div className="prose-content">
        <ReactMarkdown
          components={{
            // 代码块
            code({ node, inline, className, children, ...props }) {
              if (inline) {
                return <code {...props}>{children}</code>
              }
              return (
                <pre>
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              )
            },
            // 链接新标签打开
            a({ href, children }) {
              return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
            },
          }}
        >
          {message.content || (message.streaming ? '​' : '')}
        </ReactMarkdown>

        {/* 流式光标 */}
        {message.streaming && <span className="cursor-blink" />}
      </div>

      {/* 来源标签（RAG 检索到来源时显示） */}
      {sources.length > 0 && !message.streaming && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 6,
          marginTop: 16,
          paddingTop: 14,
          borderTop: '1px solid var(--border)',
        }}>
          {sources.map((src, i) => (
            <span key={i} style={{
              fontSize: 11,
              color: 'var(--text-muted)',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid var(--border)',
              borderRadius: 5,
              padding: '2px 8px',
              fontFamily: 'monospace',
              letterSpacing: '0.01em',
            }}>
              <span style={{ color: 'var(--text-dim)', marginRight: 5 }}>
                {String(i + 1).padStart(2, '0')}
              </span>
              {src}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * 从 AI 消息内容中提取来源文件名。
 * 匹配后端 RAG 工具返回格式：[N] 来源：xxx.txt
 */
function extractSources(content) {
  if (!content) return []
  const pattern = /来源[：:]\s*([^\s（(）)，,\n]+)/g
  const found = new Set()
  let m
  while ((m = pattern.exec(content)) !== null) {
    found.add(m[1].trim())
  }
  return [...found].slice(0, 5) // 最多显示 5 个来源
}

/* ── HITL 确认卡片 ────────────────────────────────────── */
function InterruptCard({ message, onResume }) {
  // resolved: undefined=等待, true=已确认, false=已取消
  const resolved = message.resolved

  // 图标
  const WarningIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
      <line x1="12" y1="9" x2="12" y2="13"/>
      <line x1="12" y1="17" x2="12.01" y2="17"/>
    </svg>
  )

  const CheckIcon = () => (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  )

  const XIcon = () => (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  )

  return (
    <div style={{
      border: `1px solid ${resolved === undefined ? 'rgba(234,179,8,0.35)' : resolved ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
      borderRadius: 12,
      padding: '14px 18px',
      background: resolved === undefined
        ? 'rgba(234,179,8,0.06)'
        : resolved
          ? 'rgba(34,197,94,0.05)'
          : 'rgba(239,68,68,0.05)',
      transition: 'all 0.2s',
    }}>
      {/* 标题行 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{
          color: resolved === undefined ? 'rgba(234,179,8,0.85)' : resolved ? 'rgba(34,197,94,0.85)' : 'rgba(239,68,68,0.85)',
        }}>
          <WarningIcon />
        </span>
        <span style={{
          fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: resolved === undefined ? 'rgba(234,179,8,0.7)' : resolved ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)',
        }}>
          Human-in-the-loop · 等待确认
        </span>
      </div>

      {/* 描述 */}
      <p style={{
        fontSize: 13.5, lineHeight: 1.65,
        color: 'rgba(255,255,255,0.75)',
        marginBottom: resolved === undefined ? 14 : 0,
      }}>
        {message.content}
      </p>

      {/* 按钮 or 结果标签 */}
      {resolved === undefined ? (
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => onResume?.(true)}
            style={{
              height: 30, padding: '0 16px', borderRadius: 8, border: 'none',
              background: 'rgba(34,197,94,0.18)',
              color: 'rgba(34,197,94,0.9)',
              fontSize: 12, fontWeight: 600, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6,
              border: '1px solid rgba(34,197,94,0.25)',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(34,197,94,0.28)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(34,197,94,0.18)'}
          >
            <CheckIcon /> 确认执行
          </button>
          <button
            onClick={() => onResume?.(false)}
            style={{
              height: 30, padding: '0 16px', borderRadius: 8,
              background: 'rgba(239,68,68,0.12)',
              color: 'rgba(239,68,68,0.85)',
              fontSize: 12, fontWeight: 600, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6,
              border: '1px solid rgba(239,68,68,0.22)',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.22)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(239,68,68,0.12)'}
          >
            <XIcon /> 取消
          </button>
        </div>
      ) : (
        <span style={{
          fontSize: 12, fontWeight: 500,
          color: resolved ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)',
          display: 'flex', alignItems: 'center', gap: 5,
        }}>
          {resolved ? <CheckIcon /> : <XIcon />}
          {resolved ? '已确认执行' : '已取消'}
        </span>
      )}
    </div>
  )
}
