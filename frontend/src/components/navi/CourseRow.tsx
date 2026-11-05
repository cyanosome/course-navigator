import { Link } from 'react-router-dom'
import { useNavi } from '../../navi/state'
import type { PaneState } from '../../navi/state'
import type { RowView } from '../../navi/views'
import Icon from './Icon'

interface CourseRowProps {
  row: RowView
  /** 詳細へ進むときに履歴に積む道筋 */
  linkState: PaneState
  /** PC の一覧で、中央に出している科目 */
  current?: boolean
  /** 行を押して詳細へ進むとき（研究のログ result_click など） */
  onOpen?: () => void
}

/**
 * 科目の一覧の1行（E1 0章・4章）。左に曜限・単位（いまの学期と違えば学期）、右に科目名・授業でやること・重なり・なぜ。
 * 行を押すと詳細、右の＋で候補に入れる。
 */
export default function CourseRow({ row, linkState, current = false, onOpen }: CourseRowProps) {
  return (
    <li className="row" aria-current={current ? 'true' : undefined}>
      <Link className="row-link" to={row.href} state={linkState} onClick={onOpen}>
        <span className="slot">
          {row.slotLines.map((s) => (
            <span key={s} className={row.clash !== null ? 'slot-time is-clash' : 'slot-time'}>
              {s}
            </span>
          ))}
          <span className="slot-cr">
            {row.credits !== null ? (
              `${row.credits}単位`
            ) : (
              // E1 8章: 単位は「記載なし」。左の列（40px）に収まるよう2行に分ける
              <>
                <span className="vh">単位は</span>
                記載
                <wbr />
                なし
              </>
            )}
          </span>
          {row.termNote !== null && <span className="slot-cr">{row.termNote}</span>}
        </span>
        <span className="row-body">
          <span className="name">
            {row.name}
            {row.faculty !== null && <span className="fac"> {row.faculty}</span>}
          </span>
          <span className={row.learnMissing ? 'learn is-missing' : 'learn'}>{row.learn}</span>
          {row.clash !== null && (
            <span className="clash-line">
              <span className="ic-wrap">
                <Icon name="warn" small />
              </span>
              <span>{row.clash}</span>
            </span>
          )}
          {row.why !== null && (
            <span className="why">
              <span className="ic-wrap">
                <Icon name="why" small />
              </span>
              <span>
                <span className="vh">なぜ: </span>
                {row.why}
                {row.source !== null && `（${row.source}）`}
              </span>
            </span>
          )}
        </span>
      </Link>
      {row.required ? (
        <span className="add is-fixed">
          <Icon name="check" />
          <span className="vh">必修なので、時間割に入れてあります</span>
        </span>
      ) : (
        <AddButton code={row.code} name={row.name} />
      )}
    </li>
  )
}

interface AddButtonProps {
  code: string
  name: string
}

/** 一覧の＋（読み上げは「無機化学を候補に入れる」）。押すとすぐ緑の輪とチェックに変わり、もう一度押すと外れる */
function AddButton({ code, name }: AddButtonProps) {
  const { isKept, toggleKeep } = useNavi()
  const kept = isKept(code)
  return (
    <button
      className="add"
      type="button"
      aria-pressed={kept}
      aria-label={kept ? `${name}を候補に入れた（もう一度押すと外す）` : `${name}を候補に入れる`}
      onClick={() => toggleKeep(code)}
    >
      <Icon name={kept ? 'check' : 'plus'} />
    </button>
  )
}
