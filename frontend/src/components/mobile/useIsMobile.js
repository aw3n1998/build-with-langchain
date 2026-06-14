import { useState, useEffect } from 'react'

/**
 * 视口宽度 ≤ breakpoint(默认 768px,平板竖屏以下)判定为手机端,
 * 命中则 App 渲染 MobileShell（短剧工作台移动端自适应）。
 * 监听 resize/旋转,桌面端不受影响。
 */
export default function useIsMobile(breakpoint = 768) {
  const get = () => (typeof window !== 'undefined'
    ? window.matchMedia(`(max-width: ${breakpoint}px)`).matches : false)
  const [mobile, setMobile] = useState(get)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint}px)`)
    const on = () => setMobile(mq.matches)
    mq.addEventListener ? mq.addEventListener('change', on) : mq.addListener(on)
    return () => { mq.removeEventListener ? mq.removeEventListener('change', on) : mq.removeListener(on) }
  }, [breakpoint])
  return mobile
}
