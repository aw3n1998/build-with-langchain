/* 移动端短剧工作台主体 —— 4 个 Tab 全部接真数据。
   数据源 getProject;动作走 api.js(与桌面 ProductionPanel 同款 payload),保证行为一致。 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getProject, projectStyle, autoStoryboard, autoFill, batchGenerate, batchFinish,
  sceneGenerate, sceneRender, pipelineSelect, deleteCandidate, deleteSceneVideo,
  uploadCandidate, updateScenePrompts, fileUrl, loraCreate, loraAction, loraUploadImage,
  streamJobEvents,
} from '../../api'
import {
  MI, Button, Card, StatChip, StatusBadge, Switch, CandidateImage, SceneCard,
  GpuLogBar, TabRail, Field, fieldStyle, statusOf,
} from './ui'

const TABS = [
  { id: 'script', label: '脚本' }, { id: 'characters', label: '角色&LoRA' },
  { id: 'storyboard', label: '分镜制作' }, { id: 'export', label: '导出' },
]

export default function MobileStudio({ projectId, workspace, sessionId }) {
  const [tab, setTab] = useState('storyboard')
  const [proj, setProj] = useState(null)
  const [style, setStyle] = useState({})
  const [progress, setProgress] = useState('')
  const [busy, setBusy] = useState(false)
  const [logs, setLogs] = useState([])
  const [gpu, setGpu] = useState('idle')

  const load = useCallback(async () => {
    try { setProj(await getProject(projectId, workspace)) } catch (e) { setProgress(String(e.message || e)) }
  }, [projectId, workspace])
  const loadStyle = useCallback(async () => {
    try { const r = await projectStyle(projectId, {}, workspace); setStyle(r.style || {}) } catch { /* ignore */ }
  }, [projectId, workspace])
  useEffect(() => { load(); loadStyle() }, [load, loadStyle])

  // 统一任务跑法:提交 → 跟流(收日志)→ 完成后刷新
  const runJob = useCallback(async (submit, kind = 'drawing') => {
    if (busy) return
    setBusy(true); setLogs([]); setGpu(kind)
    let errored = false
    try {
      const jobId = await submit()
      for await (const ev of streamJobEvents(jobId)) {
        if (ev.type === 'log' && ev.line) setLogs(l => [...l.slice(-40), { t: ev.line }])
        else if (ev.type === 'batch_progress' && ev.label) setLogs(l => [...l.slice(-40), { t: ev.label, tone: 'teal-bright' }])
        else if (ev.type === 'error') { errored = true; setLogs(l => [...l, { t: 'ERROR ' + (ev.content || ''), tone: 'red' }]) }
        if (ev.type === 'done' || ev.type === 'error') break
      }
    } catch (e) { errored = true }
    finally { setBusy(false); setGpu(errored ? 'error' : 'done'); await load() }
  }, [busy, load])

  const genPayload = (sid) => ({ scene_id: sid, workspace, session_id: sessionId, n: 0, width: 0, height: 0,
    image_model: '', img_steps: 0, img_guidance: -1, img_seed: -1, img_offload: '' })
  const renderPayload = (sid, lipsync) => ({ scene_id: sid, workspace, session_id: sessionId, model: '',
    segments: 1, size: '', video_params: {}, motion_prompts: [], lipsync: !!lipsync })

  const counts = proj?.counts || { total: 0, with_candidates: 0, selected: 0, done: 0 }

  return (
    <div>
      {/* 统计行 */}
      <div className="no-scrollbar" style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 12 }}>
        <StatChip label="总数" value={counts.total} />
        <StatChip label="已出图" value={counts.with_candidates} tone="yellow" />
        <StatChip label="已选" value={counts.selected} tone="purple" />
        <StatChip label="已出片" value={counts.done} tone="green" />
      </div>
      <div style={{ marginBottom: 14 }}><TabRail tabs={TABS} value={tab} onChange={setTab} /></div>

      {progress && <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', background: 'var(--surface-sunken)',
        border: '1px solid var(--border)', borderRadius: 'var(--r-btn)', padding: '8px 12px', marginBottom: 12 }}>{progress}</div>}

      {tab === 'storyboard' && <Storyboard proj={proj} busy={busy} runJob={runJob} load={load}
        genPayload={genPayload} renderPayload={renderPayload} workspace={workspace} projectId={projectId}
        gpu={gpu} logs={logs} setProgress={setProgress} />}
      {tab === 'script' && <ScriptTab projectId={projectId} workspace={workspace} proj={proj}
        style={style} setStyle={setStyle} load={load} loadStyle={loadStyle} setProgress={setProgress} runJob={runJob} />}
      {tab === 'characters' && <CharactersTab proj={proj} projectId={projectId} workspace={workspace} load={load} setProgress={setProgress} />}
      {tab === 'export' && <ExportTab proj={proj} />}
    </div>
  )
}

/* ── 分镜制作 ── */
function Storyboard({ proj, busy, runJob, load, genPayload, renderPayload, workspace, projectId, gpu, logs, setProgress }) {
  const scenes = proj?.scenes || []
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card pad={12} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <Button variant="purple" full disabled={busy} icon={<MI name="image" size={16} />}
          onClick={() => runJob(() => batchGenerate({ project_id: projectId, workspace }), 'drawing')}>一键全部出图</Button>
        <div style={{ height: 1, background: 'var(--border)' }} />
        <Button variant="teal" full disabled={busy} icon={<MI name="film" size={16} color="#04221f" />}
          onClick={() => runJob(() => batchFinish({ project_id: projectId, workspace }), 'rendering')}>一键出片并合成 · 已选 {proj?.counts?.selected ?? 0}</Button>
      </Card>

      {scenes.length === 0 && <Card style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: 13 }}>还没有分镜。去「脚本」Tab 粘小说,一键拆分镜。</Card>}

      {scenes.map(s => {
        const st = statusOf(s)
        return (
          <SceneCard key={s.scene_id} index={s.scene_number} title={s.title || '(无题)'} status={st}>
            {st === 'done' && s.video && (
              <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                <video src={fileUrl(s.video.url)} controls playsInline
                  style={{ width: 96, aspectRatio: '9/16', borderRadius: 8, background: '#000', objectFit: 'cover' }} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>{s.video.name}</span>
                  <Button variant="neutral" size="sm" disabled={busy} icon={<MI name="rotate-cw" size={14} />}
                    onClick={async () => { try { await deleteSceneVideo(s.scene_id, workspace); await load() } catch (e) { setProgress(String(e.message || e)) } }}>删除重出</Button>
                </div>
              </div>
            )}
            {st === 'review' && (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  {(s.candidates || []).map(c => (
                    <CandidateImage key={c.assetId} src={fileUrl(c.url)} selected={c.selected}
                      onClick={async () => { try { await pipelineSelect(s.scene_id, c.assetId, workspace); await load() } catch (e) { setProgress(String(e.message || e)) } }} />
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                  <Button variant="neutral" size="sm" disabled={busy} icon={<MI name="rotate-cw" size={14} />}
                    onClick={() => runJob(() => sceneGenerate(genPayload(s.scene_id)), 'drawing')}>重出图</Button>
                  {s.selected && (
                    <Button variant="teal" size="sm" disabled={busy} icon={<MI name="film" size={14} color="#04221f" />}
                      onClick={() => runJob(() => sceneRender(renderPayload(s.scene_id, s.lipsync)), 'rendering')}>出片</Button>
                  )}
                </div>
              </div>
            )}
            {st === 'drawing' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {[0, 1, 2, 3].map(i => (
                  <div key={i} style={{ aspectRatio: '3/4', borderRadius: 8, background: 'var(--surface-sunken)', boxShadow: 'inset 0 0 0 1px var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <span style={{ width: 18, height: 18, borderRadius: '50%', border: '2px solid var(--yellow)', borderTopColor: 'transparent', animation: 'mirageSpin .7s linear infinite' }} />
                  </div>
                ))}
              </div>
            )}
            {st === 'pending' && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-secondary)' }}>
                  <Switch checked={!!s.lipsync} onChange={v => updateScenePrompts(s.scene_id, { lipsync: v }, workspace).then(load).catch(() => {})} /> 对口型
                </label>
                <Button variant="purple" size="sm" disabled={busy} icon={<MI name="image" size={15} />}
                  onClick={() => runJob(() => sceneGenerate(genPayload(s.scene_id)), 'drawing')}>出图</Button>
              </div>
            )}
            {st === 'failed' && (
              <Button variant="purple" size="sm" disabled={busy} icon={<MI name="rotate-cw" size={14} />}
                onClick={() => runJob(() => sceneGenerate(genPayload(s.scene_id)), 'drawing')}>重试出图</Button>
            )}
          </SceneCard>
        )
      })}

      <GpuLogBar state={busy ? gpu : (gpu === 'idle' ? 'idle' : gpu)} lines={logs} defaultOpen={busy} />
    </div>
  )
}

/* ── 脚本 ── */
function ScriptTab({ projectId, workspace, proj, style, setStyle, load, loadStyle, setProgress, runJob }) {
  const [novel, setNovel] = useState('')
  const [n, setN] = useState(8)
  const [busy, setBusy] = useState(false)
  const sf = (k) => (e) => setStyle(s => ({ ...(s || {}), [k]: e.target.value }))
  const doAuto = async (fn, label) => {
    if (!novel.trim()) { setProgress('先粘一段小说/剧情文本'); return }
    setBusy(true); setProgress(label + '中…')
    try { const r = await fn(); setProgress('完成:' + JSON.stringify(r).slice(0, 120)); await load(); await loadStyle() }
    catch (e) { setProgress(label + '失败:' + String(e.message || e)) }
    finally { setBusy(false) }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card>
        <Field label="小说原文">
          <textarea value={novel} onChange={e => setNovel(e.target.value)} placeholder="粘贴小说/剧情文本…"
            style={{ ...fieldStyle, minHeight: 120, resize: 'none', lineHeight: 1.6, fontFamily: 'var(--font-mono)', fontSize: 13 }} />
        </Field>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>拆成</span>
          <input type="number" value={n} onChange={e => setN(e.target.value)} style={{ ...fieldStyle, width: 64, padding: '8px 10px' }} />
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>镜</span>
          <Button variant="primary" size="sm" disabled={busy} style={{ marginLeft: 'auto' }}
            onClick={() => doAuto(() => autoStoryboard(projectId, novel, Number(n) || 8, false, workspace), '拆分镜')}>拆分镜</Button>
        </div>
        <button disabled={busy} onClick={() => doAuto(() => autoFill(projectId, novel, Number(n) || 8, false, workspace), '一键 AI 分析')}
          style={{ marginTop: 10, width: '100%', height: 44, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            background: 'var(--accent-soft)', border: '1px solid var(--accent-border)', borderRadius: 'var(--r-btn)', color: 'var(--accent)',
            fontSize: 14, fontWeight: 600, fontFamily: 'inherit', cursor: busy ? 'not-allowed' : 'pointer', opacity: busy ? 0.5 : 1 }}>
          <MI name="wand" size={16} /> 一键 AI 分析小说
        </button>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>自动填 角色 / 风格 / LoRA / 分镜</div>
      </Card>

      <Card>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>本集风格</div>
        <Field label="style_prompt"><input value={style?.style_prompt || ''} onChange={sf('style_prompt')} style={fieldStyle} /></Field>
        <div style={{ display: 'flex', gap: 10 }}>
          <Field label="触发词"><input value={style?.trigger_word || ''} onChange={sf('trigger_word')} style={fieldStyle} /></Field>
          <Field label="默认尺寸"><input value={style?.size || ''} onChange={sf('size')} placeholder="768x1024" style={fieldStyle} /></Field>
        </div>
        <Field label="FLUX LoRA 路径"><input value={style?.lora || ''} onChange={sf('lora')} style={{ ...fieldStyle, fontFamily: 'var(--font-mono)', fontSize: 12 }} /></Field>
        <Field label="负向词"><input value={style?.negative_prompt || ''} onChange={sf('negative_prompt')} style={fieldStyle} /></Field>
        <Button variant="primary" full disabled={busy} style={{ marginTop: 4 }}
          onClick={async () => { setBusy(true); try { const r = await projectStyle(projectId, style || {}, workspace); setStyle(r.style); setProgress('本集风格已保存') } catch (e) { setProgress('保存失败:' + String(e.message || e)) } finally { setBusy(false) } }}>保存本集风格</Button>
      </Card>
    </div>
  )
}

/* ── 角色 & LoRA ── */
function CharactersTab({ proj, projectId, workspace, load, setProgress }) {
  const chars = proj?.characters || []
  const loras = proj?.lora_trainings || []
  const [busy, setBusy] = useState(false)
  const op = async (fn) => { setBusy(true); try { await fn(); await load() } catch (e) { setProgress(String(e.message || e)) } finally { setBusy(false) } }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>角色圣经</div>
      {chars.length === 0 && <Card style={{ fontSize: 13, color: 'var(--text-muted)' }}>还没有角色。可在「脚本」一键 AI 分析自动抽取,或用 AI 助手添加。</Card>}
      {chars.map(c => (
        <Card key={c.id || c.name} pad={12}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <div style={{ width: 36, height: 36, borderRadius: 'var(--r-btn)', background: 'var(--accent-soft)', color: 'var(--accent)',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700 }}>{(c.name || '?')[0]}</div>
            <span style={{ fontSize: 16, fontWeight: 600 }}>{c.name}</span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{c.look || c.appearance || ''}</div>
          {c.voice && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>音色:{c.voice}</div>}
        </Card>
      ))}

      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginTop: 4 }}>人物 LoRA 训练</div>
      {loras.map(l => (
        <Card key={l.id} pad={12}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{l.name}</span>
            <StatusBadge status={l.status === 'COMPLETED' ? 'done' : 'drawing'} label={`${l.count ?? l.num_images ?? 0}张 · ${l.status}`} />
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <label style={{ display: 'inline-flex' }}>
              <input type="file" accept="image/*" multiple style={{ display: 'none' }}
                onChange={e => op(async () => { for (const f of e.target.files) await loraUploadImage(l.id, f, workspace) })} />
              <Button variant="neutral" size="sm" disabled={busy} icon={<MI name="upload" size={14} />}>传参考图</Button>
            </label>
            <Button variant="primary" size="sm" disabled={busy} icon={<MI name="play" size={14} fill="#fff" />}
              onClick={() => op(() => loraAction(projectId, 'train', l.id, workspace))}>开始训练</Button>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8, fontFamily: 'var(--font-mono)' }}>后端待接入 Colab</div>
        </Card>
      ))}
      <Button variant="ghost" full disabled={busy} icon={<MI name="plus" size={16} />}
        onClick={() => op(() => loraCreate(projectId, '新角色LoRA', '', null, workspace))}>新建 LoRA 训练</Button>
    </div>
  )
}

/* ── 导出 ── */
function ExportTab({ proj }) {
  const ep = proj?.episode
  const presets = [['抖音', '1080×1920'], ['视频号', '1080×1920'], ['快手', '1080×1920'], ['YouTube Shorts', '1080×1920']]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {ep ? (
        <video src={fileUrl(ep.url)} controls playsInline
          style={{ width: '100%', aspectRatio: '9/16', maxHeight: 360, margin: '0 auto', borderRadius: 'var(--r-card)', background: '#000', objectFit: 'contain' }} />
      ) : (
        <Card style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, padding: '40px 16px' }}>整集还没合成。去「分镜制作」点「一键出片并合成」。</Card>
      )}
      {ep && (
        <a href={fileUrl(ep.url)} download style={{ textDecoration: 'none' }}>
          <Button variant="primary" full icon={<MI name="download" size={16} />}>下载整集 mp4</Button>
        </a>
      )}
      <Card>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>平台导出预设</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>预留</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {presets.map(([name, size]) => (
            <div key={name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px',
              background: 'var(--surface-sunken)', border: '1px solid var(--border)', borderRadius: 'var(--r-btn)' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><MI name="smartphone" size={16} color="var(--text-secondary)" /><span style={{ fontSize: 14 }}>{name}</span></span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>{size}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
