// Overlays — drama-list drawer, AI assistant sheet, settings sheet.
const DS_ov = window.MirageDesignSystem_c5883d;

function Drawer({ open, onClose, current, onPick }) {
  const { Logo, Button } = DS_ov;
  return (
    <div style={{ position: "absolute", inset: 0, zIndex: 60, pointerEvents: open ? "auto" : "none" }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "var(--scrim)", opacity: open ? 1 : 0, transition: "opacity var(--dur-base)" }} />
      <div style={{ position: "absolute", top: 0, bottom: 0, left: 0, width: 300, background: "var(--surface-card)", borderRight: "1px solid var(--border-strong)", transform: open ? "translateX(0)" : "translateX(-100%)", transition: "transform var(--dur-slow) var(--ease-out)", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "calc(var(--safe-top) + 12px) 16px 14px", borderBottom: "1px solid var(--border)" }}>
          <Logo size={34} showText sub />
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", padding: "4px 8px 10px", textTransform: "uppercase", letterSpacing: ".05em" }}>剧集</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {window.EPISODES.map((e) => {
              const active = e.id === current;
              return (
                <button key={e.id} onClick={() => onPick(e.id)} style={{ position: "relative", display: "flex", alignItems: "center", gap: 10, padding: "12px 12px 12px 14px", background: active ? "var(--surface-raised)" : "transparent", border: "none", borderRadius: "var(--r-btn)", cursor: "pointer", textAlign: "left", width: "100%" }}>
                  {active && <span style={{ position: "absolute", left: 0, top: 10, bottom: 10, width: 3, borderRadius: 3, background: "var(--purple)" }} />}
                  <i data-lucide="clapperboard" style={{ width: 18, height: 18, color: active ? "var(--purple)" : "var(--text-muted)" }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: active ? 600 : 500, color: active ? "var(--text-primary)" : "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.name}</div>
                    <div style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{e.scenes} 镜</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
        <div style={{ padding: 12, borderTop: "1px solid var(--border)" }}>
          <Button variant="ghost" full icon={<i data-lucide="plus" style={{ width: 16, height: 16 }} />}>新建剧集</Button>
        </div>
      </div>
    </div>
  );
}

function ToolStep({ label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)", padding: "3px 0" }}>
      <i data-lucide="check" style={{ width: 14, height: 14, color: "var(--green)" }} /> {label}
    </div>
  );
}

function AssistantSheet({ open, onClose }) {
  const { Sheet, Chip, CandidateImage, Button } = DS_ov;
  const [sel, setSel] = React.useState(1);
  return (
    <Sheet open={open} onClose={onClose} title="AI 助手" maxHeight="88%">
      <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
        <div style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
          {/* user bubble */}
          <div style={{ alignSelf: "flex-end", maxWidth: "80%", background: "transparent", border: "1px solid var(--purple)", color: "var(--text-primary)", borderRadius: 14, borderBottomRightRadius: 4, padding: "10px 12px", fontSize: 14 }}>
            把第 2 镜重新出图，要更暗的雨夜氛围
          </div>
          {/* assistant */}
          <div style={{ alignSelf: "flex-start", maxWidth: "92%" }}>
            <div style={{ fontSize: 14, color: "var(--text-primary)", marginBottom: 8 }}>好的，正在为第 2 镜重新生成候选。</div>
            <div style={{ background: "var(--surface-sunken)", border: "1px solid var(--border)", borderRadius: 12, padding: "8px 12px", marginBottom: 10 }}>
              <ToolStep label="auto_storyboard · scene_02" />
              <ToolStep label="build_prompt · +rainy +low-key" />
              <ToolStep label="flux_generate · 4 candidates" />
            </div>
            {/* param card (teal) */}
            <div style={{ background: "var(--teal-soft)", border: "1px solid rgba(0,189,176,0.4)", borderRadius: 12, padding: 12, marginBottom: 10 }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--teal-bright)", fontWeight: 600, marginBottom: 8, letterSpacing: ".04em" }}>PARAM_FORM · FLUX</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 14px", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                {[["size", "1080×1920"], ["steps", "30"], ["guidance", "5.0"], ["lora", "0.85"]].map(([k, v]) => (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between" }}><span style={{ color: "var(--text-muted)" }}>{k}</span><span style={{ color: "var(--teal-bright)" }}>{v}</span></div>
                ))}
              </div>
            </div>
            {/* candidate wall */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
              {[0, 1, 2, 3].map((i) => (
                <CandidateImage key={i} selected={sel === i} onClick={() => setSel(i)} style={{ background: window.stillBg(40 + i) }} />
              ))}
            </div>
            {/* HITL confirm */}
            <div style={{ background: "var(--surface-sunken)", border: "1px solid var(--border-strong)", borderRadius: 12, padding: 12 }}>
              <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 10 }}>已选第 2 张，是否继续合成出片？</div>
              <div style={{ display: "flex", gap: 8 }}>
                <Button variant="teal" size="sm">确认</Button>
                <Button variant="ghost" size="sm">取消</Button>
              </div>
            </div>
          </div>
          {/* quick replies */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Chip tone="purple">换个运镜</Chip>
            <Chip>再来 4 张</Chip>
            <Chip>下一镜</Chip>
          </div>
        </div>
        {/* input bar */}
        <div style={{ borderTop: "1px solid var(--border)", padding: "10px 12px calc(var(--safe-bottom) + 8px)", background: "var(--surface-card)" }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <Chip tone="accent" active icon={<i data-lucide="bot" style={{ width: 13, height: 13 }} />}>Agent</Chip>
            <Chip icon={<i data-lucide="brain" style={{ width: 13, height: 13 }} />}>深度思考</Chip>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, background: "var(--surface-sunken)", border: "1px solid var(--border-strong)", borderRadius: "var(--r-btn)", padding: "4px 4px 4px 12px" }}>
            <input placeholder="给 AI 助手发消息…" style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "var(--text-primary)", fontSize: 14, fontFamily: "var(--font-sans)" }} />
            <button aria-label="发送" style={{ width: 40, height: 40, flex: "none", display: "inline-flex", alignItems: "center", justifyContent: "center", background: "var(--logo-grad)", color: "#fff", border: "none", borderRadius: "var(--r-btn)", cursor: "pointer" }}>
              <i data-lucide="arrow-up" style={{ width: 18, height: 18 }} />
            </button>
          </div>
        </div>
      </div>
    </Sheet>
  );
}

function SettingsSheet({ open, onClose }) {
  const { Sheet, Switch, Select, Button } = DS_ov;
  const [a, setA] = React.useState(true);
  const [b, setB] = React.useState(false);
  return (
    <Sheet open={open} onClose={onClose} title="设置" maxHeight="80%">
      <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
        <Row label="ComfyUI 地址"><span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)" }}>127.0.0.1:8188</span></Row>
        <Row label="工作目录" sub="/Users/me/mirage/episodes"><i data-lucide="folder" style={{ width: 18, height: 18, color: "var(--text-secondary)" }} /></Row>
        <Row label="默认出图模型"><Select value="FLUX.1-dev" size="sm" /></Row>
        <Row label="GPU offload"><Switch checked={a} onChange={setA} /></Row>
        <Row label="生成完成提示音"><Switch checked={b} onChange={setB} /></Row>
        <div style={{ height: 1, background: "var(--border)" }} />
        <Button variant="ghost" full>清空缓存</Button>
      </div>
    </Sheet>
  );
}

function Row({ label, sub, children }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
      <div>
        <div style={{ fontSize: 14, color: "var(--text-primary)" }}>{label}</div>
        {sub && <div style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-mono)", marginTop: 2 }}>{sub}</div>}
      </div>
      {children}
    </div>
  );
}

Object.assign(window, { Drawer, AssistantSheet, SettingsSheet });
