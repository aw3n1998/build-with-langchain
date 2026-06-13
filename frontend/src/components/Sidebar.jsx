import { useState } from 'react'
import { ingestFile, ingestText, getStatus } from '../api'

export default function Sidebar({ ragStatus, onStatusChange }) {
  const [tab, setTab] = useState('file')      // 'file' | 'text'
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null) // { ok: bool, msg: string }

  // 文件上传表单
  const [fileProjectId, setFileProjectId] = useState('default')

  // 文本导入表单
  const [textContent, setTextContent]     = useState('')
  const [sourceName, setSourceName]       = useState('')
  const [textProjectId, setTextProjectId] = useState('default')

  const refreshStatus = async () => {
    try { onStatusChange(await getStatus()) } catch {}
  }

  const handleFileChange = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setBusy(true)
    setFeedback(null)
    try {
      const res = await ingestFile(file, fileProjectId)
      setFeedback({ ok: res.success, msg: res.message })
      await refreshStatus()
    } catch (err) {
      setFeedback({ ok: false, msg: `上传失败：${err.message}` })
    } finally {
      setBusy(false)
      e.target.value = ''     // 允许重复选同一个文件
    }
  }

  const handleTextImport = async () => {
    if (!textContent.trim()) return
    setBusy(true)
    setFeedback(null)
    try {
      const res = await ingestText(textContent, sourceName || 'inline', textProjectId)
      setFeedback({ ok: res.success, msg: res.message })
      if (res.success) setTextContent('')
      await refreshStatus()
    } catch (err) {
      setFeedback({ ok: false, msg: `导入失败：${err.message}` })
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="w-72 flex-shrink-0 bg-slate-800 border-r border-slate-700 flex flex-col">
      {/* ── Logo ── */}
      <div className="px-5 py-5 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <div>
            <h1 className="text-base font-bold text-white leading-tight">Mirage</h1>
            <p className="text-xs text-slate-500">蜃景 · AI 小说转短剧引擎</p>
          </div>
        </div>
      </div>

      {/* ── RAG 状态 ── */}
      <div className="px-5 py-4 border-b border-slate-700">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">
          知识库状态
        </h2>
        <div className="space-y-2">
          {/* 连接状态 */}
          <div className="flex items-center gap-2">
            <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${
              ragStatus.rag_connected ? 'bg-emerald-400' : 'bg-red-400'
            }`} />
            <span className="text-sm text-slate-300">
              {ragStatus.rag_connected ? 'Milvus 已连接' : 'Milvus 未连接'}
            </span>
          </div>

          {ragStatus.rag_connected && (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <span>{ragStatus.chunk_count} 个 chunk</span>
            </div>
          )}

          {ragStatus.model && (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <span className="font-mono text-xs truncate">{ragStatus.model}</span>
            </div>
          )}
        </div>
      </div>

      {/* ── 导入面板 ── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-5 pt-4 pb-2">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">
            导入知识库
          </h2>

          {/* Tab 切换 */}
          <div className="flex bg-slate-700/60 rounded-lg p-0.5 gap-0.5">
            {['file', 'text'].map(t => (
              <button
                key={t}
                onClick={() => { setTab(t); setFeedback(null) }}
                className={`flex-1 text-xs py-1.5 rounded-md font-medium transition-all ${
                  tab === t
                    ? 'bg-slate-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {t === 'file' ? '上传文件' : '导入文本'}
              </button>
            ))}
          </div>
        </div>

        {/* 滚动区 */}
        <div className="flex-1 overflow-y-auto px-5 pb-4">
          {tab === 'file' ? (
            // ── 文件上传 ──
            <div className="space-y-3 mt-3">
              <div>
                <label className="text-xs text-slate-400 block mb-1">项目 ID</label>
                <input
                  type="text"
                  value={fileProjectId}
                  onChange={e => setFileProjectId(e.target.value)}
                  placeholder="default"
                  className="w-full text-sm bg-slate-700 text-slate-200 placeholder-slate-500
                             border border-slate-600 rounded-lg px-3 py-2
                             focus:outline-none focus:border-blue-500 transition-colors"
                />
              </div>

              {/* 拖拽 / 点击上传区 */}
              <label
                className={`flex flex-col items-center justify-center w-full h-28
                            border-2 border-dashed rounded-xl cursor-pointer transition-all
                            ${busy
                              ? 'border-slate-600 text-slate-600 cursor-not-allowed'
                              : 'border-slate-600 hover:border-blue-500 hover:bg-blue-500/5 text-slate-400 hover:text-slate-200'
                            }`}
              >
                <span className="text-xs mb-1 text-slate-500">{busy ? '上传中' : '选择文件'}</span>
                <span className="text-xs font-medium">
                  {busy ? '上传中...' : '点击或拖拽文件到此处'}
                </span>
                <span className="text-xs text-slate-500 mt-0.5">.txt · .pdf · .docx</span>
                <input
                  type="file"
                  accept=".txt,.pdf,.docx"
                  className="hidden"
                  onChange={handleFileChange}
                  disabled={busy}
                />
              </label>
            </div>
          ) : (
            // ── 文本导入 ──
            <div className="space-y-3 mt-3">
              <div>
                <label className="text-xs text-slate-400 block mb-1">来源名称</label>
                <input
                  type="text"
                  value={sourceName}
                  onChange={e => setSourceName(e.target.value)}
                  placeholder="inline"
                  className="w-full text-sm bg-slate-700 text-slate-200 placeholder-slate-500
                             border border-slate-600 rounded-lg px-3 py-2
                             focus:outline-none focus:border-blue-500 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 block mb-1">项目 ID</label>
                <input
                  type="text"
                  value={textProjectId}
                  onChange={e => setTextProjectId(e.target.value)}
                  placeholder="default"
                  className="w-full text-sm bg-slate-700 text-slate-200 placeholder-slate-500
                             border border-slate-600 rounded-lg px-3 py-2
                             focus:outline-none focus:border-blue-500 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 block mb-1">文本内容</label>
                <textarea
                  value={textContent}
                  onChange={e => setTextContent(e.target.value)}
                  rows={6}
                  placeholder="粘贴要导入的文本内容..."
                  className="w-full text-sm bg-slate-700 text-slate-200 placeholder-slate-500
                             border border-slate-600 rounded-lg px-3 py-2 resize-none
                             focus:outline-none focus:border-blue-500 transition-colors"
                />
              </div>
              <button
                onClick={handleTextImport}
                disabled={busy || !textContent.trim()}
                className="w-full py-2 text-sm font-medium rounded-lg transition-all
                           bg-blue-600 hover:bg-blue-500 text-white
                           disabled:bg-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed"
              >
                {busy ? '导入中...' : '导入文本'}
              </button>
            </div>
          )}

          {/* 操作反馈 */}
          {feedback && (
            <div className={`mt-3 text-xs rounded-lg px-3 py-2.5 leading-relaxed ${
              feedback.ok
                ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-800'
                : 'bg-red-900/40 text-red-300 border border-red-800'
            }`}>
              {feedback.msg}
            </div>
          )}
        </div>
      </div>

      {/* ── 底部帮助提示 ── */}
      <div className="px-5 py-3 border-t border-slate-700">
        <p className="text-xs text-slate-600 leading-relaxed">
          导入文档后，直接在对话框问问题，Agent 会自动检索知识库。
        </p>
      </div>
    </aside>
  )
}
