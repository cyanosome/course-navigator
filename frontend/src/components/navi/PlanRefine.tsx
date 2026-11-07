import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import '../../navi/diagnose.css'
import type { EventPayload } from '../../navi/apiTypes'
import { findPlanCourse, inPlan } from '../../navi/diagnose'
import type { WorkingPlan } from '../../navi/diagnose'
import { formatClock, useElapsedSeconds } from '../../navi/hooks'
import { useResearchLog } from '../../navi/research'
import { courseHref, DIAGNOSE_HREF } from '../../navi/state'
import { useDiagnose } from '../../navi/useDiagnose'
import type { PlanAddResult } from '../../navi/useDiagnose'
import { usePlanRefine } from '../../navi/usePlanRefine'
import type { RefineSession } from '../../navi/usePlanRefine'
import Icon from './Icon'

const ADD_MESSAGE: Record<Exclude<PlanAddResult, 'added' | 'already'>, string> = {
  unmapped: '学年か学期が読めないので、プランに入れられません。',
  failed: '科目のデータを読めませんでした。',
}

/**
 * プランの微修正（旗 diagnose=quiz かつ assistant=on のときだけ。呼ぶ側の PlanView が出し分ける）。仮の置き方。
 * 状態と送信は navi/usePlanRefine.ts、プランの足し外しは navi/useDiagnose.ts。
 */
export default function PlanRefine({ plan }: { plan: WorkingPlan }) {
  const { session, send, cancel } = usePlanRefine()
  const [draft, setDraft] = useState('')
  const inputId = useId()
  const noteId = useId()
  const waiting = session?.status === 'waiting'

  return (
    <section className="sec" aria-labelledby={`${inputId}-h`}>
      <h2 className="sec-label" id={`${inputId}-h`}>
        AIに頼んで直す
      </h2>
      <form
        className="refine-form"
        onSubmit={(e) => {
          e.preventDefault()
          const text = draft.trim()
          if (text !== '') send(text)
        }}
      >
        <label className="vh" htmlFor={inputId}>
          プランをどう変えたいか
        </label>
        <div className="field">
          <input
            id={inputId}
            value={draft}
            placeholder="例：月曜を空けたい"
            aria-describedby={noteId}
            onChange={(e) => setDraft(e.target.value)}
            disabled={waiting}
          />
        </div>
        <p className="src" id={noteId}>
          入力した文とプランは外部のAIサービスに送られます。名前や学籍番号は書かないでください。
        </p>
        <div className="page-acts">
          <button className="primary" type="submit" disabled={waiting || draft.trim() === ''}>
            送る
          </button>
        </div>
      </form>
      {session !== null && <RefineResult session={session} plan={plan} onCancel={cancel} onResend={() => send(session.request, { retry: true })} />}
    </section>
  )
}

interface RefineResultProps {
  session: RefineSession
  plan: WorkingPlan
  onCancel: () => void
  onResend: () => void
}

interface SuggestionRow {
  code: string
  title: string
  reason: string
  /** add・remove は AI の提案、source は提案が無いときの出典 */
  kind: 'add' | 'remove' | 'source'
}

function RefineResult({ session, plan, onCancel, onResend }: RefineResultProps) {
  const { addToPlan, removeFromPlan } = useDiagnose()
  const { log } = useResearchLog()
  const waiting = session.status === 'waiting'
  const seconds = useElapsedSeconds(session.startedAt, waiting)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  if (waiting) {
    return (
      <div className="ask-wait">
        <p role="status">「{session.request}」で直しています。ふだん30秒〜1分半ほどです。ほかの画面を見ていても続きます。</p>
        <div className="ask-wait-row">
          <span className="clock">
            経過 <span aria-hidden="true">{formatClock(seconds)}</span>
          </span>
          <button className="text-btn" type="button" onClick={onCancel}>
            やめる
          </button>
        </div>
      </div>
    )
  }

  if (session.status !== 'done' || session.result === null) {
    const text =
      session.status === 'timeout'
        ? '3分たっても回答が届かないため、待つのをやめました。'
        : session.status === 'empty'
          ? '頼みに合う科目は見つかりませんでした。'
          : '回答を作れませんでした（サーバーにつながりません）。プランはこのまま使えます。'
    return (
      <div className="msg">
        <p className="msg-line" role="status">
          <span className="ic-wrap">
            <Icon name="warn" small />
          </span>
          <span>{text}</span>
        </p>
        <div className="msg-acts">
          {session.status !== 'empty' && (
            <button className="text-btn" type="button" onClick={onResend}>
              もう一度送る
            </button>
          )}
          <button className="text-btn" type="button" onClick={onCancel}>
            閉じる
          </button>
        </div>
      </div>
    )
  }

  const result = session.result
  const suggestions = session.suggestions
  const paragraphs = result.answer.split(/\n{2,}/).filter((p) => p.trim() !== '')
  const nameOf = (code: string, title: string | null) => title ?? findPlanCourse(plan, code)?.course.name ?? code
  // 提案があればそれを、無ければ（plan_context を知らないサーバー・静的経路）出典の科目を出す
  const rows: SuggestionRow[] =
    suggestions !== null
      ? [
          ...suggestions.add.map((s): SuggestionRow => ({ code: s.syllabus_id, title: nameOf(s.syllabus_id, s.title), reason: s.reason, kind: 'add' })),
          ...suggestions.remove.map((s): SuggestionRow => ({ code: s.syllabus_id, title: nameOf(s.syllabus_id, s.title), reason: s.reason, kind: 'remove' })),
        ]
      : result.sources.map((s): SuggestionRow => ({ code: s.code, title: s.title, reason: s.schedule ?? '', kind: 'source' }))
  const dropped = suggestions?.dropped.length ?? 0

  const toggle = (row: SuggestionRow) => {
    setMessage(null)
    const detail: EventPayload = { suggestion: row.kind, refine_local_id: session.localId }
    if (inPlan(plan, row.code)) {
      removeFromPlan(row.code, 'refine', detail)
      return
    }
    setBusy(row.code)
    void addToPlan(row.code, 'refine', detail).then((r) => {
      setBusy(null)
      if (r === 'unmapped' || r === 'failed') setMessage(ADD_MESSAGE[r])
    })
  }

  return (
    <div className="refine-result">
      {session.delivery === 'not_supported' && (
        <p className="msg-line chk-note" role="status">
          <span className="ic-wrap">
            <Icon name="warn" small />
          </span>
          <span>プランはAIに届いていません。回答はプランを見ずに作られています。</span>
        </p>
      )}
      <div className="ask-full">
        {paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
        <p className="src">AIの説明は間違うことがあります。シラバスの原文で確かめてください。</p>
      </div>
      <ul className="lines refine-list">
        {rows.map((row, i) => {
          const here = inPlan(plan, row.code)
          const href = courseHref(row.code, { kind: 'plan' })
          return (
            <li key={`${row.kind}-${row.code}`}>
              <span className="refine-item">
                {row.kind !== 'source' && <span className="refine-kind">{row.kind === 'add' ? '足す' : '外す'}</span>}
                <Link
                  to={href}
                  state={{ trail: [{ label: 'プラン', href: DIAGNOSE_HREF }, { label: row.title, href }], tab: 'search' }}
                  onClick={() => {
                    log('result_click', { syllabus_id: row.code, rank: i + 1, list: 'refine', refine_local_id: session.localId })
                    log('citation_click', { syllabus_id: row.code, rank: i + 1, refine_local_id: session.localId })
                  }}
                >
                  {row.title}
                </Link>
                {row.reason !== '' && <span className="meta">{row.reason}</span>}
              </span>
              <button className="text-btn" type="button" disabled={busy === row.code} aria-pressed={here} onClick={() => toggle(row)}>
                {here ? 'プランから外す' : 'プランに入れる'}
              </button>
            </li>
          )
        })}
      </ul>
      {dropped > 0 && <p className="src">確かめられなかった提案が{dropped}件あり、出していません。</p>}
      {message !== null && (
        <p className="msg-line chk-note" role="alert">
          <span className="ic-wrap">
            <Icon name="warn" small />
          </span>
          <span>{message}</span>
        </p>
      )}
      <div className="msg-acts">
        <button className="text-btn" type="button" onClick={onCancel}>
          この回答を閉じる
        </button>
      </div>
    </div>
  )
}
