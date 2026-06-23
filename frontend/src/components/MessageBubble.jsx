import { useState, useEffect, useMemo, useRef } from 'react'
import { Icon } from './icons'
import { useDialog } from './Dialog'
import { ParamCard, VideoParamCard, HelpTip } from './production/ParamCards'
import { panelBtn, miniAct, miniBtn, miniBtn2, inputStyle } from './production/uiStyles'

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
         suggestContinuation, sceneGenerate, sceneRender, sceneAppend, sceneLipsync, sceneSfx,
         cancelJob, listActiveJobs,
         projectStyle, sceneAdd, sceneDelete, listLoras,
         oneClick, autoSelect, uploadCharacterFace, uploadCharacterVoice, getLoadedLoras, getProviderHealth } from '../api'

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
  // 首镜起头模式(per-scene):'t2v'=文生链头(默认)/'i2v'=从一张关键帧(上传/出图选中)i2v 起头、首帧脸钉死
  const [firstFrameMode, setFirstFrameMode] = useState({})
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
  const [loadedLoras, setLoadedLoras] = useState(null)   // 项目已配置的角色 LoRA(t2v/i2v,查看用)
  const [loraStatusBusy, setLoraStatusBusy] = useState(false)
  const [health, setHealth] = useState(null)   // 出片后端预检 provider_health:{providers:{name:{enabled,reachable,...}}, char_lora}
  const [dedupBoundary, setDedupBoundary] = usePersistedState('dedupBoundary', false)  // 续接整集:合成时去掉镜间重复边界帧
  // 某后端是否就绪(已注册+可达)的小工具,供 B.2/B.4 按钮禁用与内联提示
  const provReady = (name) => !!(health?.providers?.[name]?.enabled && health.providers[name].reachable)
  const [sceneBusy, setSceneBusy] = useState({})   // {sceneId: 'generate'|'render'|'append'}
  const [appendPrompt, setAppendPrompt] = useState({})  // {sceneId: 追加段的运镜提示词(可空)}
  const [appendNarr, setAppendNarr] = useState({})      // {sceneId: 续接段台词(配音，可空)}
  const [appendEmo, setAppendEmo] = useState({})        // {sceneId: 续接段情感(happy/angry/sad/afraid/surprised/'')}
  const [appendCount, setAppendCount] = useState({})    // {sceneId: 本次追加几段}
  const [appendLang, setAppendLang] = useState({})      // {sceneId: 'zh'|'en'} 推荐语言
  const [appendSugBusy, setAppendSugBusy] = useState({})// {sceneId: AI 推荐请求中}
  const [sceneLipsyncOn, setSceneLipsyncOn] = useState({})  // {sceneId: 对口型开关(本地态，叠加 scene.lipsync)}（重命名避免遮蔽同名 API 导入 sceneLipsync）
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
  const [novel, setNovel] = usePersistedState('sbNovel.' + pid, '')   // ★ per-project：每集独立剧本（曾用全局键'sbNovel'导致各集剧本串成同一份）
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

  // 出片后端预检：进面板拉一次（用于按钮禁用 + 提交前内联提示：强锁脸/i2v 续接 server 起没起、角色 LoRA 挂没挂）
  useEffect(() => {
    let ok = true
    getProviderHealth(pid || '', workspace || null).then(h => { if (ok) setHealth(h) }).catch(() => {})
    return () => { ok = false }
  }, [pid, workspace])

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
    const ls = sceneLipsyncOn[sceneId] ?? !!(proj?.scenes?.find(x => x.scene_id === sceneId)?.lipsync)
    // 首镜可切 i2v 起头(firstFrameMode[sceneId]==='i2v'):后端 do_render_scene_video 走 i2v 分支、用该镜已选关键帧当首帧
    const ffMode = firstFrameMode[sceneId] === 'i2v' ? 'i2v' : 't2v'
    return { scene_id: sceneId, workspace, session_id: sessionId,
      model, segments: segs, size: vidSize, video_params: { ...vidParams, ...(lockFace ? { lock_face: true } : {}) }, motion_prompts: mp, lipsync: ls,
      video_mode: ffMode }   // t2v=直接文生(跳过出图/选图);i2v=从关键帧起头(首帧脸钉死)
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
    scene_id: sceneId, workspace, session_id: sessionId, model: 'wan2.2',   // ★追加段走 i2v(ComfyUI)：从这镜末帧续生成
    motion_prompt: appendPrompt[sceneId] || '',
    count: Math.max(1, Number(appendCount[sceneId]) || 1),
    size: vidSize, video_params: vidParams,
    seg_narration: appendNarr[sceneId] || '',   // 续接段台词→角色克隆+情感 TTS，音频定段长，配音叠回成片
    emotion: appendEmo[sceneId] || '',
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

  // 「口型同步」：把这镜【已有成片】按音轨(续接段配的情感语音)/旁白做 LatentSync 缝嘴，嘴型对到台词。需起 LatentSync server。
  const runLipsync = async (sceneId) => {
    if (busy || sceneBusy[sceneId]) return
    startAt.current[sceneId] = Date.now()
    setLogs([]); setShowLogs(true)
    setSceneBusy(p => ({ ...p, [sceneId]: 'lipsync' }))
    try {
      const jobId = await sceneLipsync({ scene_id: sceneId, workspace, session_id: sessionId })
      sceneJob.current[sceneId] = jobId
      await consume(jobId)
    } catch (e) { setProgress('口型同步失败：' + String(e.message || e)) }
    finally { delete sceneJob.current[sceneId]; setSceneBusy(p => { const n = { ...p }; delete n[sceneId]; return n }) }
  }

  // 「生成音效」：把这镜【已有成片】喂给视频→音频 Foley 模型，生成与画面同步的环境/动作音效，叠在已有人声之下。需起 Foley server。
  const runSfx = async (sceneId) => {
    if (busy || sceneBusy[sceneId]) return
    startAt.current[sceneId] = Date.now()
    setLogs([]); setShowLogs(true)
    setSceneBusy(p => ({ ...p, [sceneId]: 'sfx' }))
    try {
      const jobId = await sceneSfx({ scene_id: sceneId, workspace, session_id: sessionId })
      sceneJob.current[sceneId] = jobId
      await consume(jobId)
    } catch (e) { setProgress('生成音效失败：' + String(e.message || e)) }
    finally { delete sceneJob.current[sceneId]; setSceneBusy(p => { const n = { ...p }; delete n[sceneId]; return n }) }
  }

  // 「上传关键帧」(首镜 i2v 起头用)：上传一张图当该镜首帧候选并自动选中 → 之后「出片(i2v·锁首帧)」从它 i2v 动起来。
  // 复用 upload_candidate(登记候选)+select(选中)两步，落到「该镜有一张 selected 候选图」这个 i2v 出片前提。
  const uploadKeyframe = async (sceneId, file) => {
    if (busy || sceneBusy[sceneId]) return
    setSceneBusy(p => ({ ...p, [sceneId]: 'keyframe' }))
    try {
      const { asset_id } = await uploadCandidate(sceneId, file, workspace)
      await pipelineSelect(sceneId, asset_id, workspace)
      await load()
      setProgress('关键帧已上传并选中 → 点「出片(i2v·锁首帧)」从它起头')
    } catch (e) { setProgress('上传关键帧失败：' + String(e.message || e)) }
    finally { setSceneBusy(p => { const n = { ...p }; delete n[sceneId]; return n }) }
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
    setSceneLipsyncOn(p => ({ ...p, [sceneId]: val }))
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
    setProgress('测试出片中…（480p/4步/33帧，约 1 分钟；用项目已配置的角色 LoRA）')
    let gotVideo = false
    try {
      const jobId = await loraPreview(tid, workspace, sessionId)
      for await (const ev of streamJobEvents(jobId)) {
        if (ev.type === 'video' && ev.url) { setLoraPrevUrl(p => ({ ...p, [tid]: fileUrl(ev.url) + '&v=' + Date.now() })); gotVideo = true }
        // ★出片报错走 tool_result 事件（不是 error）——之前没接、被静默吞掉，导致"点了没反应"。这里一并显示。
        else if ((ev.type === 'error' || ev.type === 'tool_result') && ev.content) setProgress('测试出片：' + ev.content)
        else if (ev.type === 'log' && ev.line) setProgress('测试出片中…' + String(ev.line).slice(-90))
      }
      if (!gotVideo) setProgress('测试出片结束但没拿到视频——多半出片那步报错了。看 Colab 的 ComfyUI 日志定位。')
    } catch (e) { setProgress('测试出片失败：' + String(e.message || e)) }
    finally { setLoraPrevBusy(p => ({ ...p, [tid]: false })) }
  }
  // 每张 LoRA 卡选中的角色 id（选了 → 传图按该角色外貌自动打 caption；多角色就逐个选着传，全进这一个 LoRA）
  const [loraCharOf, setLoraCharOf] = useState({})   // {tid: char_id}
  // 免上传自训：每张卡的模式/张数本地态 + 上传参考脸 + 造图(+造完即训)
  const [loraBoot, setLoraBoot] = useState({})   // {tid:{mode,count}}
  const bootOf = (tid) => loraBoot[tid] || { mode: 'text', count: 16 }
  const setBootOf = (tid, patch) => setLoraBoot(b => ({ ...b, [tid]: { ...bootOf(tid), ...patch } }))
  const [loraTrainMode, setLoraTrainMode] = useState({})   // {tid:'t2v'|'i2v'} 训练目标(t2v文生/i2v续接锁脸)
  const trainModeOf = (tid) => loraTrainMode[tid] || 't2v'
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
  // 音色克隆(锁声)：给某角色传一段参考音(几秒~30s 真人录音)→ 写 characters.ref_audio_path + voice_engine。
  // 之后配音全程用这段克隆音色(对口型镜/旁白镜同源→音色一致)；没起克隆 server 时后端自动回退 edge-tts。
  const charVoiceUpload = async (charId, file) => {
    if (!file) return
    setProgress('上传参考音中…')
    try { await uploadCharacterVoice(charId, proj?.id || '', file, 'indextts2', workspace); await load(); setProgress('参考音已上传（该角色全程用这段克隆音色；想换回预置音选上面的音色下拉即可）') }
    catch (e) { setProgress('参考音上传失败：' + String(e.message || e)) }
  }
  // 查本项目已配置的角色 LoRA(t2v/i2v)——ComfyUI 按文件名加载,读项目级配置
  const checkLoadedLoras = async () => {
    setLoraStatusBusy(true)
    try { setLoadedLoras(await getLoadedLoras(pid, workspace)) }
    catch (e) { setProgress('查询已挂 LoRA 失败：' + String(e.message || e)) }
    finally { setLoraStatusBusy(false) }
  }
  const loraBootstrap = async (tid) => {
    const { mode, count } = bootOf(tid)
    setLoraBusy(true)
    try {
      // video 模式=用 t2v LoRA 造转身片→造完即训【i2v】原生 LoRA；text/pulid=造静图→训 t2v
      const lora_mode = mode === 'video' ? 'i2v' : 't2v'
      const r = await loraAction(pid, 'bootstrap', tid, workspace, { mode, count: Number(count) || 0, auto_train: true, lora_mode })
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
    // 预检(B.4):依赖没就绪就别静默等几分钟才失败——先弹清楚的提示,让用户决定
    if (kind === 'continuation' && !provReady('wan2.2')) {
      const go = await dialog.confirm('i2v 续接 server 未就绪', {
        message: '续接需要 ComfyUI 就绪（配 COMFYUI_BASE_URL，由它的 i2v provider 续接）。现在它没注册或连不上，提交多半直接失败。仍要提交吗？',
        danger: true, confirmText: '仍要提交',
      })
      if (!go) return
    }
    if (kind === 'finish' && lockFace && !provReady('standin-t2v')) {
      const go = await dialog.confirm('强锁脸 server 未就绪', {
        message: '勾了强锁脸(Stand-In)，但它的 server 没起/连不上 → 本次会自动回退普通出片（不锁脸）。继续吗？',
        confirmText: '继续(不锁脸)',
      })
      if (!go) return
    }
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
        dedup_boundary: kind === 'assemble' ? !!dedupBoundary : false,   // 续接整集合成:去镜间重复边界帧(A.2)
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
      if (kind === 'continuation') setDedupBoundary(true)   // 续接过 → 合成整集默认去镜间重复边界帧
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
          <div style={{ fontSize: 11.5, color: 'var(--text-dim)', marginBottom: 10, lineHeight: 1.6 }}>
            粘一段小说 / 剧情，AI 当导演自动拆成整套分镜（标题 / 画面词 / 运镜 / 旁白台词），自动套本集风格 + 角色外貌。
          </div>
          <textarea value={novel} onChange={e => setNovel(e.target.value)} rows={6}
            placeholder="把这一集的小说 / 剧情粘进来…"
            style={{ ...inputStyle, width: '100%', resize: 'vertical', minHeight: 120, fontSize: 13.5, lineHeight: 1.6, padding: '12px 14px' }} />

          {/* 主操作（最醒目）：一键全自动出片 —— 小说→按秒数拆镜→逐镜文生→合成整集，一路到底 */}
          <div style={{ marginTop: 14, border: '1px solid rgba(0,189,176,0.32)', background: 'rgba(0,189,176,0.06)',
                        borderRadius: 12, padding: 14 }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <button onClick={doOneClick} disabled={!!busy || afBusy || sbBusy}
                style={{ height: 42, padding: '0 22px', borderRadius: 10, border: 'none',
                         background: (busy || afBusy || sbBusy) ? 'rgba(255,255,255,0.06)' : '#00bdb0',
                         color: (busy || afBusy || sbBusy) ? 'var(--text-muted)' : '#04201e', fontSize: 14.5, fontWeight: 700,
                         cursor: (busy || afBusy || sbBusy) ? 'default' : 'pointer', display: 'inline-flex', alignItems: 'center', gap: 7,
                         boxShadow: (busy || afBusy || sbBusy) ? 'none' : '0 6px 18px rgba(0,189,176,0.28)' }}>
                {busy === 'oneclick' ? '全自动制作中…' : '✨ 一键全自动出片'}
              </button>
              <label style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>目标
                <input type="number" min={5} max={300} value={ocSec} onChange={e => setOcSec(e.target.value)}
                  style={{ ...inputStyle, width: 62, height: 30, margin: '0 5px' }} />秒</label>
              <label style={{ fontSize: 12.5, display: 'inline-flex', gap: 5, alignItems: 'center', color: 'var(--text-muted)' }}
                title="少而长的连续长镜头，切换点少 → 更连贯；关掉=多而短的快切">
                <input type="checkbox" checked={ocCoh} onChange={e => setOcCoh(e.target.checked)} />连贯优先
              </label>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8, lineHeight: 1.6 }}>
              <b>含 AI 分析</b>（角色 / 风格 / 分镜）→ 按秒数拆镜 → 逐镜文生 → 合成整集，一路到底（不必先点下面的「AI 分析填充」）。
              身份靠训好的 Wan-T2V 角色 LoRA（在「角色 &amp; LoRA」训）。
            </div>
          </div>

          {/* 次要（手动档）：想先审阅 / 改提示词再出片；或角色风格已弄好只补分镜 */}
          <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
              <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>手动档（先审阅 / 改提示词再出片）—</span>
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>拆成
                <input type="number" min={1} max={40} value={sbN} onChange={e => setSbN(e.target.value)}
                  style={{ ...inputStyle, width: 54, height: 28, margin: '0 4px' }} />镜</label>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <button onClick={doAutoFill} disabled={afBusy || sbBusy}
                style={{ height: 34, padding: '0 14px', borderRadius: 8, border: 'none',
                         background: (afBusy || sbBusy) ? 'rgba(255,255,255,0.06)' : '#6366f1',
                         color: (afBusy || sbBusy) ? 'var(--text-muted)' : '#fff', fontSize: 12.5, fontWeight: 600,
                         cursor: (afBusy || sbBusy) ? 'default' : 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {afBusy ? 'AI 分析中…' : '🪄 一键 AI 分析填充'}
              </button>
              <label style={{ fontSize: 12, display: 'inline-flex', gap: 4, alignItems: 'center', color: 'var(--text-muted)' }}>
                <input type="checkbox" checked={afReplace} onChange={e => setAfReplace(e.target.checked)} />替换现有
              </label>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>角色+风格+LoRA+分镜入库（<b>只生成、不出片</b>）</span>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
              <button onClick={doStoryboard} disabled={sbBusy || afBusy}
                style={{ ...miniBtn2, height: 30, padding: '0 12px' }}>
                {sbBusy ? 'AI 拆分镜中…' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon.Wand size={13} />只拆分镜</span>}
              </button>
              <label style={{ fontSize: 12, display: 'inline-flex', gap: 4, alignItems: 'center', color: 'var(--text-muted)' }}>
                <input type="checkbox" checked={sbReplace} onChange={e => setSbReplace(e.target.checked)} />替换现有分镜
              </label>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>角色 / 风格已弄好时，只补分镜表</span>
            </div>
          </div>
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
                <span style={{ fontSize: 11, flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                               color: c.ref_audio_path ? '#34d399' : 'var(--text-muted)' }}
                  title="配音引擎 = CosyVoice2（自托管克隆）。没传参考音=用默认成熟女声；传了参考音=克隆该角色专属音色。edge-tts 基础合成音已弃用。">
                  {c.ref_audio_path ? '🎙 克隆音色 ✓' : '🎙 默认音色 (CosyVoice2)'}
                </span>
                <label title="传一张该角色清晰正脸 → 出片勾「强锁脸(Stand-In)」即用它跨镜锁定这张脸(免训练)。"
                  style={{ ...miniBtn2, cursor: 'pointer', color: c.ref_image_path ? '#34d399' : undefined, whiteSpace: 'nowrap' }}>
                  {c.ref_image_path ? '换参考脸 ✓' : '传参考脸'}
                  <input type="file" accept="image/*" style={{ display: 'none' }}
                    onChange={e => { charFaceUpload(c.id, (e.target.files || [])[0]); e.target.value = '' }} />
                </label>
                <label title="传一段该角色参考音(几秒~30s 清晰真人录音) → 克隆专属音色，全程锁声(对口型镜/旁白镜同源、音色一致)。没起克隆 server 时自动回退预置音。"
                  style={{ ...miniBtn2, cursor: 'pointer', color: c.ref_audio_path ? '#34d399' : undefined, whiteSpace: 'nowrap' }}>
                  {c.ref_audio_path ? '换参考音 ✓' : '传参考音'}
                  <input type="file" accept="audio/*" style={{ display: 'none' }}
                    onChange={e => { charVoiceUpload(c.id, (e.target.files || [])[0]); e.target.value = '' }} />
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
            人物 LoRA 训练 —— 一次训出 high+low 两个 Wan LoRA、出片锁定这个角色（t2v 没首帧，人物一致全靠它）。
            训练目标可选 <b>t2v</b>(文生视频锁脸) 或 <b>i2v</b>(图生视频/尾帧续接锁脸，底模不同)——一镜到底续接用 i2v。
            手动传 20-30 张同脸图开训。<b style={{ color: '#ffb454' }}>务必含 8-10 张脸部特写（脸占大半画面、戴眼镜要拍清）</b>——
            只传全身照的话脸太小、训出来只像体型不像脸（头号坑）。混搭：脸特写 8-10 张 + 半身 5-6 + 全身 4-5。
            <b style={{ color: '#5fe8de' }}>免上传自训·造图</b> 需出图后端 ComfyUI（配 COMFYUI_BASE_URL）。
          </div>
          {/* 本项目已配置的角色 LoRA(t2v/i2v)——ComfyUI 按 workflow 文件名加载,这里读项目级配置 */}
          <div style={{ border: '1px dashed var(--border)', borderRadius: 6, padding: 8, marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <button onClick={checkLoadedLoras} disabled={loraStatusBusy} style={{ ...miniBtn2, cursor: 'pointer' }}>
                {loraStatusBusy ? '查询中…' : '🔄 查看本项目已配置 LoRA'}
              </button>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>核对角色 LoRA(t2v/i2v)挂没挂（训练完成会自动应用到项目）</span>
            </div>
            {loadedLoras && (
              <div style={{ marginTop: 6, fontSize: 12 }}>
                {(loadedLoras.loras || []).length === 0 ? (
                  <div style={{ color: '#fca5a5' }}>⚠ 本项目还没配置角色 LoRA。{loadedLoras.note}</div>
                ) : (
                  <>
                    <div style={{ color: loadedLoras.has_char ? '#34d399' : '#ffb454', marginBottom: 4 }}>
                      {loadedLoras.has_char ? '✅ 已配置角色 LoRA（出片会像你训的人）' : '⚠ 没配置角色 LoRA → 出片不会像你训的人'}
                    </div>
                    {loadedLoras.loras.map((l, i) => (
                      <div key={i} style={{ color: l.exists ? 'var(--text-muted)' : '#fca5a5', fontFamily: 'monospace', fontSize: 11 }}>
                        🧑 {l.kind} · {l.name} · {l.file}{l.exists ? '' : ' ❌文件不存在'}
                      </div>
                    ))}
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
                <select value={trainModeOf(t.id)} onChange={e => setLoraTrainMode(p => ({ ...p, [t.id]: e.target.value }))}
                  title="t2v=文生视频锁脸(默认);i2v=图生视频/尾帧续接锁脸(底模不同,一镜到底续接用这个)"
                  style={{ ...inputStyle, height: 26, width: 'auto' }}>
                  <option value="t2v">训练目标: t2v 文生</option>
                  <option value="i2v">训练目标: i2v 续接</option>
                </select>
                <button onClick={() => loraOp('train', t.id, { lora_mode: trainModeOf(t.id) })} disabled={loraBusy} style={panelBtn(loraBusy)}>开始训练({trainModeOf(t.id)})</button>
                <button onClick={() => toggleLoraLog(t.id)} style={miniBtn2}>{loraLogOpen[t.id] ? '收起日志' : '日志/进度'}</button>
                <button onClick={() => loraDoPreview(t.id)} disabled={loraPrevBusy[t.id]} style={miniBtn2}
                  title="用项目已配置的角色 LoRA 出一条 480p/4步/33帧 短测试片(约 1 分钟)，验证 LoRA 学的人对不对">
                  {loraPrevBusy[t.id] ? '出片中…' : '测试出片'}
                </button>
                <button onClick={async () => { if (await dialog.confirm('清空这个 LoRA 的所有参考图？', { message: '删掉已传的图和旧训练产物（保留触发词设置），用于「干净重训」——避免上一轮旧图/旧标注残留进新训练集导致训出来不像。清空后重新上传即可。', danger: true, confirmText: '清空' })) loraOp('clear_images', t.id) }} disabled={loraBusy}
                  title="重训前清掉旧参考图，避免旧图/旧 caption 残留污染新训练集（训出来不像的头号坑）。清空后重新选角色上传。"
                  style={{ ...miniBtn2, color: '#fca5a5', borderColor: 'rgba(239,68,68,0.4)' }}>清空重传</button>
              </div>
              <div style={{ fontSize: 10.5, color: 'var(--text-dim)', marginTop: 4 }}>
                测试出片：用项目已配置的角色 LoRA（训练完成会自动应用到项目）出片验脸。
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
                  <option value="video">t2v造转身片→训i2v</option>
                </select>
                {bootOf(t.id).mode === 'video' && (
                  <span style={{ fontSize: 10, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}
                    title="用项目已训好的 t2v 角色 LoRA 批量造『转身短视频』当 i2v 训练集→造完自动训 i2v 原生 LoRA(锁脸不漂)。前置:本项目须先有训好的 t2v LoRA。">
                    需先有 t2v LoRA · 造 {bootOf(t.id).count} 段
                  </span>
                )}
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

      {/* 出片流程说明(B.2):讲清 t2v 出片 与 i2v 续接 的关系,避免 4 个入口看着都能点却不知用哪个 */}
      <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 10, padding: '10px 12px',
        border: '1px dashed var(--border)', borderRadius: 8, lineHeight: 1.9 }}>
        🎬 <b style={{ color: 'var(--text-secondary)' }}>出片流程</b>：
        ① 各镜先 <b style={{ color: '#5fe8de' }}>出片(t2v)</b> 文生视频（或下方「批量出片并合成」整集出）
        → ② 要<b style={{ color: '#a5b4fc' }}>跨镜连贯 / 把镜头加长</b>时用 <b style={{ color: '#a5b4fc' }}>i2v 续接</b>（接上一镜尾帧续生成，需先起 i2v server）
        → ③ <b style={{ color: '#5eead4' }}>合成整集</b> 拼成成片。
        <br />首镜想<b style={{ color: '#a5b4fc' }}>锁首帧脸</b>：在镜1点 <b style={{ color: '#a5b4fc' }}>⇄ i2v起头</b> → 传/选一张关键帧 → <b style={{ color: '#a5b4fc' }}>出片(i2v·锁首帧)</b>（首帧脸钉死，不赌 t2v 现生）。
        <br />人物一致靠训好的 Wan 角色 LoRA（在「角色 &amp; LoRA」里训；i2v 出片会自动挂 wan_i2v_lora_*、回退 t2v）。
      </div>

      {/* 区段标题：出片 · 合成（OpenArt 式带强调竖条的小标题）*/}
      <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-secondary)', margin: '4px 0 9px', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ width: 3, height: 13, borderRadius: 2, background: '#00bdb0' }} />出片 · 合成
      </div>
      {/* 批量出片并合成（t2v）：对所有未出片分镜逐镜文生 → 合成整集（模型/分辨率可选）*/}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <button onClick={() => runJob('finish')} disabled={!!busy || !(c.total > 0)}
          style={!(c.total > 0) ? panelBtn(false, true) : {
            height: 38, padding: '0 18px', borderRadius: 9, border: 'none',
            background: busy === 'finish' ? 'rgba(0,189,176,0.7)' : '#00bdb0',
            color: '#04201e', fontSize: 13.5, fontWeight: 700, cursor: 'pointer',
            boxShadow: busy === 'finish' ? 'none' : '0 5px 16px rgba(0,189,176,0.26)',
          }}>
          {busy === 'finish' ? '出片合成中…' : `🎬 批量出片并合成（t2v · ${c.total} 镜）`}
        </button>
        <button onClick={() => runJob('continuation')} disabled={!!busy || !(c.total > 1)}
          title={'续接出片(i2v)：镜1 先用 t2v 出好当链头，镜2+ 用上一镜尾帧续生成 → 跨镜服装/场景/光线/动作连续(纯 t2v 做不到)。前置：配好 ComfyUI(COMFYUI_BASE_URL)，由其 i2v provider 续接。'
            + (provReady('wan2.2') ? '' : '\n⚠ ComfyUI 未就绪（没配/连不上），点了会先弹提示。')}
          style={!(c.total > 1) ? panelBtn(false, true) : {
            height: 34, padding: '0 14px', borderRadius: 8,
            border: provReady('wan2.2') ? '1px solid rgba(129,140,248,0.55)' : '1px solid rgba(234,179,8,0.5)',
            background: busy === 'continuation' ? 'rgba(99,102,241,0.5)' : 'transparent',
            color: provReady('wan2.2') ? '#a5b4fc' : '#eab308', fontSize: 12.5, fontWeight: 600, cursor: busy ? 'default' : 'pointer',
          }}>
          {busy === 'continuation' ? '续接中…' : ('🔗 续接出片(i2v·连贯)' + (provReady('wan2.2') ? '' : ' ⚠'))}
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
        {/* 续接整集去边界帧(A.2):i2v 续接里镜N首帧=镜N-1尾帧,直接拼有1帧卡顿;续接过会自动勾上 */}
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, alignSelf: 'center',
                        color: dedupBoundary ? '#5eead4' : 'var(--text-muted)', cursor: busy ? 'default' : 'pointer' }}
          title="续接整集去边界帧：i2v 续接里每镜首帧=上一镜尾帧，直接拼会有 1 帧卡顿；勾上合成时丢掉重复帧。各镜独立出片不用勾(用了 i2v 续接会自动勾)。">
          <input type="checkbox" checked={dedupBoundary} disabled={!!busy} onChange={e => setDedupBoundary(e.target.checked)} />
          续接去边界帧
        </label>
        {/* t2v：出片后端由 T2V_PROVIDER(comfyui-t2v) 路由、不看这个选择 → 移除误导的 i2v 模型下拉(Wan2.2-I2V/LTX)。
            出片参数(帧数/帧率/步数/seed)在下方「更多参数」调,对 t2v 生效。 */}
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
          title="出片时长。Wan 帧数须为 4n+1，这里已按 16fps 换算好；想要更长就选更大的。"
          style={{ ...inputStyle, width: 'auto', height: 32 }}>
          <option value={81}>时长 ≈ 5 秒</option>
          <option value={129}>时长 ≈ 8 秒</option>
          <option value={161}>时长 ≈ 10 秒</option>
          <option value={241}>时长 ≈ 15 秒</option>
        </select>
        {/* B.3:把最影响成片的两个开关从折叠/别页提到显眼处 —— 强锁脸 + 接续段数 */}
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, alignSelf: 'center',
                        color: lockFace ? '#5fe8de' : 'var(--text-muted)', cursor: busy ? 'default' : 'pointer' }}
          title="强锁脸(Stand-In)：给传过参考脸的角色镜「一张脸硬锁身份」(跨镜更稳、免训练)。需先在 Colab 跑「§Stand-In」起 server;没起会自动回退普通出片。">
          <input type="checkbox" checked={lockFace} disabled={!!busy} onChange={e => setLockFace(e.target.checked)} />
          强锁脸{lockFace && !provReady('standin-t2v') ? '（⚠server未就绪）' : ''}
        </label>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, alignSelf: 'center', color: 'var(--text-muted)' }}
          title="接续段数：每镜尾帧接续生成几段拼成更长镜头(段越多越长且连贯)。1=单段。也可在单镜卡片里单独覆盖。">
          接续段数
          <input type="number" min={1} max={20} value={segments} disabled={!!busy}
            onChange={e => setSegments(Math.max(1, Number(e.target.value) || 1))}
            style={{ ...inputStyle, width: 56, height: 28 }} />
        </label>
        {/* 画质档(步数)从主行移除:与「更多参数·采样步数」重复,且本机 server 多忽略 per-request 步数(画质实际在 §5d 配)——别再误导。 */}
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
              出片参数 · 帧数 / 帧率 / 采样步数 / seed（t2v 走 ComfyUI；帧数须 4n+1，如 81≈5s、121≈7.5s、161≈10s）
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
            {/* 强锁脸已上提到上方出片控制行(B.3),此处不再重复 */}
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

      {/* 区段标题：分镜（OpenArt 式带强调竖条的小标题；有分镜才显示）*/}
      {(proj?.scenes || []).length > 0 && (
        <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-secondary)', margin: '6px 0 10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 3, height: 13, borderRadius: 2, background: '#6366f1' }} />分镜
          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>（{(proj?.scenes || []).length} 镜）</span>
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
                        {sb === 'append' ? '续片中' : sb === 'undo' ? '撤销中' : sb === 'keyframe' ? '传关键帧中' : '出片中'} {fmtElapsed(s.scene_id)} · 停止
                      </button>
                    )
                  }
                  if (s.video) return null   // 已出片 → 操作都在下方成片区
                  const disabled = !!busy
                  const sec = estSec != null ? estSec : null
                  // 链头镜(首镜)可选 i2v 起头:从一张关键帧(上传/出图选中)i2v、首帧脸钉死,不赌 t2v 现生。
                  const isHead = (proj?.scenes || [])[0]?.scene_id === s.scene_id
                  if (isHead && firstFrameMode[s.scene_id] === 'i2v') {
                    return (
                      <>
                        {s.selected ? (
                          <button onClick={() => runScene('render', s.scene_id)} disabled={disabled}
                            title="从已选关键帧 i2v 出首镜:首帧脸钉死、不赌 t2v 现生(走 ComfyUI i2v,需 COMFYUI_BASE_URL)" style={miniAct(false, true)}>
                            {`出片(i2v·锁首帧)${sec != null ? ` ≈${sec.toFixed(0)}s` : ''}`}
                          </button>
                        ) : (
                          <label title="传一张关键帧当首帧(或用上方「出图」出几张、点选一张:角色配了参考脸即 PuLID 锁脸出图)→ i2v 从它动起来"
                            style={{ fontSize: 11, color: 'rgba(165,180,252,0.95)', cursor: disabled ? 'default' : 'pointer',
                                     border: '1px solid rgba(129,140,248,0.45)', borderRadius: 6, padding: '2px 8px', opacity: disabled ? 0.5 : 1 }}>
                            上传关键帧
                            <input type="file" accept="image/*" style={{ display: 'none' }} disabled={disabled}
                              onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) uploadKeyframe(s.scene_id, f) }} />
                          </label>
                        )}
                        <button onClick={() => setFirstFrameMode(p => ({ ...p, [s.scene_id]: 't2v' }))} disabled={disabled}
                          title="改回 t2v 文生起头" style={miniAct(false)}>⇄ t2v</button>
                      </>
                    )
                  }
                  // 纯 t2v：分镜文本直接出片(无出图/选图/对口型)。想长镜头先出 1 段、再用下方「再续一段」加长。
                  return (
                    <>
                      <button onClick={() => runScene('render', s.scene_id)} disabled={disabled}
                        title="文本直接生成这镜视频(t2v)" style={miniAct(false, true)}>
                        {`出片(t2v)${sec != null ? ` ≈${sec.toFixed(0)}s` : ''}`}
                      </button>
                      {isHead && (
                        <button onClick={() => setFirstFrameMode(p => ({ ...p, [s.scene_id]: 'i2v' }))} disabled={disabled}
                          title="改用关键帧 i2v 起头:首镜从一张关键帧动起来、首帧脸钉死(比 t2v 现生更可控,适合锁脸)" style={miniAct(false)}>
                          ⇄ i2v起头
                        </button>
                      )}
                    </>
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

              {/* AI 每镜决策：拆镜时 AI 给这镜定的 时长/续接/对口型/音效 —— 让「全自动决策」可见可核对（只在 AI 设了才显示）*/}
              {(() => {
                const marks = []
                if (s.seconds > 0) marks.push(['⏱ ' + s.seconds + 's', 'rgba(148,163,184,1)', 'rgba(148,163,184,0.32)', 'AI 给这镜定的时长约 ' + s.seconds + ' 秒（0=回退全局帧数）'])
                if (s.continue_prev) marks.push(['↳ 续接', 'rgba(165,180,252,1)', 'rgba(129,140,248,0.4)', 'AI 判定这镜续接上一镜尾帧（i2v 连贯，不是重新出）'])
                if (s.lipsync) marks.push(['💬 对口型', 'rgba(110,231,183,1)', 'rgba(52,211,153,0.4)', 'AI 判定这镜是正脸说话镜，出片后自动对口型（LatentSync）'])
                if (s.sfx) marks.push(['🔊 音效', 'rgba(252,211,77,1)', 'rgba(251,191,36,0.4)', 'AI 判定这镜需要环境/动作音效（MMAudio 按画面同步生成）'])
                if (!marks.length) return null
                return (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: -2, marginBottom: 10 }}>
                    {marks.map(([t, c, bd, ti]) => (
                      <span key={t} title={ti} style={{ fontSize: 10.5, lineHeight: 1, padding: '3px 8px', borderRadius: 6,
                        display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 600, color: c,
                        background: 'rgba(255,255,255,0.04)', border: '1px solid ' + bd }}>{t}</span>
                    ))}
                  </div>
                )
              })()}

              {s.video ? (
                <div>
                  {/* key 绑 url（含 &v=mtime）：追加后文件变了，强制 <video> 重建、不吃旧缓存 */}
                  <video key={s.video.url} src={fileUrl(s.video.url)} controls
                         style={{ width: '100%', maxHeight: 300, borderRadius: 8, display: 'block' }} />
                  {upscaleRow(s.scene_id, 'scene', s.scene_id, '')}
                  {faceswapRow(s.scene_id, 'scene', s.scene_id, '')}
                  {/* 这镜成片后的操作行:删除重出 / i2v 续接(+5s,接本镜尾帧续生成,可反复加、能撤销)。
                      i2v 续接是刻意保留的功能(跨镜/加长连贯),需先在 Colab 起 i2v server;另:t2v 单镜也可把上方时长调大一次性出更长。 */}
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
                    <input value={appendNarr[s.scene_id] || ''}
                      onChange={e => setAppendNarr(p => ({ ...p, [s.scene_id]: e.target.value }))}
                      placeholder="台词(配音，留空=不配)"
                      disabled={busy || !!sceneBusy[s.scene_id]}
                      title="续接段台词 → 用该镜角色的克隆音色+情感配音，音频多长片多长，自动叠回成片。留空=只续画面不配音。"
                      style={{ flex: '1 1 150px', minWidth: 110, height: 26, padding: '0 10px', borderRadius: 6,
                               border: '1px solid rgba(52,211,153,0.45)', background: 'rgba(16,185,129,0.08)',
                               color: '#e5e7eb', fontSize: 11.5, outline: 'none' }} />
                    <select value={appendEmo[s.scene_id] || ''}
                      onChange={e => setAppendEmo(p => ({ ...p, [s.scene_id]: e.target.value }))}
                      disabled={busy || !!sceneBusy[s.scene_id]}
                      title="续接段台词的情感(克隆引擎 IndexTTS2 支持)"
                      style={{ height: 26, borderRadius: 6, border: '1px solid rgba(52,211,153,0.45)',
                               background: 'rgba(16,185,129,0.08)', color: '#e5e7eb', fontSize: 11.5, outline: 'none' }}>
                      <option value="">情感:中性</option>
                      <option value="happy">开心</option>
                      <option value="angry">愤怒</option>
                      <option value="sad">悲伤</option>
                      <option value="afraid">害怕</option>
                      <option value="surprised">惊讶</option>
                      <option value="calm">平静</option>
                    </select>
                    <button onClick={() => runScene('append', s.scene_id)} disabled={busy || !!sceneBusy[s.scene_id]}
                      title="续接：从这镜【末帧】i2v 续生成一段(保人物/场景连贯)，追加到后面。填了台词会用克隆音色+情感配音并叠回。可反复加、能撤销。需 ComfyUI i2v server。"
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
                    <button onClick={() => runLipsync(s.scene_id)} disabled={busy || !!sceneBusy[s.scene_id]}
                      title="口型同步：把这镜成片按音轨(续接段配的情感语音)/旁白做 LatentSync 缝嘴，嘴型对到台词(只对正脸特写有效)。产物为独立新文件、原片保留。需起 LatentSync server(8192)。"
                      style={{
                        height: 26, padding: '0 12px', borderRadius: 6, border: '1px solid rgba(34,197,94,0.5)',
                        background: sceneBusy[s.scene_id] === 'lipsync' ? 'rgba(34,197,94,0.4)' : 'rgba(34,197,94,0.14)',
                        color: '#86efac', fontSize: 11.5, cursor: (busy || !!sceneBusy[s.scene_id]) ? 'default' : 'pointer',
                      }}>{sceneBusy[s.scene_id] === 'lipsync' ? '缝嘴中…' : '👄 口型同步'}</button>
                    <button onClick={() => runSfx(s.scene_id)} disabled={busy || !!sceneBusy[s.scene_id]}
                      title="生成音效：把这镜成片喂给视频→音频模型(Foley/MMAudio)，生成与画面同步的环境/动作音效(如篮球真触地那帧才响)，叠在已有人声之下(人声更响)。产物为独立新文件、原片保留。需起 Foley server(8194)。"
                      style={{
                        height: 26, padding: '0 12px', borderRadius: 6, border: '1px solid rgba(245,158,11,0.5)',
                        background: sceneBusy[s.scene_id] === 'sfx' ? 'rgba(245,158,11,0.4)' : 'rgba(245,158,11,0.14)',
                        color: '#fcd34d', fontSize: 11.5, cursor: (busy || !!sceneBusy[s.scene_id]) ? 'default' : 'pointer',
                      }}>{sceneBusy[s.scene_id] === 'sfx' ? '配音效中…' : '🔊 生成音效'}</button>
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

// panelBtn / miniAct / miniBtn 已抽到 ./production/uiStyles（顶部 import）
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
// miniBtn2 / inputStyle 已抽到 ./production/uiStyles（顶部 import）

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
