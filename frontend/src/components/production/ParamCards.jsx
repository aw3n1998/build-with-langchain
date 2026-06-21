// 出图 / 出视频 的内联参数卡(从 MessageBubble.jsx 抽出)。
// 这两张卡由聊天里的 param_form / video_param_form 事件渲染,与 ProductionPanel 解耦(只吃 props)。
import { useState, useEffect, useMemo } from 'react'
import { getVideoProviders } from '../../api'
import { inputStyle } from './uiStyles'

export function ParamCard({ message, onGenerate, stale }) {
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
export function HelpTip({ text }) {
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

export function VideoParamCard({ message, onRenderVideo, stale }) {
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
