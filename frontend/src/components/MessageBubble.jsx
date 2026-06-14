import { useState, useEffect, useMemo, useRef } from 'react'
import { Icon } from './icons'
import { useDialog } from './Dialog'

// 面板参数持久化：存到浏览器 localStorage，刷新后不丢，省得每次重设。
// 只用于「设置类」状态（模型/尺寸/段数/高级参数等），不用于每镜临时态或拉取的数据。
function usePersistedState(key, initial) {
  const K = 'agentlab.panel.' + key
  const [val, setVal] = useState(() => {
    try { const raw = localStorage.getItem(K); return raw != null ? JSON.parse(raw) : initial }
    catch { return initial }
  })
  useEffect(() => {
    try { localStorage.setItem(K, JSON.stringify(val)) } catch { /* 隐私模式/配额满：忽略 */ }
  }, [K, val])
  return [val, setVal]
}
import ReactMarkdown from 'react-markdown'
import { fileUrl, getVideoProviders, getImageProviders, getProject, batchGenerate, batchFinish,
         pipelineSelect, streamJobEvents, uploadCandidate, updateScenePrompts,
         deleteCandidate, deleteSceneVideo, sceneUndoAppend, deleteEpisode, suggestSegmentPrompts,
         autoStoryboard, autoFill, characters as charactersApi, templatesApi,
         loraCreate, loraAction, loraUploadImage, loraUploadRef,
         suggestContinuation, sceneGenerate, sceneRender, sceneAppend,
         cancelJob, listActiveJobs,
         projectStyle, sceneAdd, sceneDelete } from '../api'

/**
 * MessageBubble — 消息渲染
 *
 * 用户消息：右对齐纯文字
 * AI 消息：深色卡片 + Markdown + pcAction 按钮 + MSG_SPLIT 快捷区 + 图片墙
 * Interrupt：HITL 确认卡片
 * param_form：出图参数交互卡
 */
export default function MessageBubble({ message, onResume, onSend, onGenerate, onSelectImage, onRenderVideo, workspace, sessionId, stale, compact }) {
  if (message.role === 'user') {
    return <UserMessage content={message.content} />
  }
  if (message.role === 'interrupt') {
    return <InterruptCard message={message} onResume={onResume} />
  }
  // compact（浮动小助手）模式：生产类卡片不在小窗里堆，给一行轻量占位，引导去工作台。
  if (message.role === 'param_form') {
    return compact ? <CompactNote text="出图参数卡 —— 请到工作台面板出图" /> : <ParamCard message={message} onGenerate={onGenerate} stale={stale} />
  }
  if (message.role === 'video_param_form') {
    return compact ? <CompactNote text="出视频参数卡 —— 请到工作台面板出片" /> : <VideoParamCard message={message} onRenderVideo={onRenderVideo} stale={stale} />
  }
  if (message.role === 'production') {
    return compact ? <CompactNote text="短剧制作面板 —— 请在工作台查看" /> : <ProductionPanel message={message} workspace={workspace} sessionId={sessionId} />
  }
  return <AssistantMessage message={message} onSend={onSend} onSelectImage={onSelectImage} stale={stale} compact={compact} />
}

/* 浮动小助手里的生产类占位条：不渲染重卡片，引导回工作台 */
function CompactNote({ text }) {
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 7, alignSelf: 'flex-start',
      fontSize: 12, color: 'rgba(255,255,255,0.52)',
      background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)',
      borderRadius: 8, padding: '7px 11px',
    }}>
      <span>📋</span>{text}
    </div>
  )
}

/* ── 用户消息 ──────────────────────────────────────── */
function UserMessage({ content }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '4px 0' }}>
      <div style={{
        maxWidth: '72%',
        background: 'rgba(99,102,241,0.14)',
        border: '1px solid rgba(99,102,241,0.25)',
        borderRadius: '14px 14px 4px 14px',
        padding: '11px 15px',
        fontSize: 13.5,
        lineHeight: 1.55,
        color: 'rgba(255,255,255,0.87)',
        whiteSpace: 'pre-wrap',
      }}>
        {content}
      </div>
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
function AssistantMessage({ message, onSend, onSelectImage, stale, compact }) {
  const { main, quickReplies } = splitMsgSplit(message.content || '')
  const mainParts = parsePcActions(main)
  const quickParts = parsePcActions(quickReplies)

  const sources = extractSources(main)

  return (
    <div>
      {/* MIRAGE 品牌标签：裸渲染（无卡片框），紫色 SF Mono */}
      <p style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '1px',
        textTransform: 'uppercase',
        color: '#6366f1',
        fontFamily: "'SF Mono', ui-monospace, monospace",
        marginBottom: 9,
      }}>
        MIRAGE
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

      {/* 候选图墙：点击=放大，按钮=选图（compact 小助手里不堆图，去工作台看）*/}
      {!compact && message.images && message.images.length > 0 && (
        <ImageWall images={message.images} onSelectImage={onSelectImage} stale={stale} />
      )}

      {/* 成片内嵌播放器 */}
      {!compact && message.video && (
        <div style={{ marginTop: 14 }}>
          <video src={fileUrl(message.video.url)} controls
                 style={{ maxWidth: '100%', maxHeight: 420, borderRadius: 10,
                          border: '1px solid var(--border)', display: 'block' }} />
          <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-muted)', marginTop: 4 }}>
            {message.video.name}
          </div>
        </div>
      )}

      {/* RAG 来源标签：靛蓝 pill（对齐 mockup #01 file.md）*/}
      {sources.length > 0 && !message.streaming && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 11,
        }}>
          {sources.map((src, i) => (
            <span key={i} style={{
              fontSize: 10.5, color: '#a5a8ff',
              background: 'rgba(99,102,241,0.1)',
              border: '1px solid rgba(99,102,241,0.25)',
              borderRadius: 5, padding: '3px 8px',
              fontFamily: "'SF Mono', ui-monospace, monospace", letterSpacing: '0.01em',
            }}>
              <span style={{ color: 'rgba(165,168,255,0.6)', marginRight: 5 }}>
                #{String(i + 1).padStart(2, '0')}
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
              position: 'relative', borderRadius: 9, overflow: 'hidden', cursor: 'zoom-in',
              border: img.selected ? '2px solid #34d399' : '1px solid rgba(255,255,255,0.1)',
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
                  background: img.selected ? '#34d399' : 'rgba(0,0,0,0.5)',
                  color: img.selected ? '#04201a' : '#fff',
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
  // param_form 内输入框用青色描边（对齐 mockup），其余沿用 inputStyle
  const cyanInput = { ...inputStyle, border: '1px solid rgba(0,189,176,0.25)' }

  const field = (label, key, type = 'number', opts) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</span>
      {opts ? (
        <select value={p[key]} disabled={submitted}
          onChange={e => setP({ ...p, [key]: e.target.value })}
          style={cyanInput}>
          {opts.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
        </select>
      ) : (
        <input type={type} value={p[key]} disabled={submitted}
          onChange={e => setP({ ...p, [key]: type === 'number' ? Number(e.target.value) : e.target.value })}
          style={cyanInput} />
      )}
    </label>
  )

  return (
    <div style={{
      border: '1px solid rgba(0,189,176,0.3)', background: 'rgba(0,189,176,0.05)',
      borderRadius: 12, padding: '15px 17px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00bdb0" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M15 4V2"/><path d="M8 9h2"/><path d="m3 21 9-9"/><path d="M12.2 6.2 11 5"/></svg>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: '#5fe8de' }}>出图参数卡 param_form</span>
      </div>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>提示词（角色触发词已自动加好）</span>
        <textarea value={p.image_prompt} disabled={submitted} rows={2}
          onChange={e => setP({ ...p, image_prompt: e.target.value })}
          style={{ ...cyanInput, resize: 'vertical', fontFamily: 'inherit' }} />
      </label>

      {/* 常用：张数 + 尺寸（小白只看这些）*/}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 10, marginBottom: 10 }}>
        {field('张数', 'n')}
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>尺寸</span>
          <select value={sizePreset} disabled={submitted}
            onChange={e => { const [w, h] = e.target.value.split('x').map(Number); setP({ ...p, width: w, height: h }) }}
            style={cyanInput}>
            <option value="768x1024">768×1024 竖屏</option>
            <option value="1024x768">1024×768 横屏</option>
            <option value="1024x1024">1024×1024 方形</option>
            <option value={sizePreset}>{sizePreset}（当前）</option>
          </select>
        </label>
      </div>

      {/* 高级：步数 / guidance / seed / 显存（折叠）*/}
      <AdvancedSection>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 10 }}>
          {field('步数', 'steps')}
          {field('guidance', 'guidance', 'number')}
          {field('seed(-1随机)', 'seed')}
          {field('显存', 'offload', 'text', [{ v: 'model', label: 'model 快' }, { v: 'sequential', label: 'sequential 省显存' }])}
        </div>
      </AdvancedSection>

      <button
        onClick={() => onGenerate?.(message.id, p)}
        disabled={submitted}
        style={{
          marginTop: 12,
          height: 34, padding: '0 20px', borderRadius: 8, border: 'none',
          background: submitted ? 'rgba(255,255,255,0.06)' : '#00bdb0',
          color: submitted ? 'var(--text-muted)' : '#04201e',
          fontSize: 13, fontWeight: 600, cursor: submitted ? 'default' : 'pointer',
        }}>
        {submitted ? '已提交出图' : '出图'}
      </button>
    </div>
  )
}

/* ── 出视频参数交互卡（多模型 + schema 驱动）─────────── */

// 小问号 + 悬停说明气泡
function HelpTip({ text }) {
  const [show, setShow] = useState(false)
  if (!text) return null
  return (
    <span style={{ position: 'relative', display: 'inline-flex', verticalAlign: 'middle' }}
      onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
      <span style={{
        width: 13, height: 13, borderRadius: '50%', border: '1px solid var(--text-muted)',
        color: 'var(--text-muted)', fontSize: 9, fontWeight: 700, lineHeight: '11px',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        marginLeft: 5, cursor: 'help',
      }}>?</span>
      {show && (
        <span style={{
          position: 'absolute', bottom: '150%', left: '50%', transform: 'translateX(-50%)',
          width: 210, padding: '8px 11px', borderRadius: 8, background: '#0b0c0e',
          border: '1px solid var(--border)', color: 'rgba(255,255,255,0.85)',
          fontSize: 11, lineHeight: 1.55, fontWeight: 400, textTransform: 'none', letterSpacing: 0,
          zIndex: 60, boxShadow: '0 6px 22px rgba(0,0,0,0.55)', whiteSpace: 'normal', textAlign: 'left',
        }}>{text}</span>
      )}
    </span>
  )
}

// 老事件没有 fields 时的兜底 schema。与后端 Wan2.2/ComfyUI provider 字段对齐(frames/fps/steps/negative)，
// 避免旧事件显示成 frame_num(≤25)/sample_steps 那套过时的 2 参数(A14B 早已不是 ≤25/24fps 的旧 5B 档)。
function legacyVideoFields(params) {
  return [
    { key: 'size', label: '分辨率(宽*高)', type: 'select', default: params.size || '720*1280',
      help: '成片宽×高。竖屏适合手机；越大越清晰也越慢。',
      options: [
        { value: '480*832', label: '480×832 竖屏快出' },
        { value: '720*1280', label: '720×1280 竖屏高清' },
        { value: '832*480', label: '832×480 横屏快出' },
        { value: '1280*720', label: '1280×720 横屏高清' },
      ] },
    { key: 'frames', label: '帧数', type: 'number', default: params.frames ?? params.frame_num ?? 81,
      help: '总帧数。时长≈帧数÷帧率。A14B 常用 81（≈5 秒）。' },
    { key: 'fps', label: '帧率', type: 'number', default: params.fps ?? 16,
      help: '每秒帧数。Wan 系常用 16。' },
    { key: 'steps', label: '采样步数', type: 'number', default: params.steps ?? params.sample_steps ?? 30,
      help: '去噪步数，一般 20-30。' },
    { key: 'negative', label: '负向提示词', type: 'text', default: params.negative ?? '',
      help: '不想要的内容（避免畸形/水印等）。' },
  ]
}

function fieldsToValues(fields) {
  const v = {}
  for (const f of fields) v[f.key] = f.default
  return v
}

function VideoParamCard({ message, onRenderVideo, stale }) {
  const submitted = message.submitted || stale
  const init = message.params || {}

  // 全部模型的 schema（注册即出现）：优先从后端拉取，失败则用事件里携带的当前模型 schema 兜底
  const [providers, setProviders] = useState(null)   // [{name, display_name, fields}]
  const [model, setModel] = useState(init.model || '')
  const [motionPrompt, setMotionPrompt] = useState(init.motion_prompt || '')

  // 当前模型的字段定义
  const curFields = useMemo(() => {
    const fromProviders = providers?.find(p => p.name === model)?.fields
    if (fromProviders) return fromProviders
    if (init.fields && (model === init.model || !model)) return init.fields
    return legacyVideoFields(init)
  }, [providers, model, init])

  const [values, setValues] = useState(() =>
    fieldsToValues(init.fields || legacyVideoFields(init)))

  const simpleFields = curFields.filter(f => !f.advanced)
  const advancedFields = curFields.filter(f => f.advanced)

  // 拉取所有模型（仅活跃卡片需要；stale/已提交的历史卡片不必）
  useEffect(() => {
    if (submitted) return
    let alive = true
    getVideoProviders()
      .then(d => {
        if (!alive) return
        setProviders(d.providers || [])
        if (!model && d.default) setModel(d.default)
      })
      .catch(() => {})
    return () => { alive = false }
  }, [submitted])  // eslint-disable-line react-hooks/exhaustive-deps

  // 切换模型时，按该模型 schema 重置参数值
  const switchModel = (name) => {
    setModel(name)
    const f = providers?.find(p => p.name === name)?.fields
    if (f) setValues(fieldsToValues(f))
  }

  const models = (providers && providers.length)
    ? providers.map(p => ({ name: p.name, display_name: p.display_name }))
    : (init.models || (init.model ? [{ name: init.model, display_name: init.model }] : []))

  const submit = () => {
    onRenderVideo?.(message.id, {
      scene_id: init.scene_id,
      motion_prompt: motionPrompt,
      model,
      params: values,
    })
  }

  // 预计时长 = 帧数 ÷ 帧率 × 接续段数。Wan 用 frame_num + 固定 24fps；LTX 用 num_frames + 可调 fps。
  const estDuration = useMemo(() => {
    const frames = Number(values.frame_num ?? values.num_frames)
    const fps = Number(values.fps) || 24   // 无 fps 字段（如 Wan2.2）按 24fps 估
    const segs = Math.max(1, Number(values.segments) || 1)
    if (!frames || !fps) return null
    return { sec: (frames / fps) * segs, frames, fps, segs }
  }, [values])

  const renderField = (f) => {
    const val = values[f.key]
    const set = (v) => setValues(prev => ({ ...prev, [f.key]: v }))
    return (
      <label key={f.key} style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: '1 1 130px', minWidth: 120 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center' }}>
          {f.label}<HelpTip text={f.help} />
        </span>
        {f.type === 'select' ? (
          <select value={val} disabled={submitted}
            onChange={e => {
              const opt = f.options?.find(o => String(o.value) === e.target.value)
              set(opt ? opt.value : e.target.value)
            }} style={inputStyle}>
            {(f.options || []).map(o => (
              <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
            ))}
          </select>
        ) : (
          <input type={f.type === 'number' ? 'number' : 'text'} value={val ?? ''} disabled={submitted}
            onChange={e => set(f.type === 'number' ? Number(e.target.value) : e.target.value)}
            style={inputStyle} />
        )}
      </label>
    )
  }

  return (
    <div style={{
      border: '1px solid rgba(0,189,176,0.3)', background: 'rgba(0,189,176,0.05)',
      borderRadius: 12, padding: '15px 17px',
    }}>
      {/* 顶部横条：标题 + 模型选择 + 预计时长，一行读完 */}
      <div style={{
        display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00bdb0" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/></svg>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: '#5fe8de' }}>出视频参数卡 video_param_form</span>
        </div>

        {/* 模型选择（≥2 个模型时显示） */}
        {models.length > 1 && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center' }}>
              模型<HelpTip text="选择视频生成模型。Wan2.2 画质更高但更慢；LTX 出片更快，适合先预演看效果。" />
            </span>
            <select value={model} disabled={submitted}
              onChange={e => switchModel(e.target.value)} style={{ ...inputStyle, width: 'auto' }}>
              {models.map(m => <option key={m.name} value={m.name}>{m.display_name}</option>)}
            </select>
          </label>
        )}

        {/* 预计时长：新手不用心算，改帧数/帧率会实时变 */}
        {estDuration && (
          <div style={{
            marginLeft: 'auto', display: 'flex', alignItems: 'baseline', gap: 6,
            padding: '5px 12px', borderRadius: 8,
            background: 'rgba(0,189,176,0.08)', border: '1px solid rgba(0,189,176,0.2)',
          }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>预计时长</span>
            <span style={{ fontSize: 16, fontWeight: 700, color: 'rgba(94,234,212,1)' }}>
              ≈ {estDuration.sec.toFixed(1)}s
            </span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              （{estDuration.frames}帧÷{estDuration.fps}fps{estDuration.segs > 1 ? `×${estDuration.segs}段` : ''}）
            </span>
          </div>
        )}
      </div>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center' }}>
          运镜 / 动态提示词<HelpTip text="描述镜头怎么动、画面怎么变：如推近、拉远、摇镜、人物动作、光影流动等，越具体效果越好。" />
        </span>
        <textarea value={motionPrompt} disabled={submitted} rows={2}
          onChange={e => setMotionPrompt(e.target.value)}
          style={{ ...inputStyle, height: 'auto', padding: '6px 8px', resize: 'vertical', fontFamily: 'inherit' }} />
      </label>

      {/* 常用参数横向铺开（小白只看这些）；高级参数折叠 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 12, alignItems: 'flex-end' }}>
        {simpleFields.map(renderField)}
        <button
          onClick={submit}
          disabled={submitted}
          style={{
            flex: '0 0 auto', height: 30, padding: '0 22px', borderRadius: 8,
            border: 'none',
            background: submitted ? 'rgba(255,255,255,0.06)' : '#00bdb0',
            color: submitted ? 'var(--text-muted)' : '#04201e',
            fontSize: 13, fontWeight: 600, cursor: submitted ? 'default' : 'pointer',
          }}>
          {submitted ? '已提交' : '出视频'}
        </button>
      </div>

      {advancedFields.length > 0 && (
        <AdvancedSection>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'flex-end' }}>
            {advancedFields.map(renderField)}
          </div>
        </AdvancedSection>
      )}
    </div>
  )
}

/* 折叠的「高级参数」区：小白默认看不到，进阶用户点开 */
function AdvancedSection({ children }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ marginTop: 2 }}>
      <button onClick={() => setOpen(o => !o)} style={{
        background: 'none', border: 'none', cursor: 'pointer', padding: '2px 0',
        color: 'var(--text-muted)', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4,
      }}>
        <span style={{ display: 'inline-block', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>▸</span>
        高级参数
      </button>
      {open && <div style={{ marginTop: 8 }}>{children}</div>}
    </div>
  )
}

/* ── 制作面板：确定性整片流程（一键出图 → 点选 → 一键出片合成）──────── */
const STATE_LABEL = {
  DRAFT:                   { t: '待出图',     c: 'rgba(255,255,255,0.52)', bg: 'rgba(255,255,255,0.06)', bd: 'rgba(255,255,255,0.13)' },
  PENDING_FLUX_GEN:        { t: '出图中',     c: '#eab308', bg: 'rgba(234,179,8,0.12)',  bd: 'rgba(234,179,8,0.35)', spin: true },
  PENDING_HUMAN_SELECTION: { t: '待选图',     c: '#c084fc', bg: 'rgba(168,85,247,0.12)', bd: 'rgba(168,85,247,0.35)' },
  PENDING_VIDEO_GEN:       { t: '已选·待出片', c: '#5fe8de', bg: 'rgba(0,189,176,0.12)',  bd: 'rgba(0,189,176,0.35)' },
  COMPLETED:               { t: '已出片',     c: '#34d399', bg: 'rgba(52,211,153,0.12)', bd: 'rgba(52,211,153,0.35)' },
  FAILED:                  { t: '失败',       c: '#f87171', bg: 'rgba(239,68,68,0.12)',  bd: 'rgba(239,68,68,0.35)' },
}

export function ProductionPanel({ message, workspace, sessionId }) {
  const dialog = useDialog()
  const pid = message.project_id
  const [proj, setProj] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')       // '' | 'generate' | 'finish'
  const [progress, setProgress] = useState('')
  const [zoom, setZoom] = useState(null)
  const [models, setModels] = useState([])
  const [model, setModel] = usePersistedState('videoModel', '')   // 持久化：上次选的出片模型
  const [imgModels, setImgModels] = useState([])     // 出图模型（公开名 flux 等；ComfyUI 透明顶替，不单列）
  const [imgModel, setImgModel] = usePersistedState('imageModel', '')  // 持久化：上次选的出图模型
  const [segments, setSegments] = usePersistedState('segments', 1)     // 持久化：全局默认段数
  const [sceneSegments, setSceneSegments] = useState({})  // {sceneId: 段数} 单镜覆盖
  const [sceneSegPrompts, setSceneSegPrompts] = useState({}) // {sceneId: [每段运镜提示词]}（AI生成/手改，不入库）
  const [sceneIntent, setSceneIntent] = useState({})      // {sceneId: 中文意图}（喂给AI拆分段）
  const [segGenBusy, setSegGenBusy] = useState({})        // {sceneId: 正在生成分段提示词}
  const [imgN, setImgN] = usePersistedState('imgN', 4)              // 持久化：每镜候选张数
  const [imgSize, setImgSize] = usePersistedState('imgSize', '768x1024')  // 持久化：出图尺寸
  const [vidSize, setVidSize] = usePersistedState('vidSize', '')   // 持久化：出片分辨率（空=默认）
  // 「更多参数」专业档：出图（空=用默认）；出片（按所选模型 schema 动态生成）。均持久化。
  const [showAdv, setShowAdv] = usePersistedState('showAdv', false)
  const [imgAdv, setImgAdv] = usePersistedState('imgAdv', { steps: '', guidance: '', seed: '', offload: '' })
  const [vidParams, setVidParams] = usePersistedState('vidParams', {})
  const [sceneBusy, setSceneBusy] = useState({})   // {sceneId: 'generate'|'render'|'append'}
  const [appendPrompt, setAppendPrompt] = useState({})  // {sceneId: 追加段的运镜提示词(可空)}
  const [appendCount, setAppendCount] = useState({})    // {sceneId: 本次追加几段}
  const [appendLang, setAppendLang] = useState({})      // {sceneId: 'zh'|'en'} 推荐语言
  const [appendSugBusy, setAppendSugBusy] = useState({})// {sceneId: AI 推荐请求中}
  const [sceneLipsync, setSceneLipsync] = useState({})  // {sceneId: 对口型开关(本地态，叠加 scene.lipsync)}
  // 剧集级风格（每集一种风格）+ 自助新增分镜
  const [showStyle, setShowStyle] = useState(false)
  const [style, setStyle] = useState(null)              // {style_prompt,trigger_word,flux_lora,negative_prompt,default_size}
  const [styleBusy, setStyleBusy] = useState(false)
  const [showAddScene, setShowAddScene] = useState(false)
  const [newScene, setNewScene] = useState({ title: '', narration: '', image_prompt: '', motion_prompt: '', subtitle: '', lipsync: false })
  const [addBusy, setAddBusy] = useState(false)
  // 小说→自动拆分镜
  const [showSB, setShowSB] = useState(false)
  const [novel, setNovel] = usePersistedState('sbNovel', '')
  const [sbN, setSbN] = usePersistedState('sbN', 8)
  const [sbReplace, setSbReplace] = useState(false)
  const [sbBusy, setSbBusy] = useState(false)
  // 一键 AI 分析填充（角色+风格+LoRA+分镜）
  const [afBusy, setAfBusy] = useState(false)
  const [afReplace, setAfReplace] = useState(false)
  // 角色/声音圣经
  const [showChars, setShowChars] = useState(false)
  const [charsBusy, setCharsBusy] = useState(false)
  // 面板分 Tab：script(剧本) / cast(角色&LoRA) / shots(分镜) / export(导出)
  const [tab, setTab] = usePersistedState('panelTab', 'shots')
  const [logs, setLogs] = useState([])             // GPU 实时日志行（尾部 N 条）
  const [showLogs, setShowLogs] = useState(true)
  const logEndRef = useRef(null)
  const cancelled = useRef(false)
  const batchJob = useRef(null)                    // 当前批量任务 job_id（供停止）
  const sceneJob = useRef({})                      // {sceneId: job_id}（供单镜停止）
  const startAt = useRef({})                       // {key: 起始时间戳}，用于"已运行 Xs"
  const [, setTick] = useState(0)                  // 每秒触发重渲染，刷新计时

  // 有任务在跑时每秒走表，让"出片中"显示已运行时长（证明在干活、没冻住）
  useEffect(() => {
    if (!busy && Object.keys(sceneBusy).length === 0) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [busy, sceneBusy])
  const fmtElapsed = (key) => {
    const t0 = startAt.current[key]
    if (!t0) return ''
    const s = Math.floor((Date.now() - t0) / 1000)
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}分${s % 60}秒`
  }
  // 新日志到达时自动滚到底
  useEffect(() => {
    if (showLogs) logEndRef.current?.scrollIntoView({ block: 'nearest' })
  }, [logs, showLogs])

  // 出视频预估时长（秒）= 帧数 ÷ 帧率 × 接续段数。
  // 帧数/帧率优先用「更多参数」覆盖值；没设就回退到所选模型 schema 的默认值
  // ——这样默认（不开高级参数）也能显示预估，否则 vidParams 为空时永远算不出（功能等于消失）。
  // 字段名：ComfyUI=frames+fps；Wan2.2=frame_num（无 fps→按 16fps，A14B 原生帧率）；LTX=num_frames+fps。
  const estSec = (() => {
    const flds = (models.find(m => m.name === model) || models[0])?.fields || []
    const def = (k) => flds.find(f => f.key === k)?.default
    const frames = Number(
      vidParams.frame_num ?? vidParams.frames ?? vidParams.num_frames ??
      def('frame_num') ?? def('frames') ?? def('num_frames'))
    const fps = Number(vidParams.fps ?? def('fps')) || 16
    if (!frames || !fps) return null
    return (frames / fps) * Math.max(1, segments)
  })()
  const genPayload = (sceneId) => {
    const [iw, ih] = (imgSize || '0x0').split('x').map(Number)
    return { scene_id: sceneId, workspace, session_id: sessionId, n: imgN,
      width: iw || 0, height: ih || 0, image_model: imgModel,
      img_steps: Number(imgAdv.steps) || 0,
      img_guidance: imgAdv.guidance !== '' ? Number(imgAdv.guidance) : -1,
      img_seed: imgAdv.seed !== '' ? Number(imgAdv.seed) : -1, img_offload: imgAdv.offload || '' }
  }
  const renderPayload = (sceneId) => {
    const segs = sceneSegments[sceneId] ?? segments   // 单镜段数优先，没设则用全局默认
    // 多段时带上每段独立运镜提示词（AI 生成/手改）；单段不带（用分镜自身的 motion_prompt）
    const mp = segs > 1 ? (sceneSegPrompts[sceneId] || []).slice(0, segs) : []
    const ls = sceneLipsync[sceneId] ?? !!(proj?.scenes?.find(x => x.scene_id === sceneId)?.lipsync)
    return { scene_id: sceneId, workspace, session_id: sessionId,
      model, segments: segs, size: vidSize, video_params: vidParams, motion_prompts: mp, lipsync: ls }
  }

  // 让 AI 据画面 + 一句中文意图，把动作拆成 N 段递进运镜提示词
  const genSegPrompts = async (sceneId) => {
    const segs = sceneSegments[sceneId] ?? segments
    setSegGenBusy(p => ({ ...p, [sceneId]: true }))
    try {
      const { prompts } = await suggestSegmentPrompts(sceneId, segs, sceneIntent[sceneId] || '', workspace)
      setSceneSegPrompts(p => ({ ...p, [sceneId]: prompts }))
    } catch (e) {
      setProgress('生成分段提示词失败：' + String(e.message || e))
    } finally {
      setSegGenBusy(p => { const n = { ...p }; delete n[sceneId]; return n })
    }
  }
  const editSegPrompt = (sceneId, i, val) => {
    setSceneSegPrompts(p => {
      const arr = [...(p[sceneId] || [])]
      while (arr.length <= i) arr.push('')
      arr[i] = val
      return { ...p, [sceneId]: arr }
    })
  }

  // 「再续一段」：取现有成片末帧续生成、拼到末尾（同 vidParams 以便无缝拼接）。段数不写死。
  const appendPayload = (sceneId) => ({
    scene_id: sceneId, workspace, session_id: sessionId, model,
    motion_prompt: appendPrompt[sceneId] || '',
    count: Math.max(1, Number(appendCount[sceneId]) || 1),
    size: vidSize, video_params: vidParams,
  })
  const runScene = async (kind, sceneId) => {
    if (busy || sceneBusy[sceneId]) return
    startAt.current[sceneId] = Date.now()
    setLogs([]); setShowLogs(true)
    setSceneBusy(p => ({ ...p, [sceneId]: kind }))
    try {
      const submit = kind === 'generate' ? sceneGenerate : kind === 'append' ? sceneAppend : sceneRender
      const payload = kind === 'generate' ? genPayload(sceneId)
        : kind === 'append' ? appendPayload(sceneId) : renderPayload(sceneId)
      const jobId = await submit(payload)
      sceneJob.current[sceneId] = jobId
      await consume(jobId)
    } catch { /* ignore */ }
    finally { delete sceneJob.current[sceneId]; setSceneBusy(p => { const n = { ...p }; delete n[sceneId]; return n }) }
  }

  // ✨ AI 推荐续段运镜提示词：据现有成片末帧（配了视觉模型则真看图），一键填好可改。防抽卡。
  const suggestAppendPrompt = async (sceneId) => {
    if (appendSugBusy[sceneId]) return
    setAppendSugBusy(p => ({ ...p, [sceneId]: true }))
    try {
      const lang = appendLang[sceneId] || 'zh'
      const { prompt, saw_frame } = await suggestContinuation(sceneId, lang, workspace)
      setAppendPrompt(p => ({ ...p, [sceneId]: prompt }))
      setProgress(saw_frame ? 'AI 已据尾帧画面推荐运镜（可改）'
        : 'AI 已据上下文推荐运镜（未配视觉模型，没真看图；可改）')
    } catch (e) {
      setProgress('推荐失败：' + String(e.message || e))
    } finally {
      setAppendSugBusy(p => { const n = { ...p }; delete n[sceneId]; return n })
    }
  }

  // 对口型开关：本地立即生效 + 持久化到分镜（survives 刷新）
  const toggleLipsync = async (sceneId, val) => {
    setSceneLipsync(p => ({ ...p, [sceneId]: val }))
    try { await updateScenePrompts(sceneId, { lipsync: val }, workspace) } catch { /* 本地态仍生效 */ }
  }

  const stopScene = async (sceneId) => {
    const jid = sceneJob.current[sceneId]
    if (jid) { try { await cancelJob(jid) } catch { /* ignore */ } }
  }

  // 按所选模型 schema 整理专业参数（排除主行已有的 size）
  const curFields = (models.find(m => m.name === model)?.fields || []).filter(f => f.key !== 'size')
  const prevModel = useRef(null)
  useEffect(() => {
    if (!curFields.length) return
    const switched = prevModel.current !== null && prevModel.current !== model
    setVidParams(prev => {
      const out = {}
      for (const f of curFields) {
        // 真切模型 → 用新模型默认值；初次/同模型 → 保留本地持久化的值（没有才用默认）→ 修复"刷新后参数被重置"
        out[f.key] = (!switched && prev && prev[f.key] !== undefined) ? prev[f.key] : f.default
      }
      return out
    })
    prevModel.current = model
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, models.length])

  const load = async () => {
    try { setProj(await getProject(pid, workspace)); setErr('') }
    catch (e) { setErr(String(e.message || e)) }
  }
  // 剧集级风格：读/存
  const loadStyle = async () => {
    try { const r = await projectStyle(pid, {}, workspace); setStyle(r.style || {}) } catch { /* 忽略 */ }
  }
  const saveStyle = async () => {
    setStyleBusy(true)
    try { const r = await projectStyle(pid, style || {}, workspace); setStyle(r.style); setProgress('本集风格已保存（下次出图自动套用）') }
    catch (e) { setProgress('保存风格失败：' + String(e.message || e)) }
    finally { setStyleBusy(false) }
  }
  // 小说 → 自动拆分镜（导演式，一次拆 N 镜入库）
  const doStoryboard = async () => {
    if (!novel.trim()) { setProgress('先粘一段小说/剧情文本'); return }
    setSbBusy(true); setProgress('AI 导演拆分镜中…（读全文，约 10-30 秒）')
    try {
      const r = await autoStoryboard(pid, novel, Number(sbN) || 8, sbReplace, workspace)
      setProgress(`已拆出 ${r.count} 个分镜${sbReplace ? '（已替换原有）' : '（接在末尾）'}，可逐镜出图了`)
      setShowSB(false); await load()
    } catch (e) { setProgress('拆分镜失败：' + String(e.message || e)) }
    finally { setSbBusy(false) }
  }
  // 一键 AI 分析：抽角色(+空 LoRA) → 风格 → 分镜，全套入库
  const doAutoFill = async () => {
    if (!novel.trim()) { setProgress('先粘一段小说/剧情文本'); return }
    const hasContent = (proj?.characters?.length || 0) > 0 || (proj?.scenes?.length || 0) > 0 || !!(proj?.style?.style_prompt)
    if (afReplace && hasContent) {
      if (!await dialog.confirm('将替换现有 角色 / 风格 / 分镜，继续？', {
        message: '已有内容会被本次分析结果覆盖（LoRA 任务保留，不会误删你传的参考图）。', danger: true, confirmText: '替换',
      })) return
    }
    setAfBusy(true); setProgress('AI 分析小说中…（抽角色 → 风格 → 分镜，约 20-60 秒）')
    try {
      const r = await autoFill(pid, novel, Number(sbN) || 8, afReplace, workspace)
      setProgress(`已自动填充：${r.characters} 角色 · ${r.lora_created} 个新 LoRA · 风格已生成 · ${r.scenes_count} 分镜`)
      await load(); await loadStyle()   // loadStyle：把 AI 生成的风格刷进「本集风格」编辑器(否则显示滞后)
    } catch (e) { setProgress('一键分析失败：' + String(e.message || e)) }
    finally { setAfBusy(false) }
  }
  // 角色/声音圣经
  const charOp = async (action, fields = {}) => {
    setCharsBusy(true)
    try { await charactersApi(pid, action, fields, workspace); await load() }
    catch (e) { setProgress('角色操作失败：' + String(e.message || e)) }
    finally { setCharsBusy(false) }
  }
  // 人物 LoRA 训练（界面框架）
  const [loraBusy, setLoraBusy] = useState(false)
  const newLora = async () => {
    setLoraBusy(true)
    try { await loraCreate(pid, '新角色LoRA', '', null, workspace); await load() }
    catch (e) { setProgress('新建 LoRA 失败：' + String(e.message || e)) }
    finally { setLoraBusy(false) }
  }
  const loraOp = async (action, tid, extra = {}) => {
    setLoraBusy(true)
    try { const r = await loraAction(pid, action, tid, workspace, extra); await load()
      const t = (r.trainings || []).find(x => x.id === tid)
      if (action === 'train' && t && t.message) setProgress(t.message)
    } catch (e) { setProgress('LoRA 操作失败：' + String(e.message || e)) }
    finally { setLoraBusy(false) }
  }
  const loraUpload = async (tid, files) => {
    setLoraBusy(true)
    try { for (const f of files) await loraUploadImage(tid, f, workspace); await load() }
    catch (e) { setProgress('传图失败：' + String(e.message || e)) }
    finally { setLoraBusy(false) }
  }
  // 免上传自训：每张卡的模式/张数本地态 + 上传参考脸 + 造图(+造完即训)
  const [loraBoot, setLoraBoot] = useState({})   // {tid:{mode,count}}
  const bootOf = (tid) => loraBoot[tid] || { mode: 'text', count: 16 }
  const setBootOf = (tid, patch) => setLoraBoot(b => ({ ...b, [tid]: { ...bootOf(tid), ...patch } }))
  const loraUploadRefFile = async (tid, file) => {
    if (!file) return
    setLoraBusy(true)
    try { await loraUploadRef(tid, file, workspace); await load(); setProgress('参考脸已上传，可点「造图+开训」') }
    catch (e) { setProgress('传参考脸失败：' + String(e.message || e)) }
    finally { setLoraBusy(false) }
  }
  const loraBootstrap = async (tid) => {
    const { mode, count } = bootOf(tid)
    setLoraBusy(true)
    try {
      const r = await loraAction(pid, 'bootstrap', tid, workspace, { mode, count: Number(count) || 0, auto_train: true })
      await load()
      const t = (r.trainings || []).find(x => x.id === tid)
      setProgress(t?.message || '自动造训练集已启动…造完会自动开训，进度看这张卡的状态。')
    } catch (e) { setProgress('自动造训练集失败：' + String(e.message || e)) }
    finally { setLoraBusy(false) }
  }

  // 自助新增 / 删除分镜（不绕 agent）
  const addScene = async () => {
    if (!newScene.image_prompt && !newScene.title) { setProgress('至少填个标题或出图提示词'); return }
    setAddBusy(true)
    try {
      await sceneAdd(pid, newScene, workspace)
      setNewScene({ title: '', narration: '', image_prompt: '', motion_prompt: '', subtitle: '', lipsync: false })
      setShowAddScene(false); await load()
    } catch (e) { setProgress('新增分镜失败：' + String(e.message || e)) }
    finally { setAddBusy(false) }
  }
  const removeScene = async (sceneId) => {
    if (!await dialog.confirm('删除这个分镜？', { message: '含它的候选图，不可恢复。', danger: true, confirmText: '删除' })) return
    try { await sceneDelete(sceneId, workspace); await load() }
    catch (e) { setProgress('删除分镜失败：' + String(e.message || e)) }
  }
  const styleField = (label, key, ph = '') => (
    <div style={{ marginBottom: 6 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      <input value={(style && style[key]) || ''} placeholder={ph}
        onChange={e => setStyle(s => ({ ...(s || {}), [key]: e.target.value }))}
        style={{ ...inputStyle, width: '100%', height: 30, boxSizing: 'border-box' }} />
    </div>
  )
  const addField = (label, key) => (
    <div style={{ marginBottom: 6 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      <input value={newScene[key] || ''} onChange={e => setNewScene(s => ({ ...s, [key]: e.target.value }))}
        style={{ ...inputStyle, width: '100%', height: 30, boxSizing: 'border-box' }} />
    </div>
  )
  const subBox = { background: '#161616', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: '16px 18px', marginBottom: 12 }
  useEffect(() => { cancelled.current = false; load(); return () => { cancelled.current = true } }, [pid])  // eslint-disable-line
  useEffect(() => { if (tab === 'script' && !style) loadStyle() }, [tab])  // eslint-disable-line 进剧本 tab 时加载本集风格
  useEffect(() => {
    getVideoProviders().then(d => {
      setModels(d.providers || [])
      if (!model && d.default) setModel(d.default)
    }).catch(() => {})
    getImageProviders().then(d => {
      setImgModels(d.providers || [])
      if (!imgModel && d.default) setImgModel(d.default)
    }).catch(() => {})
  }, [])  // eslint-disable-line

  // 统一消费任务事件流（首发与刷新重连共用）
  const consume = async (jobId) => {
    for await (const ev of streamJobEvents(jobId)) {
      if (cancelled.current) break
      if (ev.type === 'log') setLogs(prev => [...prev, ev.line].slice(-300))
      else if (ev.type === 'batch_progress') setProgress(ev.label || '处理中…')
      else if (ev.type === 'scene_ready' || ev.type === 'image' || ev.type === 'video') load()
      else if (ev.type === 'tool_result' && ev.content) { setProgress(ev.content); setLogs(prev => [...prev, '» ' + ev.content].slice(-300)) }
      else if (ev.type === 'error') { setProgress(ev.content || '已停止'); setLogs(prev => [...prev, '✗ ' + (ev.content || '已停止')].slice(-300)) }
    }
    await load()
  }

  // 刷新后重连：把本项目在跑/排队的任务接回面板（恢复进度 + 停止按钮）
  useEffect(() => {
    let alive = true
    listActiveJobs(pid).then(d => {
      if (!alive) return
      for (const j of (d.jobs || [])) {
        if (j.kind === 'batch_generate' || j.kind === 'batch_finish') {
          if (busy || batchJob.current) continue
          batchJob.current = j.job_id
          startAt.current.batch = Date.now()   // 重连无法知真实起点，以重连时刻起算
          setBusy(j.kind === 'batch_generate' ? 'generate' : 'finish')
          setProgress('重新连接到进行中的任务…')
          consume(j.job_id).finally(() => { batchJob.current = null; setBusy('') })
        } else if (j.scene_id) {
          if (sceneJob.current[j.scene_id]) continue
          sceneJob.current[j.scene_id] = j.job_id
          startAt.current[j.scene_id] = Date.now()
          setSceneBusy(p => ({ ...p, [j.scene_id]: j.kind === 'generate' ? 'generate' : 'render' }))
          consume(j.job_id).finally(() => {
            delete sceneJob.current[j.scene_id]
            setSceneBusy(p => { const n = { ...p }; delete n[j.scene_id]; return n })
          })
        }
      }
    }).catch(() => {})
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])

  const runJob = async (kind) => {
    if (busy) return
    startAt.current.batch = Date.now()
    setLogs([]); setShowLogs(true)
    setBusy(kind); setProgress('提交任务…')
    try {
      const submit = kind === 'generate' ? batchGenerate : batchFinish
      const [iw, ih] = (imgSize || '0x0').split('x').map(Number)
      const jobId = await submit({
        project_id: pid, workspace, session_id: sessionId,
        model: kind === 'finish' ? model : '',
        segments: kind === 'finish' ? segments : 1,
        size: kind === 'finish' ? vidSize : '',
        video_params: kind === 'finish' ? vidParams : {},
        n: kind === 'generate' ? imgN : 0,
        width: kind === 'generate' ? (iw || 0) : 0,
        height: kind === 'generate' ? (ih || 0) : 0,
        // 出图专业档：留空=用默认
        img_steps: kind === 'generate' ? (Number(imgAdv.steps) || 0) : 0,
        img_guidance: kind === 'generate' && imgAdv.guidance !== '' ? Number(imgAdv.guidance) : -1,
        img_seed: kind === 'generate' && imgAdv.seed !== '' ? Number(imgAdv.seed) : -1,
        img_offload: kind === 'generate' ? (imgAdv.offload || '') : '',
      })
      batchJob.current = jobId
      await consume(jobId)
    } catch (e) {
      setProgress('任务失败：' + String(e.message || e))
    } finally {
      batchJob.current = null
      setBusy('')
    }
  }

  const stopBatch = async () => {
    setProgress('正在停止…（已下发的当前分镜会跑完，后续分镜不再下发）')
    if (batchJob.current) { try { await cancelJob(batchJob.current) } catch { /* ignore */ } }
  }

  const select = async (sceneId, assetId) => {
    try {
      await pipelineSelect(sceneId, assetId, workspace)
      load()
    } catch (e) { /* ignore */ }
  }

  const delCandidate = async (assetId) => {
    if (!await dialog.confirm('删除这张候选图？', { danger: true, confirmText: '删除' })) return
    try { await deleteCandidate(assetId, workspace); load() } catch { /* ignore */ }
  }
  const delSceneVideo = async (sceneId) => {
    if (!await dialog.confirm('删除这个分镜的成片？', { message: '删除后可重新出片（图还在）。', danger: true, confirmText: '删除' })) return
    try { await deleteSceneVideo(sceneId, workspace); load() }
    catch (e) { dialog.alert('删除成片失败：' + (e.message || e)) }   // 别再静默吞错
  }
  const undoAppend = async (sceneId) => {
    setSceneBusy(b => ({ ...b, [sceneId]: 'undo' }))
    try {
      const r = await sceneUndoAppend(sceneId, workspace)
      if (r && r.ok === false && r.message) dialog.alert(r.message)   // 没得回退/文件被占用 → 提示
      load()
    } catch (e) { dialog.alert('撤销失败：' + (e.message || e)) }
    finally { setSceneBusy(b => { const n = { ...b }; delete n[sceneId]; return n }) }
  }
  const delEpisode = async () => {
    if (!await dialog.confirm('删除整集成片？', { message: '各分镜不受影响，可重新合成。', danger: true, confirmText: '删除' })) return
    try { await deleteEpisode(pid, workspace); load() } catch { /* ignore */ }
  }

  const c = proj?.counts || { total: 0, with_candidates: 0, selected: 0, done: 0 }
  const allSelected = c.total > 0 && c.selected === c.total
  const someSelected = c.selected > 0

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 16, marginBottom: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.87)' }}>
          {proj?.title || pid}
        </div>
        <div style={{ display: 'flex', gap: 14, fontSize: 12, color: 'rgba(255,255,255,0.52)' }}>
          <span>总数 <b style={{ color: 'rgba(255,255,255,0.87)', fontWeight: 600 }}>{c.total}</b></span>
          <span>已出图 <b style={{ color: '#eab308', fontWeight: 600 }}>{c.with_candidates}</b></span>
          <span>已选 <b style={{ color: '#c084fc', fontWeight: 600 }}>{c.selected}</b></span>
          <span>已出片 <b style={{ color: '#34d399', fontWeight: 600 }}>{c.done}</b></span>
        </div>
        <button onClick={load} title="刷新" style={{ ...miniBtn, marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}><Icon.Refresh size={13} /></button>
      </div>

      {/* Tab 栏：剧本 / 角色&LoRA / 分镜 / 导出 */}
      <div style={{ display: 'flex', gap: 26, marginBottom: 18, borderBottom: '1px solid rgba(255,255,255,0.07)', flexWrap: 'wrap' }}>
        {[['script', '剧本', Icon.Script], ['cast', '角色 & LoRA', Icon.Users], ['shots', '分镜制作', Icon.Layers], ['export', '导出', Icon.Download]].map(([k, label, Ico]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            display: 'inline-flex', alignItems: 'center', gap: 7,
            background: 'none', border: 'none', borderBottom: tab === k ? '2px solid #6366f1' : '2px solid transparent',
            color: tab === k ? 'rgba(255,255,255,0.87)' : 'rgba(255,255,255,0.52)', cursor: 'pointer',
            padding: '0 0 11px', fontSize: 13, fontWeight: tab === k ? 650 : 500, marginBottom: -1,
            transition: 'color .14s',
          }}><Ico size={15} style={{ opacity: tab === k ? 1 : 0.7 }} />{label}</button>
        ))}
      </div>

      {tab === 'script' && (
        <div style={subBox}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8 }}>
            粘一段小说/剧情，AI 当导演自动拆成整套分镜（标题/出图词/运镜/旁白台词/对口型），自动套本集风格 + 角色外貌。
          </div>
          <textarea value={novel} onChange={e => setNovel(e.target.value)} rows={5}
            placeholder="把这一集的小说/剧情粘进来…" style={{ ...inputStyle, width: '100%', resize: 'vertical', minHeight: 90 }} />
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', margin: '8px 0' }}>
            <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>拆成
              <input type="number" min={1} max={40} value={sbN} onChange={e => setSbN(e.target.value)}
                style={{ ...inputStyle, width: 56, height: 28, margin: '0 4px' }} />镜</label>
            <label style={{ fontSize: 12, display: 'inline-flex', gap: 4, alignItems: 'center' }}>
              <input type="checkbox" checked={sbReplace} onChange={e => setSbReplace(e.target.checked)} />替换现有分镜
            </label>
          </div>
          {/* 主推：一键 AI 分析，把角色/风格/LoRA/分镜 全套填好 */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
            <button onClick={doAutoFill} disabled={afBusy || sbBusy}
              style={{ height: 36, padding: '0 16px', borderRadius: 8, border: 'none',
                       background: (afBusy || sbBusy) ? 'rgba(255,255,255,0.06)' : (afBusy ? '#5254cc' : '#6366f1'),
                       color: (afBusy || sbBusy) ? 'var(--text-muted)' : '#fff', fontSize: 13, fontWeight: 600,
                       cursor: (afBusy || sbBusy) ? 'default' : 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {afBusy ? 'AI 分析中…' : '🪄 一键 AI 分析填充'}
            </button>
            <label style={{ fontSize: 12, display: 'inline-flex', gap: 4, alignItems: 'center', color: 'var(--text-muted)' }}>
              <input type="checkbox" checked={afReplace} onChange={e => setAfReplace(e.target.checked)} />替换现有
            </label>
            <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>角色 + 风格 + LoRA + 分镜，全自动</span>
          </div>
          {/* 次要：角色/风格已设好、只想补分镜 */}
          <div style={{ fontSize: 10.5, color: 'var(--text-dim)', marginBottom: 6 }}>或只想补分镜（角色/风格已弄好时）：</div>
          <button onClick={doStoryboard} disabled={sbBusy || afBusy}
            style={{ ...miniBtn2, height: 30, padding: '0 12px' }}>
            {sbBusy ? 'AI 拆分镜中…' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon.Wand size={13} />只拆分镜</span>}
          </button>
        </div>
      )}

      {tab === 'cast' && (<>
        <div style={subBox}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8 }}>
            角色/声音圣经 —— 每个角色固定外貌+音色。拆分镜/出图自动用其外貌（跨镜同一个人），配音用其音色。
          </div>
          {(proj?.characters || []).map(c => (
            <div key={c.id} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 8, marginBottom: 6 }}>
              <input defaultValue={c.name} placeholder="角色名"
                onBlur={e => e.target.value !== c.name && charOp('update', { char_id: c.id, name: e.target.value })}
                style={{ ...inputStyle, height: 28, marginBottom: 4 }} />
              <textarea defaultValue={c.appearance} rows={2}
                placeholder="外貌（写明确年龄+发型+特征，如：45岁中年男，短寸花白发，左眉旧疤）"
                onBlur={e => e.target.value !== c.appearance && charOp('update', { char_id: c.id, appearance: e.target.value })}
                style={{ ...inputStyle, width: '100%', resize: 'vertical', marginBottom: 4 }} />
              <div style={{ display: 'flex', gap: 6 }}>
                <select defaultValue={c.voice || ''} onChange={e => charOp('update', { char_id: c.id, voice: e.target.value })}
                  style={{ ...inputStyle, height: 28, flex: 1 }}>
                  {VOICES.map(v => <option key={v.v} value={v.v}>{v.label}</option>)}
                </select>
                <button onClick={() => charOp('delete', { char_id: c.id })} disabled={charsBusy}
                  style={{ ...miniBtn2, color: '#fca5a5', borderColor: 'rgba(239,68,68,0.4)' }}>删除</button>
              </div>
            </div>
          ))}
          <button onClick={() => charOp('add', { name: '新角色', appearance: '', voice: '' })} disabled={charsBusy}
            style={{ ...panelBtn(charsBusy), display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon.Plus size={14} />添加角色</button>
        </div>

        <div style={subBox}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8 }}>
            人物 LoRA 训练 —— 训出专属 LoRA、出图锁定这张脸（最稳的人物一致）。可手动传 10-20 张，
            也可<b style={{ color: '#5fe8de' }}>免上传自训</b>：纯文字零图，或传 1 张脸用 PuLID 批量造同人图，造完自动开训。
          </div>
          {(proj?.lora_trainings || []).map(t => (
            <div key={t.id} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 8, marginBottom: 6 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
                <input defaultValue={t.name} placeholder="LoRA / 角色名称"
                  onBlur={e => { const v = e.target.value.trim(); if (v && v !== t.name) loraOp('update', t.id, { name: v }) }}
                  style={{ ...inputStyle, height: 26, flex: 1, fontWeight: 600 }} />
                <span style={{ fontSize: 10.5, color: 'var(--text-muted)', whiteSpace: 'nowrap', flexShrink: 0 }}>{t.image_count} 张图 · {t.status}</span>
                <button onClick={async () => { if (await dialog.confirm('删除这个 LoRA 训练？', { message: '参考图也会一并删除，不可恢复。', danger: true, confirmText: '删除' })) loraOp('delete', t.id) }} disabled={loraBusy}
                  style={{ ...miniBtn2, color: '#fca5a5', borderColor: 'rgba(239,68,68,0.4)', flexShrink: 0 }}>删除</button>
              </div>
              <input defaultValue={t.trigger_word || ''} placeholder="触发词 trigger_word（出图自动注入；没有可留空）"
                onBlur={e => { if (e.target.value !== (t.trigger_word || '')) loraOp('update', t.id, { trigger_word: e.target.value }) }}
                style={{ ...inputStyle, height: 26, width: '100%', boxSizing: 'border-box', marginBottom: 4 }} />
              {t.message && <div style={{ fontSize: 10.5, color: '#ffb454', marginBottom: 4 }}>{t.message}</div>}
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <label style={{ ...miniBtn2, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <Icon.Plus size={13} />传参考图
                  <input type="file" accept="image/*" multiple style={{ display: 'none' }}
                    onChange={e => { loraUpload(t.id, Array.from(e.target.files || [])); e.target.value = '' }} />
                </label>
                <button onClick={() => loraOp('train', t.id)} disabled={loraBusy} style={panelBtn(loraBusy)}>开始训练</button>
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 10.5, color: '#5fe8de', whiteSpace: 'nowrap' }}>免上传自训：</span>
                <select value={bootOf(t.id).mode} onChange={e => setBootOf(t.id, { mode: e.target.value })}
                  style={{ ...inputStyle, height: 26, width: 'auto' }}>
                  <option value="text">纯文字零图</option>
                  <option value="pulid">单张脸图(PuLID)</option>
                </select>
                {bootOf(t.id).mode === 'pulid' && (
                  <label style={{ ...miniBtn2, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <Icon.Plus size={12} />传参考脸
                    <input type="file" accept="image/*" style={{ display: 'none' }}
                      onChange={e => { loraUploadRefFile(t.id, (e.target.files || [])[0]); e.target.value = '' }} />
                  </label>
                )}
                <input type="number" min={5} value={bootOf(t.id).count}
                  onChange={e => setBootOf(t.id, { count: e.target.value })} title="自动生成张数(建议 12-20)"
                  style={{ ...inputStyle, height: 26, width: 56 }} />
                <button onClick={() => loraBootstrap(t.id)} disabled={loraBusy} style={panelBtn(loraBusy)}>造图+开训</button>
              </div>
            </div>
          ))}
          <button onClick={newLora} disabled={loraBusy} style={{ ...panelBtn(loraBusy), display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon.Plus size={14} />新建 LoRA 训练</button>
        </div>
      </>)}

      {tab === 'script' && (
        <div style={subBox}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8 }}>
            本集统一风格 —— 出图自动套用到每个分镜，全集一个调性（这就是「一集一种风格」）。
          </div>
          {styleField('通用风格词', 'style_prompt', '如：写实，电影感，冷蓝调，浅景深（自动拼到每镜出图词后）')}
          {styleField('角色触发词', 'trigger_word', '人物 LoRA 触发词；没有就留空')}
          {styleField('FLUX LoRA 路径', 'flux_lora', 'GPU 上 LoRA 路径；none=不加载任何 LoRA')}
          {styleField('负向词', 'negative_prompt', '不想要的元素（ComfyUI 出图用）')}
          {styleField('默认出图尺寸', 'default_size', '如 768x1024（留空用面板尺寸）')}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button onClick={saveStyle} disabled={styleBusy} style={panelBtn(styleBusy)}>
              {styleBusy ? '保存中…' : '保存本集风格'}
            </button>
            <TemplateBar kind="style" label="风格" workspace={workspace}
              getContent={() => JSON.stringify(style || {})}
              onApply={c => { try { setStyle({ ...(style || {}), ...JSON.parse(c) }) } catch { /* ignore */ } }} />
          </div>
        </div>
      )}

      {tab === 'shots' && (<>
      <div style={{ marginBottom: 8 }}>
        <button onClick={() => setShowAddScene(v => !v)} style={{ ...miniBtn2, display: 'inline-flex', alignItems: 'center', gap: 5 }}><Icon.Plus size={13} />新增分镜</button>
      </div>
      {showAddScene && (
        <div style={subBox}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8 }}>新增一个分镜（接在本集末尾，之后可出图/出片）。</div>
          {addField('标题', 'title')}
          {addField('出图提示词（写中文就行）', 'image_prompt')}
          {addField('运镜提示词', 'motion_prompt')}
          {addField('旁白 / 台词', 'narration')}
          {addField('字幕（可空，留空=用旁白）', 'subtitle')}
          <label style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center', margin: '4px 0 8px' }}>
            <input type="checkbox" checked={newScene.lipsync}
              onChange={e => setNewScene(s => ({ ...s, lipsync: e.target.checked }))} />
            <Icon.Mic size={13} style={{ opacity: 0.75 }} />对口型镜头（人物开口说话，走 S2V）
          </label>
          <button onClick={addScene} disabled={addBusy} style={panelBtn(addBusy)}>
            {addBusy ? '添加中…' : '添加到本集'}
          </button>
        </div>
      )}

      {/* 第①步：出图（张数/尺寸可选）*/}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <button onClick={() => runJob('generate')} disabled={!!busy}
          style={panelBtn(busy === 'generate')}>
          {busy === 'generate' ? '出图中…' : '① 一键全部出图'}
        </button>
        <select value={imgN} disabled={!!busy} onChange={e => setImgN(Number(e.target.value))}
          title="每个分镜出几张候选" style={{ ...inputStyle, width: 'auto', height: 32 }}>
          <option value={2}>每镜2张</option>
          <option value={4}>每镜4张</option>
          <option value={6}>每镜6张</option>
        </select>
        <select value={imgSize} disabled={!!busy} onChange={e => setImgSize(e.target.value)}
          title="出图尺寸" style={{ ...inputStyle, width: 'auto', height: 32 }}>
          <option value="768x1024">768×1024 竖屏</option>
          <option value="1024x768">1024×768 横屏</option>
          <option value="1024x1024">1024×1024 方形</option>
        </select>
        <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>已有图的分镜可在下方直接「上传图片」跳过生图</span>
      </div>

      {/* 第③步：出片并合成（模型/段数/分辨率可选）*/}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <button onClick={() => runJob('finish')} disabled={!!busy || !someSelected}
          style={!someSelected ? panelBtn(false, true) : {
            height: 32, padding: '0 14px', borderRadius: 8, border: 'none',
            background: busy === 'finish' ? 'rgba(0,189,176,0.7)' : '#00bdb0',
            color: '#04201e', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
          }}>
          {busy === 'finish' ? '出片合成中…' : (allSelected ? '③ 一键出片并合成' : `③ 出片并合成（已选${c.selected}/${c.total}）`)}
        </button>
        {models.length > 0 && (
          <select value={model} disabled={!!busy} onChange={e => setModel(e.target.value)}
            title="视频模型：LTX 快适合预演，Wan 慢画质高" style={{ ...inputStyle, width: 'auto', height: 32 }}>
            {models.map(m => <option key={m.name} value={m.name}>{m.display_name}</option>)}
          </select>
        )}
        <select value={segments} disabled={!!busy} onChange={e => setSegments(Number(e.target.value))}
          title="接续段数的全局默认（批量出片用；每个分镜也可在自己那行单独设）" style={{ ...inputStyle, width: 'auto', height: 32 }}>
          <option value={1}>单段</option>
          <option value={2}>接续×2</option>
          <option value={3}>接续×3</option>
        </select>
        <select value={vidSize} disabled={!!busy} onChange={e => setVidSize(e.target.value)}
          title="出片分辨率 —— 480p 快(草稿/走量)，720p 精修(成片)。一键切，不用改 .env。" style={{ ...inputStyle, width: 'auto', height: 32 }}>
          <option value="">默认(跟随 .env)</option>
          <option value="480*832">480×832 竖屏·快(草稿)</option>
          <option value="720*1280">720×1280 竖屏·精修</option>
          <option value="704*1280">704×1280 竖屏</option>
          <option value="832*480">832×480 横屏·快</option>
          <option value="1280*704">1280×704 横屏</option>
        </select>
        {estSec != null && (
          <span style={{ fontSize: 11, color: 'rgba(94,234,212,0.95)', alignSelf: 'center',
                         padding: '0 8px', borderRadius: 6, background: 'rgba(0,189,176,0.1)',
                         border: '1px solid rgba(0,189,176,0.2)', height: 32, display: 'inline-flex',
                         alignItems: 'center', gap: 4 }}>
            预估 ≈ {estSec.toFixed(1)}s/镜
          </span>
        )}
        {busy && (
          <button onClick={stopBatch} title="停止：当前分镜跑完即止，后续分镜不再下发，省 GPU"
            style={{ height: 32, padding: '0 14px', borderRadius: 8, alignSelf: 'center',
                     border: '1px solid rgba(239,68,68,0.4)', background: 'rgba(239,68,68,0.16)',
                     color: 'rgba(252,165,165,1)', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                     display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: 'currentColor' }} />停止 {fmtElapsed('batch')}
          </button>
        )}
        {busy && <span style={{ fontSize: 11, color: 'var(--text-muted)', alignSelf: 'center' }}>{progress}</span>}
      </div>

      {/* 更多参数：专业档（默认收起，小白无感；进阶用户全量可调）*/}
      <div style={{ marginBottom: 12 }}>
        <button onClick={() => setShowAdv(v => !v)} style={{
          background: 'none', border: 'none', cursor: 'pointer', padding: 0,
          color: 'var(--text-muted)', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4,
        }}>
          <span style={{ display: 'inline-block', transform: showAdv ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>▸</span>
          更多参数（专业）
        </button>
        {showAdv && (
          <div style={{ marginTop: 8, padding: '10px 12px', borderRadius: 8,
                        border: '1px solid var(--border)', background: 'rgba(255,255,255,0.02)' }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: 'rgba(165,168,255,0.8)', marginBottom: 6 }}>
              出图（{imgModels.find(m => m.name === imgModel)?.display_name || imgModel || 'FLUX'}）· 留空=默认
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
              {imgModels.length > 1 && (
                <label style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 180 }}>
                  <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>出图模型</span>
                  <select value={imgModel} disabled={!!busy}
                    onChange={e => setImgModel(e.target.value)}
                    style={{ ...inputStyle, height: 28 }}>
                    {imgModels.map(m => (<option key={m.name} value={m.name}>{m.display_name}</option>))}
                  </select>
                </label>
              )}
              {[['steps', '采样步数(默认28)'], ['guidance', 'guidance(默认3.5)'], ['seed', 'seed(-1随机)']].map(([k, label]) => (
                <label key={k} style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 130 }}>
                  <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{label}</span>
                  <input type="number" value={imgAdv[k]} disabled={!!busy} placeholder="默认"
                    onChange={e => setImgAdv(p => ({ ...p, [k]: e.target.value }))}
                    style={{ ...inputStyle, height: 28 }} />
                </label>
              ))}
              <label style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 150 }}>
                <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>显存策略</span>
                <select value={imgAdv.offload} disabled={!!busy}
                  onChange={e => setImgAdv(p => ({ ...p, offload: e.target.value }))}
                  style={{ ...inputStyle, height: 28 }}>
                  <option value="">默认</option>
                  <option value="model">model（快）</option>
                  <option value="sequential">sequential（省显存）</option>
                </select>
              </label>
            </div>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: 'rgba(94,234,212,0.8)', marginBottom: 6 }}>
              出片（{models.find(m => m.name === model)?.display_name || model}）· 按模型动态
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {curFields.map(f => (
                <label key={f.key} style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 150 }}>
                  <span style={{ fontSize: 10.5, color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center' }}>
                    {f.label}<HelpTip text={f.help} />
                  </span>
                  {f.type === 'select' ? (
                    <select value={vidParams[f.key] ?? f.default} disabled={!!busy}
                      onChange={e => {
                        const opt = f.options?.find(o => String(o.value) === e.target.value)
                        setVidParams(p => ({ ...p, [f.key]: opt ? opt.value : e.target.value }))
                      }} style={{ ...inputStyle, height: 28 }}>
                      {(f.options || []).map(o => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}
                    </select>
                  ) : (
                    <input type={f.type === 'number' ? 'number' : 'text'}
                      value={vidParams[f.key] ?? f.default ?? ''} disabled={!!busy}
                      onChange={e => setVidParams(p => ({ ...p, [f.key]: f.type === 'number' ? Number(e.target.value) : e.target.value }))}
                      style={{ ...inputStyle, height: 28 }} />
                  )}
                </label>
              ))}
            </div>
          </div>
        )}
      </div>
      {!busy && progress && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>{progress}</div>
      )}
      {err && <div style={{ fontSize: 11, color: 'rgba(239,68,68,0.9)', marginBottom: 10 }}>读取失败：{err}（确认工作目录正确）</div>}

      {/* GPU 实时日志：把"黑盒出片"变成可见的进度（FLUX/Wan/LTX 的加载与采样步数都会滚出来）*/}
      {logs.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <button onClick={() => setShowLogs(v => !v)} style={{
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
              color: 'var(--text-muted)', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4,
            }}>
              <span style={{ display: 'inline-block', transform: showLogs ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>▸</span>
              实时日志（{logs.length}）
            </button>
            <button onClick={() => setLogs([])} title="清空日志" style={{
              background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', fontSize: 11,
            }}>清空</button>
          </div>
          {showLogs && (
            <div style={{
              maxHeight: 200, overflowY: 'auto', borderRadius: 8, padding: '8px 10px',
              background: '#0a0a0a', border: '1px solid var(--border)',
              fontFamily: '"SF Mono","Fira Code",ui-monospace,monospace', fontSize: 11, lineHeight: 1.7,
              color: '#34d399', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            }}>
              {logs.map((l, i) => (
                <div key={i} style={{ color: l.startsWith('✗') ? '#f87171'
                  : l.startsWith('»') ? '#6cb6ff'
                  : /warn/i.test(l) ? '#eab308' : 'inherit' }}>{l}</div>
              ))}
              <div ref={logEndRef} />
            </div>
          )}
        </div>
      )}

      {/* 成片 */}
      {proj?.episode && (
        <div style={{ marginBottom: 12, padding: 10, borderRadius: 10,
                      background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.25)' }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: 'rgba(134,239,172,1)' }}>整集成片</span>
            <button onClick={delEpisode} title="删除整集成片（可重新合成）" style={{
              marginLeft: 'auto', height: 22, padding: '0 10px', borderRadius: 6,
              border: '1px solid rgba(239,68,68,0.35)', background: 'rgba(239,68,68,0.12)',
              color: 'rgba(252,165,165,1)', fontSize: 11, cursor: 'pointer',
            }}>删除</button>
          </div>
          <video src={fileUrl(proj.episode.url)} controls
                 style={{ width: '100%', maxHeight: 420, borderRadius: 8, display: 'block' }} />
        </div>
      )}

      {/* 分镜列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {(proj?.scenes || []).map(s => {
          const sl = STATE_LABEL[s.state] || { t: s.state, c: 'var(--text-muted)' }
          return (
            <div key={s.scene_id} style={{
              border: `1px solid ${s.state === 'PENDING_FLUX_GEN' ? 'rgba(234,179,8,0.25)' : 'rgba(255,255,255,0.07)'}`,
              borderRadius: 12, padding: '15px 18px', background: '#161616',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'rgba(255,255,255,0.8)' }}>
                  #{s.scene_number}
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-sec)', flex: 1, overflow: 'hidden',
                               textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.title || '(无题)'}</span>
                <button onClick={() => removeScene(s.scene_id)} disabled={!!busy} title="删除这个分镜（含候选图）"
                  style={{ ...miniBtn, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: 'rgba(252,165,165,0.9)', borderColor: 'rgba(239,68,68,0.3)' }}><Icon.Trash size={13} /></button>

                {/* 单镜独立操作：出图（随时可重出）/ 出视频（已选图后）*/}
                {(() => {
                  const sb = sceneBusy[s.scene_id]
                  if (sb) {   // 该镜正在跑 → 显示可点的「停止」
                    return (
                      <button onClick={() => stopScene(s.scene_id)} title="点击停止这个分镜的任务"
                        style={{ ...miniAct(false), border: '1px solid rgba(239,68,68,0.4)',
                                 background: 'rgba(239,68,68,0.16)', color: 'rgba(252,165,165,1)' }}>
                        {sb === 'generate' ? '出图中' : '出片中'} {fmtElapsed(s.scene_id)} · 停止
                      </button>
                    )
                  }
                  const disabled = !!busy
                  return (<>
                    <button onClick={() => runScene('generate', s.scene_id)} disabled={disabled}
                      title="只对这个分镜出图" style={miniAct(false)}>
                      {s.candidates.length ? '重出图' : '出图'}
                    </button>
                    {s.selected && !s.video && (() => {
                      const segs = sceneSegments[s.scene_id] ?? segments
                      const sec = estSec != null ? estSec / Math.max(1, segments) * segs : null
                      const ls = sceneLipsync[s.scene_id] ?? !!s.lipsync
                      return (<>
                        <label title="勾上=人物开口说话、嘴型跟「旁白(=台词)」同步(Wan2.2-S2V 语音驱动)；不勾=普通运镜出片。"
                          style={{ fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 3,
                                   cursor: disabled ? 'default' : 'pointer',
                                   color: ls ? 'rgba(94,234,212,1)' : 'var(--text-muted)' }}>
                          <input type="checkbox" checked={ls} disabled={disabled}
                            onChange={e => toggleLipsync(s.scene_id, e.target.checked)} />
                          <Icon.Mic size={12} />对口型
                        </label>
                        {!ls && (
                          <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'inline-flex',
                                          alignItems: 'center', gap: 3 }}
                            title="这个分镜的接续段数（1=单段；越多越长越连贯，想多长填多少、没有上限）。也可先出 1 段、看效果后用「再续一段」逐段加长。">
                            接续
                            <input type="number" min={1} value={segs} disabled={disabled}
                              onChange={e => setSceneSegments(p => ({ ...p, [s.scene_id]: Math.max(1, Number(e.target.value) || 1) }))}
                              style={{ ...inputStyle, width: 48, height: 22, fontSize: 11 }} />
                            段
                          </label>
                        )}
                        <button onClick={() => runScene('render', s.scene_id)} disabled={disabled}
                          title={ls ? '人物开口说话、对口型出片(Wan2.2-S2V)' : '只对这个分镜出视频'}
                          style={miniAct(false, true)}>
                          {ls ? '对口型出片' : `出视频${sec != null ? ` ≈${sec.toFixed(0)}s` : ''}`}
                        </button>
                      </>)
                    })()}
                  </>)
                })()}

                {!s.video && (
                  <label title="已有这镜的图？直接上传当候选，跳过生图"
                    style={{ fontSize: 11, color: 'rgba(165,168,255,0.9)', cursor: 'pointer',
                             border: '1px solid rgba(99,102,241,0.35)', borderRadius: 6, padding: '2px 8px' }}>
                    上传图片
                    <input type="file" accept=".png,.jpg,.jpeg,.webp" style={{ display: 'none' }}
                      onChange={async e => {
                        const f = e.target.files?.[0]
                        e.target.value = ''
                        if (!f) return
                        setProgress(`上传 #${s.scene_number} 的图片…`)
                        try { await uploadCandidate(s.scene_id, f, workspace); setProgress(''); load() }
                        catch (err) { setProgress('上传失败：' + String(err.message || err)) }
                      }} />
                  </label>
                )}
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 22, padding: '0 9px',
                               borderRadius: 6, fontSize: 11, color: sl.c,
                               background: sl.bg || 'rgba(255,255,255,0.06)',
                               border: `1px solid ${sl.bd || 'rgba(255,255,255,0.13)'}` }}>
                  {sl.spin
                    ? <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ animation: 'al-spin 1s linear infinite' }}><path d="M21 12a9 9 0 1 1-6.2-8.5"/></svg>
                    : <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor' }} />}
                  {sl.t}
                </span>
              </div>

              {s.video ? (
                <div>
                  {/* key 绑 url（含 &v=mtime）：追加后文件变了，强制 <video> 重建、不吃旧缓存 */}
                  <video key={s.video.url} src={fileUrl(s.video.url)} controls
                         style={{ width: '100%', maxHeight: 300, borderRadius: 8, display: 'block' }} />
                  {/* 看效果再加长：取现有成片末帧续生成、拼到末尾，可反复点。段数不写死。 */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, alignItems: 'center' }}>
                    <input value={appendPrompt[s.scene_id] || ''} disabled={busy || !!sceneBusy[s.scene_id]}
                      onChange={e => setAppendPrompt(p => ({ ...p, [s.scene_id]: e.target.value }))}
                      placeholder="续段运镜提示词（可空；点「AI 推荐」据尾帧给一句，可改）"
                      style={{ ...inputStyle, flex: '1 1 160px', height: 26, fontSize: 11.5 }} />
                    <select value={appendLang[s.scene_id] || 'zh'} disabled={busy || !!sceneBusy[s.scene_id]}
                      onChange={e => setAppendLang(p => ({ ...p, [s.scene_id]: e.target.value }))}
                      title="推荐提示词的语言（Wan2.2 原生支持中文；纯英文模型选 EN）"
                      style={{ ...inputStyle, width: 'auto', height: 26, fontSize: 11 }}>
                      <option value="zh">中</option>
                      <option value="en">EN</option>
                    </select>
                    <button onClick={() => suggestAppendPrompt(s.scene_id)}
                      disabled={busy || !!sceneBusy[s.scene_id] || !!appendSugBusy[s.scene_id]}
                      title="据现有视频的最后一帧，AI 推荐一句续段运镜提示词（配了视觉模型则真看画面）。不用自己憋提示词、少抽卡。"
                      style={{ ...miniAct(false), display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      {appendSugBusy[s.scene_id] ? '推荐中…' : <><Icon.Wand size={12} />AI 推荐</>}
                    </button>
                    <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'inline-flex',
                                    alignItems: 'center', gap: 3 }}
                      title="本次追加几段（想加多长加多长，没有上限）">
                      续
                      <input type="number" min={1} value={appendCount[s.scene_id] ?? 1}
                        disabled={busy || !!sceneBusy[s.scene_id]}
                        onChange={e => setAppendCount(p => ({ ...p, [s.scene_id]: Math.max(1, Number(e.target.value) || 1) }))}
                        style={{ ...inputStyle, width: 44, height: 26 }} />
                      段
                    </label>
                    <button onClick={() => runScene('append', s.scene_id)} disabled={busy || !!sceneBusy[s.scene_id]}
                      title="取现有视频最后一帧继续生成、拼到末尾，让这镜变长（可反复点，看效果再决定加多少）"
                      style={{ ...miniAct(false, true), display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      <Icon.Plus size={12} />再续一段{sceneBusy[s.scene_id] === 'append' ? `…${fmtElapsed(s.scene_id)}` : ''}
                    </button>
                    <button onClick={() => undoAppend(s.scene_id)} disabled={busy || !!sceneBusy[s.scene_id]}
                      title="撤销最近一次「再续一段」，成片回退到续接之前（可多次回退），然后可重新续"
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        height: 26, padding: '0 12px', borderRadius: 6,
                        border: '1px solid rgba(124,108,255,0.4)', background: 'rgba(124,108,255,0.12)',
                        color: 'rgba(203,166,255,1)', fontSize: 11.5, cursor: 'pointer',
                      }}><Icon.Undo size={12} />撤销上一段{sceneBusy[s.scene_id] === 'undo' ? '…' : ''}</button>
                    <button onClick={() => delSceneVideo(s.scene_id)} disabled={busy || !!sceneBusy[s.scene_id]}
                      title="删除这个分镜的成片（图还在，可重新出片）" style={{
                        height: 26, padding: '0 12px', borderRadius: 6,
                        border: '1px solid rgba(239,68,68,0.35)', background: 'rgba(239,68,68,0.12)',
                        color: 'rgba(252,165,165,1)', fontSize: 11.5, cursor: 'pointer',
                      }}>删除成片 · 重出</button>
                  </div>
                </div>
              ) : s.candidates.length > 0 ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(96px,1fr))', gap: 8 }}>
                  {s.candidates.map(img => (
                    <div key={img.assetId} style={{
                      position: 'relative', borderRadius: 9, overflow: 'hidden', cursor: 'pointer',
                      border: img.selected ? '2px solid #34d399' : '1px solid rgba(255,255,255,0.1)',
                    }}>
                      <img src={fileUrl(img.url)} alt={img.name} onClick={() => setZoom(img)}
                           style={{ width: '100%', aspectRatio: '3/4', objectFit: 'cover', display: 'block' }} />
                      <button onClick={() => select(s.scene_id, img.assetId)}
                        title={img.selected ? '已选' : '选这张'}
                        style={{
                          position: 'absolute', top: 4, right: 4, width: 22, height: 22, borderRadius: 6,
                          border: 'none', cursor: 'pointer', fontSize: 12,
                          color: img.selected ? '#04201a' : '#fff',
                          background: img.selected ? '#34d399' : 'rgba(0,0,0,0.55)',
                        }}>{img.selected ? '✓' : '○'}</button>
                      <button onClick={() => delCandidate(img.assetId)} title="删除这张候选图"
                        style={{
                          position: 'absolute', top: 4, left: 4, width: 22, height: 22, borderRadius: 6,
                          border: 'none', cursor: 'pointer', fontSize: 13, lineHeight: 1, color: '#fff',
                          background: 'rgba(239,68,68,0.7)',
                        }}>×</button>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>尚未出图</div>
              )}

              {/* 多段接续：AI 把动作拆成每段独立运镜提示词（你想不出提示词时用），可改可不改 */}
              {s.selected && !s.video && (sceneSegments[s.scene_id] ?? segments) > 1 && (
                <SegmentPromptsEditor
                  segs={sceneSegments[s.scene_id] ?? segments}
                  prompts={sceneSegPrompts[s.scene_id] || []}
                  intent={sceneIntent[s.scene_id] || ''}
                  busy={!!segGenBusy[s.scene_id]}
                  onIntent={v => setSceneIntent(p => ({ ...p, [s.scene_id]: v }))}
                  onGenerate={() => genSegPrompts(s.scene_id)}
                  onEdit={(i, v) => editSegPrompt(s.scene_id, i, v)}
                />
              )}

              {/* 提示词全透明：AI 写的也给用户看，且可改（改完再出图/出片更省 GPU） */}
              <ScenePrompts scene={s} workspace={workspace} onSaved={load} />
            </div>
          )
        })}
      </div>
      </>)}

      {tab === 'export' && (
        <div style={subBox}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8 }}>
            导出 —— 全部分镜出完片后，「③ 一键出片并合成」在「分镜制作」里点；成片在这里下载。
          </div>
          {proj?.episode ? (
            <div>
              <video src={fileUrl(proj.episode.url)} controls style={{ width: '100%', borderRadius: 8, marginBottom: 8 }} />
              <a href={fileUrl(proj.episode.url)} download style={{ ...panelBtn(false), textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon.Download size={14} />下载整集 mp4</a>
            </div>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>还没有整集成片。去「分镜制作」点「③ 一键出片并合成」。</div>
          )}
          <div style={{ fontSize: 10.5, color: '#ffb454', marginTop: 8 }}>平台导出预设（抖音 1080×1920 等）待补。</div>
        </div>
      )}

      {zoom && (
        <div onClick={() => setZoom(null)} style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)', zIndex: 2000,
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
        }}>
          <img src={fileUrl(zoom.url)} alt={zoom.name}
               style={{ maxWidth: '90vw', maxHeight: '85vh', objectFit: 'contain', borderRadius: 8 }} />
        </div>
      )}
    </div>
  )
}

/* 分镜提示词（出图/运镜/旁白）：AI 生成的也全部可见，且可改完保存再出图/出片 */
function ScenePrompts({ scene, workspace, onSaved }) {
  const [open, setOpen] = useState(false)
  const [tit, setTit] = useState(scene.title || '')
  const [num, setNum] = useState(String(scene.scene_number ?? ''))
  const [img, setImg] = useState(scene.image_prompt || '')
  const [mot, setMot] = useState(scene.motion_prompt || '')
  const [nar, setNar] = useState(scene.narration || '')
  const [sub, setSub] = useState(scene.subtitle || '')
  const [saving, setSaving] = useState(false)
  const numChanged = num !== '' && Number(num) !== scene.scene_number
  const dirty = img !== (scene.image_prompt || '') || mot !== (scene.motion_prompt || '')
    || nar !== (scene.narration || '') || sub !== (scene.subtitle || '')
    || tit !== (scene.title || '') || numChanged

  const save = async () => {
    setSaving(true)
    try {
      const fields = { image_prompt: img, motion_prompt: mot, narration: nar, subtitle: sub, title: tit }
      if (numChanged) fields.scene_number = Number(num)
      await updateScenePrompts(scene.scene_id, fields, workspace)
      onSaved?.()
    } catch { /* 保持编辑态，用户可重试 */ }
    setSaving(false)
  }

  const ta = (label, val, set, rows = 2) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{label}</span>
      <textarea value={val} rows={rows} onChange={e => set(e.target.value)}
        style={{ ...inputStyle, height: 'auto', padding: '5px 8px', resize: 'vertical',
                 fontFamily: 'inherit', fontSize: 11.5, lineHeight: 1.5 }} />
    </label>
  )

  return (
    <div style={{ marginTop: 8 }}>
      <button onClick={() => setOpen(o => !o)} style={{
        background: 'none', border: 'none', cursor: 'pointer', padding: 0,
        color: 'var(--text-muted)', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4,
      }}>
        <span style={{ display: 'inline-block', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>▸</span>
        提示词{!open && (scene.image_prompt
          ? <span style={{ color: 'var(--text-dim)', maxWidth: 360, overflow: 'hidden',
                           textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              ：{scene.image_prompt}</span>
          : <span style={{ color: 'var(--text-dim)' }}>（空）</span>)}
      </button>
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 6 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 70 }}>
              <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>镜号</span>
              <input type="number" value={num} onChange={e => setNum(e.target.value)}
                style={{ ...inputStyle, height: 28, fontSize: 11.5 }} />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
              <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>标题</span>
              <input value={tit} onChange={e => setTit(e.target.value)}
                style={{ ...inputStyle, height: 28, fontSize: 11.5 }} />
            </label>
          </div>
          {ta('出图提示词（image_prompt，角色触发词自动注入）', img, setImg, 3)}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '0 0 6px' }}>
            <TemplateBar kind="prompt" label="提示词" workspace={workspace} getContent={() => img} onApply={c => setImg(c)} />
          </div>
          {ta('运镜/动态提示词（motion_prompt，出视频用）', mot, setMot)}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '0 0 6px' }}>
            <TemplateBar kind="motion" label="运镜" workspace={workspace} getContent={() => mot} onApply={c => setMot(c)} />
          </div>
          {ta('旁白（narration，转 TTS 配音）', nar, setNar)}
          {ta('字幕（subtitle，屏幕文字；留空=同旁白）', sub, setSub)}
          <div>
            <button onClick={save} disabled={!dirty || saving} style={{
              height: 26, padding: '0 14px', borderRadius: 6,
              border: '1px solid rgba(99,102,241,0.4)',
              background: dirty ? 'rgba(99,102,241,0.22)' : 'rgba(255,255,255,0.05)',
              color: dirty ? 'rgba(190,192,255,1)' : 'var(--text-muted)',
              fontSize: 11.5, fontWeight: 600, cursor: dirty ? 'pointer' : 'default',
            }}>{saving ? '保存中…' : dirty ? '保存修改' : '未修改'}</button>
          </div>
        </div>
      )}
    </div>
  )
}

/* 分段运镜提示词编辑器：多段接续时，AI 据画面+中文意图把动作拆成每段独立提示词，可改可不改。
   提示词存在 ProductionPanel 的 sceneSegPrompts 里（出片时随 renderPayload 下发），此组件只做展示/编辑。 */
function SegmentPromptsEditor({ segs, prompts, intent, busy, onIntent, onGenerate, onEdit }) {
  const has = prompts.some(p => (p || '').trim())
  return (
    <div style={{ marginTop: 8, padding: '8px 10px', borderRadius: 8,
      border: '1px dashed rgba(99,102,241,0.4)', background: 'rgba(99,102,241,0.05)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: 'rgba(190,192,255,1)' }}>
          分段运镜 · 接续×{segs}
        </span>
        <input value={intent} disabled={busy} onChange={e => onIntent(e.target.value)}
          placeholder="想要的动作/运镜（中文，可留空让 AI 看画面自拟）"
          style={{ ...inputStyle, flex: 1, minWidth: 180, height: 26, fontSize: 11.5 }} />
        <button onClick={onGenerate} disabled={busy} title="让 AI 把动作拆成每段递进的运镜提示词"
          style={{ height: 26, padding: '0 12px', borderRadius: 6, whiteSpace: 'nowrap',
            border: '1px solid rgba(99,102,241,0.45)', cursor: busy ? 'default' : 'pointer',
            background: busy ? 'rgba(255,255,255,0.05)' : 'rgba(99,102,241,0.22)',
            color: busy ? 'var(--text-muted)' : 'rgba(190,192,255,1)', fontSize: 11.5, fontWeight: 600 }}>
          {busy ? '生成中…' : has ? '重新生成' : 'AI 生成分段运镜'}
        </button>
      </div>
      {has && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
          {Array.from({ length: segs }).map((_, i) => (
            <label key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>段 #{i + 1}</span>
              <textarea value={prompts[i] || ''} rows={2} onChange={e => onEdit(i, e.target.value)}
                style={{ ...inputStyle, height: 'auto', padding: '5px 8px', resize: 'vertical',
                  fontFamily: 'inherit', fontSize: 11.5, lineHeight: 1.5 }} />
            </label>
          ))}
          <span style={{ fontSize: 10.5, color: 'var(--text-dim)' }}>
            出视频时按每段提示词逐段生成、尾帧接续拼接成连贯长镜头。
          </span>
        </div>
      )}
    </div>
  )
}

const panelBtn = (active, disabled) => ({
  height: 32, padding: '0 14px', borderRadius: 8, border: 'none',
  background: disabled ? 'rgba(255,255,255,0.06)' : active ? '#5254cc' : '#6366f1',
  color: disabled ? 'var(--text-muted)' : '#fff',
  fontSize: 12.5, fontWeight: 600, cursor: disabled ? 'default' : 'pointer',
})
// 单镜操作小按钮（出图=紫、出视频=青）
const miniAct = (active, teal) => ({
  height: 22, padding: '0 9px', borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: 'pointer',
  border: `1px solid ${teal ? 'rgba(0,189,176,0.4)' : 'rgba(99,102,241,0.4)'}`,
  background: active ? (teal ? 'rgba(0,189,176,0.3)' : 'rgba(99,102,241,0.3)')
    : (teal ? 'rgba(0,189,176,0.14)' : 'rgba(99,102,241,0.14)'),
  color: teal ? 'rgba(94,234,212,1)' : 'rgba(190,192,255,1)',
})
const miniBtn = {
  width: 24, height: 24, borderRadius: 6, border: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.05)', color: 'var(--text-sec)', cursor: 'pointer', fontSize: 13,
}
// edge-tts 常用中文音色（角色声音圣经用）
const VOICES = [
  { v: '', label: '默认音色' },
  { v: 'zh-CN-YunxiNeural', label: '云希·男·活泼' },
  { v: 'zh-CN-YunyangNeural', label: '云扬·男·沉稳' },
  { v: 'zh-CN-YunjianNeural', label: '云健·男·浑厚' },
  { v: 'zh-CN-XiaoxiaoNeural', label: '晓晓·女·温柔' },
  { v: 'zh-CN-XiaoyiNeural', label: '晓伊·女·少女' },
  { v: 'zh-CN-XiaohanNeural', label: '晓涵·女·成熟' },
  { v: 'zh-CN-XiaomoNeural', label: '晓墨·男·清朗' },
  // 英文音色（欧美短剧台词用英文，必须配英文嗓；edge-tts 后端可直接用这些 id）
  { v: 'en-US-GuyNeural', label: 'EN · Guy · 男 · 年轻沉稳' },
  { v: 'en-US-ChristopherNeural', label: 'EN · Christopher · 男 · 低沉旁白' },
  { v: 'en-US-EricNeural', label: 'EN · Eric · 男 · 冷峻' },
  { v: 'en-GB-RyanNeural', label: 'EN-GB · Ryan · 男 · 英式贵族' },
  { v: 'en-US-JennyNeural', label: 'EN · Jenny · 女 · 自然' },
  { v: 'en-US-AriaNeural', label: 'EN · Aria · 女 · 成熟' },
  { v: 'en-GB-SoniaNeural', label: 'EN-GB · Sonia · 女 · 英式高傲' },
]
// 多字小按钮（本集风格 / 新增分镜等）：自动宽度 + 不换行，避免文字竖排
const miniBtn2 = {
  height: 24, padding: '0 9px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.05)', color: 'var(--text-sec)', cursor: 'pointer',
  fontSize: 12, whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', gap: 4,
}

const inputStyle = {
  height: 30, padding: '0 8px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.85)', fontSize: 12,
  width: '100%', colorScheme: 'dark',
}

/* ── 可复用模板库小条：存当前值为模板 + 套用/删除已存模板（风格/运镜/提示词复用）── */
function TemplateBar({ kind, label, getContent, onApply, workspace }) {
  const dialog = useDialog()
  const [list, setList] = useState([])
  const [open, setOpen] = useState(false)
  const load = async () => {
    try { const r = await templatesApi('list', { kind }, workspace); setList(r.templates || []) }
    catch { /* ignore */ }
  }
  useEffect(() => { load() }, [])  // eslint-disable-line react-hooks/exhaustive-deps
  const save = async () => {
    const content = getContent()
    const empty = !content || (typeof content === 'string' && !content.trim())
    if (empty) { return }
    const name = await dialog.prompt(`存为${label}模板`, '', { title: `${label}模板命名`, placeholder: '给这个模板起个名' })
    if (name == null) return
    try {
      await templatesApi('add', { kind, name: name || label, content: typeof content === 'string' ? content : JSON.stringify(content) }, workspace)
      load()
    } catch { /* ignore */ }
  }
  const del = async (id) => { try { await templatesApi('delete', { kind, template_id: id }, workspace); load() } catch { /* ignore */ } }
  return (
    <div style={{ display: 'inline-flex', gap: 6, alignItems: 'center', position: 'relative' }}>
      <button onClick={save} style={miniBtn2} title={`把当前${label}存成可复用模板`}>存{label}模板</button>
      <button onClick={() => { if (!open) load(); setOpen(v => !v) }} style={miniBtn2} title="套用已存模板">套用 ({list.length})</button>
      {open && (
        <div style={{ position: 'absolute', top: 30, left: 0, zIndex: 20, width: 240, maxHeight: 220, overflowY: 'auto',
                      background: '#0d0d0d', border: '1px solid var(--border-strong)', borderRadius: 8, padding: 6,
                      boxShadow: '0 12px 30px rgba(0,0,0,0.5)' }}>
          {list.length === 0 && <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 6 }}>还没有{label}模板</div>}
          {list.map(t => (
            <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 6px', borderRadius: 6 }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <span onClick={() => { onApply(t.content); setOpen(false) }} title="点击套用"
                style={{ flex: 1, fontSize: 12, cursor: 'pointer', overflow: 'hidden', textOverflow: 'ellipsis',
                         whiteSpace: 'nowrap', color: 'rgba(255,255,255,0.85)' }}>{t.name}</span>
              <button onClick={() => del(t.id)} title="删除模板"
                style={{ ...miniBtn, width: 20, height: 20, color: '#fca5a5', borderColor: 'rgba(239,68,68,0.4)' }}>×</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
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
    <div style={{
      border: '1px solid rgba(99,102,241,0.2)',
      background: 'rgba(99,102,241,0.06)',
      borderRadius: 10,
      padding: '12px 14px',
      marginBottom: 14,
      display: 'flex', flexDirection: 'column', gap: 7,
    }}>
      {steps.map((s, i) => (
        <div key={i} style={{ fontSize: 12, fontFamily: "'SF Mono', ui-monospace, monospace" }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: s.done ? '#34d399' : 'rgba(234,179,8,0.9)' }}>
              {s.done ? '✓' : '·'}
            </span>
            <span style={{ fontWeight: 600, color: 'rgba(255,255,255,0.52)' }}>{s.name}</span>
            {s.args && Object.keys(s.args).length > 0 && (
              <span style={{ color: 'rgba(255,255,255,0.4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {summarizeArgs(s.args)}
              </span>
            )}
          </div>
          {s.result && (
            <div style={{
              marginTop: 6,
              paddingTop: 6,
              borderTop: '1px solid rgba(99,102,241,0.15)',
              color: 'rgba(255,255,255,0.4)',
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
  if (isQuickReply) {
    // 快捷回复区按钮：中性灰（对齐 mockup）
    bgColor   = 'rgba(255,255,255,0.04)'
    borderColor = 'rgba(255,255,255,0.13)'
    textColor = 'rgba(255,255,255,0.87)'
    hoverBg   = 'rgba(255,255,255,0.08)'
  } else if (hasUserInput) {
    // 内联快捷动作：紫色调
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
        height: isQuickReply ? 28 : 30,
        padding: isQuickReply ? '0 12px' : '0 14px',
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
      {!isQuickReply && <span style={{ fontSize: 13, lineHeight: 1 }}>{icon}</span>}
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
      border: '1px solid rgba(255,255,255,0.13)',
      borderRadius: 12,
      padding: '15px 17px',
      background: '#161616',
      transition: 'all 0.2s',
    }}>
      <p style={{
        fontSize: 12.5, lineHeight: 1.6,
        color: 'rgba(255,255,255,0.87)',
        marginBottom: resolved === undefined ? 13 : 0,
      }}>
        {message.content}
      </p>

      {resolved === undefined ? (
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={() => onResume?.(true)}
            style={{
              height: 32, padding: '0 16px', borderRadius: 8, border: 'none',
              background: '#34d399', color: '#04201a',
              fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6, transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.opacity = '0.88'}
            onMouseLeave={e => e.currentTarget.style.opacity = '1'}
          >
            <CheckIcon /> 确认执行
          </button>
          <button
            onClick={() => onResume?.(false)}
            style={{
              height: 32, padding: '0 16px', borderRadius: 8,
              background: 'rgba(239,68,68,0.1)', color: '#f87171',
              fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6,
              border: '1px solid rgba(239,68,68,0.4)', transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.2)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(239,68,68,0.1)'}
          >
            <XIcon /> 取消
          </button>
        </div>
      ) : (
        <span style={{
          fontSize: 12, fontWeight: 500,
          color: resolved ? '#34d399' : '#f87171',
          display: 'flex', alignItems: 'center', gap: 5,
        }}>
          {resolved ? <CheckIcon /> : <XIcon />}
          {resolved ? '已确认执行' : '已取消'}
        </span>
      )}
    </div>
  )
}
