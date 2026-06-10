import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { fileUrl } from '../api'

/**
 * MessageBubble — 消息渲染
 *
 * 用户消息：右对齐纯文字
 * AI 消息：深色卡片 + Markdown + pcAction 按钮 + MSG_SPLIT 快捷区 + 图片墙
 * Interrupt：HITL 确认卡片
 * param_form：出图参数交互卡
 */
export default function MessageBubble({ message, onResume, onSend, onGenerate, onSelectImage, onRenderVideo, stale }) {
  if (message.role === 'user') {
    return <UserMessage content={message.content} />
  }
  if (message.role === 'interrupt') {
    return <InterruptCard message={message} onResume={onResume} />
  }
  if (message.role === 'param_form') {
    return <ParamCard message={message} onGenerate={onGenerate} stale={stale} />
  }
  if (message.role === 'video_param_form') {
    return <VideoParamCard message={message} onRenderVideo={onRenderVideo} stale={stale} />
  }
  return <AssistantMessage message={message} onSend={onSend} onSelectImage={onSelectImage} stale={stale} />
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

/* ── pcAction 解析工具 ──────────────────────────────── */

/**
 * 把原始内容按 <MSG_SPLIT>...</MSG_SPLIT> 或 <MSG_SPLIT> 分割成两部分：
 * { main: string, quickReplies: string }
 */
function splitMsgSplit(content) {
  if (!content) return { main: '', quickReplies: '' }
  // 兼容带闭合标签 <MSG_SPLIT>...</MSG_SPLIT> 和单标签 <MSG_SPLIT>
  const splitRe = /<MSG_SPLIT>([\s\S]*?)<\/MSG_SPLIT>|<MSG_SPLIT>/i
  const m = splitRe.exec(content)
  if (!m) return { main: content, quickReplies: '' }
  const main = content.slice(0, m.index).trim()
  const quickReplies = m[1] !== undefined ? m[1].trim() : content.slice(m.index + m[0].length).trim()
  return { main, quickReplies }
}

/**
 * 把一段文本按 <pcAction>...</pcAction> 拆分成混合数组：
 * ['文字', { label, ...json }, '文字', ...]
 */
function parsePcActions(text) {
  if (!text) return []
  const re = /<pcAction>([\s\S]*?)<\/pcAction>/gi
  const parts = []
  let lastIndex = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > lastIndex) {
      parts.push(text.slice(lastIndex, m.index))
    }
    try {
      parts.push(JSON.parse(m[1].trim()))
    } catch {
      // JSON 解析失败时作为普通文字
      parts.push(m[1].trim())
    }
    lastIndex = re.lastIndex
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

/* ── AI 消息卡片 ────────────────────────────────────── */
function AssistantMessage({ message, onSend, onSelectImage, stale }) {
  const { main, quickReplies } = splitMsgSplit(message.content || '')
  const mainParts = parsePcActions(main)
  const quickParts = parsePcActions(quickReplies)

  const sources = extractSources(main)

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

      {/* 工具调用链：让"调用了什么"在页面可见 */}
      {message.steps && message.steps.length > 0 && (
        <ToolSteps steps={message.steps} />
      )}

      {/* 主内容区：文字 + 内嵌 pcAction */}
      <div className="prose-content">
        {mainParts.map((part, i) => {
          if (typeof part === 'string') {
            return (
              <ReactMarkdown key={i} components={markdownComponents}>
                {part}
              </ReactMarkdown>
            )
          }
          return <PcActionButton key={i} action={part} onSend={onSend} />
        })}
        {message.streaming && <span className="cursor-blink" />}
      </div>

      {/* 候选图墙：点击=放大，按钮=选图 */}
      {message.images && message.images.length > 0 && (
        <ImageWall images={message.images} onSelectImage={onSelectImage} stale={stale} />
      )}

      {/* 成片内嵌播放器 */}
      {message.video && (
        <div style={{ marginTop: 14 }}>
          <video src={fileUrl(message.video.url)} controls
                 style={{ maxWidth: '100%', maxHeight: 420, borderRadius: 10,
                          border: '1px solid var(--border)', display: 'block' }} />
          <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-muted)', marginTop: 4 }}>
            {message.video.name}
          </div>
        </div>
      )}

      {/* RAG 来源标签 */}
      {sources.length > 0 && !message.streaming && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 6,
          marginTop: 16, paddingTop: 14,
          borderTop: '1px solid var(--border)',
        }}>
          {sources.map((src, i) => (
            <span key={i} style={{
              fontSize: 11, color: 'var(--text-muted)',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid var(--border)',
              borderRadius: 5, padding: '2px 8px',
              fontFamily: 'monospace', letterSpacing: '0.01em',
            }}>
              <span style={{ color: 'var(--text-dim)', marginRight: 5 }}>
                {String(i + 1).padStart(2, '0')}
              </span>
              {src}
            </span>
          ))}
        </div>
      )}

      {/* MSG_SPLIT 快捷回复区 */}
      {quickParts.length > 0 && !message.streaming && (
        <div style={{
          marginTop: 14,
          paddingTop: 12,
          borderTop: '1px solid var(--border)',
          display: 'flex',
          flexWrap: 'wrap',
          gap: 8,
        }}>
          {quickParts.filter(p => typeof p === 'object').map((action, i) => (
            <PcActionButton key={i} action={action} onSend={onSend} isQuickReply />
          ))}
        </div>
      )}
    </div>
  )
}

/* ── 候选图墙（点击=放大预览，灯箱里再选图）──────────── */
function ImageWall({ images, onSelectImage, stale }) {
  const [zoom, setZoom] = useState(null)   // 当前放大查看的图
  const canSelect = !stale
  return (
    <>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(140px,1fr))',
        gap: 10, marginTop: 14,
      }}>
        {images.map((img, i) => (
          <div key={img.assetId || i}
            onClick={() => setZoom(img)}
            title="点击放大查看"
            style={{
              position: 'relative', borderRadius: 10, overflow: 'hidden', cursor: 'zoom-in',
              border: img.selected ? '2px solid rgba(34,197,94,0.9)' : '1px solid var(--border)',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.02)'}
            onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
          >
            <img src={fileUrl(img.url)} alt={img.name}
                 style={{ width: '100%', display: 'block', aspectRatio: '3/4', objectFit: 'cover' }} />
            {/* 缩略图上的小选图按钮（回合结束后禁用） */}
            {(canSelect || img.selected) && (
              <button
                onClick={e => { e.stopPropagation(); if (canSelect) onSelectImage?.(img.sceneId, img.assetId) }}
                title={canSelect ? '选这张' : '已选'}
                disabled={!canSelect}
                style={{
                  position: 'absolute', top: 6, right: 6, width: 24, height: 24, borderRadius: 6,
                  border: 'none', cursor: canSelect ? 'pointer' : 'default', fontSize: 13,
                  background: img.selected ? 'rgba(34,197,94,0.9)' : 'rgba(0,0,0,0.5)',
                  color: '#fff',
                }}>{img.selected ? '✓' : '○'}</button>
            )}
            <div style={{
              position: 'absolute', left: 0, right: 0, bottom: 0,
              padding: '3px 6px', fontSize: 10, fontFamily: 'monospace',
              color: '#fff', background: 'rgba(0,0,0,0.55)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{img.name}</span>
              {img.selected && <span style={{ color: 'rgba(134,239,172,1)' }}>✓选中</span>}
            </div>
          </div>
        ))}
      </div>

      {/* 放大灯箱 */}
      {zoom && (
        <div onClick={() => setZoom(null)} style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)', zIndex: 2000,
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14,
          padding: 24,
        }}>
          <img src={fileUrl(zoom.url)} alt={zoom.name}
               onClick={e => e.stopPropagation()}
               style={{ maxWidth: '90vw', maxHeight: '78vh', objectFit: 'contain',
                        borderRadius: 8, boxShadow: '0 8px 40px rgba(0,0,0,0.6)' }} />
          <div onClick={e => e.stopPropagation()}
               style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 12, fontFamily: 'monospace', color: 'rgba(255,255,255,0.7)' }}>{zoom.name}</span>
            {canSelect && (
              <button onClick={() => { onSelectImage?.(zoom.sceneId, zoom.assetId); setZoom(null) }}
                style={{
                  height: 32, padding: '0 18px', borderRadius: 8, border: '1px solid rgba(34,197,94,0.4)',
                  background: 'rgba(34,197,94,0.2)', color: 'rgba(134,239,172,1)',
                  fontSize: 13, fontWeight: 600, cursor: 'pointer',
                }}>选这张</button>
            )}
            <button onClick={() => setZoom(null)} style={{
              height: 32, padding: '0 16px', borderRadius: 8, border: '1px solid var(--border)',
              background: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.75)',
              fontSize: 13, cursor: 'pointer',
            }}>关闭</button>
          </div>
        </div>
      )}
    </>
  )
}

/* ── 出图参数交互卡 ─────────────────────────────────── */
function ParamCard({ message, onGenerate, stale }) {
  const [p, setP] = useState(message.params)
  const submitted = message.submitted || stale   // 回合结束后参数卡也失效
  const sizePreset = `${p.width}x${p.height}`

  const field = (label, key, type = 'number', opts) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</span>
      {opts ? (
        <select value={p[key]} disabled={submitted}
          onChange={e => setP({ ...p, [key]: e.target.value })}
          style={inputStyle}>
          {opts.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
        </select>
      ) : (
        <input type={type} value={p[key]} disabled={submitted}
          onChange={e => setP({ ...p, [key]: type === 'number' ? Number(e.target.value) : e.target.value })}
          style={inputStyle} />
      )}
    </label>
  )

  return (
    <div style={{
      border: '1px solid rgba(99,102,241,0.3)', background: 'rgba(99,102,241,0.06)',
      borderRadius: 12, padding: '16px 18px',
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                    color: 'rgba(165,168,255,0.8)', marginBottom: 12 }}>
        出图参数 · 确认后生成
      </div>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>提示词（含触发词 ch4r_cael）</span>
        <textarea value={p.image_prompt} disabled={submitted} rows={2}
          onChange={e => setP({ ...p, image_prompt: e.target.value })}
          style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
      </label>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginBottom: 12 }}>
        {field('张数', 'n')}
        {field('步数', 'steps')}
        {field('guidance', 'guidance', 'number')}
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>尺寸</span>
          <select value={sizePreset} disabled={submitted}
            onChange={e => { const [w, h] = e.target.value.split('x').map(Number); setP({ ...p, width: w, height: h }) }}
            style={inputStyle}>
            <option value="768x1024">768×1024 竖屏</option>
            <option value="1024x768">1024×768 横屏</option>
            <option value="1024x1024">1024×1024 方形</option>
            <option value={sizePreset}>{sizePreset}（当前）</option>
          </select>
        </label>
        {field('seed(-1随机)', 'seed')}
        {field('显存', 'offload', 'text', [{ v: 'model', label: 'model 快' }, { v: 'sequential', label: 'sequential 省显存' }])}
      </div>

      <button
        onClick={() => onGenerate?.(message.id, p)}
        disabled={submitted}
        style={{
          height: 34, padding: '0 20px', borderRadius: 8, border: '1px solid rgba(99,102,241,0.35)',
          background: submitted ? 'rgba(255,255,255,0.06)' : 'rgba(99,102,241,0.22)',
          color: submitted ? 'var(--text-muted)' : 'rgba(190,192,255,1)',
          fontSize: 13, fontWeight: 600, cursor: submitted ? 'default' : 'pointer',
        }}>
        {submitted ? '已提交出图' : '出图'}
      </button>
    </div>
  )
}

/* ── 出视频参数交互卡 ───────────────────────────────── */
function VideoParamCard({ message, onRenderVideo, stale }) {
  const [p, setP] = useState(message.params)
  const submitted = message.submitted || stale

  return (
    <div style={{
      border: '1px solid rgba(0,189,176,0.3)', background: 'rgba(0,189,176,0.06)',
      borderRadius: 12, padding: '16px 18px',
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                    color: 'rgba(94,234,212,0.85)', marginBottom: 12 }}>
        出视频参数 · 确认后生成
      </div>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>运镜 / 动态提示词</span>
        <textarea value={p.motion_prompt} disabled={submitted} rows={2}
          onChange={e => setP({ ...p, motion_prompt: e.target.value })}
          style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
      </label>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginBottom: 12 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>分辨率</span>
          <select value={p.size} disabled={submitted}
            onChange={e => setP({ ...p, size: e.target.value })} style={inputStyle}>
            <option value="704*1280">704×1280 竖屏</option>
            <option value="1280*704">1280×704 横屏</option>
            <option value="960*960">960×960 方形</option>
            <option value={p.size}>{p.size}（当前）</option>
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>帧数(≤25稳)</span>
          <input type="number" value={p.frame_num} disabled={submitted}
            onChange={e => setP({ ...p, frame_num: Number(e.target.value) })} style={inputStyle} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>采样步数</span>
          <input type="number" value={p.sample_steps} disabled={submitted}
            onChange={e => setP({ ...p, sample_steps: Number(e.target.value) })} style={inputStyle} />
        </label>
      </div>

      <button
        onClick={() => onRenderVideo?.(message.id, p)}
        disabled={submitted}
        style={{
          height: 34, padding: '0 20px', borderRadius: 8, border: '1px solid rgba(0,189,176,0.4)',
          background: submitted ? 'rgba(255,255,255,0.06)' : 'rgba(0,189,176,0.22)',
          color: submitted ? 'var(--text-muted)' : 'rgba(94,234,212,1)',
          fontSize: 13, fontWeight: 600, cursor: submitted ? 'default' : 'pointer',
        }}>
        {submitted ? '已提交出视频' : '出视频'}
      </button>
    </div>
  )
}

const inputStyle = {
  height: 30, padding: '0 8px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.85)', fontSize: 12,
}

/* ── 工具调用链渲染 ─────────────────────────────────── */
function ToolSteps({ steps }) {
  const summarizeArgs = (args) => {
    if (!args || typeof args !== 'object') return ''
    try {
      const s = JSON.stringify(args)
      return s.length > 80 ? s.slice(0, 80) + '…' : s
    } catch {
      return ''
    }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
      {steps.map((s, i) => (
        <div key={i} style={{
          fontSize: 12,
          fontFamily: 'monospace',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '8px 10px',
          background: 'rgba(255,255,255,0.03)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ color: s.done ? 'rgba(134,239,172,0.9)' : 'rgba(234,179,8,0.9)' }}>
              {s.done ? '✓' : '·'}
            </span>
            <span style={{ fontWeight: 700, color: 'rgba(147,197,253,0.95)' }}>{s.name}</span>
            {s.args && Object.keys(s.args).length > 0 && (
              <span style={{ color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {summarizeArgs(s.args)}
              </span>
            )}
          </div>
          {s.result && (
            <div style={{
              marginTop: 6,
              paddingTop: 6,
              borderTop: '1px solid var(--border)',
              color: 'var(--text-muted)',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              maxHeight: 90,
              overflow: 'auto',
            }}>
              {s.result}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/* ── pcAction 按钮渲染 ──────────────────────────────── */
function PcActionButton({ action, onSend, isQuickReply = false }) {
  const hasUserInput = !!action.userInput
  const openType = action.openType || ''

  // 颜色主题
  let bgColor, borderColor, textColor, hoverBg
  if (hasUserInput || isQuickReply) {
    // 快捷回复按钮：紫色调
    bgColor   = 'rgba(99,102,241,0.12)'
    borderColor = 'rgba(99,102,241,0.3)'
    textColor = 'rgba(165,168,255,0.9)'
    hoverBg   = 'rgba(99,102,241,0.22)'
  } else if (openType === 'add') {
    // 新增操作：蓝色调
    bgColor   = 'rgba(59,130,246,0.1)'
    borderColor = 'rgba(59,130,246,0.3)'
    textColor = 'rgba(147,197,253,0.9)'
    hoverBg   = 'rgba(59,130,246,0.2)'
  } else if (openType === 'check') {
    // 查看操作：绿色调
    bgColor   = 'rgba(34,197,94,0.1)'
    borderColor = 'rgba(34,197,94,0.3)'
    textColor = 'rgba(134,239,172,0.9)'
    hoverBg   = 'rgba(34,197,94,0.2)'
  } else {
    // 其他：灰色
    bgColor   = 'rgba(255,255,255,0.06)'
    borderColor = 'rgba(255,255,255,0.12)'
    textColor = 'rgba(255,255,255,0.6)'
    hoverBg   = 'rgba(255,255,255,0.1)'
  }

  const handleClick = () => {
    if (hasUserInput && onSend) {
      onSend(action.userInput)
    }
    // 导航类按钮在 agent 侧暂不做路由，仅作展示
  }

  // 图标
  const icon = hasUserInput
    ? '>'
    : openType === 'add'
      ? '+'
      : openType === 'check'
        ? '→'
        : '·'

  return (
    <button
      onClick={handleClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        height: 30,
        padding: '0 14px',
        borderRadius: 8,
        border: `1px solid ${borderColor}`,
        background: bgColor,
        color: textColor,
        fontSize: 12,
        fontWeight: 500,
        cursor: hasUserInput ? 'pointer' : 'default',
        transition: 'all 0.15s',
        whiteSpace: 'nowrap',
        marginTop: isQuickReply ? 0 : 8,
      }}
      onMouseEnter={e => { if (hasUserInput) e.currentTarget.style.background = hoverBg }}
      onMouseLeave={e => { if (hasUserInput) e.currentTarget.style.background = bgColor }}
    >
      <span style={{ fontSize: 13, lineHeight: 1 }}>{icon}</span>
      {action.label || action.name || '操作'}
    </button>
  )
}

/* ── Markdown 组件配置 ──────────────────────────────── */
const markdownComponents = {
  // react-markdown v9 不再传 inline 参数：用「是否含换行 / 有无 language- 类名」判断块级，
  // 否则所有行内 `code` 都会被渲染成整块黑条。
  code({ node, className, children, ...props }) {
    const text = String(children ?? '')
    const isBlock = /language-/.test(className || '') || text.includes('\n')
    if (!isBlock) return <code className="inline-code" {...props}>{children}</code>
    return (
      <pre>
        <code className={className} {...props}>{children}</code>
      </pre>
    )
  },
  a({ href, children }) {
    return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
  },
}

/* ── RAG 来源提取 ───────────────────────────────────── */
function extractSources(content) {
  if (!content) return []
  const pattern = /来源[：:]\s*([^\s（(）)，,\n]+)/g
  const found = new Set()
  let m
  while ((m = pattern.exec(content)) !== null) found.add(m[1].trim())
  return [...found].slice(0, 5)
}

/* ── HITL 确认卡片 ────────────────────────────────────── */
function InterruptCard({ message, onResume }) {
  const resolved = message.resolved

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

  const accentColor = resolved === undefined
    ? 'rgba(234,179,8,0.85)'
    : resolved ? 'rgba(34,197,94,0.85)' : 'rgba(239,68,68,0.85)'

  return (
    <div style={{
      border: `1px solid ${resolved === undefined ? 'rgba(234,179,8,0.35)' : resolved ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
      borderRadius: 12,
      padding: '14px 18px',
      background: resolved === undefined
        ? 'rgba(234,179,8,0.06)'
        : resolved ? 'rgba(34,197,94,0.05)' : 'rgba(239,68,68,0.05)',
      transition: 'all 0.2s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ color: accentColor }}><WarningIcon /></span>
        <span style={{
          fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: accentColor.replace('0.85', '0.7'),
        }}>
          Human-in-the-loop · 等待确认
        </span>
      </div>

      <p style={{
        fontSize: 13.5, lineHeight: 1.65,
        color: 'rgba(255,255,255,0.75)',
        marginBottom: resolved === undefined ? 14 : 0,
      }}>
        {message.content}
      </p>

      {resolved === undefined ? (
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => onResume?.(true)}
            style={{
              height: 30, padding: '0 16px', borderRadius: 8, border: '1px solid rgba(34,197,94,0.25)',
              background: 'rgba(34,197,94,0.18)', color: 'rgba(34,197,94,0.9)',
              fontSize: 12, fontWeight: 600, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6, transition: 'all 0.15s',
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
              background: 'rgba(239,68,68,0.12)', color: 'rgba(239,68,68,0.85)',
              fontSize: 12, fontWeight: 600, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6,
              border: '1px solid rgba(239,68,68,0.22)', transition: 'all 0.15s',
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
