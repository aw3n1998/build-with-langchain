// 制作面板共用的样式常量(从 MessageBubble.jsx 抽出,供 ProductionPanel / ParamCards 等复用)。
export const panelBtn = (active, disabled) => ({
  height: 32, padding: '0 14px', borderRadius: 8, border: 'none',
  background: disabled ? 'rgba(255,255,255,0.06)' : active ? '#5254cc' : '#6366f1',
  color: disabled ? 'var(--text-muted)' : '#fff',
  fontSize: 12.5, fontWeight: 600, cursor: disabled ? 'default' : 'pointer',
})
// 单镜操作小按钮（出图=紫、出视频=青）
export const miniAct = (active, teal) => ({
  height: 22, padding: '0 9px', borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: 'pointer',
  border: `1px solid ${teal ? 'rgba(0,189,176,0.4)' : 'rgba(99,102,241,0.4)'}`,
  background: active ? (teal ? 'rgba(0,189,176,0.3)' : 'rgba(99,102,241,0.3)')
    : (teal ? 'rgba(0,189,176,0.14)' : 'rgba(99,102,241,0.14)'),
  color: teal ? 'rgba(94,234,212,1)' : 'rgba(190,192,255,1)',
})
export const miniBtn = {
  width: 24, height: 24, borderRadius: 6, border: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.05)', color: 'var(--text-sec)', cursor: 'pointer', fontSize: 13,
}
// 多字小按钮（本集风格 / 新增分镜等）：自动宽度 + 不换行，避免文字竖排
export const miniBtn2 = {
  height: 24, padding: '0 9px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.05)', color: 'var(--text-sec)', cursor: 'pointer',
  fontSize: 12, whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', gap: 4,
}
export const inputStyle = {
  height: 30, padding: '0 8px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.85)', fontSize: 12,
  width: '100%', colorScheme: 'dark',
}
