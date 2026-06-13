/**
 * 统一图标集 —— lucide 风格的细线描边 SVG，单色（继承父级 currentColor）。
 *
 * 为什么不用 emoji：emoji 跨平台渲染不一、彩色卡通感拉低专业度。描边图标随文字色走，
 * 在暗色 UI 里干净统一，放进按钮/标签即「图标 + 文案」的克制排版。
 *
 * 用法：<Icon.Plus />、<Icon.Film size={18} />、<Icon.Mic style={{opacity:.8}}/>
 * 默认 15px、描边 1.7、圆角端点；尺寸/颜色都可被父级覆盖。
 */
import React from 'react'

function S({ size = 15, stroke = 1.7, children, style, ...rest }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round"
         style={{ flexShrink: 0, display: 'block', ...style }} aria-hidden {...rest}>
      {children}
    </svg>
  )
}

export const Icon = {
  // 场记板：短剧工作台 logo / 分镜
  Clapper: (p) => <S {...p}><path d="M20.2 6 3 11M4 11l16-4.5M5.5 6.5l2 4M10 5l2 4M14.5 3.7l2 4" /><rect x="3" y="11" width="18" height="9" rx="2" /></S>,
  // 加号：新建
  Plus: (p) => <S {...p}><path d="M12 5v14M5 12h14" /></S>,
  // 文件夹：工作目录
  Folder: (p) => <S {...p}><path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></S>,
  // 对话气泡：AI 助手
  Chat: (p) => <S {...p}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.5A8 8 0 1 1 21 12z" /></S>,
  // 铅笔：重命名
  Pencil: (p) => <S {...p}><path d="m4 20 4-1 9.5-9.5a2 2 0 0 0-2.8-2.8L5 16zM13 6l3 3" /></S>,
  // 垃圾桶：删除
  Trash: (p) => <S {...p}><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M10 11v6M14 11v6" /></S>,
  // 魔棒：AI 生成 / 推荐
  Wand: (p) => <S {...p}><path d="m4 20 9-9M14 4l.8 2.2L17 7l-2.2.8L14 10l-.8-2.2L11 7l2.2-.8zM19 12l.5 1.5L21 14l-1.5.5L19 16l-.5-1.5L17 14l1.5-.5z" /></S>,
  // 双人：角色圣经
  Users: (p) => <S {...p}><path d="M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM22 19v-1a4 4 0 0 0-3-3.85M16 4.15A3.5 3.5 0 0 1 16 11" /></S>,
  // 分镜格：分镜制作
  Layers: (p) => <S {...p}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M7 20h10M9 16v4M15 16v4" /></S>,
  // 下载：导出 / 下载成片
  Download: (p) => <S {...p}><path d="M12 4v11m0 0 4-4m-4 4-4-4M5 19h14" /></S>,
  // 麦克风：对口型
  Mic: (p) => <S {...p}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></S>,
  // 人脸框：人物 LoRA（锁定一张脸）
  Face: (p) => <S {...p}><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M9 10h.01M15 10h.01M9 15c1 1 5 1 6 0" /></S>,
  // 撤销
  Undo: (p) => <S {...p}><path d="M9 7 4 12l5 5M4 12h11a5 5 0 0 1 0 10h-1" /></S>,
  // 文稿：剧本
  Script: (p) => <S {...p}><path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" /><path d="M14 3v4h4M8 12h8M8 16h6" /></S>,
  // 调色板：本集风格
  Palette: (p) => <S {...p}><path d="M12 3a9 9 0 1 0 0 18 2 2 0 0 0 1.5-3.3 2 2 0 0 1 1.5-3.2H17a4 4 0 0 0 4-4c0-4.2-4-7.5-9-7.5z" /><path d="M7.5 12h.01M9.5 8h.01M14.5 7.5h.01" /></S>,
  // 刷新
  Refresh: (p) => <S {...p}><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v4h-4" /></S>,
}

export default Icon
