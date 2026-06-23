import React, { useState } from 'react'

/**
 * 官网 / 落地页（未登录可见）—— 参考 OpenArt 这类 AI studio：顶栏 + Hero(含提示词条) + 作品展示墙 + 能力 + 页脚。
 * Props：onStart(主 CTA，开始创作)、onLogin(去登录页)、authEnabled。
 * 纯展示，登录在独立的 Login 页（由 AppGate 切换）。
 */
const SHOWCASE = [
  ['都市赘婿·逆袭', 'linear-gradient(135deg,#7c3aed,#db2777)'],
  ['总裁的隐婚妻', 'linear-gradient(135deg,#2563eb,#06b6d4)'],
  ['修仙：废柴到剑神', 'linear-gradient(135deg,#f59e0b,#ef4444)'],
  ['重生之商业帝国', 'linear-gradient(135deg,#10b981,#3b82f6)'],
  ['穿越古代当王妃', 'linear-gradient(135deg,#ec4899,#8b5cf6)'],
  ['末世求生录', 'linear-gradient(135deg,#475569,#0ea5e9)'],
  ['校园青春恋曲', 'linear-gradient(135deg,#f472b6,#fb923c)'],
  ['豪门继承人', 'linear-gradient(135deg,#6366f1,#a855f7)'],
]
const FEAT = [
  ['🎬', 'AI 一键拆镜', '小说 → 自动分镜，每镜由 AI 定时长、续接、对口型、音效，零手动'],
  ['🎥', '出片 · 续接', 'Wan2.2 出片 + i2v 尾帧续接，人物与场景跨镜连贯一致'],
  ['🗣', '克隆配音 + 对口型', 'CosyVoice2 情感克隆配音，正脸说话镜自动 LatentSync 缝嘴'],
  ['🔊', '同步音效', 'MMAudio 按画面生成与动作同步的环境/动作音效，垫在人声之下'],
]

export default function Landing({ onStart, onLogin, authEnabled }) {
  const [prompt, setPrompt] = useState('')
  return (
    <div style={S.page}>
      <div style={S.glow} />
      <header style={S.nav}>
        <div style={S.brand}>蜃景<span style={{ color: '#a78bfa' }}> Mirage</span></div>
        <nav style={S.navlinks}>
          <a style={S.nl} href="#showcase">探索</a>
          <a style={S.nl} href="#features">功能</a>
          <a style={S.nl} href="#pricing">价格</a>
          <a style={S.nl} href="/api/v1/metadata" target="_blank" rel="noreferrer">API</a>
        </nav>
        <div style={{ display: 'flex', gap: 10 }}>
          <button style={S.ghost} onClick={onLogin}>登录</button>
          <button style={S.cta} onClick={onStart}>免费开始</button>
        </div>
      </header>

      <section style={S.hero}>
        <div style={S.badge}>✦ 全自动 AI 短剧流水线</div>
        <h1 style={S.h1}>小说，一键变 AI 短剧</h1>
        <p style={S.sub}>粘贴小说或剧情，AI 自动拆镜 · 出片续接 · 克隆配音 · 对口型 · 同步音效 · 合成出片。竖屏成片，开放 API。</p>
        <div style={S.promptbar}>
          <input style={S.pinput} value={prompt} onChange={(e) => setPrompt(e.target.value)}
                 placeholder="粘贴你的小说 / 一句剧情，AI 帮你出片…" onKeyDown={(e) => e.key === 'Enter' && onStart(prompt)} />
          <button style={S.pbtn} onClick={() => onStart(prompt)}>开始创作 →</button>
        </div>
        <div style={S.trust}>AI 拆镜 · 出片 · 配音 · 对口型 · 音效 · 合成 —— 全程零手动</div>
      </section>

      <section id="showcase" style={S.section}>
        <div style={S.secttitle}>用 Mirage 生成的短剧</div>
        <div style={S.grid}>
          {SHOWCASE.map(([t, g], i) => (
            <div key={t} style={{ ...S.shot, aspectRatio: i % 3 === 1 ? '9/16' : '9/14' }}>
              <div style={{ ...S.shotbg, background: g }} />
              <div style={S.play}>▶</div>
              <div style={S.shottitle}>{t}</div>
              <div style={S.aibadge}>AI 生成</div>
            </div>
          ))}
        </div>
      </section>

      <section id="features" style={S.section}>
        <div style={S.secttitle}>一条龙，全自动</div>
        <div style={S.featgrid}>
          {FEAT.map(([i, t, d]) => (
            <div key={t} style={S.card}>
              <div style={{ fontSize: 28 }}>{i}</div>
              <div style={{ fontWeight: 700, margin: '12px 0 6px', color: '#e2e8f0', fontSize: 15 }}>{t}</div>
              <div style={{ color: '#94a3b8', fontSize: 13, lineHeight: 1.65 }}>{d}</div>
            </div>
          ))}
        </div>
      </section>

      <section id="pricing" style={{ ...S.section, textAlign: 'center' }}>
        <div style={S.secttitle}>按需付费，先免费试</div>
        <div style={S.pricerow}>
          {[['免费', '注册即送 100 积分', '体验一键出片'], ['按量', '积分充值，用多少付多少', '出片/续接按操作计费'], ['API', '开放接口 + API Key', '接你的业务 / 第三方']].map(([a, b, c]) => (
            <div key={a} style={S.pricecard}>
              <div style={{ fontWeight: 800, fontSize: 18, color: '#a78bfa' }}>{a}</div>
              <div style={{ color: '#e2e8f0', margin: '10px 0 6px', fontWeight: 600 }}>{b}</div>
              <div style={{ color: '#94a3b8', fontSize: 13 }}>{c}</div>
            </div>
          ))}
        </div>
        <button style={{ ...S.cta, height: 48, padding: '0 34px', fontSize: 15, marginTop: 30 }} onClick={onStart}>免费开始创作 →</button>
      </section>

      <footer style={S.foot}>© 蜃景 Mirage · 全自托管 AI 短剧流水线 · 开放 API 对接{authEnabled ? '' : ' · (开发态：未开登录)'}</footer>
    </div>
  )
}

const S = {
  page: { position: 'relative', height: '100vh', overflowY: 'auto', overflowX: 'hidden', background: '#0a0a12', color: '#e2e8f0', fontFamily: 'system-ui,-apple-system,"Segoe UI",sans-serif' },
  glow: { position: 'absolute', top: -260, left: '50%', transform: 'translateX(-50%)', width: 1000, height: 560, background: 'radial-gradient(circle, rgba(124,58,237,0.28), transparent 62%)', filter: 'blur(20px)', pointerEvents: 'none' },
  nav: { position: 'sticky', top: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 32px', maxWidth: 1200, margin: '0 auto', backdropFilter: 'blur(8px)' },
  brand: { fontSize: 20, fontWeight: 800, letterSpacing: 0.5 },
  navlinks: { display: 'flex', gap: 26 },
  nl: { color: '#94a3b8', textDecoration: 'none', fontSize: 14, fontWeight: 500 },
  ghost: { height: 36, padding: '0 16px', borderRadius: 9, border: '1px solid rgba(148,163,184,0.25)', background: 'transparent', color: '#e2e8f0', fontSize: 13.5, fontWeight: 600, cursor: 'pointer' },
  cta: { height: 36, padding: '0 18px', borderRadius: 9, border: 'none', background: 'linear-gradient(90deg,#7c3aed,#a855f7)', color: '#fff', fontWeight: 700, fontSize: 13.5, cursor: 'pointer', boxShadow: '0 6px 20px rgba(124,58,237,0.35)' },
  hero: { position: 'relative', textAlign: 'center', padding: '80px 20px 40px', maxWidth: 860, margin: '0 auto' },
  badge: { display: 'inline-block', padding: '5px 14px', borderRadius: 999, border: '1px solid rgba(167,139,250,0.35)', background: 'rgba(124,58,237,0.12)', color: '#c4b5fd', fontSize: 12.5, marginBottom: 22 },
  h1: { fontSize: 52, fontWeight: 900, lineHeight: 1.1, margin: 0, letterSpacing: -1 },
  sub: { color: '#94a3b8', fontSize: 17, lineHeight: 1.7, margin: '22px auto 30px', maxWidth: 660 },
  promptbar: { display: 'flex', gap: 8, maxWidth: 620, margin: '0 auto', padding: 7, borderRadius: 14, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(148,163,184,0.2)' },
  pinput: { flex: 1, height: 44, padding: '0 14px', borderRadius: 10, border: 'none', background: 'transparent', color: '#e2e8f0', fontSize: 14.5, outline: 'none' },
  pbtn: { height: 44, padding: '0 22px', borderRadius: 10, border: 'none', background: 'linear-gradient(90deg,#7c3aed,#a855f7)', color: '#fff', fontWeight: 700, fontSize: 14, cursor: 'pointer', whiteSpace: 'nowrap' },
  trust: { color: '#64748b', fontSize: 12.5, marginTop: 18 },
  section: { position: 'relative', maxWidth: 1140, margin: '64px auto', padding: '0 24px' },
  secttitle: { fontSize: 24, fontWeight: 800, textAlign: 'center', marginBottom: 28, color: '#f1f5f9' },
  grid: { columns: 4, columnGap: 14 },
  shot: { position: 'relative', breakInside: 'avoid', marginBottom: 14, borderRadius: 14, overflow: 'hidden', border: '1px solid rgba(148,163,184,0.14)', cursor: 'pointer' },
  shotbg: { position: 'absolute', inset: 0, opacity: 0.9 },
  play: { position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 30, color: 'rgba(255,255,255,0.92)', textShadow: '0 2px 12px rgba(0,0,0,0.4)' },
  shottitle: { position: 'absolute', left: 12, bottom: 10, fontSize: 14, fontWeight: 700, color: '#fff', textShadow: '0 1px 6px rgba(0,0,0,0.6)' },
  aibadge: { position: 'absolute', right: 10, top: 10, padding: '3px 8px', borderRadius: 7, background: 'rgba(0,0,0,0.4)', color: '#e9d5ff', fontSize: 10.5, fontWeight: 600, backdropFilter: 'blur(4px)' },
  featgrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 16 },
  card: { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(148,163,184,0.15)', borderRadius: 16, padding: 22 },
  pricerow: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 16, maxWidth: 820, margin: '0 auto' },
  pricecard: { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(148,163,184,0.15)', borderRadius: 16, padding: 26 },
  foot: { textAlign: 'center', color: '#64748b', fontSize: 12.5, padding: '40px 20px 50px', borderTop: '1px solid rgba(148,163,184,0.1)', marginTop: 30 },
}
