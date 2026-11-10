import { useEffect, useId } from 'react'
import type { CSSProperties } from 'react'
import { Navigate } from 'react-router-dom'
import '../../navi/diagnose.css'
import '../../navi/study.css'
import { apiErrorMessage } from '../../navi/api'
import type { DiagnoseConfig, DiagnoseQuestion } from '../../navi/apiTypes'
import { firstUnanswered, isAnswered, isPickBlocked, planTermLabel, SCALE_POINTS, selectedIds } from '../../navi/diagnose'
import { useNavi } from '../../navi/state'
import { termIndex } from '../../navi/timetable'
import { useDiagnose } from '../../navi/useDiagnose'
import { useHistory } from '../../navi/useHistory'
import { useVariant } from '../../navi/variant'
import Icon from './Icon'
import PastTermScreen from './PastTermScreen'
import PlanScreen from './PlanScreen'
import TermChangeScreen from './TermChangeScreen'
import { TermPicker } from './TermTable'

/**
 * 診断の画面（/navi/diagnose。旗 diagnose=quiz のときだけ）。作る場所（PlanLayout の左）に出す。
 * 設定（GET /api/diagnose/config）から質問を1問ずつ組み立て、全部答えたら送ってプランを出す（PlanScreen）。
 * 状態と記録はすべて navi/useDiagnose.ts（この部品は値を出して、押されたら関数を呼ぶだけ）。
 * 取った科目を記録しているとき（調査のモードでないとき。navi/useHistory）: 今の学期をまだ選んでいなければ学期の表の
 * ボタン（TermPicker）、学期が切り替わっていれば切り替わりの画面（TermChangeScreen）を先に出す。今の学期より前の学期を
 * 見ているときは、プランの代わりに取った科目（PastTermScreen）
 */
export default function DiagnoseScreen() {
  const { flags, variantId } = useVariant()
  const d = useDiagnose()
  const history = useHistory()
  const { focusTerm } = useNavi()
  const { markShown } = d
  useEffect(() => {
    if (flags.diagnose === 'quiz') markShown()
  }, [flags.diagnose, markShown])

  // 旗を受け取る前（variantId が null）は、診断の無い既定の旗なので、まだ送り返さない
  if (flags.diagnose !== 'quiz' && variantId !== null) return <Navigate to="/navi" replace />
  if (flags.diagnose === 'quiz' && history.enabled && history.current === null) {
    return (
      <div className="page pl-page">
        <TermPicker mode="first" />
      </div>
    )
  }
  if (flags.diagnose === 'quiz' && history.change !== null) {
    return (
      <div className="page pl-page">
        <TermChangeScreen from={history.change.from} to={history.change.to} />
      </div>
    )
  }
  if (flags.diagnose !== 'quiz' || d.config === null || d.config.status === 'loading') {
    return (
      <div className="page pl-page">
        <p className="text" role="status">
          読み込んでいます
        </p>
      </div>
    )
  }
  if (d.config.status === 'failed') {
    return (
      <div className="page pl-page">
        <div role="alert">
          <h1 className="title">質問を読み込めませんでした</h1>
          <p className="text">{apiErrorMessage(d.config.error)}</p>
        </div>
        <div className="page-acts">
          <button className="primary" type="button" onClick={d.reloadConfig}>
            もう一度読み込む
          </button>
        </div>
      </div>
    )
  }
  const config = d.config.value
  const past = history.currentIdx !== null && termIndex(focusTerm) < history.currentIdx
  return (
    <div className="page pl-page">
      {d.phase === 'plan' && d.working !== null ? (
        past ? (
          <PastTermScreen plan={d.working} />
        ) : (
          <PlanScreen plan={d.working} />
        )
      ) : d.phase === 'answering' ? (
        <QuestionStep config={config} />
      ) : (
        <Intro config={config} />
      )}
    </div>
  )
}

/**
 * 診断の最初の画面。取った科目を記録しているときは、埋めるのは今の学期から先だけ（その学期を挙げる）。
 * 今の学期が診断の学期より後なら作れない（backend は 422）。取った科目か登録済みの科目があれば、送ることを1行で書く
 */
function Intro({ config }: { config: DiagnoseConfig }) {
  const { start } = useDiagnose()
  const history = useHistory()
  const from = history.currentIdx
  const filled = config.scope.terms.filter((t) => from === null || termIndex({ year: t.year, half: t.term }) >= from)
  const last = config.scope.terms.at(-1)
  const sends = history.stored.records.some((r) => r.courses.length > 0) || history.stored.registered.length > 0
  if (filled.length === 0) {
    return (
      <>
        <h1 className="title">プランを作る</h1>
        <p className="lead">この診断は{last === undefined ? '' : planTermLabel(last)}までです。</p>
      </>
    )
  }
  return (
    <>
      <h1 className="title">プランを作る</h1>
      <p className="lead">
        {config.questions.length}問に答えると、{filled.map(planTermLabel).join('と')}の科目を選んで出します。
      </p>
      {sends && <p className="text">取った科目も送ります。サーバーには残りません。</p>}
      <div className="page-acts">
        <button className="primary" type="button" onClick={start}>
          はじめる
        </button>
      </div>
    </>
  )
}

function QuestionStep({ config }: { config: DiagnoseConfig }) {
  const { answers, index, goTo, submit, submitting, notice, plan, backToPlan } = useDiagnose()
  const q = config.questions[index]
  if (q === undefined) return <p className="text">質問がありません。</p>
  const last = index === config.questions.length - 1
  const answered = isAnswered(q, answers[q.id])
  const lacking = firstUnanswered(config, answers)
  return (
    <>
      <p className="diag-count" aria-live="polite">
        {index + 1} / {config.questions.length}
      </p>
      <QuestionField key={q.id} q={q} />
      {notice !== null && (
        <p className="msg-line chk-note" role="alert">
          <span className="ic-wrap">
            <Icon name="warn" small />
          </span>
          <span>{notice.message}</span>
        </p>
      )}
      <div className="page-acts">
        {last ? (
          <button className="primary" type="button" disabled={submitting || lacking >= 0} onClick={submit}>
            {submitting ? '作っています' : 'プランを出す'}
          </button>
        ) : (
          <button className="primary" type="button" disabled={!answered} onClick={() => goTo(index + 1)}>
            次へ
          </button>
        )}
        {index > 0 && (
          <button className="text-btn" type="button" onClick={() => goTo(index - 1)}>
            前へ
          </button>
        )}
        {last && lacking >= 0 && (
          <button className="text-btn" type="button" onClick={() => goTo(lacking)}>
            答えていない質問へ
          </button>
        )}
        {plan !== null && (
          <button className="text-btn" type="button" onClick={backToPlan}>
            プランに戻る
          </button>
        )}
      </div>
    </>
  )
}

/** 1問の答えの欄。single はラジオ、multi はチェック（上限まで）、scale5 は 1〜5（n 番目の選択肢の文を添える） */
function QuestionField({ q }: { q: DiagnoseQuestion }) {
  const { answers, pick, scale } = useDiagnose()
  const name = useId()
  if (q.kind === 'scale5') {
    const value = answers[q.id]
    return (
      <fieldset className="q-item">
        <legend className="q-legend">{q.text}</legend>
        <div className="q-scale" style={{ '--n': SCALE_POINTS.length } as CSSProperties}>
          {SCALE_POINTS.map((v) => (
            <label key={v} className="q-opt">
              <input type="radio" name={name} checked={value === v} onChange={() => scale(q, v)} />
              <span>{q.options[v - 1]?.label ?? v}</span>
            </label>
          ))}
        </div>
      </fieldset>
    )
  }
  const picked = selectedIds(answers, q.id)
  const multi = q.kind === 'multi'
  return (
    <fieldset className="q-item">
      <legend className="q-legend">{q.text}</legend>
      <ul className="pick-list">
        {q.options.map((o) => (
          <li key={o.id}>
            <label>
              <input
                type={multi ? 'checkbox' : 'radio'}
                name={name}
                checked={picked.includes(o.id)}
                disabled={isPickBlocked(q, answers, o.id)}
                onChange={() => pick(q, o.id)}
              />
              <span>{o.label}</span>
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  )
}
