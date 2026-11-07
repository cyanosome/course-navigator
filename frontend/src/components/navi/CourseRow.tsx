import { Link } from 'react-router-dom'
import type { ShortlistFrom } from '../../navi/research'
import { useNavi } from '../../navi/state'
import type { PaneState } from '../../navi/state'
import { useDiagnose } from '../../navi/useDiagnose'
import { useFlags } from '../../navi/variant'
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
  /** ＋で候補に入れたときの「どこから」（研究のログ。省くと unknown） */
  keepFrom?: ShortlistFrom
}

/**
 * 科目の一覧の1行（E1 0章・4章）。左に曜限・単位（いまの学期と違えば学期）、右に科目名・授業でやること・重なり・なぜ。
 * 行を押すと詳細、右の＋で候補に入れる。
 * 診断の変種（diagnose=quiz）では、行から授業でやることを外し（デザインのコンペの U-a）、右は［入れる］［外す］で
 * プランへの足し外しにする（プランの画面の行と同じ形。プランがまだ無ければ出さない）。
 */
export default function CourseRow({ row, linkState, current = false, onOpen, keepFrom }: CourseRowProps) {
  const planMode = useFlags().diagnose === 'quiz'
  return (
    <li className={planMode ? 'row is-plan' : 'row'} aria-current={current ? 'true' : undefined}>
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
          {!planMode && <span className={row.learnMissing ? 'learn is-missing' : 'learn'}>{row.learn}</span>}
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
      {planMode ? (
        <PlanButton code={row.code} name={row.name} from={keepFrom} />
      ) : row.required ? (
        <span className="add is-fixed">
          <Icon name="check" />
          <span className="vh">必修なので、時間割に入れてあります</span>
        </span>
      ) : (
        <AddButton code={row.code} name={row.name} from={keepFrom} />
      )}
    </li>
  )
}

/** 診断の変種の［入れる］［外す］（プランへの足し外し。NaviApp の toggleKeep がプランを直す） */
function PlanButton({ code, name, from }: AddButtonProps) {
  const { isKept, toggleKeep } = useNavi()
  const { working } = useDiagnose()
  if (working === null) return <span />
  const kept = isKept(code)
  return (
    <button
      className="pr-act"
      type="button"
      aria-label={kept ? `${name}をプランから外す` : `${name}をプランに入れる`}
      onClick={() => toggleKeep(code, from)}
    >
      {kept ? '外す' : '入れる'}
    </button>
  )
}

interface AddButtonProps {
  code: string
  name: string
  from?: ShortlistFrom
}

/** 一覧の＋（読み上げは「無機化学を候補に入れる」）。押すとすぐ緑の輪とチェックに変わり、もう一度押すと外れる */
function AddButton({ code, name, from }: AddButtonProps) {
  const { isKept, toggleKeep } = useNavi()
  const kept = isKept(code)
  return (
    <button
      className="add"
      type="button"
      aria-pressed={kept}
      aria-label={kept ? `${name}を候補に入れた（もう一度押すと外す）` : `${name}を候補に入れる`}
      onClick={() => toggleKeep(code, from)}
    >
      <Icon name={kept ? 'check' : 'plus'} />
    </button>
  )
}
