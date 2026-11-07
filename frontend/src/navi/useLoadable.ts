import { useEffect, useState } from 'react'

export type Loadable<T> = { status: 'loading' } | { status: 'ready'; value: T } | { status: 'failed'; error: unknown }

export const LOADING: Loadable<never> = { status: 'loading' }

/**
 * key が変わるたびに load を呼び、結果を返す（key が null なら呼ばずに null）。
 * key には load の入力をすべて含め、load は useCallback で作る。前の問い合わせは中断し、その結果は捨てる。
 * 失敗は console.error に残し、failed として返す。
 */
export function useLoadable<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
  what: string,
): Loadable<T> | null {
  const [done, setDone] = useState<{ key: string; result: Loadable<T> } | null>(null)
  useEffect(() => {
    if (key === null) return
    const control = new AbortController()
    load(control.signal).then(
      (value) => {
        if (!control.signal.aborted) setDone({ key, result: { status: 'ready', value } })
      },
      (error: unknown) => {
        if (control.signal.aborted) return
        console.error(`${what}を読み込めませんでした`, error)
        setDone({ key, result: { status: 'failed', error } })
      },
    )
    return () => control.abort()
  }, [key, load, what])
  if (key === null) return null
  return done !== null && done.key === key ? done.result : LOADING
}
