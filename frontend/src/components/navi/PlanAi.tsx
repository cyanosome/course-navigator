import { useEffect, useId, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import '../../navi/plan.css'
import type { EventPayload, PlanSuggestion, PlanSuggestions } from '../../navi/apiTypes'
import { useNaviData } from '../../navi/dataSource'
import { addCourseToPlan, findPlanCourse, inPlan, removeCourseFromPlan } from '../../navi/diagnose'
import type { PlanPlace, WorkingPlan } from '../../navi/diagnose'
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
  /** 外す行は外す科目、ほかは入れる科目（移す行は移す先のクラス） */
  code: string
  title: string
  reason: string
  /**
   * add・remove は AI の案、move は外す案と入れる案の組（同じ学期の同じ名前の別クラスへ移す。from のクラスから code のクラスへ）、
   * source は案が無いとき（plan_context を知らないサーバー）の出典の科目で「入れる」の候補
   */
  kind: 'add' | 'remove' | 'move' | 'source'
  /** move のときだけ、移す元（今のプランの科目）。ほかは null */
  from: string | null
  /** 入れる学年と学期（move は移す元の学期、add は案にあればそれ）。null なら科目の配当の学年と学期 */
  at: PlanPlace | null
}

const rowKey = (r: ProposalRow) => (r.kind === 'move' ? `move:${r.from}>${r.code}` : `${r.kind}:${r.code}`)

const OP_WORD: Record<ProposalRow['kind'], string> = { remove: '外す', add: '入れる', source: '入れる', move: '移す' }

/**
 * AI の案の行。外す案と入れる案のうち科目名が同じ組は「移す」の1行にまとめ、移す先は元の科目と同じ学年・学期に入れる
 * （backend は、プランの科目と同じ学期の同じ名前の別クラスを入れる案を、元の科目を外す案と組のときだけ残す）。
 * 元の科目がもうプランに無い（移し終えた）組はまとめない（外す行・入れる行とも「入れてある」として出さない）
 */
function suggestionRows(s: PlanSuggestions, plan: WorkingPlan): ProposalRow[] {
  const nameOf = (x: PlanSuggestion) => x.title ?? findPlanCourse(plan, x.syllabus_id)?.course.name ?? x.syllabus_id
  const paired = new Set<string>()
  const rows: ProposalRow[] = []
  for (const out of s.remove) {
    const hit = findPlanCourse(plan, out.syllabus_id)
    const to =
      hit === undefined
        ? undefined
        : s.add.find((a) => !paired.has(a.syllabus_id) && a.syllabus_id !== out.syllabus_id && nameOf(a) === nameOf(out))
    if (hit === undefined || to === undefined) {
      rows.push({ code: out.syllabus_id, title: nameOf(out), reason: out.reason, kind: 'remove', from: null, at: null })
      continue
    }
    paired.add(to.syllabus_id)
    const reason = [...new Set([out.reason, to.reason].filter((x) => x !== ''))].join('／')
    rows.push({
      code: to.syllabus_id,
      title: nameOf(to),
      reason,
      kind: 'move',
      from: out.syllabus_id,
      at: { year: hit.term.year, term: hit.term.term },
    })
  }
  for (const a of s.add) {
    if (paired.has(a.syllabus_id)) continue
    const at = a.year !== undefined && a.term !== undefined ? { year: a.year, term: a.term } : null
    rows.push({ code: a.syllabus_id, title: nameOf(a), reason: a.reason, kind: 'add', from: null, at })
  }
  return rows
}

/** まだ今のプランに入れていない案の行か（外す行は科目がプランにある、移す行は元がプランにあり移す先が無い、ほかは科目が無い） */
function pending(r: ProposalRow, plan: WorkingPlan): boolean {
  if (r.kind === 'remove') return inPlan(plan, r.code)
  if (r.from !== null && !inPlan(plan, r.from)) return false
  return !inPlan(plan, r.code)
}

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

  // 案があればそれを、無ければ出典の科目を出す。もうプランに入れた（外した）行は出さない
  const all: ProposalRow[] =
    suggestions !== null
      ? suggestionRows(suggestions, plan)
      : (result?.sources ?? []).map((s): ProposalRow => ({ code: s.code, title: s.title, reason: '', kind: 'source', from: null, at: null }))
  const rows = all.filter((r) => pending(r, plan))
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
      if (r.from !== null) after = removeCourseFromPlan(after, r.from)
      const m = added.get(r.code)
      if (m !== undefined && m !== 'failed' && m.ok) after = addCourseToPlan(after, m.course, 'refine', r.at ?? undefined)
    }
    const afterStatus = buildStatus(statusCoursesFromPlan(dept, after, placement.lookup))
    const terms = ledgerTerms(
      [...view.terms, ...after.terms.map((t) => ({ year: t.year, half: t.term }))],
      afterStatus,
    )
    return proposalEffects(view.status, afterStatus, terms, view.checkTerm)
  })()

  const paragraphs = (result?.answer ?? '').split(/\n{2,}/).filter((p) => p.trim() !== '')
  // 照合で落ちた案。系統図の科目を外す案（locked）だけ分けて出す
  const droppedAll = suggestions?.dropped ?? []
  const locked = droppedAll.filter((d) => d.reason === 'locked' && d.action === 'remove').length
  const dropped = droppedAll.length - locked

  const toggle = (r: ProposalRow) => {
    setMessage(null)
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(rowKey(r))) next.delete(rowKey(r))
      else next.add(rowKey(r))
      return next
    })
  }

  /**
   * 案を採った・採らなかったの判断（plan_refine_decide を1件。示した行のうち選んだ行と選ばなかった行）。
   * 移す行は組の両方を書く（moved_from: 外す元、moved_to: 入れる先。チェックの直し方の記録と同じ名前）
   */
  const decide = (action: 'apply' | 'cancel') => {
    const line = (r: ProposalRow): EventPayload =>
      r.kind === 'move' ? { kind: r.kind, moved_from: r.from, moved_to: r.code } : { kind: r.kind, syllabus_id: r.code }
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
    const detail = (r: ProposalRow): EventPayload =>
      r.kind === 'move'
        ? { suggestion: r.kind, refine_local_id: session.localId, moved_from: r.from, moved_to: r.code }
        : { suggestion: r.kind, refine_local_id: session.localId }
    for (const r of chosen.filter((x) => x.kind === 'remove')) removeFromPlan(r.code, 'refine', detail(r))
    // 移す行は、移す先を入れられてから元の科目を外す（入れられなければ元のクラスのまま。チェックの直し方と同じ）
    const results = await Promise.all(
      chosen
        .filter((x) => x.kind !== 'remove')
        .map(async (r) => {
          const got = await addToPlan(r.code, 'refine', detail(r), r.at ?? undefined)
          if (r.from !== null && (got === 'added' || got === 'already')) removeFromPlan(r.from, 'refine', detail(r))
          return got
        }),
    )
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

  const planSlots = (code: string): string => findPlanCourse(plan, code)?.course.slots.join('・') || 'なし'
  const addSlots = (code: string): string => {
    const m = added.get(code)
    if (m !== undefined && m !== 'failed' && m.ok) return m.course.slots.join('・') || 'なし'
    return resolveCourse(dept, code, placement)?.slots.join('・') ?? ''
  }
  const slotsOf = (r: ProposalRow): string => (r.kind === 'remove' ? planSlots(r.code) : addSlots(r.code))
  /** 移す行の曜限の変わり方「元の曜限 → 移す先の曜限」（移す先が読めるまでは元の曜限だけ） */
  const moveSlots = (from: string, code: string): string => {
    const to = addSlots(code)
    return to === '' ? planSlots(from) : `${planSlots(from)} → ${to}`
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
                  {OP_WORD[r.kind]}
                  <span className="vh">: {r.title}</span>
                </label>
                {/* 移す行の曜限は、狭い列で折り返さないよう科目名の下に「元 → 先」で出す（この列は空ける） */}
                <span className="ai-slot">{r.from === null ? slotsOf(r) : ''}</span>
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
                  {r.from !== null && <span className="ai-slot">{moveSlots(r.from, r.code)}</span>}
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
      {locked > 0 && <p className="ai-src">系統図の科目を外す案が{locked}件あり、出していません。</p>}
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
