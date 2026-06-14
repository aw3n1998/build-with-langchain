/* @ds-bundle: {"format":3,"namespace":"MirageDesignSystem_c5883d","components":[{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"Card","sourcePath":"components/core/Card.jsx"},{"name":"Chip","sourcePath":"components/core/Chip.jsx"},{"name":"IconButton","sourcePath":"components/core/IconButton.jsx"},{"name":"Logo","sourcePath":"components/core/Logo.jsx"},{"name":"Select","sourcePath":"components/core/Select.jsx"},{"name":"StatChip","sourcePath":"components/core/StatChip.jsx"},{"name":"StatusBadge","sourcePath":"components/core/StatusBadge.jsx"},{"name":"Switch","sourcePath":"components/core/Switch.jsx"},{"name":"TabRail","sourcePath":"components/navigation/TabRail.jsx"},{"name":"CandidateImage","sourcePath":"components/studio/CandidateImage.jsx"},{"name":"FAB","sourcePath":"components/studio/FAB.jsx"},{"name":"GpuLogBar","sourcePath":"components/studio/GpuLogBar.jsx"},{"name":"SceneCard","sourcePath":"components/studio/SceneCard.jsx"},{"name":"Sheet","sourcePath":"components/studio/Sheet.jsx"}],"sourceHashes":{"components/core/Button.jsx":"1f9991071f96","components/core/Card.jsx":"646afd83a172","components/core/Chip.jsx":"a98a4b722af9","components/core/IconButton.jsx":"dffd66e2342e","components/core/Logo.jsx":"28ab637a1fd3","components/core/Select.jsx":"95aca4caf2d2","components/core/StatChip.jsx":"f582739c52c9","components/core/StatusBadge.jsx":"dc4777bdccb7","components/core/Switch.jsx":"64d059a32e61","components/navigation/TabRail.jsx":"e71c2a0e50cb","components/studio/CandidateImage.jsx":"ff3f958597a6","components/studio/FAB.jsx":"8324606dc38b","components/studio/GpuLogBar.jsx":"7c6449cfc117","components/studio/SceneCard.jsx":"16caabee74a5","components/studio/Sheet.jsx":"596262ed41b6","ui_kits/mirage/App.jsx":"df013673a57d","ui_kits/mirage/data.jsx":"c44eb967f052","ui_kits/mirage/overlays.jsx":"8520adcc4ef4","ui_kits/mirage/storyboard.jsx":"9e266f66b987","ui_kits/mirage/tabs.jsx":"7edbfcf1c08e"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.MirageDesignSystem_c5883d = window.MirageDesignSystem_c5883d || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Mirage primary action button. Press (active) feedback only — no hover.
 * variant: primary (indigo) | teal (出片/param) | purple (出图) | ghost | danger | neutral
 */
function Button({
  children,
  variant = "primary",
  size = "md",
  full = false,
  disabled = false,
  icon = null,
  style = {},
  ...rest
}) {
  const palettes = {
    primary: {
      bg: "var(--accent)",
      press: "var(--accent-press)",
      fg: "#fff",
      bd: "transparent"
    },
    teal: {
      bg: "var(--teal)",
      press: "#009a8f",
      fg: "#04221f",
      bd: "transparent"
    },
    purple: {
      bg: "var(--purple)",
      press: "#a855e6",
      fg: "#23103a",
      bd: "transparent"
    },
    danger: {
      bg: "transparent",
      press: "var(--red-soft)",
      fg: "var(--red)",
      bd: "var(--border-strong)"
    },
    ghost: {
      bg: "transparent",
      press: "var(--neutral-soft)",
      fg: "var(--text-primary)",
      bd: "var(--border-strong)"
    },
    neutral: {
      bg: "var(--surface-raised)",
      press: "#262626",
      fg: "var(--text-primary)",
      bd: "var(--border)"
    }
  };
  const sizes = {
    sm: {
      h: 36,
      px: 12,
      fs: 13,
      gap: 6
    },
    md: {
      h: 44,
      px: 16,
      fs: 15,
      gap: 8
    },
    lg: {
      h: 50,
      px: 20,
      fs: 16,
      gap: 8
    }
  };
  const p = palettes[variant] || palettes.primary;
  const s = sizes[size] || sizes.md;
  const [down, setDown] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", _extends({
    disabled: disabled,
    onPointerDown: () => setDown(true),
    onPointerUp: () => setDown(false),
    onPointerLeave: () => setDown(false),
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: s.gap,
      width: full ? "100%" : "auto",
      minHeight: s.h,
      height: s.h,
      padding: `0 ${s.px}px`,
      fontFamily: "var(--font-sans)",
      fontSize: s.fs,
      fontWeight: 600,
      lineHeight: 1,
      color: p.fg,
      background: down && !disabled ? p.press : p.bg,
      border: `1px solid ${p.bd}`,
      borderRadius: "var(--r-btn)",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.4 : 1,
      transform: down && !disabled ? "scale(0.97)" : "scale(1)",
      transition: "transform var(--dur-fast) var(--ease-out), background var(--dur-fast)",
      userSelect: "none",
      WebkitTapHighlightColor: "transparent",
      ...style
    }
  }, rest), icon, children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Generic flat card surface — #161616, hairline border, 12px radius, no shadow.
 * `tone="code"` switches to the #0a0a0a log well. `pad` controls inner padding.
 */
function Card({
  children,
  tone = "default",
  pad = 16,
  style = {},
  ...rest
}) {
  const bg = tone === "code" ? "var(--surface-code)" : tone === "sunken" ? "var(--surface-sunken)" : "var(--surface-card)";
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      background: bg,
      border: "1px solid var(--border)",
      borderRadius: "var(--r-card)",
      padding: pad,
      fontFamily: "var(--font-sans)",
      color: "var(--text-primary)",
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Card.jsx", error: String((e && e.message) || e) }); }

// components/core/Chip.jsx
try { (() => {
/**
 * Small selectable chip — used for quick replies, agent toggles, filter pills.
 * `tone` tints it; `active` fills with the tone color.
 */
function Chip({
  children,
  tone = "neutral",
  active = false,
  icon = null,
  onClick,
  style = {}
}) {
  const tones = {
    neutral: "var(--text-secondary)",
    accent: "var(--accent)",
    teal: "var(--teal-bright)",
    purple: "var(--purple)",
    green: "var(--green)"
  };
  const c = tones[tone] || tones.neutral;
  const softMap = {
    neutral: "var(--neutral-soft)",
    accent: "var(--accent-soft)",
    teal: "var(--teal-soft)",
    purple: "var(--purple-soft)",
    green: "var(--green-soft)"
  };
  const [down, setDown] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", {
    onPointerDown: () => setDown(true),
    onPointerUp: () => setDown(false),
    onPointerLeave: () => setDown(false),
    onClick: onClick,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      height: 32,
      padding: "0 12px",
      fontFamily: "var(--font-sans)",
      fontSize: 13,
      fontWeight: 500,
      lineHeight: 1,
      whiteSpace: "nowrap",
      color: active ? c : "var(--text-secondary)",
      background: active ? softMap[tone] : "var(--surface-card)",
      border: `1px solid ${active ? c : "var(--border)"}`,
      borderRadius: "var(--r-chip)",
      cursor: "pointer",
      transform: down ? "scale(0.96)" : "scale(1)",
      transition: "transform var(--dur-fast) var(--ease-out)",
      WebkitTapHighlightColor: "transparent",
      ...style
    }
  }, icon, children);
}
Object.assign(__ds_scope, { Chip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Chip.jsx", error: String((e && e.message) || e) }); }

// components/core/IconButton.jsx
try { (() => {
/**
 * Square icon-only tap target (≥44px by default). Pass a lucide name to render
 * via the global `lucide` CDN, or pass children (inline svg). tone colors the glyph.
 */
function IconButton({
  name,
  children,
  size = 44,
  tone = "default",
  onClick,
  ariaLabel,
  style = {}
}) {
  const colors = {
    default: "var(--text-primary)",
    muted: "var(--text-secondary)",
    danger: "var(--red)",
    accent: "var(--accent)"
  };
  const [down, setDown] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", {
    "aria-label": ariaLabel,
    onClick: onClick,
    onPointerDown: () => setDown(true),
    onPointerUp: () => setDown(false),
    onPointerLeave: () => setDown(false),
    style: {
      width: size,
      height: size,
      flex: "none",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      color: colors[tone] || colors.default,
      background: down ? "var(--neutral-soft)" : "transparent",
      border: "none",
      borderRadius: "var(--r-btn)",
      cursor: "pointer",
      transform: down ? "scale(0.92)" : "scale(1)",
      transition: "transform var(--dur-fast) var(--ease-out), background var(--dur-fast)",
      WebkitTapHighlightColor: "transparent",
      ...style
    }
  }, name ? /*#__PURE__*/React.createElement("i", {
    "data-lucide": name,
    style: {
      width: 22,
      height: 22
    }
  }) : children);
}
Object.assign(__ds_scope, { IconButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/IconButton.jsx", error: String((e && e.message) || e) }); }

// components/core/Logo.jsx
try { (() => {
/** Brand lockup — gradient clapperboard square + optional wordmark. */
function Logo({
  size = 32,
  showText = false,
  sub = false,
  style = {}
}) {
  const r = Math.round(size * 0.28);
  const ic = Math.round(size * 0.58);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: size * 0.34,
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: size,
      height: size,
      flex: "none",
      borderRadius: r,
      background: "var(--logo-grad)",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: ic,
    height: ic,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "#fff",
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M20.2 6 3 11l-.9-2.4c-.3-.8.1-1.7.9-2l11.3-4.2c.8-.3 1.7.1 2 .9z"
  }), /*#__PURE__*/React.createElement("path", {
    d: "m6.2 5.3 3.1 3.9M12.4 3.4l3.1 4M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
  }))), showText && /*#__PURE__*/React.createElement("div", {
    style: {
      lineHeight: 1.15
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontWeight: 700,
      fontSize: size * 0.5,
      color: "var(--text-primary)",
      letterSpacing: "-0.01em"
    }
  }, "\u8703\u666F Mirage"), sub && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontWeight: 500,
      fontSize: size * 0.34,
      color: "var(--text-secondary)"
    }
  }, "\u77ED\u5267\u5DE5\u4F5C\u53F0")));
}
Object.assign(__ds_scope, { Logo });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Logo.jsx", error: String((e && e.message) || e) }); }

// components/core/Select.jsx
try { (() => {
/**
 * Compact dropdown trigger styled as a mobile picker control. Shows the current
 * value + chevron; opening a real picker is the consumer's concern (this is the
 * resting control used inline in global-action rows).
 */
function Select({
  label,
  value,
  size = "md",
  tone = "neutral",
  onClick,
  style = {}
}) {
  const h = size === "sm" ? 32 : 40;
  const accent = tone === "teal" ? "var(--teal-bright)" : "var(--text-primary)";
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      height: h,
      padding: "0 10px",
      fontFamily: "var(--font-sans)",
      fontSize: size === "sm" ? 13 : 14,
      fontWeight: 500,
      color: accent,
      background: "var(--surface-sunken)",
      border: "1px solid var(--border-strong)",
      borderRadius: "var(--r-btn)",
      cursor: "pointer",
      whiteSpace: "nowrap",
      WebkitTapHighlightColor: "transparent",
      ...style
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)",
      fontSize: 12
    }
  }, label), /*#__PURE__*/React.createElement("span", null, value), /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "var(--text-muted)",
    strokeWidth: "2.2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    style: {
      marginLeft: -2
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "m6 9 6 6 6-6"
  })));
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Select.jsx", error: String((e && e.message) || e) }); }

// components/core/StatChip.jsx
try { (() => {
/**
 * Colored count chip for the workbench header row (总数 / 已出图 / 已选 / 已出片).
 * tone sets the hue; value rides next to the label.
 */
function StatChip({
  label,
  value,
  tone = "neutral",
  style = {}
}) {
  const tones = {
    neutral: {
      c: "var(--text-secondary)",
      s: "var(--neutral-soft)"
    },
    yellow: {
      c: "var(--yellow)",
      s: "var(--yellow-soft)"
    },
    purple: {
      c: "var(--purple)",
      s: "var(--purple-soft)"
    },
    green: {
      c: "var(--green)",
      s: "var(--green-soft)"
    },
    teal: {
      c: "var(--teal-bright)",
      s: "var(--teal-soft)"
    }
  };
  const t = tones[tone] || tones.neutral;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      height: 28,
      padding: "0 10px",
      fontFamily: "var(--font-sans)",
      fontSize: 12,
      fontWeight: 600,
      lineHeight: 1,
      whiteSpace: "nowrap",
      color: t.c,
      background: t.s,
      borderRadius: "var(--r-chip)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: tone === "neutral" ? "var(--text-secondary)" : t.c,
      opacity: tone === "neutral" ? 1 : 0.82
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontVariantNumeric: "tabular-nums",
      color: t.c
    }
  }, value));
}
Object.assign(__ds_scope, { StatChip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/StatChip.jsx", error: String((e && e.message) || e) }); }

// components/core/StatusBadge.jsx
try { (() => {
const MAP = {
  pending: {
    label: "待出图",
    color: "var(--text-secondary)",
    soft: "var(--neutral-soft)",
    spin: false
  },
  drawing: {
    label: "出图中",
    color: "var(--yellow)",
    soft: "var(--yellow-soft)",
    spin: true
  },
  review: {
    label: "待选图",
    color: "var(--purple)",
    soft: "var(--purple-soft)",
    spin: false
  },
  done: {
    label: "已出片",
    color: "var(--green)",
    soft: "var(--green-soft)",
    spin: false
  },
  rendering: {
    label: "出片中",
    color: "var(--teal-bright)",
    soft: "var(--teal-soft)",
    spin: true
  },
  stopped: {
    label: "已停止",
    color: "var(--red)",
    soft: "var(--red-soft)",
    spin: false
  }
};

/**
 * Pipeline status badge — tinted pill with a state dot. `drawing`/`rendering`
 * spin a ring instead of a static dot.
 */
function StatusBadge({
  status = "pending",
  label,
  style = {}
}) {
  const s = MAP[status] || MAP.pending;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      height: 24,
      padding: "0 9px",
      fontFamily: "var(--font-sans)",
      fontSize: 12,
      fontWeight: 600,
      lineHeight: 1,
      color: s.color,
      background: s.soft,
      borderRadius: "var(--r-tag)",
      ...style
    }
  }, s.spin ? /*#__PURE__*/React.createElement("span", {
    style: {
      width: 10,
      height: 10,
      borderRadius: "50%",
      border: `1.6px solid ${s.color}`,
      borderTopColor: "transparent",
      animation: "mirageSpin 0.7s linear infinite"
    }
  }) : /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: "50%",
      background: s.color
    }
  }), label || s.label, /*#__PURE__*/React.createElement("style", null, `@keyframes mirageSpin{to{transform:rotate(360deg)}}
        @media (prefers-reduced-motion: reduce){[style*="mirageSpin"]{animation:none!important}}`));
}
Object.assign(__ds_scope, { StatusBadge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/StatusBadge.jsx", error: String((e && e.message) || e) }); }

// components/core/Switch.jsx
try { (() => {
/** iOS-style toggle (对口型 etc.). Indigo when on. Controlled via checked/onChange. */
function Switch({
  checked = false,
  onChange,
  disabled = false,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("button", {
    role: "switch",
    "aria-checked": checked,
    disabled: disabled,
    onClick: () => !disabled && onChange && onChange(!checked),
    style: {
      width: 46,
      height: 28,
      flex: "none",
      borderRadius: "var(--r-pill)",
      border: "none",
      padding: 2,
      background: checked ? "var(--accent)" : "var(--surface-raised)",
      boxShadow: checked ? "none" : "inset 0 0 0 1px var(--border-strong)",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.4 : 1,
      transition: "background var(--dur-base) var(--ease-out)",
      display: "inline-flex",
      alignItems: "center",
      WebkitTapHighlightColor: "transparent",
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 24,
      height: 24,
      borderRadius: "50%",
      background: "#fff",
      transform: checked ? "translateX(18px)" : "translateX(0)",
      transition: "transform var(--dur-base) var(--ease-out)",
      boxShadow: "0 1px 3px rgba(0,0,0,0.4)"
    }
  }));
}
Object.assign(__ds_scope, { Switch });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Switch.jsx", error: String((e && e.message) || e) }); }

// components/navigation/TabRail.jsx
try { (() => {
/**
 * Horizontally-scrollable segmented tab rail with an indigo underline on the
 * active tab. Mobile pattern: swipeable, no wrap.
 */
function TabRail({
  tabs = [],
  value,
  onChange,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "no-scrollbar",
    style: {
      display: "flex",
      gap: 4,
      overflowX: "auto",
      borderBottom: "1px solid var(--border)",
      WebkitOverflowScrolling: "touch",
      ...style
    }
  }, tabs.map(t => {
    const key = typeof t === "string" ? t : t.id;
    const label = typeof t === "string" ? t : t.label;
    const active = key === value;
    return /*#__PURE__*/React.createElement("button", {
      key: key,
      onClick: () => onChange && onChange(key),
      style: {
        position: "relative",
        flex: "none",
        height: 44,
        padding: "0 14px",
        fontFamily: "var(--font-sans)",
        fontSize: 15,
        fontWeight: active ? 600 : 500,
        color: active ? "var(--text-primary)" : "var(--text-secondary)",
        background: "transparent",
        border: "none",
        cursor: "pointer",
        whiteSpace: "nowrap",
        WebkitTapHighlightColor: "transparent"
      }
    }, label, /*#__PURE__*/React.createElement("span", {
      style: {
        position: "absolute",
        left: 12,
        right: 12,
        bottom: -1,
        height: 2,
        borderRadius: 2,
        background: active ? "var(--accent)" : "transparent",
        transition: "background var(--dur-base)"
      }
    }));
  }));
}
Object.assign(__ds_scope, { TabRail });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/TabRail.jsx", error: String((e && e.message) || e) }); }

// components/studio/CandidateImage.jsx
try { (() => {
/**
 * One image in the 待选图 candidate wall — 3:4 portrait. Selected = green ring
 * + "选中" corner tag. Pass `src` for a real still, else a placeholder fill.
 */
function CandidateImage({
  src,
  selected = false,
  label,
  onClick,
  style = {}
}) {
  const [down, setDown] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    onPointerDown: () => setDown(true),
    onPointerUp: () => setDown(false),
    onPointerLeave: () => setDown(false),
    style: {
      position: "relative",
      aspectRatio: "3 / 4",
      width: "100%",
      padding: 0,
      border: "none",
      borderRadius: "var(--r-btn)",
      overflow: "hidden",
      cursor: "pointer",
      background: src ? "#000" : "var(--surface-sunken)",
      boxShadow: selected ? "0 0 0 2px var(--green)" : "inset 0 0 0 1px var(--border)",
      transform: down ? "scale(0.98)" : "scale(1)",
      transition: "transform var(--dur-fast) var(--ease-out)",
      WebkitTapHighlightColor: "transparent",
      ...style
    }
  }, src ? /*#__PURE__*/React.createElement("img", {
    src: src,
    alt: label || "",
    style: {
      width: "100%",
      height: "100%",
      objectFit: "cover",
      display: "block"
    }
  }) : /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      inset: 0,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "var(--text-faint)"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "image",
    style: {
      width: 22,
      height: 22
    }
  })), selected && /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 6,
      right: 6,
      display: "inline-flex",
      alignItems: "center",
      gap: 3,
      height: 20,
      padding: "0 7px",
      fontSize: 11,
      fontWeight: 600,
      color: "#04221f",
      background: "var(--green)",
      borderRadius: "var(--r-tag)"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "11",
    height: "11",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "#04221f",
    strokeWidth: "3.2",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M20 6 9 17l-5-5"
  })), "\u9009\u4E2D"));
}
Object.assign(__ds_scope, { CandidateImage });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/studio/CandidateImage.jsx", error: String((e && e.message) || e) }); }

// components/studio/FAB.jsx
try { (() => {
/** Floating AI-assistant button — gradient round, bottom-right, indigo glow. */
function FAB({
  onClick,
  icon = "sparkles",
  size = 56,
  style = {}
}) {
  const [down, setDown] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", {
    "aria-label": "AI \u52A9\u624B",
    onClick: onClick,
    onPointerDown: () => setDown(true),
    onPointerUp: () => setDown(false),
    onPointerLeave: () => setDown(false),
    style: {
      width: size,
      height: size,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      color: "#fff",
      background: "var(--logo-grad)",
      border: "none",
      borderRadius: "var(--r-pill)",
      boxShadow: "var(--shadow-fab)",
      cursor: "pointer",
      transform: down ? "scale(0.94)" : "scale(1)",
      transition: "transform var(--dur-fast) var(--ease-out)",
      WebkitTapHighlightColor: "transparent",
      ...style
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": icon,
    style: {
      width: 24,
      height: 24
    }
  }));
}
Object.assign(__ds_scope, { FAB });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/studio/FAB.jsx", error: String((e && e.message) || e) }); }

// components/studio/GpuLogBar.jsx
try { (() => {
/**
 * GPU status condensé — a collapsed bar (● state + elapsed) that expands to a
 * mono colored log well. Sits docked above the bottom bar.
 */
function GpuLogBar({
  state = "idle",
  elapsed,
  lines = [],
  defaultOpen = false,
  style = {}
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const meta = {
    idle: {
      c: "var(--text-secondary)",
      t: "空闲",
      spin: false
    },
    drawing: {
      c: "var(--yellow)",
      t: "出图中",
      spin: true
    },
    rendering: {
      c: "var(--teal-bright)",
      t: "出片中",
      spin: true
    },
    done: {
      c: "var(--green)",
      t: "完成",
      spin: false
    },
    error: {
      c: "var(--red)",
      t: "错误",
      spin: false
    }
  }[state] || {
    c: "var(--text-secondary)",
    t: "空闲",
    spin: false
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-card)",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-card)",
      overflow: "hidden",
      fontFamily: "var(--font-mono)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setOpen(o => !o),
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      width: "100%",
      height: 40,
      padding: "0 12px",
      background: "transparent",
      border: "none",
      cursor: "pointer",
      color: "var(--text-primary)",
      WebkitTapHighlightColor: "transparent"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: "50%",
      flex: "none",
      background: meta.c,
      boxShadow: meta.spin ? `0 0 8px ${meta.c}` : "none"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: meta.c,
      fontWeight: 600
    }
  }, meta.t), elapsed && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)"
    }
  }, elapsed), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto",
      color: "var(--text-muted)",
      display: "inline-flex",
      transform: open ? "rotate(180deg)" : "none",
      transition: "transform var(--dur-base)"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.2",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "m18 15-6-6-6 6"
  })))), open && /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-code)",
      borderTop: "1px solid var(--border)",
      padding: "10px 12px",
      maxHeight: 160,
      overflowY: "auto",
      fontSize: 11.5,
      lineHeight: 1.7
    }
  }, lines.map((l, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      color: l.tone ? `var(--${l.tone})` : "var(--text-secondary)"
    }
  }, l.t))));
}
Object.assign(__ds_scope, { GpuLogBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/studio/GpuLogBar.jsx", error: String((e && e.message) || e) }); }

// components/studio/SceneCard.jsx
try { (() => {
/**
 * Scene card shell — numbered header (#序号 + title + status badge + delete),
 * with arbitrary body children below (candidate wall / clip thumb / draw button).
 * Left edge tints with the status hue.
 */
function SceneCard({
  index,
  title,
  status = "pending",
  onDelete,
  children,
  style = {}
}) {
  const edge = {
    pending: "var(--border-strong)",
    drawing: "var(--yellow)",
    review: "var(--purple)",
    done: "var(--green)",
    rendering: "var(--teal)",
    stopped: "var(--red)"
  }[status] || "var(--border-strong)";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-card)",
      border: "1px solid var(--border)",
      borderLeft: `2px solid ${edge}`,
      borderRadius: "var(--r-card)",
      overflow: "hidden",
      fontFamily: "var(--font-sans)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10,
      padding: "12px 12px 12px 14px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 13,
      fontWeight: 600,
      color: "var(--text-muted)",
      flex: "none"
    }
  }, "#", String(index).padStart(2, "0")), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      color: "var(--text-primary)",
      flex: 1,
      minWidth: 0,
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap"
    }
  }, title), /*#__PURE__*/React.createElement(__ds_scope.StatusBadge, {
    status: status
  }), onDelete && /*#__PURE__*/React.createElement("button", {
    "aria-label": "\u5220\u9664",
    onClick: onDelete,
    style: {
      width: 32,
      height: 32,
      flex: "none",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      color: "var(--red)",
      background: "transparent",
      border: "none",
      borderRadius: "var(--r-btn)",
      cursor: "pointer",
      WebkitTapHighlightColor: "transparent"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "17",
    height: "17",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"
  })))), children && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "0 12px 12px 14px"
    }
  }, children));
}
Object.assign(__ds_scope, { SceneCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/studio/SceneCard.jsx", error: String((e && e.message) || e) }); }

// components/studio/Sheet.jsx
try { (() => {
/**
 * Bottom sheet — slides up over a scrim, rounded top, grab handle. Use for the AI
 * assistant, pickers, settings, folder chooser. `open` toggles visibility.
 */
function Sheet({
  open = true,
  title,
  onClose,
  children,
  height = "auto",
  maxHeight = "86%",
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      zIndex: 50,
      pointerEvents: open ? "auto" : "none"
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: onClose,
    style: {
      position: "absolute",
      inset: 0,
      background: "var(--scrim)",
      opacity: open ? 1 : 0,
      transition: "opacity var(--dur-base) var(--ease-out)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      right: 0,
      bottom: 0,
      height,
      maxHeight,
      display: "flex",
      flexDirection: "column",
      background: "var(--surface-card)",
      borderTop: "1px solid var(--border-strong)",
      borderTopLeftRadius: 18,
      borderTopRightRadius: 18,
      boxShadow: "var(--shadow-sheet)",
      transform: open ? "translateY(0)" : "translateY(100%)",
      transition: "transform var(--dur-slow) var(--ease-out)",
      fontFamily: "var(--font-sans)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "center",
      paddingTop: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 36,
      height: 4,
      borderRadius: 2,
      background: "var(--border-strong)"
    }
  })), title && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "10px 16px 12px",
      borderBottom: "1px solid var(--border)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 16,
      fontWeight: 600,
      color: "var(--text-primary)"
    }
  }, title), onClose && /*#__PURE__*/React.createElement("button", {
    "aria-label": "\u5173\u95ED",
    onClick: onClose,
    style: {
      width: 32,
      height: 32,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      color: "var(--text-secondary)",
      background: "transparent",
      border: "none",
      cursor: "pointer",
      borderRadius: "var(--r-btn)"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "18",
    height: "18",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M18 6 6 18M6 6l12 12"
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      overflowY: "auto",
      WebkitOverflowScrolling: "touch",
      flex: 1,
      minHeight: 0
    }
  }, children)));
}
Object.assign(__ds_scope, { Sheet });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/studio/Sheet.jsx", error: String((e && e.message) || e) }); }

// ui_kits/mirage/App.jsx
try { (() => {
// App shell — iPhone frame, top bar, stat row, tabs, overlays, FAB.
const DS_app = window.MirageDesignSystem_c5883d;
function StatusBar() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: "var(--safe-top)",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "0 24px",
      flex: "none"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 600,
      color: "var(--text-primary)",
      fontVariantNumeric: "tabular-nums"
    }
  }, "9:41"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 6,
      color: "var(--text-primary)"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "signal",
    style: {
      width: 16,
      height: 16
    }
  }), /*#__PURE__*/React.createElement("i", {
    "data-lucide": "wifi",
    style: {
      width: 16,
      height: 16
    }
  }), /*#__PURE__*/React.createElement("i", {
    "data-lucide": "battery-full",
    style: {
      width: 20,
      height: 20
    }
  })));
}
function TopBar({
  onMenu,
  onAssistant,
  name
}) {
  const {
    IconButton
  } = DS_app;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: "var(--topbar-h)",
      display: "flex",
      alignItems: "center",
      padding: "0 6px",
      borderBottom: "1px solid var(--border)",
      flex: "none"
    }
  }, /*#__PURE__*/React.createElement(IconButton, {
    name: "menu",
    ariaLabel: "\u5267\u96C6\u5217\u8868",
    onClick: onMenu
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 7,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "clapperboard",
    style: {
      width: 17,
      height: 17,
      color: "var(--accent)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 16,
      fontWeight: 600,
      color: "var(--text-primary)",
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap"
    }
  }, name)), /*#__PURE__*/React.createElement("button", {
    onClick: onAssistant,
    "aria-label": "AI \u52A9\u624B",
    style: {
      width: 44,
      height: 44,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: "transparent",
      border: "none",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 30,
      height: 30,
      borderRadius: "50%",
      background: "var(--logo-grad)",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      color: "#fff"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "sparkles",
    style: {
      width: 16,
      height: 16
    }
  }))));
}
function StatRow() {
  const {
    StatChip
  } = DS_app;
  return /*#__PURE__*/React.createElement("div", {
    className: "no-scrollbar",
    style: {
      display: "flex",
      gap: 8,
      padding: "12px var(--gutter)",
      overflowX: "auto",
      flex: "none"
    }
  }, /*#__PURE__*/React.createElement(StatChip, {
    label: "\u603B\u6570",
    value: 8
  }), /*#__PURE__*/React.createElement(StatChip, {
    label: "\u5DF2\u51FA\u56FE",
    value: 6,
    tone: "yellow"
  }), /*#__PURE__*/React.createElement(StatChip, {
    label: "\u5DF2\u9009",
    value: 4,
    tone: "purple"
  }), /*#__PURE__*/React.createElement(StatChip, {
    label: "\u5DF2\u51FA\u7247",
    value: 2,
    tone: "green"
  }));
}
function App() {
  const {
    TabRail,
    FAB
  } = DS_app;
  const [tab, setTab] = React.useState("storyboard");
  const [drawer, setDrawer] = React.useState(false);
  const [assistant, setAssistant] = React.useState(false);
  const [settings, setSettings] = React.useState(false);
  const [ep, setEp] = React.useState("ep1");
  React.useEffect(() => {
    if (window.lucide) window.lucide.createIcons();
  });
  const epName = (window.EPISODES.find(e => e.id === ep) || {}).name || "";
  const Panel = {
    storyboard: window.StoryboardTab,
    script: window.ScriptTab,
    characters: window.CharactersTab,
    export: window.ExportTab
  }[tab];
  return /*#__PURE__*/React.createElement("div", {
    className: "mirage-phone"
  }, /*#__PURE__*/React.createElement(StatusBar, null), /*#__PURE__*/React.createElement(TopBar, {
    name: epName,
    onMenu: () => setDrawer(true),
    onAssistant: () => setAssistant(true)
  }), /*#__PURE__*/React.createElement(StatRow, null), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "0 var(--gutter)",
      flex: "none"
    }
  }, /*#__PURE__*/React.createElement(TabRail, {
    value: tab,
    onChange: setTab,
    tabs: [{
      id: "script",
      label: "脚本"
    }, {
      id: "characters",
      label: "角色&LoRA"
    }, {
      id: "storyboard",
      label: "分镜制作"
    }, {
      id: "export",
      label: "导出"
    }]
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minHeight: 0,
      overflowY: "auto",
      WebkitOverflowScrolling: "touch",
      padding: "14px var(--gutter) calc(var(--safe-bottom) + 80px)"
    }
  }, Panel ? /*#__PURE__*/React.createElement(Panel, null) : null), /*#__PURE__*/React.createElement("button", {
    onClick: () => setSettings(true),
    "aria-label": "\u8BBE\u7F6E",
    style: {
      position: "absolute",
      left: 16,
      bottom: "calc(var(--safe-bottom) + 16px)",
      width: 48,
      height: 48,
      borderRadius: "var(--r-pill)",
      background: "var(--surface-raised)",
      border: "1px solid var(--border-strong)",
      color: "var(--text-secondary)",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "settings",
    style: {
      width: 20,
      height: 20
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      right: 16,
      bottom: "calc(var(--safe-bottom) + 16px)"
    }
  }, /*#__PURE__*/React.createElement(FAB, {
    onClick: () => setAssistant(true)
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      right: 0,
      bottom: 8,
      display: "flex",
      justifyContent: "center",
      pointerEvents: "none"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 134,
      height: 5,
      borderRadius: 3,
      background: "rgba(255,255,255,0.32)"
    }
  })), /*#__PURE__*/React.createElement(window.Drawer, {
    open: drawer,
    onClose: () => setDrawer(false),
    current: ep,
    onPick: id => {
      setEp(id);
      setDrawer(false);
    }
  }), /*#__PURE__*/React.createElement(window.AssistantSheet, {
    open: assistant,
    onClose: () => setAssistant(false)
  }), /*#__PURE__*/React.createElement(window.SettingsSheet, {
    open: settings,
    onClose: () => setSettings(false)
  }));
}
Object.assign(window, {
  App
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/mirage/App.jsx", error: String((e && e.message) || e) }); }

// ui_kits/mirage/data.jsx
try { (() => {
// Mirage UI-kit mock data + shared helpers. Exposed on window for sibling scripts.

// Deterministic dark "film still" placeholder backgrounds (no fake photos —
// just tonal frames so the candidate wall / clips read as content).
function stillBg(seed) {
  const hues = [248, 268, 210, 12, 170, 32];
  const h = hues[seed % hues.length];
  const h2 = (h + 28) % 360;
  return `radial-gradient(120% 90% at 30% 20%, hsl(${h} 32% 16%), hsl(${h2} 28% 8%) 70%, #060606)`;
}
const EPISODES = [{
  id: "ep1",
  name: "第一集 · 雨夜追凶",
  scenes: 8,
  active: true
}, {
  id: "ep2",
  name: "第二集 · 旧城迷踪",
  scenes: 6,
  active: false
}, {
  id: "ep3",
  name: "第三集 · 最后通牒",
  scenes: 0,
  active: false
}];
const SCENES = [{
  id: 1,
  title: "开场航拍 · 都市夜景",
  status: "done"
}, {
  id: 2,
  title: "雨中对峙 · 巷口",
  status: "review"
}, {
  id: 3,
  title: "电话亭独白",
  status: "drawing"
}, {
  id: 4,
  title: "天台追逐",
  status: "pending",
  lip: true
}, {
  id: 5,
  title: "审讯室 · 灯下",
  status: "pending",
  lip: false
}];
const CHARACTERS = [{
  id: "c1",
  name: "林深",
  look: "30岁刑警，短寸黑发，风衣，左眉疤痕，冷峻",
  voice: "沉稳男声 · 磁性"
}, {
  id: "c2",
  name: "苏晚",
  look: "27岁法医，齐肩卷发，金丝眼镜，白大褂",
  voice: "清冷女声"
}];
const LORAS = [{
  id: "l1",
  name: "ep01_xianxia_style",
  count: 18,
  status: "COMPLETED"
}, {
  id: "l2",
  name: "char_linshen_face",
  count: 3,
  status: "DRAFT"
}];
Object.assign(window, {
  stillBg,
  EPISODES,
  SCENES,
  CHARACTERS,
  LORAS
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/mirage/data.jsx", error: String((e && e.message) || e) }); }

// ui_kits/mirage/overlays.jsx
try { (() => {
// Overlays — drama-list drawer, AI assistant sheet, settings sheet.
const DS_ov = window.MirageDesignSystem_c5883d;
function Drawer({
  open,
  onClose,
  current,
  onPick
}) {
  const {
    Logo,
    Button
  } = DS_ov;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      zIndex: 60,
      pointerEvents: open ? "auto" : "none"
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: onClose,
    style: {
      position: "absolute",
      inset: 0,
      background: "var(--scrim)",
      opacity: open ? 1 : 0,
      transition: "opacity var(--dur-base)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      top: 0,
      bottom: 0,
      left: 0,
      width: 300,
      background: "var(--surface-card)",
      borderRight: "1px solid var(--border-strong)",
      transform: open ? "translateX(0)" : "translateX(-100%)",
      transition: "transform var(--dur-slow) var(--ease-out)",
      display: "flex",
      flexDirection: "column"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "calc(var(--safe-top) + 12px) 16px 14px",
      borderBottom: "1px solid var(--border)"
    }
  }, /*#__PURE__*/React.createElement(Logo, {
    size: 34,
    showText: true,
    sub: true
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600,
      color: "var(--text-muted)",
      padding: "4px 8px 10px",
      textTransform: "uppercase",
      letterSpacing: ".05em"
    }
  }, "\u5267\u96C6"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 4
    }
  }, window.EPISODES.map(e => {
    const active = e.id === current;
    return /*#__PURE__*/React.createElement("button", {
      key: e.id,
      onClick: () => onPick(e.id),
      style: {
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "12px 12px 12px 14px",
        background: active ? "var(--surface-raised)" : "transparent",
        border: "none",
        borderRadius: "var(--r-btn)",
        cursor: "pointer",
        textAlign: "left",
        width: "100%"
      }
    }, active && /*#__PURE__*/React.createElement("span", {
      style: {
        position: "absolute",
        left: 0,
        top: 10,
        bottom: 10,
        width: 3,
        borderRadius: 3,
        background: "var(--purple)"
      }
    }), /*#__PURE__*/React.createElement("i", {
      "data-lucide": "clapperboard",
      style: {
        width: 18,
        height: 18,
        color: active ? "var(--purple)" : "var(--text-muted)"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 14,
        fontWeight: active ? 600 : 500,
        color: active ? "var(--text-primary)" : "var(--text-secondary)",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      }
    }, e.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: "var(--text-muted)",
        fontFamily: "var(--font-mono)"
      }
    }, e.scenes, " \u955C")));
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 12,
      borderTop: "1px solid var(--border)"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    full: true,
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "plus",
      style: {
        width: 16,
        height: 16
      }
    })
  }, "\u65B0\u5EFA\u5267\u96C6"))));
}
function ToolStep({
  label
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      color: "var(--text-secondary)",
      padding: "3px 0"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "check",
    style: {
      width: 14,
      height: 14,
      color: "var(--green)"
    }
  }), " ", label);
}
function AssistantSheet({
  open,
  onClose
}) {
  const {
    Sheet,
    Chip,
    CandidateImage,
    Button
  } = DS_ov;
  const [sel, setSel] = React.useState(1);
  return /*#__PURE__*/React.createElement(Sheet, {
    open: open,
    onClose: onClose,
    title: "AI \u52A9\u624B",
    maxHeight: "88%"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      height: "100%"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: 16,
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      alignSelf: "flex-end",
      maxWidth: "80%",
      background: "transparent",
      border: "1px solid var(--purple)",
      color: "var(--text-primary)",
      borderRadius: 14,
      borderBottomRightRadius: 4,
      padding: "10px 12px",
      fontSize: 14
    }
  }, "\u628A\u7B2C 2 \u955C\u91CD\u65B0\u51FA\u56FE\uFF0C\u8981\u66F4\u6697\u7684\u96E8\u591C\u6C1B\u56F4"), /*#__PURE__*/React.createElement("div", {
    style: {
      alignSelf: "flex-start",
      maxWidth: "92%"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      color: "var(--text-primary)",
      marginBottom: 8
    }
  }, "\u597D\u7684\uFF0C\u6B63\u5728\u4E3A\u7B2C 2 \u955C\u91CD\u65B0\u751F\u6210\u5019\u9009\u3002"), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-sunken)",
      border: "1px solid var(--border)",
      borderRadius: 12,
      padding: "8px 12px",
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement(ToolStep, {
    label: "auto_storyboard \xB7 scene_02"
  }), /*#__PURE__*/React.createElement(ToolStep, {
    label: "build_prompt \xB7 +rainy +low-key"
  }), /*#__PURE__*/React.createElement(ToolStep, {
    label: "flux_generate \xB7 4 candidates"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--teal-soft)",
      border: "1px solid rgba(0,189,176,0.4)",
      borderRadius: 12,
      padding: 12,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: "var(--teal-bright)",
      fontWeight: 600,
      marginBottom: 8,
      letterSpacing: ".04em"
    }
  }, "PARAM_FORM \xB7 FLUX"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "6px 14px",
      fontFamily: "var(--font-mono)",
      fontSize: 12
    }
  }, [["size", "1080×1920"], ["steps", "30"], ["guidance", "5.0"], ["lora", "0.85"]].map(([k, v]) => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)"
    }
  }, k), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--teal-bright)"
    }
  }, v))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 8,
      marginBottom: 10
    }
  }, [0, 1, 2, 3].map(i => /*#__PURE__*/React.createElement(CandidateImage, {
    key: i,
    selected: sel === i,
    onClick: () => setSel(i),
    style: {
      background: window.stillBg(40 + i)
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-sunken)",
      border: "1px solid var(--border-strong)",
      borderRadius: 12,
      padding: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: "var(--text-secondary)",
      marginBottom: 10
    }
  }, "\u5DF2\u9009\u7B2C 2 \u5F20\uFF0C\u662F\u5426\u7EE7\u7EED\u5408\u6210\u51FA\u7247\uFF1F"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "teal",
    size: "sm"
  }, "\u786E\u8BA4"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm"
  }, "\u53D6\u6D88")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement(Chip, {
    tone: "purple"
  }, "\u6362\u4E2A\u8FD0\u955C"), /*#__PURE__*/React.createElement(Chip, null, "\u518D\u6765 4 \u5F20"), /*#__PURE__*/React.createElement(Chip, null, "\u4E0B\u4E00\u955C"))), /*#__PURE__*/React.createElement("div", {
    style: {
      borderTop: "1px solid var(--border)",
      padding: "10px 12px calc(var(--safe-bottom) + 8px)",
      background: "var(--surface-card)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement(Chip, {
    tone: "accent",
    active: true,
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "bot",
      style: {
        width: 13,
        height: 13
      }
    })
  }, "Agent"), /*#__PURE__*/React.createElement(Chip, {
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "brain",
      style: {
        width: 13,
        height: 13
      }
    })
  }, "\u6DF1\u5EA6\u601D\u8003")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      background: "var(--surface-sunken)",
      border: "1px solid var(--border-strong)",
      borderRadius: "var(--r-btn)",
      padding: "4px 4px 4px 12px"
    }
  }, /*#__PURE__*/React.createElement("input", {
    placeholder: "\u7ED9 AI \u52A9\u624B\u53D1\u6D88\u606F\u2026",
    style: {
      flex: 1,
      background: "transparent",
      border: "none",
      outline: "none",
      color: "var(--text-primary)",
      fontSize: 14,
      fontFamily: "var(--font-sans)"
    }
  }), /*#__PURE__*/React.createElement("button", {
    "aria-label": "\u53D1\u9001",
    style: {
      width: 40,
      height: 40,
      flex: "none",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--logo-grad)",
      color: "#fff",
      border: "none",
      borderRadius: "var(--r-btn)",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "arrow-up",
    style: {
      width: 18,
      height: 18
    }
  }))))));
}
function SettingsSheet({
  open,
  onClose
}) {
  const {
    Sheet,
    Switch,
    Select,
    Button
  } = DS_ov;
  const [a, setA] = React.useState(true);
  const [b, setB] = React.useState(false);
  return /*#__PURE__*/React.createElement(Sheet, {
    open: open,
    onClose: onClose,
    title: "\u8BBE\u7F6E",
    maxHeight: "80%"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16,
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(Row, {
    label: "ComfyUI \u5730\u5740"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      color: "var(--text-secondary)"
    }
  }, "127.0.0.1:8188")), /*#__PURE__*/React.createElement(Row, {
    label: "\u5DE5\u4F5C\u76EE\u5F55",
    sub: "/Users/me/mirage/episodes"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "folder",
    style: {
      width: 18,
      height: 18,
      color: "var(--text-secondary)"
    }
  })), /*#__PURE__*/React.createElement(Row, {
    label: "\u9ED8\u8BA4\u51FA\u56FE\u6A21\u578B"
  }, /*#__PURE__*/React.createElement(Select, {
    value: "FLUX.1-dev",
    size: "sm"
  })), /*#__PURE__*/React.createElement(Row, {
    label: "GPU offload"
  }, /*#__PURE__*/React.createElement(Switch, {
    checked: a,
    onChange: setA
  })), /*#__PURE__*/React.createElement(Row, {
    label: "\u751F\u6210\u5B8C\u6210\u63D0\u793A\u97F3"
  }, /*#__PURE__*/React.createElement(Switch, {
    checked: b,
    onChange: setB
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: "var(--border)"
    }
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    full: true
  }, "\u6E05\u7A7A\u7F13\u5B58")));
}
function Row({
  label,
  sub,
  children
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      color: "var(--text-primary)"
    }
  }, label), sub && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      fontFamily: "var(--font-mono)",
      marginTop: 2
    }
  }, sub)), children);
}
Object.assign(window, {
  Drawer,
  AssistantSheet,
  SettingsSheet
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/mirage/overlays.jsx", error: String((e && e.message) || e) }); }

// ui_kits/mirage/storyboard.jsx
try { (() => {
// Storyboard tab — the core screen. Global-action card + scene cards.
const DS_sb = window.MirageDesignSystem_c5883d;
function GlobalActionCard() {
  const {
    Button,
    Select
  } = DS_sb;
  const [more, setMore] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-card)",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-card)",
      padding: 12,
      display: "flex",
      flexDirection: "column",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "purple",
    full: true,
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "image",
      style: {
        width: 16,
        height: 16
      }
    })
  }, "\u4E00\u952E\u5168\u90E8\u51FA\u56FE"), /*#__PURE__*/React.createElement(Select, {
    value: "4 \u5F20"
  }), /*#__PURE__*/React.createElement(Select, {
    value: "3:4"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: "var(--border)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "teal",
    full: true,
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "film",
      style: {
        width: 16,
        height: 16
      }
    })
  }, "\u4E00\u952E\u51FA\u7247\u5E76\u5408\u6210 \xB7 \u5DF2\u9009 4"), /*#__PURE__*/React.createElement(Select, {
    value: "Wan2.2",
    tone: "teal"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(Select, {
    label: "\u6BB5\u6570",
    value: "\u5355\u6BB5",
    tone: "teal",
    style: {
      flex: 1,
      justifyContent: "space-between"
    }
  }), /*#__PURE__*/React.createElement("button", {
    onClick: () => setMore(m => !m),
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      height: 40,
      padding: "0 12px",
      background: "transparent",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-btn)",
      color: "var(--text-secondary)",
      fontSize: 13,
      fontFamily: "var(--font-sans)",
      cursor: "pointer"
    }
  }, "\u66F4\u591A\u53C2\u6570", /*#__PURE__*/React.createElement("i", {
    "data-lucide": more ? "chevron-up" : "chevron-down",
    style: {
      width: 14,
      height: 14
    }
  }))), more && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 8,
      background: "var(--surface-sunken)",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-btn)",
      padding: 10
    }
  }, [["steps", "28"], ["guidance", "4.5"], ["seed", "88421"], ["offload", "on"]].map(([k, v]) => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      display: "flex",
      justifyContent: "space-between",
      fontFamily: "var(--font-mono)",
      fontSize: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)"
    }
  }, k), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--teal-bright)"
    }
  }, v)))));
}
function PromptEditor() {
  const [open, setOpen] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 10
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setOpen(o => !o),
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      background: "transparent",
      border: "none",
      color: "var(--text-secondary)",
      fontSize: 13,
      fontFamily: "var(--font-sans)",
      cursor: "pointer",
      padding: 0
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": open ? "chevron-down" : "chevron-right",
    style: {
      width: 15,
      height: 15
    }
  }), " \u63D0\u793A\u8BCD\u7F16\u8F91\u5668"), open && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      background: "var(--surface-sunken)",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-btn)",
      padding: 10,
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      lineHeight: 1.6,
      color: "var(--text-secondary)"
    }
  }, "rain night, two figures facing off in alley, neon reflection, cinematic, ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--purple)"
    }
  }, "<lora:ep01_xianxia:0.8>")));
}
function ContinueControls() {
  const {
    Button
  } = DS_sb;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginTop: 10,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "sparkles",
      style: {
        width: 14,
        height: 14
      }
    })
  }, "AI \u63A8\u8350\u8FD0\u955C"), /*#__PURE__*/React.createElement(Button, {
    variant: "neutral",
    size: "sm",
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "plus",
      style: {
        width: 14,
        height: 14
      }
    })
  }, "\u518D\u7EED\u4E00\u6BB5"), /*#__PURE__*/React.createElement(Button, {
    variant: "neutral",
    size: "sm",
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "undo-2",
      style: {
        width: 14,
        height: 14
      }
    })
  }, "\u64A4\u9500\u4E0A\u4E00\u6BB5"));
}
function StoryboardTab() {
  const {
    SceneCard,
    CandidateImage,
    Button,
    Switch,
    GpuLogBar,
    stillBg
  } = {
    ...DS_sb,
    stillBg: window.stillBg
  };
  const [sel, setSel] = React.useState({
    2: 0
  });
  const [lip, setLip] = React.useState({
    4: true
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement(GlobalActionCard, null), window.SCENES.map(sc => /*#__PURE__*/React.createElement(SceneCard, {
    key: sc.id,
    index: sc.id,
    title: sc.title,
    status: sc.status,
    onDelete: () => {}
  }, sc.status === "done" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 12,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 86,
      aspectRatio: "9/16",
      borderRadius: 8,
      background: window.stillBg(sc.id),
      boxShadow: "inset 0 0 0 1px var(--border)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "rgba(255,255,255,0.7)"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "play",
    style: {
      width: 22,
      height: 22
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: "var(--text-muted)"
    }
  }, "scene_0", sc.id, ".mp4 \xB7 4.2s"), /*#__PURE__*/React.createElement(Button, {
    variant: "neutral",
    size: "sm",
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "rotate-cw",
      style: {
        width: 14,
        height: 14
      }
    })
  }, "\u5220\u9664\u91CD\u51FA"))), sc.status === "review" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 8
    }
  }, [0, 1, 2, 3].map(i => /*#__PURE__*/React.createElement(CandidateImage, {
    key: i,
    selected: sel[sc.id] === i,
    onClick: () => setSel(s => ({
      ...s,
      [sc.id]: i
    })),
    style: {
      background: window.stillBg(sc.id * 7 + i)
    }
  }))), /*#__PURE__*/React.createElement(PromptEditor, null), /*#__PURE__*/React.createElement(ContinueControls, null)), sc.status === "drawing" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 8
    }
  }, [0, 1, 2, 3].map(i => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      aspectRatio: "3/4",
      borderRadius: 8,
      background: "var(--surface-sunken)",
      boxShadow: "inset 0 0 0 1px var(--border)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 18,
      height: 18,
      borderRadius: "50%",
      border: "2px solid var(--yellow)",
      borderTopColor: "transparent",
      animation: "mirageSpin .7s linear infinite"
    }
  })))), sc.status === "pending" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      fontSize: 13,
      color: "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(Switch, {
    checked: !!lip[sc.id],
    onChange: v => setLip(s => ({
      ...s,
      [sc.id]: v
    }))
  }), " \u5BF9\u53E3\u578B"), /*#__PURE__*/React.createElement(Button, {
    variant: "purple",
    size: "sm",
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "image",
      style: {
        width: 15,
        height: 15
      }
    })
  }, "\u51FA\u56FE")))), /*#__PURE__*/React.createElement(GpuLogBar, {
    state: "drawing",
    elapsed: "12s",
    lines: [{
      t: "● FLUX  scene_03  step 14/28  guidance 4.5",
      tone: "yellow"
    }, {
      t: "✓ Wan2.2 i2v → scene_01.mp4  done",
      tone: "green"
    }, {
      t: "/models/lora/ep01_xianxia.safetensors loaded",
      tone: "text-muted"
    }]
  }));
}
Object.assign(window, {
  StoryboardTab
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/mirage/storyboard.jsx", error: String((e && e.message) || e) }); }

// ui_kits/mirage/tabs.jsx
try { (() => {
// Script / Characters / Export tabs.
const DS_tabs = window.MirageDesignSystem_c5883d;
function FieldLabel({
  children
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600,
      color: "var(--text-secondary)",
      marginBottom: 6
    }
  }, children);
}
function field(extra) {
  return {
    width: "100%",
    background: "var(--surface-sunken)",
    border: "1px solid var(--border)",
    borderRadius: "var(--r-btn)",
    color: "var(--text-primary)",
    fontFamily: "var(--font-sans)",
    fontSize: 14,
    padding: "10px 12px",
    outline: "none",
    boxSizing: "border-box",
    ...extra
  };
}
function ScriptTab() {
  const {
    Button,
    Card
  } = DS_tabs;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement(FieldLabel, null, "\u5C0F\u8BF4\u539F\u6587"), /*#__PURE__*/React.createElement("textarea", {
    defaultValue: "雨点砸在霓虹招牌上，林深握紧了腰间的配枪。巷子尽头，那个熟悉的背影正缓缓转过身……",
    style: field({
      minHeight: 120,
      resize: "none",
      lineHeight: 1.6,
      fontFamily: "var(--font-mono)",
      fontSize: 13
    })
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginTop: 10,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm"
  }, "\u62C6\u6210 8 \u955C"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm"
  }, "\u66FF\u6362\u73B0\u6709\u5206\u955C")), /*#__PURE__*/React.createElement("button", {
    style: {
      marginTop: 10,
      width: "100%",
      height: 44,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 8,
      background: "var(--accent-soft)",
      border: "1px solid var(--accent-border)",
      borderRadius: "var(--r-btn)",
      color: "var(--accent)",
      fontSize: 14,
      fontWeight: 600,
      fontFamily: "var(--font-sans)",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "wand-2",
    style: {
      width: 16,
      height: 16
    }
  }), " \u4E00\u952E AI \u5206\u6790\u5C0F\u8BF4"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginTop: 6
    }
  }, "\u81EA\u52A8\u586B\u89D2\u8272 / \u98CE\u683C / LoRA / \u5206\u955C")), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      marginBottom: 12
    }
  }, "\u672C\u96C6\u98CE\u683C"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "style_prompt"), /*#__PURE__*/React.createElement("input", {
    defaultValue: "cinematic noir, rain, neon, shallow depth of field",
    style: field({
      fontFamily: "var(--font-mono)",
      fontSize: 13
    })
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement(FieldLabel, null, "\u89E6\u53D1\u8BCD"), /*#__PURE__*/React.createElement("input", {
    defaultValue: "ep01_xianxia",
    style: field({
      fontFamily: "var(--font-mono)",
      fontSize: 13
    })
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement(FieldLabel, null, "\u9ED8\u8BA4\u5C3A\u5BF8"), /*#__PURE__*/React.createElement("input", {
    defaultValue: "1080\xD71920",
    style: field({
      fontFamily: "var(--font-mono)",
      fontSize: 13
    })
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "FLUX LoRA \u8DEF\u5F84"), /*#__PURE__*/React.createElement("input", {
    defaultValue: "/models/lora/ep01_xianxia.safetensors",
    style: field({
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      color: "var(--text-secondary)"
    })
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "\u8D1F\u5411\u8BCD"), /*#__PURE__*/React.createElement("input", {
    defaultValue: "blurry, lowres, extra fingers, watermark",
    style: field({
      fontFamily: "var(--font-mono)",
      fontSize: 13
    })
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    full: true
  }, "\u4FDD\u5B58"))));
}
function CharactersTab() {
  const {
    Button,
    Card,
    Select,
    StatusBadge
  } = DS_tabs;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 600,
      color: "var(--text-secondary)"
    }
  }, "\u89D2\u8272\u5723\u7ECF"), window.CHARACTERS.map(c => /*#__PURE__*/React.createElement(Card, {
    key: c.id,
    pad: 12
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      borderRadius: "var(--r-btn)",
      background: "var(--accent-soft)",
      color: "var(--accent)",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      fontWeight: 700
    }
  }, c.name[0]), /*#__PURE__*/React.createElement("input", {
    defaultValue: c.name,
    style: {
      flex: 1,
      background: "transparent",
      border: "none",
      color: "var(--text-primary)",
      fontSize: 16,
      fontWeight: 600,
      outline: "none"
    }
  }), /*#__PURE__*/React.createElement("button", {
    "aria-label": "\u5220\u9664",
    style: {
      width: 32,
      height: 32,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      color: "var(--red)",
      background: "transparent",
      border: "none",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "trash-2",
    style: {
      width: 16,
      height: 16
    }
  }))), /*#__PURE__*/React.createElement(FieldLabel, null, "\u5916\u8C8C"), /*#__PURE__*/React.createElement("textarea", {
    defaultValue: c.look,
    style: field({
      minHeight: 56,
      resize: "none",
      fontSize: 13,
      lineHeight: 1.5
    })
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 10,
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      color: "var(--text-secondary)"
    }
  }, "\u97F3\u8272"), /*#__PURE__*/React.createElement(Select, {
    value: c.voice,
    size: "sm"
  })))), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    full: true,
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "plus",
      style: {
        width: 16,
        height: 16
      }
    })
  }, "\u6DFB\u52A0\u89D2\u8272"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 600,
      color: "var(--text-secondary)",
      marginTop: 6
    }
  }, "\u4EBA\u7269 LoRA \u8BAD\u7EC3"), window.LORAS.map(l => /*#__PURE__*/React.createElement(Card, {
    key: l.id,
    pad: 12
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 13,
      color: "var(--text-primary)",
      flex: 1,
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap"
    }
  }, l.name), /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      height: 24,
      padding: "0 9px",
      fontSize: 12,
      fontWeight: 600,
      borderRadius: "var(--r-tag)",
      color: l.status === "COMPLETED" ? "var(--green)" : "var(--yellow)",
      background: l.status === "COMPLETED" ? "var(--green-soft)" : "var(--yellow-soft)"
    }
  }, l.count, "\u5F20 \xB7 ", l.status)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "neutral",
    size: "sm",
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "upload",
      style: {
        width: 14,
        height: 14
      }
    })
  }, "\u4F20\u53C2\u8003\u56FE"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm",
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "play",
      style: {
        width: 14,
        height: 14
      }
    })
  }, "\u5F00\u59CB\u8BAD\u7EC3")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)",
      marginTop: 8,
      fontFamily: "var(--font-mono)"
    }
  }, "\u540E\u7AEF\u5F85\u63A5\u5165 Colab"))));
}
function ExportTab() {
  const {
    Button,
    Card
  } = DS_tabs;
  const presets = [["抖音", "1080×1920"], ["视频号", "1080×1920"], ["快手", "1080×1920"], ["YouTube Shorts", "1080×1920"]];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      width: "100%",
      aspectRatio: "9/16",
      maxHeight: 360,
      margin: "0 auto",
      borderRadius: "var(--r-card)",
      overflow: "hidden",
      background: window.stillBg(2),
      boxShadow: "inset 0 0 0 1px var(--border)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 64,
      height: 64,
      borderRadius: "50%",
      background: "rgba(0,0,0,0.45)",
      backdropFilter: "blur(4px)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "#fff"
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "play",
    style: {
      width: 26,
      height: 26
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 12,
      right: 12,
      bottom: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 3,
      borderRadius: 2,
      background: "rgba(255,255,255,0.25)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "38%",
      height: "100%",
      borderRadius: 2,
      background: "var(--accent)"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      marginTop: 6,
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: "rgba(255,255,255,0.8)"
    }
  }, /*#__PURE__*/React.createElement("span", null, "00:16"), /*#__PURE__*/React.createElement("span", null, "00:42")))), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    full: true,
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "download",
      style: {
        width: 16,
        height: 16
      }
    })
  }, "\u4E0B\u8F7D\u6574\u96C6 mp4"), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      marginBottom: 4
    }
  }, "\u5E73\u53F0\u5BFC\u51FA\u9884\u8BBE"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginBottom: 12
    }
  }, "\u9884\u7559"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 8
    }
  }, presets.map(([name, size]) => /*#__PURE__*/React.createElement("div", {
    key: name,
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "10px 12px",
      background: "var(--surface-sunken)",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-btn)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "smartphone",
    style: {
      width: 16,
      height: 16,
      color: "var(--text-secondary)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14
    }
  }, name)), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      color: "var(--text-muted)"
    }
  }, size))))));
}
Object.assign(window, {
  ScriptTab,
  CharactersTab,
  ExportTab
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/mirage/tabs.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.Chip = __ds_scope.Chip;

__ds_ns.IconButton = __ds_scope.IconButton;

__ds_ns.Logo = __ds_scope.Logo;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.StatChip = __ds_scope.StatChip;

__ds_ns.StatusBadge = __ds_scope.StatusBadge;

__ds_ns.Switch = __ds_scope.Switch;

__ds_ns.TabRail = __ds_scope.TabRail;

__ds_ns.CandidateImage = __ds_scope.CandidateImage;

__ds_ns.FAB = __ds_scope.FAB;

__ds_ns.GpuLogBar = __ds_scope.GpuLogBar;

__ds_ns.SceneCard = __ds_scope.SceneCard;

__ds_ns.Sheet = __ds_scope.Sheet;

})();
