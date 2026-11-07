import { useEffect, useId, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import '../../navi/plan.css'
import type { EventPayload } from '../../navi/apiTypes'
import { useNaviData } from '../../navi/dataSource'
import { addCourseToPlan, findPlanCourse, inPlan, removeCourseFromPlan } from '../../navi/diagnose'
import type { WorkingPlan } from '../../navi/diagnose'
import { formatClock, useElapsedSeconds } from '../../navi/hooks'
import { ledgerTerms, proposalEffects } from '../../navi/ledger'
import type { CourseMapping } from '../../navi/mapping'
import { useResearchLog } from '../../navi/research'
import { courseHref, DIAGNOSE_AI_HREF, DIAGNOSE_HREF, useNavi } from '../../navi/state'
import { buildStatus, statusCoursesFromPlan } from '../../navi/status'
import { resolveCourse } from '../../navi/timetable'
import { useDiagnose } from '../../navi/useDiagnose'
import { useLedger } from '../../navi/useLedger'
import { usePlanRefine } from '../../navi/usePlanRefine'
import type { RefineSession } from '../../navi/usePlanRefine'
import { useFlags } from '../../navi/variant'
import Accordion from './Accordion'
import BackLink from './BackLink'
import Icon from './Icon'

const ROOT = { label: 'プラン', href: DIAGNOSE_HREF }

/**
 * プランの直しを AI に頼む画面（/navi/diagnose/ai。旗 diagnose=quiz かつ assistant=on のときだけ。デザインのコンペの U-a）。
 * 返事は会話の文でなく「外す／入れる」の行で、1行ずつ選んで［この案にする］で入れる。案を入れた場合の単位・重なり・
 * 要確認の数の変わり方は、この欄の中だけで出す（右の列とスマホの帯は、入れるまで今のプランのまま。両方の条件で同じに保つ）。
 * 状態と送信は navi/usePlanRefine.ts、プランの足し外しは navi/useDiagnose.ts。
 */
export default function PlanAi() {
  const flags = useFlags()
  const { working } = useDiagnose()
  if (flags.assistant !== 'on' || working === null) return <Navigate to={DIAGNOSE_HREF} replace />
  return <AiPane plan={working} />
}

function AiPane({ plan }: { plan: WorkingPlan }) {
  const { session, send, cancel } = usePlanRefine()
  const [draft, setDraft] = useState('')
  const titleId = useId()
  const inputId = useId()
  const noteId = useId()
  const waiting = session?.status === 'waiting'
  return (
    <section className="ai" data-role="ai" aria-labelledby={titleId}>
      <BackLink entry={ROOT} />
      <h1 className="pl-title" id={titleId}>
        AIに直しを頼む
      </h1>
      <form
        className="ai-form"
        onSubmit={(e) => {
          e.preventDefault()
          const text = draft.trim()
          if (text === '') return
          if (send(text) !== null) setDraft('')
        }}
      >
        <label className="vh" htmlFor={inputId}>
          プランをどう変えたいか
        </label>
        <textarea
          className="ai-box"
          id={inputId}
          value={draft}
          placeholder="例：月曜を空けたい"
          aria-describedby={noteId}
          disabled={waiting}
          onChange={(e) => setDraft(e.target.value)}
        />
        <p className="ai-note" id={noteId}>
          入力した文とプランは外部のAIサービスに送られます。名前や学籍番号は書かないでください。
        </p>
        <button className="pl-line" type="submit" disabled={waiting || draft.trim() === ''}>
          送る
        </button>
      </form>
      {session !== null && <Result session={session} plan={plan} onResend={() => send(session.request, { retry: true })} onClose={cancel} />}
    </section>
  )
}

interface ResultProps {
  session: RefineSession
  plan: WorkingPlan
  onResend: () => void
  onClose: () => void
}

function Result({ session, plan, onResend, onClose }: ResultProps) {
  const waiting = session.status === 'waiting'
  const seconds = useElapsedSeconds(session.startedAt, waiting)
  if (waiting) {
    return (
      <div className="ai-wait">
        <p role="status">「{session.request}」で直しています。ふだん30秒〜1分半。ほかの画面に移っても続きます。</p>
        <p className="ai-wait-row">
          <span className="clock">
            経過 <span aria-hidden="true">{formatClock(seconds)}</span>
          </span>
          <button className="pl-tbtn" type="button" onClick={onClose}>
            やめる
          </button>
        </p>
      </div>
    )
  }
  if (session.status !== 'done' || session.result === null) {
    const text =
      session.status === 'timeout'
        ? '時間がかかりすぎて止まりました。もう一度送れます。'
        : session.status === 'empty'
          ? '頼みに合う科目は見つかりませんでした。'
          : '回答を作れませんでした（サーバーにつながりません）。プランはこのまま使えます。'
    return (
      <div className="ai-msg">
        <p className="ai-msg-line" role="status">
          <Icon name="warn" small />
          <span>{text}</span>
        </p>
        <p className="ai-acts">
          {session.status !== 'empty' && (
            <button className="pl-tbtn" type="button" onClick={onResend}>
              もう一度送る
            </button>
          )}
          <button className="pl-tbtn" type="button" onClick={onClose}>
            閉じる
          </button>
        </p>
      </div>
    )
  }
  return <Proposal key={session.localId} session={session} plan={plan} onClose={onClose} />
}

interface ProposalRow {
  code: string
  title: string
  reason: string
  /** add・remove は AI の案、source は案が無いとき（plan_context を知らないサーバー）の出典の科目で「入れる」の候補 */
  kind: 'add' | 'remove' | 'source'
}

const rowKey = (r: ProposalRow) => `${r.kind}:${r.code}`

/** 案の「入れる」科目の詳細（学期・曜限・単位）。読めなければ 'failed' */
function useAddedCourses(codes: string[]): ReadonlyMap<string, CourseMapping | 'failed'> {
  const { loadCourse } = useNaviData()
  const key = codes.join(',')
  const [got, setGot] = useState<ReadonlyMap<string, CourseMapping | 'failed'>>(() => new Map())
  useEffect(() => {
    if (key === '') return
    const control = new AbortController()
    for (const code of key.split(',')) {
      loadCourse(code, control.signal)
        .then((m) => setGot((prev) => new Map(prev).set(code, m)))
        .catch((err: unknown) => {
          if (control.signal.aborted) return
          console.error('案の科目の詳細を読めませんでした', err)
          setGot((prev) => new Map(prev).set(code, 'failed'))
        })
    }
    return () => control.abort()
  }, [key, loadCourse])
  return got
}

interface ProposalProps {
  session: RefineSession
  plan: WorkingPlan
  onClose: () => void
}

function Proposal({ session, plan, onClose }: ProposalProps) {
  const { dept, placement, announce } = useNavi()
  const { addToPlan, removeFromPlan } = useDiagnose()
  const { log } = useResearchLog()
  const view = useLedger(plan)
  const location = useLocation()
  const navigate = useNavigate()
  const listId = useId()
  const result = session.result
  const suggestions = session.suggestions
  const nameOf = (code: string, title: string | null) => title ?? findPlanCourse(plan, code)?.course.name ?? code

  // 案があればそれを、無ければ出典の科目を出す。もうプランに入れた（外した）行は出さない
  const all: ProposalRow[] =
    suggestions !== null
      ? [
          ...suggestions.remove.map((s): ProposalRow => ({ code: s.syllabus_id, title: nameOf(s.syllabus_id, s.title), reason: s.reason, kind: 'remove' })),
          ...suggestions.add.map((s): ProposalRow => ({ code: s.syllabus_id, title: nameOf(s.syllabus_id, s.title), reason: s.reason, kind: 'add' })),
        ]
      : (result?.sources ?? []).map((s): ProposalRow => ({ code: s.code, title: s.title, reason: '', kind: 'source' }))
  const rows = all.filter((r) => (r.kind === 'remove' ? inPlan(plan, r.code) : !inPlan(plan, r.code)))
  const [picked, setPicked] = useState<ReadonlySet<string>>(() => new Set(all.filter((r) => r.kind !== 'source').map(rowKey)))
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const chosen = rows.filter((r) => picked.has(rowKey(r)))
  const addCodes = rows.filter((r) => r.kind !== 'remove').map((r) => r.code)
  const added = useAddedCourses(addCodes)
  const loading = chosen.some((r) => r.kind !== 'remove' && !added.has(r.code))

  // 案を入れた場合の単位・重なり・要確認の数（右の列と同じ判定）。入れる前の今のプランと比べる
  const effects = (() => {
    let after = plan
    for (const r of chosen) {
      if (r.kind === 'remove') {
        after = removeCourseFromPlan(after, r.code)
        continue
      }
      const m = added.get(r.code)
      if (m !== undefined && m !== 'failed' && m.ok) after = addCourseToPlan(after, m.course, 'refine')
    }
    const afterStatus = buildStatus(statusCoursesFromPlan(dept, after, placement.lookup))
    const terms = ledgerTerms(
      [...view.terms, ...after.terms.map((t) => ({ year: t.year, half: t.term }))],
      afterStatus,
    )
    return proposalEffects(view.status, afterStatus, terms, view.checkTerm)
  })()

  const paragraphs = (result?.answer ?? '').split(/\n{2,}/).filter((p) => p.trim() !== '')
  const dropped = suggestions?.dropped.length ?? 0

  const toggle = (r: ProposalRow) => {
    setMessage(null)
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(rowKey(r))) next.delete(rowKey(r))
      else next.add(rowKey(r))
      return next
    })
  }

  /** 案を採った・採らなかったの判断（plan_refine_decide を1件。示した行のうち選んだ行と選ばなかった行） */
  const decide = (action: 'apply' | 'cancel') => {
    const line = (r: ProposalRow): EventPayload => ({ kind: r.kind, syllabus_id: r.code })
    const taken = action === 'apply' ? chosen : []
    log('plan_refine_decide', {
      refine_local_id: session.localId,
      action,
      shown: rows.map(line),
      accepted: taken.map(line),
      rejected: rows.filter((r) => !taken.includes(r)).map(line),
      dropped: suggestions?.dropped.length ?? 0,
      delivery: session.delivery,
    })
  }

  const apply = async () => {
    setBusy(true)
    setMessage(null)
    decide('apply')
    const detail = (r: ProposalRow): EventPayload => ({ suggestion: r.kind, refine_local_id: session.localId })
    for (const r of chosen.filter((x) => x.kind === 'remove')) removeFromPlan(r.code, 'refine', detail(r))
    const results = await Promise.all(chosen.filter((x) => x.kind !== 'remove').map((r) => addToPlan(r.code, 'refine', detail(r))))
    setBusy(false)
    const failed = results.filter((x) => x === 'failed' || x === 'unmapped').length
    if (failed > 0) {
      setMessage(`${failed}科目は入れられませんでした（学年か学期が読めないか、詳細を読めない科目です）。ほかは入れました。`)
      return
    }
    announce('案をプランに入れました。')
    if (location.key !== 'default') navigate(-1)
    else navigate(DIAGNOSE_HREF, { replace: true })
  }

  const close = () => {
    if (rows.length > 0) decide('cancel')
    onClose()
    if (location.key !== 'default') navigate(-1)
    else navigate(DIAGNOSE_HREF, { replace: true })
  }

  const slotsOf = (r: ProposalRow): string => {
    if (r.kind === 'remove') return findPlanCourse(plan, r.code)?.course.slots.join('・') || 'なし'
    const m = added.get(r.code)
    if (m !== undefined && m !== 'failed' && m.ok) return m.course.slots.join('・') || 'なし'
    return resolveCourse(dept, r.code, placement)?.slots.join('・') ?? ''
  }
  const creditsOf = (r: ProposalRow): number | null => {
    if (r.kind === 'remove') return findPlanCourse(plan, r.code)?.course.credits ?? null
    const m = added.get(r.code)
    return m !== undefined && m !== 'failed' && m.ok ? m.course.credits : null
  }

  return (
    <section className="ai-prop" aria-labelledby={`${listId}-h`}>
      <h2 className="pl-label" id={`${listId}-h`}>
        案
      </h2>
      <p className="ai-req">「{session.request}」</p>
      {session.delivery === 'not_supported' && (
        <p className="ai-msg-line">
          <Icon name="warn" small />
          <span>プランはAIに届いていません。回答はプランを見ずに作られています。</span>
        </p>
      )}
      {rows.length === 0 ? (
        <p className="ai-note">{all.length === 0 ? '外す・入れる科目の案はありませんでした。' : 'この案はプランに入れてあります。'}</p>
      ) : (
        <ul className="ai-diff" id={listId}>
          {rows.map((r, i) => {
            const id = `${listId}-${i}`
            const href = courseHref(r.code, { kind: 'refine' })
            const credits = creditsOf(r)
            return (
              <li key={rowKey(r)} className={r.kind === 'remove' ? 'is-out' : undefined}>
                <input type="checkbox" id={id} checked={picked.has(rowKey(r))} disabled={busy} onChange={() => toggle(r)} />
                <label className={r.kind === 'remove' ? 'ai-op' : 'ai-op is-add'} htmlFor={id}>
                  {r.kind === 'remove' ? '外す' : '入れる'}
                  <span className="vh">: {r.title}</span>
                </label>
                <span className="ai-slot">{slotsOf(r)}</span>
                <span className="ai-body">
                  <Link
                    className="ai-name"
                    to={href}
                    state={{ trail: [ROOT, { label: 'AIに直しを頼む', href: DIAGNOSE_AI_HREF }, { label: r.title, href }], tab: 'search' }}
                    onClick={() => {
                      log('result_click', { syllabus_id: r.code, rank: i + 1, list: 'refine', refine_local_id: session.localId })
                      log('citation_click', { syllabus_id: r.code, rank: i + 1, refine_local_id: session.localId })
                    }}
                  >
                    {r.title}
                  </Link>
                  <span className="ai-meta">
                    {credits !== null && `${credits}単位`}
                    {credits !== null && r.reason !== '' && '　'}
                    {r.reason}
                  </span>
                </span>
              </li>
            )
          })}
        </ul>
      )}
      {rows.length > 0 && (
        <div className="ai-effect" aria-live="polite">
          {chosen.length === 0 ? (
            <p>選んだ行はありません。</p>
          ) : loading ? (
            <p>入れる科目を読んでいます。</p>
          ) : effects.length === 0 ? (
            <p>単位と重なりは変わりません。</p>
          ) : (
            effects.map((e) => <p key={e.text}>{e.text}</p>)
          )}
        </div>
      )}
      <p className="ai-src">AIの判断です。間違うことがあります。</p>
      {dropped > 0 && <p className="ai-src">確かめられなかった案が{dropped}件あり、出していません。</p>}
      {message !== null && (
        <p className="ai-msg-line" role="alert">
          <Icon name="warn" small />
          <span>{message}</span>
        </p>
      )}
      <p className="ai-acts">
        {rows.length > 0 && (
          <button className="pl-primary" type="button" disabled={busy || chosen.length === 0} onClick={() => void apply()}>
            この案にする
          </button>
        )}
        <button className="pl-tbtn" type="button" onClick={close}>
          やめる
        </button>
      </p>
      {paragraphs.length > 0 && (
        <div className="accs ai-answer">
          <Accordion label="AIの説明" hint="">
            <div className="ai-text">
              {paragraphs.map((p, i) => (
                <p key={i}>{p}</p>
              ))}
            </div>
          </Accordion>
        </div>
      )}
    </section>
  )
}
