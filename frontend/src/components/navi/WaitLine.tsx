import { useNavigate } from 'react-router-dom'
import { formatClock, useElapsedSeconds } from '../../navi/hooks'
import { useNavi } from '../../navi/state'
import Glyph from './Glyph'

/**
 * 自由記述の状態の1行（UX 仕様 C08、DESIGN.md 3.3）。スマホは下部ナビのすぐ上、PC は見出しの下。
 * 読み上げは状態の文だけで、経過の数字は読み上げない（requirements.md R6-2）。
 */
export default function WaitLine() {
  const { ask, cancelAsk } = useNavi()
  const navigate = useNavigate()
  const waiting = ask?.status === 'waiting'
  const seconds = useElapsedSeconds(ask?.startedAt ?? 0, waiting)
  if (ask === null) return null

  const view = () => navigate(`/navi/ask/${encodeURIComponent(ask.localId)}`)

  if (waiting) {
    return (
      <div className="wait">
        <span className="pulse" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <p className="wait__text">
          <span role="status">回答を作っています</span>{' '}
          <span className="wait__time" aria-hidden="true">
            {formatClock(seconds)}
          </span>
        </p>
        <button className="btn" type="button" onClick={cancelAsk}>
          やめる
        </button>
      </div>
    )
  }

  if (ask.status === 'done') {
    return (
      <div className="wait wait--done">
        <p className="wait__text" role="status">
          回答が届きました
        </p>
        <button className="btn btn--ink" type="button" onClick={view}>
          見る
        </button>
      </div>
    )
  }

  const text =
    ask.status === 'empty'
      ? '合う科目が見つかりませんでした'
      : ask.status === 'timeout'
        ? '回答が届かないため、待つのをやめました'
        : '回答を作れませんでした'
  return (
    <div className="wait wait--error">
      <Glyph name="warn" />
      <p className="wait__text" role="status">
        {text}
      </p>
      <button className="btn" type="button" onClick={view}>
        見る
      </button>
    </div>
  )
}
