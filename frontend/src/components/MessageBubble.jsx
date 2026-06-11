import { useState, useEffect, useMemo, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { fileUrl, getVideoProviders, getProject, batchGenerate, batchFinish,
         pipelineSelect, streamJobEvents, uploadCandidate, updateScenePrompts,
         deleteCandidate, deleteSceneVideo, deleteEpisode,
         sceneGenerate, sceneRender, cancelJob, listActiveJobs } from '../api'

/**
 * MessageBubble — 消息渲染
 *
 * 用户消息：右对齐纯文字
 * AI 消息：深色卡片 + Markdown + pcAction 按钮 + MSG_SPLIT 快捷区 + 图片墙
 * Interrupt：HITL 确认卡片
 * param_form：出图参数交互卡
 */
export default function MessageBubble({ message, onResume, onSend, onGenerate, onSelectImage, onRenderVideo, workspace, sessionId, stale }) {
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
  if (message.role === 'production') {
    return <ProductionPanel message={message} workspace={workspace} sessionId={sessionId} />
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
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>提示词（角色触发词已自动加好）</span>
        <textarea value={p.image_prompt} disabled={submitted} rows={2}
          onChange={e => setP({ ...p, image_prompt: e.target.value })}
          style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
      </label>

      {/* 常用：张数 + 尺寸（小白只看这些）*/}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 10, marginBottom: 10 }}>
        {field('张数', 'n')}
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

// 老事件没有 fields 时，用扁平字段合成 Wan2.2 的默认 schema，保证旧会话仍可渲染
function legacyVideoFields(params) {
  return [
    { key: 'size', label: '分辨率', type: 'select', default: params.size || '704*1280',
      help: '成片画面尺寸。竖屏适合手机短视频，横屏适合横版播放。',
      options: [
        { value: '704*1280', label: '704×1280 竖屏' },
        { value: '1280*704', label: '1280×704 横屏' },
        { value: '960*960', label: '960×960 方形' },
      ] },
    { key: 'frame_num', label: '帧数(≤25稳)', type: 'number', default: params.frame_num ?? 25,
      help: '总帧数，决定视频长度（约 帧数÷24 秒）。越多越长越吃显存，24G 显卡建议不超过 25 帧。' },
    { key: 'sample_steps', label: '采样步数', type: 'number', default: params.sample_steps ?? 25,
      help: '去噪迭代次数。越大画质/稳定性略好但越慢，一般 20-30。' },
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
      border: '1px solid rgba(0,189,176,0.3)', background: 'rgba(0,189,176,0.06)',
      borderRadius: 12, padding: '16px 18px',
    }}>
      {/* 顶部横条：标题 + 模型选择 + 预计时长，一行读完 */}
      <div style={{
        display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 12,
      }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                      color: 'rgba(94,234,212,0.85)' }}>
          出视频参数
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
            flex: '0 0 auto', height: 30, padding: '0 22px', borderRadius: 6,
            border: '1px solid rgba(0,189,176,0.4)',
            background: submitted ? 'rgba(255,255,255,0.06)' : 'rgba(0,189,176,0.22)',
            color: submitted ? 'var(--text-muted)' : 'rgba(94,234,212,1)',
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
  DRAFT: { t: '待出图', c: 'var(--text-muted)' },
  PENDING_FLUX_GEN: { t: '出图中', c: 'rgba(234,179,8,0.9)' },
  PENDING_HUMAN_SELECTION: { t: '待选图', c: 'rgba(99,102,241,0.95)' },
  PENDING_VIDEO_GEN: { t: '已选·待出片', c: 'rgba(94,234,212,0.95)' },
  COMPLETED: { t: '已出片', c: 'rgba(34,197,94,0.95)' },
  FAILED: { t: '失败', c: 'rgba(239,68,68,0.95)' },
}

export function ProductionPanel({ message, workspace, sessionId }) {
  const pid = message.project_id
  const [proj, setProj] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')       // '' | 'generate' | 'finish'
  const [progress, setProgress] = useState('')
  const [zoom, setZoom] = useState(null)
  const [models, setModels] = useState([])
  const [model, setModel] = useState('')
  const [segments, setSegments] = useState(1)
  const [imgN, setImgN] = useState(4)              // 出图：每镜候选张数
  const [imgSize, setImgSize] = useState('768x1024')  // 出图：尺寸
  const [vidSize, setVidSize] = useState('')       // 出片：分辨率（空=默认）
  // 「更多参数」专业档：出图（空=用默认）；出片（按所选模型 schema 动态生成）
  const [showAdv, setShowAdv] = useState(false)
  const [imgAdv, setImgAdv] = useState({ steps: '', guidance: '', seed: '', offload: '' })
  const [vidParams, setVidParams] = useState({})
  const [sceneBusy, setSceneBusy] = useState({})   // {sceneId: 'generate'|'render'}
  const cancelled = useRef(false)
  const batchJob = useRef(null)                    // 当前批量任务 job_id（供停止）
  const sceneJob = useRef({})                      // {sceneId: job_id}（供单镜停止）

  // 出视频预估时长（秒）= 帧数 ÷ 帧率 × 接续段数。无 fps 字段（Wan）按 24fps。
  const estSec = (() => {
    const frames = Number(vidParams.frame_num ?? vidParams.num_frames)
    const fps = Number(vidParams.fps) || 24
    if (!frames || !fps) return null
    return (frames / fps) * Math.max(1, segments)
  })()
  const genPayload = (sceneId) => {
    const [iw, ih] = (imgSize || '0x0').split('x').map(Number)
    return { scene_id: sceneId, workspace, session_id: sessionId, n: imgN,
      width: iw || 0, height: ih || 0,
      img_steps: Number(imgAdv.steps) || 0,
      img_guidance: imgAdv.guidance !== '' ? Number(imgAdv.guidance) : -1,
      img_seed: imgAdv.seed !== '' ? Number(imgAdv.seed) : -1, img_offload: imgAdv.offload || '' }
  }
  const renderPayload = (sceneId) => ({
    scene_id: sceneId, workspace, session_id: sessionId,
    model, segments, size: vidSize, video_params: vidParams })

  const runScene = async (kind, sceneId) => {
    if (busy || sceneBusy[sceneId]) return
    setSceneBusy(p => ({ ...p, [sceneId]: kind }))
    try {
      const submit = kind === 'generate' ? sceneGenerate : sceneRender
      const jobId = await submit(kind === 'generate' ? genPayload(sceneId) : renderPayload(sceneId))
      sceneJob.current[sceneId] = jobId
      await consume(jobId)
    } catch { /* ignore */ }
    finally { delete sceneJob.current[sceneId]; setSceneBusy(p => { const n = { ...p }; delete n[sceneId]; return n }) }
  }

  const stopScene = async (sceneId) => {
    const jid = sceneJob.current[sceneId]
    if (jid) { try { await cancelJob(jid) } catch { /* ignore */ } }
  }

  // 切换视频模型时，按该模型 schema 重置专业参数（排除主行已有的 size）
  const curFields = (models.find(m => m.name === model)?.fields || []).filter(f => f.key !== 'size')
  useEffect(() => {
    const init = {}
    for (const f of curFields) init[f.key] = f.default
    setVidParams(init)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, models.length])

  const load = async () => {
    try { setProj(await getProject(pid, workspace)); setErr('') }
    catch (e) { setErr(String(e.message || e)) }
  }
  useEffect(() => { cancelled.current = false; load(); return () => { cancelled.current = true } }, [pid])  // eslint-disable-line
  useEffect(() => {
    getVideoProviders().then(d => {
      setModels(d.providers || [])
      if (!model && d.default) setModel(d.default)
    }).catch(() => {})
  }, [])  // eslint-disable-line

  // 统一消费任务事件流（首发与刷新重连共用）
  const consume = async (jobId) => {
    for await (const ev of streamJobEvents(jobId)) {
      if (cancelled.current) break
      if (ev.type === 'batch_progress') setProgress(ev.label || '处理中…')
      else if (ev.type === 'scene_ready' || ev.type === 'image' || ev.type === 'video') load()
      else if (ev.type === 'tool_result' && ev.content) setProgress(ev.content)
      else if (ev.type === 'error') setProgress(ev.content || '已停止')
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
          setBusy(j.kind === 'batch_generate' ? 'generate' : 'finish')
          setProgress('重新连接到进行中的任务…')
          consume(j.job_id).finally(() => { batchJob.current = null; setBusy('') })
        } else if (j.scene_id) {
          if (sceneJob.current[j.scene_id]) continue
          sceneJob.current[j.scene_id] = j.job_id
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
    if (!window.confirm('删除这张候选图？')) return
    try { await deleteCandidate(assetId, workspace); load() } catch { /* ignore */ }
  }
  const delSceneVideo = async (sceneId) => {
    if (!window.confirm('删除这个分镜的成片？删除后可重新出片（图还在）。')) return
    try { await deleteSceneVideo(sceneId, workspace); load() } catch { /* ignore */ }
  }
  const delEpisode = async () => {
    if (!window.confirm('删除整集成片？各分镜不受影响，可重新合成。')) return
    try { await deleteEpisode(pid, workspace); load() } catch { /* ignore */ }
  }

  const c = proj?.counts || { total: 0, with_candidates: 0, selected: 0, done: 0 }
  const allSelected = c.total > 0 && c.selected === c.total
  const someSelected = c.selected > 0

  return (
    <div style={{
      border: '1px solid rgba(99,102,241,0.3)', background: 'rgba(99,102,241,0.05)',
      borderRadius: 12, padding: '16px 18px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.05em', color: 'rgba(190,192,255,1)' }}>
          短剧制作面板 · {proj?.title || pid}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {c.total} 分镜 · 已出图 {c.with_candidates} · 已选 {c.selected} · 已出片 {c.done}
        </div>
        <button onClick={load} title="刷新" style={miniBtn}>↻</button>
      </div>

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
          style={panelBtn(busy === 'finish', !someSelected)}>
          {busy === 'finish' ? '出片合成中…' : (allSelected ? '③ 一键出片并合成' : `③ 出片并合成（已选${c.selected}/${c.total}）`)}
        </button>
        {models.length > 0 && (
          <select value={model} disabled={!!busy} onChange={e => setModel(e.target.value)}
            title="视频模型：LTX 快适合预演，Wan 慢画质高" style={{ ...inputStyle, width: 'auto', height: 32 }}>
            {models.map(m => <option key={m.name} value={m.name}>{m.display_name}</option>)}
          </select>
        )}
        <select value={segments} disabled={!!busy} onChange={e => setSegments(Number(e.target.value))}
          title="尾帧接续段数：越多镜头越长越连贯" style={{ ...inputStyle, width: 'auto', height: 32 }}>
          <option value={1}>单段</option>
          <option value={2}>接续×2</option>
          <option value={3}>接续×3</option>
        </select>
        <select value={vidSize} disabled={!!busy} onChange={e => setVidSize(e.target.value)}
          title="出片分辨率" style={{ ...inputStyle, width: 'auto', height: 32 }}>
          <option value="">默认分辨率</option>
          <option value="704*1280">704×1280 竖屏</option>
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
            <span style={{ width: 8, height: 8, borderRadius: 2, background: 'currentColor' }} />停止
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
            <div style={{ fontSize: 10.5, fontWeight: 700, color: 'rgba(165,168,255,0.8)', marginBottom: 6 }}>出图（FLUX）· 留空=默认</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
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
              border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px',
              background: 'rgba(255,255,255,0.02)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'rgba(255,255,255,0.8)' }}>
                  #{s.scene_number}
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-sec)', flex: 1, overflow: 'hidden',
                               textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.title || '(无题)'}</span>

                {/* 单镜独立操作：出图（随时可重出）/ 出视频（已选图后）*/}
                {(() => {
                  const sb = sceneBusy[s.scene_id]
                  if (sb) {   // 该镜正在跑 → 显示可点的「停止」
                    return (
                      <button onClick={() => stopScene(s.scene_id)} title="停止这个分镜的任务"
                        style={{ ...miniAct(false), border: '1px solid rgba(239,68,68,0.4)',
                                 background: 'rgba(239,68,68,0.16)', color: 'rgba(252,165,165,1)' }}>
                        {sb === 'generate' ? '出图中·停止' : '出片中·停止'}
                      </button>
                    )
                  }
                  const disabled = !!busy
                  return (<>
                    <button onClick={() => runScene('generate', s.scene_id)} disabled={disabled}
                      title="只对这个分镜出图" style={miniAct(false)}>
                      {s.candidates.length ? '重出图' : '出图'}
                    </button>
                    {s.selected && !s.video && (
                      <button onClick={() => runScene('render', s.scene_id)} disabled={disabled}
                        title="只对这个分镜出视频" style={miniAct(false, true)}>出视频</button>
                    )}
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
                <span style={{ fontSize: 11, fontWeight: 600, color: sl.c }}>{sl.t}</span>
              </div>

              {s.video ? (
                <div>
                  <video src={fileUrl(s.video.url)} controls
                         style={{ width: '100%', maxHeight: 300, borderRadius: 8, display: 'block' }} />
                  <button onClick={() => delSceneVideo(s.scene_id)}
                    title="删除这个分镜的成片（图还在，可重新出片）" style={{
                      marginTop: 6, height: 24, padding: '0 12px', borderRadius: 6,
                      border: '1px solid rgba(239,68,68,0.35)', background: 'rgba(239,68,68,0.12)',
                      color: 'rgba(252,165,165,1)', fontSize: 11.5, cursor: 'pointer',
                    }}>删除成片 · 重出</button>
                </div>
              ) : s.candidates.length > 0 ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(96px,1fr))', gap: 8 }}>
                  {s.candidates.map(img => (
                    <div key={img.assetId} style={{
                      position: 'relative', borderRadius: 8, overflow: 'hidden', cursor: 'pointer',
                      border: img.selected ? '2px solid rgba(34,197,94,0.9)' : '1px solid var(--border)',
                    }}>
                      <img src={fileUrl(img.url)} alt={img.name} onClick={() => setZoom(img)}
                           style={{ width: '100%', aspectRatio: '3/4', objectFit: 'cover', display: 'block' }} />
                      <button onClick={() => select(s.scene_id, img.assetId)}
                        title={img.selected ? '已选' : '选这张'}
                        style={{
                          position: 'absolute', top: 4, right: 4, width: 22, height: 22, borderRadius: 6,
                          border: 'none', cursor: 'pointer', fontSize: 12, color: '#fff',
                          background: img.selected ? 'rgba(34,197,94,0.9)' : 'rgba(0,0,0,0.55)',
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

              {/* 提示词全透明：AI 写的也给用户看，且可改（改完再出图/出片更省 GPU） */}
              <ScenePrompts scene={s} workspace={workspace} onSaved={load} />
            </div>
          )
        })}
      </div>

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
  const [img, setImg] = useState(scene.image_prompt || '')
  const [mot, setMot] = useState(scene.motion_prompt || '')
  const [nar, setNar] = useState(scene.narration || '')
  const [saving, setSaving] = useState(false)
  const dirty = img !== (scene.image_prompt || '') || mot !== (scene.motion_prompt || '')
    || nar !== (scene.narration || '')

  const save = async () => {
    setSaving(true)
    try {
      await updateScenePrompts(scene.scene_id,
        { image_prompt: img, motion_prompt: mot, narration: nar }, workspace)
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
          {ta('出图提示词（image_prompt，角色触发词自动注入）', img, setImg, 3)}
          {ta('运镜/动态提示词（motion_prompt，出视频用）', mot, setMot)}
          {ta('旁白（narration，合成时转 TTS + 字幕）', nar, setNar)}
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

const panelBtn = (active, disabled) => ({
  height: 32, padding: '0 16px', borderRadius: 8,
  border: '1px solid rgba(99,102,241,0.4)',
  background: disabled ? 'rgba(255,255,255,0.05)' : active ? 'rgba(99,102,241,0.35)' : 'rgba(99,102,241,0.2)',
  color: disabled ? 'var(--text-muted)' : 'rgba(190,192,255,1)',
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

const inputStyle = {
  height: 30, padding: '0 8px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.85)', fontSize: 12,
  width: '100%', colorScheme: 'dark',
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
