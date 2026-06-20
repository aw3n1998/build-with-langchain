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
import { fileUrl, getVideoProviders, getImageProviders, getProject, batchGenerate, batchFinish, continuation, continuationOne, assembleEpisode,
         pipelineSelect, streamJobEvents, pipelineUpscale, pipelineFaceswap, uploadCandidate, uploadContinueVideo, updateScenePrompts,
         deleteCandidate, deleteSceneVideo, sceneUndoAppend, deleteEpisode, suggestSegmentPrompts,
         autoStoryboard, autoFill, characters as charactersApi, templatesApi,
         loraCreate, loraAction, loraUploadImage, loraUploadRef, loraPreview,
         suggestContinuation, sceneGenerate, sceneRender, sceneAppend,
         cancelJob, listActiveJobs,
         projectStyle, sceneAdd, sceneDelete, listLoras,
         oneClick, autoSelect, uploadCharacterFace, getLoadedLoras } from '../api'

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

/* ── 制作面板：纯 t2v 流程（拆分镜 → 逐镜文生视频 → 合成整集）──────── */
const STATE_LABEL = {
  DRAFT:                   { t: '待出片',     c: 'rgba(255,255,255,0.52)', bg: 'rgba(255,255,255,0.06)', bd: 'rgba(255,255,255,0.13)' },
  PENDING_FLUX_GEN:        { t: '出图中',     c: '#eab308', bg: 'rgba(234,179,8,0.12)',  bd: 'rgba(234,179,8,0.35)', spin: true },
  PENDING_HUMAN_SELECTION: { t: '待选图',     c: '#c084fc', bg: 'rgba(168,85,247,0.12)', bd: 'rgba(168,85,247,0.35)' },
  PENDING_VIDEO_GEN:       { t: '出片中',     c: '#5fe8de', bg: 'rgba(0,189,176,0.12)',  bd: 'rgba(0,189,176,0.35)', spin: true },
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
  const [lockFace, setLockFace] = usePersistedState('lockFace', false)   // 强锁脸(Stand-In):有参考脸的角色镜走「一张脸硬锁」通道(需先跑 Colab §Stand-In)
  const [loadedLoras, setLoadedLoras] = useState(null)   // lightx2v server 当前实际加载的 LoRA(查看用)
  const [loraStatusBusy, setLoraStatusBusy] = useState(false)
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
  const [loras, setLoras] = useState({ loras: [], model: {} })   // ComfyUI 可用 LoRA + 对话/全局出图配置
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
  // 一键全自动出片（纯 t2v：按目标秒数自算镜数 → 拆镜 → 逐镜文生视频 → 合成整集）
  const [ocSec, setOcSec] = usePersistedState('ocSec', 60)      // 目标成片时长(秒)
  const [ocCoh, setOcCoh] = usePersistedState('ocCoh', true)    // true=少而长连贯档；false=快切
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
      model, segments: segs, size: vidSize, video_params: { ...vidParams, ...(lockFace ? { lock_face: true } : {}) }, motion_prompts: mp, lipsync: ls,
      video_mode: 't2v' }   // 纯 t2v：单镜「出片」直接文生(跳过出图/选图)
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
    scene_id: sceneId, workspace, session_id: sessionId, model: 'lightx2v-i2v',   // ★追加段走 i2v：从这镜末帧续生成
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

  // 「续这镜」：只重出这一镜——用【上一镜】的尾帧当首帧走 i2v 续接，其它镜不动。快速试参/修单镜。
  const runContinueOne = async (sceneId) => {
    if (busy || sceneBusy[sceneId]) return
    startAt.current[sceneId] = Date.now()
    setLogs([]); setShowLogs(true)
    setSceneBusy(p => ({ ...p, [sceneId]: 'continue1' }))
    try {
      const jobId = await continuationOne({
        project_id: pid, scene_id: sceneId, workspace, session_id: sessionId,
        size: vidSize, video_params: { ...vidParams },
      })
      sceneJob.current[sceneId] = jobId
      await consume(jobId)
    } catch (e) { setProgress('单镜续接失败：' + String(e.message || e)) }
    finally { delete sceneJob.current[sceneId]; setSceneBusy(p => { const n = { ...p }; delete n[sceneId]; return n }) }
  }

  // 「上传视频续接」：把你的一段视频拼到该镜成片末尾，再从它的尾帧 AI 续写（复用续段的运镜词/段数）。
  const runUploadContinue = async (sceneId, file, opts = {}) => {
    if (busy || sceneBusy[sceneId]) return
    startAt.current[sceneId] = Date.now()
    setLogs([]); setShowLogs(true)
    setSceneBusy(p => ({ ...p, [sceneId]: 'append' }))
    try {
      // opts.count 显式给(如「没出片就上传」用 0=只当成片不强行续写)；否则用「续 N 段」框
      const jobId = await uploadContinueVideo(sceneId, file, {
        model, motionPrompt: appendPrompt[sceneId] || '', size: vidSize,
        count: opts.count != null ? Math.max(0, Number(opts.count) || 0) : Math.max(1, Number(appendCount[sceneId]) || 1),
      }, workspace)
      sceneJob.current[sceneId] = jobId
      await consume(jobId)
    } catch (err) { setProgress('上传续接失败：' + String(err.message || err)) }
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
  const loadLoras = async () => {
    try { const r = await listLoras(workspace); setLoras(r || { loras: [], model: {} }) } catch { /* 忽略 */ }
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
  // 一键全自动出片：按目标秒数自算镜数 → 拆镜/角色/风格 → 出图 → 自动/手动选图 → 出片 → 合成
  const doOneClick = async () => {
    if (busy) return
    if (!novel.trim()) { setProgress('先在上方粘一段小说/剧情文本'); return }
    const hasContent = (proj?.characters?.length || 0) > 0 || (proj?.scenes?.length || 0) > 0 || !!(proj?.style?.style_prompt)
    if (hasContent) {
      if (!await dialog.confirm('一键全自动会重拆分镜并覆盖现有 角色 / 风格 / 分镜，继续？', {
        message: '按目标时长自动拆镜 → 逐镜文生视频(t2v) → 合成整集（LoRA 任务保留）。',
        danger: true, confirmText: '开始',
      })) return
    }
    cancelled.current = false
    startAt.current.batch = Date.now()
    setLogs([]); setShowLogs(true); setBusy('oneclick'); setProgress('提交一键全自动任务…')
    try {
      const jobId = await oneClick({
        project_id: pid, workspace, session_id: sessionId,
        novel_text: novel, target_sec: Number(ocSec) || 60, coherence: ocCoh,
        replace: true, lightning: true, model, size: vidSize, video_mode: 't2v',
      })
      batchJob.current = jobId
      await consume(jobId)
    } catch (e) { setProgress('一键全自动失败：' + String(e.message || e)) }
    finally { batchJob.current = null; setBusy('') }
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
      if (action === 'train') setLoraLogOpen(p => ({ ...p, [tid]: true }))   // 开训即展开日志
    } catch (e) { setProgress('LoRA 操作失败：' + String(e.message || e)) }
    finally { setLoraBusy(false) }
  }
  // 训练实时日志 + 轮询进度（训练在后台线程跑，状态/日志要主动拉才更新，否则界面冻在 TRAINING）
  const [loraLog, setLoraLog] = useState({})         // {tid: 日志尾部}
  const [loraLogOpen, setLoraLogOpen] = useState({}) // {tid: 是否展开}
  const fetchLoraLog = async (tid) => {
    try { const r = await loraAction(pid, 'log', tid, workspace); setLoraLog(p => ({ ...p, [tid]: r.log || '(暂无日志——训练刚起/在造图;ai-toolkit 拉起底模约 1-2 分钟才出第一行)' })) }
    catch { /* ignore */ }
  }
  const toggleLoraLog = async (tid) => {
    const open = !loraLogOpen[tid]; setLoraLogOpen(p => ({ ...p, [tid]: open }))
    if (open) await fetchLoraLog(tid)
  }
  // 有任务非终态(TRAINING/QUEUED/造图中)就每 4s 轮询：刷新状态 + 已展开的日志
  useEffect(() => {
    if (tab !== 'cast') return
    const active = (proj?.lora_trainings || []).some(t => t.status && !['DONE', 'FAILED', 'DRAFT'].includes(t.status))
    if (!active) return
    const id = setInterval(() => {
      load(); Object.keys(loraLogOpen).forEach(tid => loraLogOpen[tid] && fetchLoraLog(tid))
    }, 4000)
    return () => clearInterval(id)
  }, [tab, proj?.lora_trainings, loraLogOpen])  // eslint-disable-line
  const loraUpload = async (tid, files, characterId = '') => {
    // 没选角色就上传 = 不会写触发词 caption → 训出绑不上人物的废 LoRA(出片像别人)。
    // 但「LoRA 记录自带触发词」是合法的不打标路径(后端 routes 仍会按记录触发词写) → 此时不拦。
    if (!characterId) {
      const rec = (proj?.lora_trainings || []).find(x => x.id === tid)
      const hasTrigger = !!(rec?.trigger_word || '').trim()
      if (!hasTrigger) {
        const ok = await dialog.confirm('没选角色，这批图不会打触发词标', {
          message: '不打标训出的 LoRA 绑不上人物，出片会像别人。建议先在上方下拉选好角色（自动按角色触发词打标），或给这个 LoRA 填个触发词。\n\n仍要直接上传吗？',
          confirmText: '仍然上传', danger: true,
        })
        if (!ok) return
      }
    }
    setLoraBusy(true)
    try { for (const f of files) await loraUploadImage(tid, f, workspace, characterId); await load() }
    catch (e) { setProgress('传图失败：' + String(e.message || e)) }
    finally { setLoraBusy(false) }
  }
  // 测试出片：用「当前 server 已挂载的 LoRA」出一条短测试片(480p/4步/33帧)，内嵌在该卡播放。验证 LoRA 学的人对不对。
  const [loraPrevBusy, setLoraPrevBusy] = useState({})   // {tid: 出片中}
  const [loraPrevUrl, setLoraPrevUrl] = useState({})     // {tid: 测试片 url}
  const loraDoPreview = async (tid) => {
    setLoraPrevBusy(p => ({ ...p, [tid]: true }))
    setProgress('测试出片中…（480p/4步/33帧，约 1 分钟；用当前 server 已挂载的 LoRA）')
    let gotVideo = false
    try {
      const jobId = await loraPreview(tid, workspace, sessionId)
      for await (const ev of streamJobEvents(jobId)) {
        if (ev.type === 'video' && ev.url) { setLoraPrevUrl(p => ({ ...p, [tid]: fileUrl(ev.url) + '&v=' + Date.now() })); gotVideo = true }
        // ★出片报错走 tool_result 事件（不是 error）——之前没接、被静默吞掉，导致"点了没反应"。这里一并显示。
        else if ((ev.type === 'error' || ev.type === 'tool_result') && ev.content) setProgress('测试出片：' + ev.content)
        else if (ev.type === 'log' && ev.line) setProgress('测试出片中…' + String(ev.line).slice(-90))
      }
      if (!gotVideo) setProgress('测试出片结束但没拿到视频——多半出片那步报错了。看 Colab 的 lightx2v 日志（§日志速查 或 tail /content/lightx2v.log）定位。')
    } catch (e) { setProgress('测试出片失败：' + String(e.message || e)) }
    finally { setLoraPrevBusy(p => ({ ...p, [tid]: false })) }
  }
  // 每张 LoRA 卡选中的角色 id（选了 → 传图按该角色外貌自动打 caption；多角色就逐个选着传，全进这一个 LoRA）
  const [loraCharOf, setLoraCharOf] = useState({})   // {tid: char_id}
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
  // 强锁脸(Stand-In)参考脸：给某角色传 1 张正脸 → 写 characters.ref_image_path；出片勾「强锁脸」即用它跨镜锁脸。
  const charFaceUpload = async (charId, file) => {
    if (!file) return
    setProgress('上传参考脸中…')
    try { await uploadCharacterFace(charId, proj?.id || '', file, workspace); await load(); setProgress('参考脸已上传（出片勾「强锁脸(Stand-In)」即用它锁这张脸）') }
    catch (e) { setProgress('参考脸上传失败：' + String(e.message || e)) }
  }
  // 查 lightx2v server 当前【实际加载】的 LoRA(权威:读运行中 server 的 config)——核对角色/蒸馏挂没挂
  const checkLoadedLoras = async () => {
    setLoraStatusBusy(true)
    try { setLoadedLoras(await getLoadedLoras()) }
    catch (e) { setProgress('查询已挂 LoRA 失败：' + String(e.message || e)) }
    finally { setLoraStatusBusy(false) }
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
    if (!newScene.image_prompt && !newScene.title) { setProgress('至少填个标题或画面提示词'); return }
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
  const styleLoraField = () => {
    const hi = (style && style.wan_t2v_lora_high) || ''
    const lo = (style && style.wan_t2v_lora_low) || ''
    return (
      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>本集 Wan-T2V 角色 LoRA（在「角色 &amp; LoRA」里训出后自动挂这里；t2v 出片锁人物）</div>
        <div style={{ fontSize: 11.5, color: hi ? '#5fe8de' : 'var(--text-dim)' }}>
          {hi ? `已挂 high+low：${hi} / ${lo || '(缺 low)'}` : '未训练 —— t2v 没首帧，人物一致全靠这套 LoRA（去「角色 & LoRA」训）'}
        </div>
      </div>
    )
  }
  const addField = (label, key) => (
    <div style={{ marginBottom: 6 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      <input value={newScene[key] || ''} onChange={e => setNewScene(s => ({ ...s, [key]: e.target.value }))}
        style={{ ...inputStyle, width: '100%', height: 30, boxSizing: 'border-box' }} />
    </div>
  )
  const subBox = { background: '#161616', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: '16px 18px', marginBottom: 12 }
  useEffect(() => { cancelled.current = false; load(); loadLoras(); return () => { cancelled.current = true } }, [pid])  // eslint-disable-line loadLoras 全局拿 comfyui 标志,门控换脸/造图入口
  useEffect(() => {
    if (tab === 'script' && !style) loadStyle()
    if (tab === 'script' || tab === 'cast') loadLoras()   // cast tab 也要 loras.comfyui 决定「造图自训」入口显不显示
  }, [tab])  // eslint-disable-line
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
        if (j.kind === 'batch_generate' || j.kind === 'batch_finish' || j.kind === 'one_click') {
          if (busy || batchJob.current) continue
          batchJob.current = j.job_id
          startAt.current.batch = Date.now()   // 重连无法知真实起点，以重连时刻起算
          setBusy(j.kind === 'batch_generate' ? 'generate' : j.kind === 'one_click' ? 'oneclick' : 'finish')
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
      const submit = kind === 'generate' ? batchGenerate : kind === 'continuation' ? continuation : kind === 'assemble' ? assembleEpisode : batchFinish
      const [iw, ih] = (imgSize || '0x0').split('x').map(Number)
      const jobId = await submit({
        project_id: pid, workspace, session_id: sessionId,
        model: kind === 'finish' ? model : '',
        segments: kind === 'finish' ? segments : 1,
        size: (kind === 'finish' || kind === 'continuation') ? vidSize : '',
        video_params: kind === 'finish' ? { ...vidParams, ...(lockFace ? { lock_face: true } : {}) }
          : (kind === 'continuation' ? { ...vidParams } : {}),
        video_mode: 't2v',   // 纯 t2v：批量出片直接逐镜文生(跳过出图/选图)
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

  // ── 一键转规格（放大到 4K 等；输出独立文件、不覆盖原片；引擎 auto=AI超分/ffmpeg）──
  const UPSCALE_PRESETS = [
    ['4K竖屏', 2160, 3840], ['4K横屏', 3840, 2160], ['2K竖屏', 1440, 2560],
    ['1080P竖屏', 1080, 1920], ['1080P横屏', 1920, 1080], ['自定义', 0, 0],
  ]
  const [upSpec, setUpSpec] = useState({})   // tag -> 预设名
  const [upWH, setUpWH] = useState({})       // tag -> {w,h}（自定义）
  const [upBusy, setUpBusy] = useState({})   // tag -> 转换中
  const [upUrl, setUpUrl] = useState({})     // tag -> 高清版 url
  const doUpscale = async (tag, kind, sceneId, projectId) => {
    const spec = upSpec[tag] || '4K竖屏'
    let w, h
    if (spec === '自定义') { w = Number(upWH[tag]?.w) || 0; h = Number(upWH[tag]?.h) || 0 }
    else { const p = UPSCALE_PRESETS.find(x => x[0] === spec); w = p?.[1]; h = p?.[2] }
    if (!w || !h) { setProgress('请填有效的目标宽高'); return }
    setUpBusy(b => ({ ...b, [tag]: true })); setShowLogs(true)
    setProgress(`转规格 ${spec} ${w}×${h}…（AI 超分会慢些）`)
    try {
      const jobId = await pipelineUpscale({
        kind, scene_id: sceneId || '', project_id: projectId || '',
        width: w, height: h, workspace, session_id: sessionId,
      })
      for await (const ev of streamJobEvents(jobId)) {
        if (ev.type === 'log') setLogs(prev => [...prev, ev.line].slice(-300))
        else if (ev.type === 'video' && ev.url) setUpUrl(u => ({ ...u, [tag]: fileUrl(ev.url) + '&v=' + Date.now() }))
        else if (ev.type === 'tool_result' && ev.content) { setProgress(ev.content); setLogs(prev => [...prev, '» ' + ev.content].slice(-300)) }
        else if (ev.type === 'error') setProgress(ev.content || '转规格已停止')
      }
    } catch (e) { setProgress('转规格失败：' + String(e.message || e)) }
    finally { setUpBusy(b => { const n = { ...b }; delete n[tag]; return n }) }
  }
  const upscaleRow = (tag, kind, sceneId, projectId) => {
    const spec = upSpec[tag] || '4K竖屏'; const bz = !!upBusy[tag]
    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}
          title="把这个低清成片放大转成目标规格；输出独立新文件、不覆盖原片。引擎 auto：有 ComfyUI 走 AI 超分(RealESRGAN)、否则 ffmpeg 快缩。">转规格</span>
        <select value={spec} disabled={bz} onChange={e => setUpSpec(p => ({ ...p, [tag]: e.target.value }))}
          style={{ ...inputStyle, width: 'auto', height: 26, fontSize: 11.5 }}>
          {UPSCALE_PRESETS.map(p => <option key={p[0]} value={p[0]}>{p[0]}{p[1] ? ` ${p[1]}×${p[2]}` : ''}</option>)}
        </select>
        {spec === '自定义' && (<>
          <input type="number" placeholder="宽" value={upWH[tag]?.w || ''} disabled={bz}
            onChange={e => setUpWH(p => ({ ...p, [tag]: { ...(p[tag] || {}), w: e.target.value } }))}
            style={{ ...inputStyle, width: 58, height: 26, fontSize: 11 }} />
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>×</span>
          <input type="number" placeholder="高" value={upWH[tag]?.h || ''} disabled={bz}
            onChange={e => setUpWH(p => ({ ...p, [tag]: { ...(p[tag] || {}), h: e.target.value } }))}
            style={{ ...inputStyle, width: 58, height: 26, fontSize: 11 }} />
        </>)}
        <button onClick={() => doUpscale(tag, kind, sceneId, projectId)} disabled={bz} style={miniAct(false)}>
          {bz ? '转换中…' : '一键转'}
        </button>
        {upUrl[tag] && (<>
          <span style={{ fontSize: 11, color: 'rgba(134,239,172,1)', width: '100%' }}>✓ 高清版（原片保留，可对比）</span>
          <video key={upUrl[tag]} src={upUrl[tag]} controls
            style={{ width: '100%', maxHeight: 320, borderRadius: 8, display: 'block', border: '1px solid rgba(134,239,172,0.4)' }} />
        </>)}
      </div>
    )
  }


  // ── 一键换脸：上传一张源脸 → 换到这段成片里的人物上(产物独立新文件、原片保留)──
  // 合规红线：仅用于你有权使用的脸(原创/AI/本人授权);换可识别真人=deepfake,平台 ToS 与法律禁止。
  const [swBusy, setSwBusy] = useState({})   // tag -> 换脸中
  const [swUrl, setSwUrl] = useState({})     // tag -> 换脸版 url
  const [swFile, setSwFile] = useState({})   // tag -> 已选源脸 File（先选后确认，避免一选就跑、看不到确定键）
  const doFaceswap = async (tag, kind, sceneId, projectId, file) => {
    if (!file) return
    setSwBusy(b => ({ ...b, [tag]: true })); setShowLogs(true)
    setProgress('换脸中（上传源脸 → 逐帧换脸，会慢些）…')
    try {
      const jobId = await pipelineFaceswap(file, {
        sceneId: sceneId || '', kind, projectId: projectId || '', workspace, sessionId,
      })
      for await (const ev of streamJobEvents(jobId)) {
        if (ev.type === 'log') { setLogs(prev => [...prev, ev.line].slice(-300)); if (ev.line) setProgress(ev.line) }   // 心跳也刷到主状态条，让你看到「换脸还在跑·已等待Ns」，不再像卡住
        else if (ev.type === 'video' && ev.url) setSwUrl(u => ({ ...u, [tag]: fileUrl(ev.url) + '&v=' + Date.now() }))
        else if (ev.type === 'tool_result' && ev.content) { setProgress(ev.content); setLogs(prev => [...prev, '» ' + ev.content].slice(-300)) }
        else if (ev.type === 'error') setProgress(ev.content || '换脸已停止')
      }
    } catch (e) { setProgress('换脸失败：' + String(e.message || e)) }
    finally {
      setSwBusy(b => { const n = { ...b }; delete n[tag]; return n })
      setSwFile(s => { const n = { ...s }; delete n[tag]; return n })   // 跑完清掉已选脸，行复位
    }
  }
  const faceswapRow = (tag, kind, sceneId, projectId) => {
    if (!loras.comfyui) return null   // 换脸靠 ComfyUI(ReActor)，纯 t2v 无 ComfyUI → 不显示，免点了报「未配置」
    const bz = !!swBusy[tag]
    const f = swFile[tag]
    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}
          title="把你上传的源脸换到这段成片里的人物上；输出独立新文件、不覆盖原片。仅限你有权使用的脸(原创/AI/本人授权)。">一键换脸</span>
        {/* 第一步：选源脸——只暂存，不立刻跑（之前一选就跑，没有确定键，体验像坏了） */}
        <label style={{ ...miniAct(false), opacity: bz ? 0.6 : 1, cursor: bz ? 'default' : 'pointer' }}>
          {f ? `🖼 已选：${(f.name || '源脸').slice(0, 16)}` : '🖼 选源脸'}
          <input type="file" accept="image/png,image/jpeg,image/webp" hidden disabled={bz}
            onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) setSwFile(s => ({ ...s, [tag]: file })) }} />
        </label>
        {/* 第二步：确定开始（选了脸才可点） */}
        <button type="button" disabled={bz || !f}
          onClick={() => doFaceswap(tag, kind, sceneId, projectId, f)}
          style={{ ...miniAct(false), border: '1px solid rgba(134,239,172,0.5)',
            color: (!bz && f) ? 'rgba(134,239,172,1)' : 'var(--text-dim)',
            opacity: (bz || !f) ? 0.45 : 1, cursor: (bz || !f) ? 'default' : 'pointer' }}>
          {bz ? '换脸中…' : '✅ 开始换脸'}
        </button>
        {f && !bz && (
          <button type="button" onClick={() => setSwFile(s => { const n = { ...s }; delete n[tag]; return n })}
            style={{ ...miniAct(false), fontSize: 10.5 }}>✕ 重选</button>
        )}
        <span style={{ fontSize: 10.5, color: 'var(--text-dim)', width: '100%' }}>
          ⚠️ 选好源脸后点「✅ 开始换脸」。仅用于你有权使用的脸（原创/AI 生成/本人授权）；换可识别真人=deepfake，平台 ToS 与法律禁止。
        </span>
        {swUrl[tag] && (<>
          <span style={{ fontSize: 11, color: 'rgba(134,239,172,1)', width: '100%' }}>✓ 换脸版（原片保留，可对比）</span>
          <video key={swUrl[tag]} src={swUrl[tag]} controls
            style={{ width: '100%', maxHeight: 320, borderRadius: 8, display: 'block', border: '1px solid rgba(134,239,172,0.4)' }} />
        </>)}
      </div>
    )
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
          <span>分镜 <b style={{ color: 'rgba(255,255,255,0.87)', fontWeight: 600 }}>{c.total}</b></span>
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
            粘一段小说/剧情，AI 当导演自动拆成整套分镜（标题/画面词/运镜/旁白台词），自动套本集风格 + 角色外貌。
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
            <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>角色 + 风格 + LoRA + 分镜入库（<b>只生成分镜表、不出片</b>；想先审阅/改提示词再出片用它）</span>
          </div>
          {/* 终极一键：小说 → 按秒数自算镜数 → 逐镜文生视频(t2v) → 合成整集，全自动到底 */}
          <div style={{ border: '1px solid rgba(0,189,176,0.35)', background: 'rgba(0,189,176,0.07)',
                        borderRadius: 8, padding: 10, marginBottom: 8 }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <button onClick={doOneClick} disabled={!!busy || afBusy || sbBusy}
                style={{ height: 38, padding: '0 18px', borderRadius: 8, border: 'none',
                         background: (busy || afBusy || sbBusy) ? 'rgba(255,255,255,0.06)' : '#00bdb0',
                         color: (busy || afBusy || sbBusy) ? 'var(--text-muted)' : '#04201e', fontSize: 13.5, fontWeight: 700,
                         cursor: (busy || afBusy || sbBusy) ? 'default' : 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {busy === 'oneclick' ? '全自动制作中…' : '✨ 一键全自动出片'}
              </button>
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>目标
                <input type="number" min={5} max={300} value={ocSec} onChange={e => setOcSec(e.target.value)}
                  style={{ ...inputStyle, width: 60, height: 28, margin: '0 4px' }} />秒</label>
              <label style={{ fontSize: 12, display: 'inline-flex', gap: 4, alignItems: 'center', color: 'var(--text-muted)' }}
                title="少而长的连续长镜头，切换点少 → 更连贯；关掉=多而短的快切">
                <input type="checkbox" checked={ocCoh} onChange={e => setOcCoh(e.target.checked)} />连贯优先
              </label>
            </div>
            <div style={{ fontSize: 10.5, color: 'var(--text-dim)', marginTop: 6 }}>
              <b>含上面的 AI 分析</b>（角色/风格/分镜）→ 按秒数拆镜 → 逐镜文生 → 合成整集，一路到底（<b>不必先点「AI 分析填充」</b>）。
              身份靠训好的 Wan-T2V 角色 LoRA（在「角色 &amp; LoRA」训）。
            </div>
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
            角色/声音圣经 —— 每个角色固定外貌+音色。拆分镜/出片自动用其外貌（跨镜同一个人），配音用其音色。
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
              <input defaultValue={c.trigger_word || ''}
                placeholder="触发词（建议留空！系统自动生成不撞车的罕见词。别填 char/人名等常见词，否则训出来像别人）"
                title="角色 LoRA 能不能对得上人的命门：触发词必须是无含义的罕见词。留空或填了常见词(char/person/人名)时，系统自动换成 zq 开头的罕见 token，打 caption 与出片注入都用它、保持一致。"
                onBlur={e => e.target.value !== (c.trigger_word || '') && charOp('update', { char_id: c.id, trigger_word: e.target.value })}
                style={{ ...inputStyle, height: 28, width: '100%', boxSizing: 'border-box', marginBottom: 4 }} />
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>音色</span>
                <select defaultValue={c.voice || ''} onChange={e => charOp('update', { char_id: c.id, voice: e.target.value })}
                  title="该角色的配音音色（声音圣经）；旁白/多角色对话出现该角色台词时，按此音色配音"
                  style={{ ...inputStyle, height: 28, flex: 1 }}>
                  {VOICES.map(v => <option key={v.v} value={v.v}>{v.label}</option>)}
                </select>
                <label title="传一张该角色清晰正脸 → 出片勾「强锁脸(Stand-In)」即用它跨镜锁定这张脸(免训练)。"
                  style={{ ...miniBtn2, cursor: 'pointer', color: c.ref_image_path ? '#34d399' : undefined, whiteSpace: 'nowrap' }}>
                  {c.ref_image_path ? '换参考脸 ✓' : '传参考脸'}
                  <input type="file" accept="image/*" style={{ display: 'none' }}
                    onChange={e => { charFaceUpload(c.id, (e.target.files || [])[0]); e.target.value = '' }} />
                </label>
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
            人物 LoRA 训练（Wan-T2V）—— 一次训出 high+low 两个 Wan LoRA、t2v 出片锁定这个角色（t2v 没首帧，人物一致全靠它）。
            手动传 20-30 张同脸图开训。<b style={{ color: '#ffb454' }}>务必含 8-10 张脸部特写（脸占大半画面、戴眼镜要拍清）</b>——
            只传全身照的话脸太小、训出来只像体型不像脸（头号坑）。混搭：脸特写 8-10 张 + 半身 5-6 + 全身 4-5。
            <b style={{ color: '#5fe8de' }}>免上传自训·造图</b> 需出图后端 ComfyUI；纯 lightx2v t2v 无 ComfyUI → 请手动上传。
          </div>
          {/* 当前 server 实际加载的 LoRA(权威:读运行中 lightx2v 的 --config_json)——一眼看出角色/蒸馏挂没挂 */}
          <div style={{ border: '1px dashed var(--border)', borderRadius: 6, padding: 8, marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <button onClick={checkLoadedLoras} disabled={loraStatusBusy} style={{ ...miniBtn2, cursor: 'pointer' }}>
                {loraStatusBusy ? '查询中…' : '🔄 查看 server 当前已挂 LoRA'}
              </button>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>核对角色/蒸馏 LoRA 到底挂没挂（权威=lightx2v 起服务的 config）</span>
            </div>
            {loadedLoras && (
              <div style={{ marginTop: 6, fontSize: 12 }}>
                {(loadedLoras.loras || []).length === 0 ? (
                  <div style={{ color: '#fca5a5' }}>⚠ 没读到已挂 LoRA。{loadedLoras.note}<br /><span style={{ color: 'var(--text-dim)', fontSize: 10 }}>来源: {loadedLoras.source}</span></div>
                ) : (
                  <>
                    <div style={{ color: loadedLoras.has_char ? '#34d399' : '#ffb454', marginBottom: 4 }}>
                      {loadedLoras.has_char ? '✅ 已挂角色 LoRA（出片会像你训的人）' : '⚠ 只挂了蒸馏、没挂角色 LoRA → 出片不会像你训的人（去 §5d 挂上）'}
                      {loadedLoras.infer_steps != null && <span style={{ color: 'var(--text-dim)' }}>　·　步数 {loadedLoras.infer_steps}{loadedLoras.enable_cfg ? '（CFG开·高画质档）' : '（蒸馏档）'}</span>}
                    </div>
                    {loadedLoras.loras.map((l, i) => (
                      <div key={i} style={{ color: l.exists ? 'var(--text-muted)' : '#fca5a5', fontFamily: 'monospace', fontSize: 11 }}>
                        {l.kind === '角色' ? '🧑 ' : '⚡ '}{l.kind} · {l.name} · str {l.strength} · {l.file}{l.exists ? '' : ' ❌文件不存在'}
                      </div>
                    ))}
                    <div style={{ color: 'var(--text-dim)', fontSize: 10, marginTop: 4 }}>来源: {loadedLoras.source}</div>
                  </>
                )}
              </div>
            )}
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
              <input defaultValue={t.trigger_word || ''} placeholder="触发词（建议留空，系统自动用罕见词；别填 char/人名等常见词，否则训出来像别人）"
                title="留空或填常见词时系统自动换成 zq 开头的罕见 token；caption 打标与出片注入统一用它。"
                onBlur={e => { if (e.target.value !== (t.trigger_word || '')) loraOp('update', t.id, { trigger_word: e.target.value }) }}
                style={{ ...inputStyle, height: 26, width: '100%', boxSizing: 'border-box', marginBottom: 4 }} />
              {t.message && <div style={{ fontSize: 10.5, color: '#ffb454', marginBottom: 4 }}>{t.message}</div>}
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                <label style={{ ...miniBtn2, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <Icon.Plus size={13} />传参考图
                  <input type="file" accept="image/*" multiple style={{ display: 'none' }}
                    onChange={e => { loraUpload(t.id, Array.from(e.target.files || []), loraCharOf[t.id] || ''); e.target.value = '' }} />
                </label>
                <select value={loraCharOf[t.id] || ''} onChange={e => setLoraCharOf(p => ({ ...p, [t.id]: e.target.value }))}
                  title="选角色后传的图会自动按该角色外貌打提示词；多角色就逐个角色选着传，全进这一个 LoRA"
                  style={{ ...inputStyle, height: 26, width: 'auto' }}>
                  <option value="">⚠ 不打标(训出会不像)</option>
                  {(proj?.characters || []).map(c => <option key={c.id} value={c.id}>{c.name || '(未命名)'}</option>)}
                </select>
                <button onClick={() => loraOp('train', t.id)} disabled={loraBusy} style={panelBtn(loraBusy)}>开始训练</button>
                <button onClick={() => toggleLoraLog(t.id)} style={miniBtn2}>{loraLogOpen[t.id] ? '收起日志' : '日志/进度'}</button>
                <button onClick={() => loraDoPreview(t.id)} disabled={loraPrevBusy[t.id]} style={miniBtn2}
                  title="用当前 server 已挂载的 LoRA 出一条 480p/4步/33帧 短测试片(约 1 分钟)，验证 LoRA 学的人对不对">
                  {loraPrevBusy[t.id] ? '出片中…' : '测试出片'}
                </button>
                <button onClick={async () => { if (await dialog.confirm('清空这个 LoRA 的所有参考图？', { message: '删掉已传的图和旧训练产物（保留触发词设置），用于「干净重训」——避免上一轮旧图/旧标注残留进新训练集导致训出来不像。清空后重新上传即可。', danger: true, confirmText: '清空' })) loraOp('clear_images', t.id) }} disabled={loraBusy}
                  title="重训前清掉旧参考图，避免旧图/旧 caption 残留污染新训练集（训出来不像的头号坑）。清空后重新选角色上传。"
                  style={{ ...miniBtn2, color: '#fca5a5', borderColor: 'rgba(239,68,68,0.4)' }}>清空重传</button>
              </div>
              <div style={{ fontSize: 10.5, color: 'var(--text-dim)', marginTop: 4 }}>
                测试出片：预览当前 server 已挂载的 LoRA；先用笔记本 §5d 把这张卡训出的 LoRA 挂上再测。
              </div>
              {loraPrevUrl[t.id] && (
                <video key={loraPrevUrl[t.id]} src={loraPrevUrl[t.id]} controls
                  style={{ width: '100%', maxHeight: 320, borderRadius: 8, display: 'block', marginTop: 6, border: '1px solid rgba(134,239,172,0.4)' }} />
              )}
              <div style={{ fontSize: 10.5, color: 'var(--text-dim)', marginTop: 4 }}>
                选角色后传的图会自动按该角色外貌打提示词；多角色就逐个角色选着传，全进这一个 LoRA。
              </div>
              {loraLogOpen[t.id] && (
                <pre style={{ marginTop: 6, maxHeight: 220, overflow: 'auto', background: '#0d0d0d',
                  border: '1px solid var(--border)', borderRadius: 6, padding: 8, fontSize: 10.5,
                  lineHeight: 1.5, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: '6px 0 0' }}>
                  {loraLog[t.id] || '加载中…'}
                </pre>
              )}
              {loras.comfyui ? (
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
              ) : (
                <div style={{ fontSize: 10.5, color: 'var(--text-dim)', marginTop: 6 }}>
                  「免上传自训·造图」需 ComfyUI 出图后端，纯 t2v 未配 → 已停用。请用上方「传参考图」手动上传 16-20 张同脸图再「开始训练」。
                </div>
              )}
            </div>
          ))}
          <button onClick={newLora} disabled={loraBusy} style={{ ...panelBtn(loraBusy), display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon.Plus size={14} />新建 LoRA 训练</button>
        </div>
      </>)}

      {tab === 'script' && (
        <div style={subBox}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8 }}>
            本集统一风格 —— 出片自动套用到每个分镜，全集一个调性（这就是「一集一种风格」）。
          </div>
          {styleField('通用风格词', 'style_prompt', '如：写实，电影感，冷蓝调，浅景深（自动拼到每镜画面词后）')}
          {styleField('角色触发词', 'trigger_word', '人物 LoRA 触发词；没有就留空')}
          {styleLoraField()}
          {(loras.model && (loras.model.trigger_word || loras.model.flux_lora)) ? (
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 6 }}>
              对话/全局设置（本集留空时回退用）：触发词={loras.model.trigger_word || '（无）'} · LoRA={loras.model.flux_lora || '（无）'}
            </div>
          ) : null}
          <div style={{ fontSize: 10.5, color: 'var(--text-dim)', marginBottom: 6 }}>
            （t2v 的负向词 / 分辨率在「分镜制作」里按需调：分辨率用顶部下拉，负向词在「更多参数」；本集风格只管画面调性 + 角色 LoRA。）
          </div>
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
          {addField('画面提示词（写中文就行；t2v 文生视频的画面描述）', 'image_prompt')}
          {addField('运镜提示词', 'motion_prompt')}
          {addField('旁白 / 台词', 'narration')}
          {addField('字幕（可空，留空=用旁白）', 'subtitle')}
          <button onClick={addScene} disabled={addBusy} style={panelBtn(addBusy)}>
            {addBusy ? '添加中…' : '添加到本集'}
          </button>
        </div>
      )}

      {/* 文生视频(t2v)：不出图/不选图——分镜文本直接生成视频。每镜单出，或下面批量出整集，或顶部「✨ 一键」从小说全自动。 */}
      <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 10, padding: '10px 12px',
        border: '1px dashed var(--border)', borderRadius: 8, lineHeight: 1.7 }}>
        🎬 <b style={{ color: 'var(--text-secondary)' }}>文生视频 (t2v)</b>：不出图、不选图——分镜文本直接生成视频。
        每镜点「<b style={{ color: '#5fe8de' }}>出片(t2v)</b>」单出，或用下面「批量出片并合成」整集出。
        人物一致靠训好的 Wan-T2V 角色 LoRA（在「角色 &amp; LoRA」里训）。
      </div>

      {/* 批量出片并合成（t2v）：对所有未出片分镜逐镜文生 → 合成整集（模型/分辨率可选）*/}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <button onClick={() => runJob('finish')} disabled={!!busy || !(c.total > 0)}
          style={!(c.total > 0) ? panelBtn(false, true) : {
            height: 34, padding: '0 16px', borderRadius: 8, border: 'none',
            background: busy === 'finish' ? 'rgba(0,189,176,0.7)' : '#00bdb0',
            color: '#04201e', fontSize: 13, fontWeight: 700, cursor: 'pointer',
          }}>
          {busy === 'finish' ? '出片合成中…' : `🎬 批量出片并合成（t2v · ${c.total} 镜）`}
        </button>
        <button onClick={() => runJob('continuation')} disabled={!!busy || !(c.total > 1)}
          title="续接出片(i2v)：镜1 先用 t2v 出好当链头，镜2+ 用上一镜尾帧续生成 → 跨镜服装/场景/光线/动作连续(纯 t2v 做不到)。前置：在 Colab 跑「§i2v续接」起 i2v server。i2v 默认 40 步、较慢。"
          style={!(c.total > 1) ? panelBtn(false, true) : {
            height: 34, padding: '0 14px', borderRadius: 8, border: '1px solid rgba(129,140,248,0.55)',
            background: busy === 'continuation' ? 'rgba(99,102,241,0.5)' : 'transparent',
            color: '#a5b4fc', fontSize: 12.5, fontWeight: 600, cursor: busy ? 'default' : 'pointer',
          }}>
          {busy === 'continuation' ? '续接中…' : '🔗 续接出片(i2v·连贯)'}
        </button>
        <button onClick={() => runJob('assemble')} disabled={!!busy || !(c.total > 0)}
          title="合成整集：把所有已出片的分镜按序拼成一条短剧（去重帧 + crossfade 0.4s 抹接缝跳变 + 旁白/字幕）。不重出片、不占 GPU。"
          style={!(c.total > 0) ? panelBtn(false, true) : {
            height: 34, padding: '0 14px', borderRadius: 8, border: '1px solid rgba(45,212,191,0.5)',
            background: busy === 'assemble' ? 'rgba(20,184,166,0.5)' : 'transparent',
            color: '#5eead4', fontSize: 12.5, fontWeight: 600, cursor: busy ? 'default' : 'pointer',
          }}>
          {busy === 'assemble' ? '合成中…' : '🎬 合成整集'}
        </button>
        {/* 纯 t2v：出片后端由 T2V_PROVIDER(lightx2v) 路由、不看这个选择 → 移除误导的 i2v 模型下拉(Wan2.2-I2V/LTX)。
            出片参数(帧数/帧率/步数/seed)在下方「更多参数」调,字段名与 lightx2v 一致、对 t2v 生效。 */}
        <select value={vidSize} disabled={!!busy} onChange={e => setVidSize(e.target.value)}
          title="出片分辨率 —— 480p 快(草稿/走量)，720p 精修(成片)。一键切，不用改 .env。" style={{ ...inputStyle, width: 'auto', height: 32 }}>
          <option value="">默认(跟随 .env)</option>
          <option value="480*832">480×832 竖屏·快(草稿)</option>
          <option value="720*1280">720×1280 竖屏·精修</option>
          <option value="704*1280">704×1280 竖屏</option>
          <option value="832*480">832×480 横屏·快</option>
          <option value="1280*704">1280×704 横屏</option>
        </select>
        {/* 时长：用户按秒选，内部换成 Wan 要求的 4n+1 帧数(@16fps)。比直接填帧数直观,且避免填了非 4n+1 被 server 回退成 81≈5s。 */}
        <select value={vidParams.frames || 81} disabled={!!busy}
          onChange={e => setVidParams(p => ({ ...p, frames: Number(e.target.value) }))}
          title="出片时长。Wan 帧数须为 4n+1，这里已按 16fps 换算好；想要更长就选更大的。注:若改了时长出片仍是 5 秒，说明你的 lightx2v server 按启动 config 锁了帧长——按笔记本 §5d 把帧长写进 config 重起即可。"
          style={{ ...inputStyle, width: 'auto', height: 32 }}>
          <option value={81}>时长 ≈ 5 秒</option>
          <option value={129}>时长 ≈ 8 秒</option>
          <option value={161}>时长 ≈ 10 秒</option>
          <option value={241}>时长 ≈ 15 秒</option>
        </select>
        {/* 画质档(步数)从主行移除:与「更多参数·采样步数」重复,且本机 server 多忽略 per-request 步数(画质实际在 §5d 配)——别再误导。
            强锁脸(Stand-In)移到「更多参数」(进阶,需另起 server)。主行只留:出片 + 分辨率 + 时长 + 预估。 */}
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
            <div style={{ fontSize: 10.5, fontWeight: 700, color: 'rgba(94,234,212,0.8)', marginBottom: 6 }}>
              出片参数 · 帧数 / 帧率 / 采样步数 / seed（纯 t2v 走 lightx2v；帧数须 4n+1，如 81≈5s、121≈7.5s、161≈10s）
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
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, marginTop: 10,
                            color: lockFace ? '#5fe8de' : 'var(--text-muted)', cursor: 'pointer' }}
              title="强锁脸(Stand-In)：给角色传过参考脸的镜头用「一张脸硬锁身份」出片(跨镜更稳、免训练)。需先在 Colab 跑「§Stand-In」起 server;没起就自动回退普通出片。进阶功能,默认关。">
              <input type="checkbox" checked={lockFace} disabled={!!busy} onChange={e => setLockFace(e.target.checked)} />
              强锁脸 Stand-In（进阶 · 需先起 server）
            </label>
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
          {upscaleRow('episode', 'episode', '', pid)}
          {faceswapRow('episode', 'episode', '', pid)}
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
                        {sb === 'append' ? '续片中' : sb === 'undo' ? '撤销中' : '出片中'} {fmtElapsed(s.scene_id)} · 停止
                      </button>
                    )
                  }
                  if (s.video) return null   // 已出片 → 操作都在下方成片区
                  const disabled = !!busy
                  const sec = estSec != null ? estSec : null
                  // 纯 t2v：分镜文本直接出片(无出图/选图/对口型)。想长镜头先出 1 段、再用下方「再续一段」加长。
                  return (
                    <button onClick={() => runScene('render', s.scene_id)} disabled={disabled}
                      title="文本直接生成这镜视频(t2v)" style={miniAct(false, true)}>
                      {`出片(t2v)${sec != null ? ` ≈${sec.toFixed(0)}s` : ''}`}
                    </button>
                  )
                })()}
                {!s.video && (
                  <label title="已有这镜的视频？直接上传当成片，跳过出图/出片。之后可在下方继续 AI 续接 / 换脸 / 无缝化。"
                    style={{ fontSize: 11, color: 'rgba(94,234,212,0.95)',
                             cursor: (busy || !!sceneBusy[s.scene_id]) ? 'default' : 'pointer',
                             border: '1px solid rgba(45,212,191,0.35)', borderRadius: 6, padding: '2px 8px',
                             opacity: (busy || !!sceneBusy[s.scene_id]) ? 0.5 : 1 }}>
                    上传视频
                    <input type="file" accept="video/*,.mp4,.mov,.webm,.mkv,.m4v" style={{ display: 'none' }}
                      disabled={busy || !!sceneBusy[s.scene_id]}
                      onChange={async e => {
                        const f = e.target.files?.[0]; e.target.value = ''
                        if (f) await runUploadContinue(s.scene_id, f, { count: 0 })   // 0=只当成片，不强行 AI 续写
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
                  {upscaleRow(s.scene_id, 'scene', s.scene_id, '')}
                  {faceswapRow(s.scene_id, 'scene', s.scene_id, '')}
                  {/* 纯 t2v：尾帧接续(再续一段/上传视频续接/撤销)是 i2v 功能、lightx2v 不支持 → 已移除。
                      想要更长镜头:把上方「画质档/更多参数」的帧数调大(t2v 单镜一次性生成,81→121→161)。 */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, alignItems: 'center' }}>
                    <button onClick={() => delSceneVideo(s.scene_id)} disabled={busy || !!sceneBusy[s.scene_id]}
                      title="删除这个分镜的成片，可重新出片" style={{
                        height: 26, padding: '0 12px', borderRadius: 6,
                        border: '1px solid rgba(239,68,68,0.35)', background: 'rgba(239,68,68,0.12)',
                        color: 'rgba(252,165,165,1)', fontSize: 11.5, cursor: 'pointer',
                      }}>删除成片 · 重出</button>
                    <input value={appendPrompt[s.scene_id] || ''}
                      onChange={e => setAppendPrompt(p => ({ ...p, [s.scene_id]: e.target.value }))}
                      placeholder="续接的新内容(运镜/动作/剧情)，留空=延续当前"
                      disabled={busy || !!sceneBusy[s.scene_id]}
                      style={{ flex: '1 1 200px', minWidth: 150, height: 26, padding: '0 10px', borderRadius: 6,
                               border: '1px solid rgba(129,140,248,0.4)', background: 'rgba(99,102,241,0.08)',
                               color: '#e5e7eb', fontSize: 11.5, outline: 'none' }} />
                    <button onClick={() => runScene('append', s.scene_id)} disabled={busy || !!sceneBusy[s.scene_id]}
                      title="续接：从这镜【末帧】用左边新提示词 i2v 续生成一段，追加到后面(5s→10s)。可反复加、能撤销。需先在 Colab 起 i2v server。"
                      style={{
                        height: 26, padding: '0 12px', borderRadius: 6, border: '1px solid rgba(129,140,248,0.5)',
                        background: sceneBusy[s.scene_id] === 'append' ? 'rgba(99,102,241,0.4)' : 'rgba(99,102,241,0.14)',
                        color: '#a5b4fc', fontSize: 11.5, cursor: (busy || !!sceneBusy[s.scene_id]) ? 'default' : 'pointer',
                      }}>{sceneBusy[s.scene_id] === 'append' ? '续接中…' : '🔗 续接(+5s)'}</button>
                    <button onClick={() => undoAppend(s.scene_id)} disabled={busy || !!sceneBusy[s.scene_id]}
                      title="撤销上一段续接：成片回退到最近一次「续接」之前(可多次回退)。"
                      style={{
                        height: 26, padding: '0 10px', borderRadius: 6, border: '1px solid rgba(148,163,184,0.4)',
                        background: sceneBusy[s.scene_id] === 'undo' ? 'rgba(148,163,184,0.3)' : 'transparent',
                        color: '#cbd5e1', fontSize: 11.5, cursor: (busy || !!sceneBusy[s.scene_id]) ? 'default' : 'pointer',
                      }}>{sceneBusy[s.scene_id] === 'undo' ? '撤销中…' : '↩ 撤销上一段'}</button>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  还没出片 —— 点上方「出片(t2v)」生成这镜视频，或用顶部「批量出片并合成」整集出。
                </div>
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
              <ScenePrompts scene={s} characters={proj?.characters || []} workspace={workspace} onSaved={load} />
            </div>
          )
        })}
      </div>
      </>)}

      {tab === 'export' && (
        <div style={subBox}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8 }}>
            导出 —— 全部分镜出完片后，「批量出片并合成（t2v）」在「分镜制作」里点；成片在这里下载。
          </div>
          {proj?.episode ? (
            <div>
              <video src={fileUrl(proj.episode.url)} controls style={{ width: '100%', borderRadius: 8, marginBottom: 8 }} />
              <a href={fileUrl(proj.episode.url)} download style={{ ...panelBtn(false), textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon.Download size={14} />下载整集 mp4</a>
            </div>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>还没有整集成片。去「分镜制作」点「批量出片并合成（t2v）」。</div>
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
function ScenePrompts({ scene, characters, workspace, onSaved }) {
  const [open, setOpen] = useState(false)
  const [tit, setTit] = useState(scene.title || '')
  const [num, setNum] = useState(String(scene.scene_number ?? ''))
  const [img, setImg] = useState(scene.image_prompt || '')
  const [mot, setMot] = useState(scene.motion_prompt || '')
  const [nar, setNar] = useState(scene.narration || '')
  const [sub, setSub] = useState(scene.subtitle || '')
  const [cha, setCha] = useState(scene.character || '')   // 本镜主角(t2v 注入该角色触发词锁脸)
  const [dlgRows, setDlgRows] = useState(() => _parseDlg(scene.dialogue || ''))
  const [saving, setSaving] = useState(false)
  const dlgStr = dlgRows.map(r => (r.speaker ? r.speaker + '：' + r.text : r.text)).filter(x => x.trim()).join('\n')
  const numChanged = num !== '' && Number(num) !== scene.scene_number
  const dirty = img !== (scene.image_prompt || '') || mot !== (scene.motion_prompt || '')
    || nar !== (scene.narration || '') || sub !== (scene.subtitle || '') || dlgStr !== (scene.dialogue || '')
    || tit !== (scene.title || '') || cha !== (scene.character || '') || numChanged

  const save = async () => {
    setSaving(true)
    try {
      const fields = { image_prompt: img, motion_prompt: mot, narration: nar, subtitle: sub, dialogue: dlgStr, title: tit, character: cha }
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
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>本镜主角（t2v 自动注入该角色触发词锁脸；单人镜务必选好，多人镜留空防串脸）</span>
            <select value={cha} onChange={e => setCha(e.target.value)} style={{ ...inputStyle, height: 28, fontSize: 11.5 }}>
              <option value="">（空 / 多人镜）</option>
              {(characters || []).map(c => <option key={c.id} value={c.name}>{c.name || '(未命名)'}</option>)}
              {cha && !(characters || []).some(c => c.name === cha) && <option value={cha}>{cha}（无此角色）</option>}
            </select>
          </label>
          {ta('画面提示词（image_prompt，t2v 出片的画面描述；角色触发词自动注入）', img, setImg, 3)}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '0 0 6px' }}>
            <TemplateBar kind="prompt" label="提示词" workspace={workspace} getContent={() => img} onApply={c => setImg(c)} />
          </div>
          {ta('运镜/动态提示词（motion_prompt，出视频用）', mot, setMot)}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '0 0 6px' }}>
            <TemplateBar kind="motion" label="运镜" workspace={workspace} getContent={() => mot} onApply={c => setMot(c)} />
          </div>
          {ta('旁白（narration，转 TTS 配音）', nar, setNar)}
          {ta('字幕（subtitle，屏幕文字；留空=同旁白）', sub, setSub)}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>角色对话（每句选说话人＋台词；按角色音色各自配音，填了优先于旁白）</span>
            {dlgRows.map((r, idx) => (
              <div key={idx} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <select value={r.speaker} onChange={e => setDlgRows(rs => rs.map((x, i) => i === idx ? { ...x, speaker: e.target.value } : x))}
                  style={{ ...inputStyle, height: 28, width: 104, fontSize: 11 }}>
                  <option value="">旁白/无名</option>
                  {(characters || []).map(c => <option key={c.id} value={c.name}>{c.name || '(未命名)'}</option>)}
                  {r.speaker && !(characters || []).some(c => c.name === r.speaker) && <option value={r.speaker}>{r.speaker}（无此角色）</option>}
                </select>
                <input value={r.text} placeholder="台词" onChange={e => setDlgRows(rs => rs.map((x, i) => i === idx ? { ...x, text: e.target.value } : x))}
                  style={{ ...inputStyle, height: 28, flex: 1, fontSize: 11.5 }} />
                <button onClick={() => setDlgRows(rs => rs.filter((_, i) => i !== idx))} title="删除这句"
                  style={{ ...miniBtn2, padding: '0 9px', color: '#fca5a5' }}>×</button>
              </div>
            ))}
            <button onClick={() => setDlgRows(rs => [...rs, { speaker: '', text: '' }])}
              style={{ ...miniBtn2, alignSelf: 'flex-start' }}>＋ 加一句台词</button>
          </div>
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
// 把「说话人：台词」逐行解析成 [{speaker,text}]（中英文冒号都认；空行跳过）
function _parseDlg(s) {
  return (s || '').split('\n').map(line => {
    const t = line.trim()
    if (!t) return null
    let i = t.indexOf('：'); if (i < 0) i = t.indexOf(':')
    return i >= 0 ? { speaker: t.slice(0, i).trim(), text: t.slice(i + 1).trim() } : { speaker: '', text: t }
  }).filter(Boolean)
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
