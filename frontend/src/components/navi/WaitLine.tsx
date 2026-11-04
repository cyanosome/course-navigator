import { useNavigate } from 'react-router-dom'
import { formatClock, useElapsedSeconds } from '../../navi/hooks'
import { useNavi } from '../../navi/state'
import Icon from './Icon'

/**
 * 自由記述の状態の1行（UX 仕様 C08）。スマホは下のタブのすぐ上、PC は上の帯の下。
 * 読み上げは状態の文だけで、経過の数字は読み上げない（requirements.md R6-2）。点滅などの動きは付けない（E1 0章）。
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
        <p role="status">回答を作っています</p>
        <span className="clock" aria-hidden="true">
          {formatClock(seconds)}
        </span>
        <span className="spacer" />
        <button className="text-btn" type="button" onClick={cancelAsk}>
          やめる
        </button>
      </div>
    )
  }

  const text =
    ask.status === 'done'
      ? '回答が届きました'
      : ask.status === 'empty'
        ? '合う科目が見つかりませんでした'
        : ask.status === 'timeout'
          ? '回答が届かないため、待つのをやめました'
          : '回答を作れませんでした'
  return (
    <div className="wait">
      {ask.status !== 'done' && (
        <span className="err">
          <Icon name="warn" small />
        </span>
      )}
      <p role="status">{text}</p>
      <span className="spacer" />
      <button className="text-btn" type="button" onClick={view}>
        見る
      </button>
    </div>
  )
}
