import { useEffect, useState, useSyncExternalStore } from 'react'

/** PC（幅 840px 以上）とスマホの切り替え（UX 仕様 5.3。Material 3 の expanded の幅） */
export const PC_QUERY = '(min-width: 840px)'

/** 動きを減らす設定（知らせを動かさずに4秒出す。E1 5章） */
export const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
  )
}

/** 待ちの経過秒。running のあいだ1秒ごとに描き直す */
export function useElapsedSeconds(startedAt: number, running: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  return Math.max(0, Math.floor((now - startedAt) / 1000))
}

/** 経過の表示（例 0:24）。数字は等幅なので桁が変わっても揺れない（DESIGN.md 2.3） */
export function formatClock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** 使った時間の表示（例 4分12秒） */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(total / 60)}分${total % 60}秒`
}
