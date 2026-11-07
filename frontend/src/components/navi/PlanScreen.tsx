import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import '../../navi/plan.css'
import { findPlanCourse, inPlan, planCodes } from '../../navi/diagnose'
import type { WorkingCourse, WorkingPlan } from '../../navi/diagnose'
import { courseIndex } from '../../navi/graph'
import { slotOrder } from '../../navi/ledger'
import { useResearchLog } from '../../navi/research'
import { courseHref, DIAGNOSE_AI_HREF, DIAGNOSE_HREF, useNavi } from '../../navi/state'
import type { Origin } from '../../navi/state'
import type { StatusCourse } from '../../navi/status'
import { clashesOf, inTerm, resolveCourse, sameTerm, shortName, slotShort } from '../../navi/timetable'
import { useDiagnose } from '../../navi/useDiagnose'
import { useLedger } from '../../navi/useLedger'
import { usePlanRefine } from '../../navi/usePlanRefine'
import { useFlags } from '../../navi/variant'
import Icon from './Icon'

const ORIGIN: Origin = { kind: 'plan' }
const ROOT = { label: 'プラン', href: DIAGNOSE_HREF }
/** 入れられる科目は最初に3つだけ出し、残りは「ほかに N 科目」で開く */
const CANDIDATES_SHOWN = 3

interface RowData {
  code: string
  name: string
  slots: string[]
  credits: number | null
  /** 通年の科目（春と秋の両方に出る） */
  yearLong: boolean
  /** 重なる科目の略称 */
  clash: string[]
  why: string | null
}

/** 行の「なぜ」。診断の理由の1つ目、AI が入れた科目と自分で足した科目は、その旨だけ */
function whyOf(entry: WorkingCourse | undefined): string | null {
  if (entry === undefined) return null
  if (entry.origin === 'refine') return 'AIの案'
  if (entry.origin === 'user') return '自分で追加'
  return entry.reasons[0]?.text ?? null
}

/**
 * プランの画面（デザインのコンペの U-a に、U-b の「行ごとの外す・候補の入れる」を取り込んだもの）。
 * 見ている学期（右の列かスマホの帯で切り替える）の科目を、曜限の順に1行ずつ出す。行は曜限・単位・科目名・重なり・なぜの1つだけ。
 * 押すと詳細、［外す］でプランから外す。下に、その学期の系統図の科目でプランに無いものを［入れる］つきで出す。
 * 旗 assistant=on のときだけ「AIに直しを頼む」の行を足す（AI の欄はその先の画面）。
 */
export default function PlanScreen({ plan }: { plan: WorkingPlan }) {
  const { dept, placement, toggleKeep } = useNavi()
  const { retake } = useDiagnose()
  const { session } = usePlanRefine()
  const flags = useFlags()
  const { log } = useResearchLog()
  const view = useLedger(plan)
  const term = view.term
  const here = view.here.status
  const overlaps = here.terms[0]?.overlaps ?? []
  const codes = planCodes(plan)
  const rankOf = new Map(codes.map((code, i) => [code, i + 1]))

  const shortOf = (code: string): string => {
    const c = resolveCourse(dept, code, placement)
    return c === undefined ? (here.courses.find((x) => x.code === code)?.name ?? code) : shortName(c)
  }
  const slotsOf = (code: string, slots: string[] | null): string[] => {
    const c = resolveCourse(dept, code, placement)
    if (c !== undefined) return slotShort(c)
    return slots !== null && slots.length > 0 ? slots : ['なし']
  }

  const rows: RowData[] = [...here.courses]
    .sort((a, b) => slotOrder(a.slots) - slotOrder(b.slots))
    .map((c: StatusCourse) => {
      const others = overlaps.filter((o) => o.codes.includes(c.code)).flatMap((o) => o.codes.filter((x) => x !== c.code))
      return {
        code: c.code,
        name: c.name,
        slots: slotsOf(c.code, c.slots),
        credits: c.credits,
        yearLong: resolveCourse(dept, c.code, placement)?.term === '通年',
        clash: [...new Set(others)].map(shortOf),
        why: whyOf(findPlanCourse(plan, c.code)?.course),
      }
    })

  const candidates = dept.courses
    .filter((c) => inTerm(c, term) && !inPlan(plan, c.code))
    .map((c) => ({ course: c, clash: clashesOf(dept, codes, c, placement).filter((x) => sameTerm(x.term, term)) }))
    .sort((a, b) => Number(a.clash.length > 0) - Number(b.clash.length > 0) || courseIndex(dept, a.course.code) - courseIndex(dept, b.course.code))
    .map(({ course, clash }): RowData => ({
      code: course.code,
      name: course.name,
      slots: slotShort(course),
      credits: course.credits,
      yearLong: course.term === '通年',
      clash: [...new Set(clash.map((x) => shortName(x.other)))],
      why: null,
    }))

  return (
    <div className="pl-plan">
      <h1 className="vh">プラン</h1>
      <div className="pl-head">
        <p className="pl-count">{rows.length}科目</p>
        <button className="pl-tbtn" type="button" onClick={retake}>
          答え直す
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="pl-empty">この学期の科目はありません。</p>
      ) : (
        <ul className="pl-rows">
          {rows.map((r) => (
            <PlanRow
              key={r.code}
              row={r}
              inPlan
              onOpen={() => log('result_click', { syllabus_id: r.code, rank: rankOf.get(r.code) ?? null, list: 'plan' })}
              onAct={() => toggleKeep(r.code, 'plan')}
            />
          ))}
        </ul>
      )}
      {flags.assistant === 'on' && (
        <Link className="pl-ask" to={DIAGNOSE_AI_HREF}>
          <span>AIに直しを頼む</span>
          {session?.status === 'waiting' && <span className="pl-ask-hint">待っています</span>}
          <Icon name="next" small />
        </Link>
      )}
      <Candidates rows={candidates} onAct={(code) => toggleKeep(code, 'plan')} />
    </div>
  )
}

interface PlanRowProps {
  row: RowData
  /** プランに入っている行（［外す］）か、入れられる科目の行（［入れる］） */
  inPlan: boolean
  onOpen: () => void
  onAct: () => void
}

function PlanRow({ row, inPlan: placed, onOpen, onAct }: PlanRowProps) {
  const href = courseHref(row.code, ORIGIN)
  return (
    <li className={placed ? 'pr' : 'pr is-cand'} data-role={placed ? 'plan-row' : undefined}>
      <Link className="pr-link" to={href} state={{ trail: [ROOT, { label: row.name, href }], tab: 'search' }} onClick={onOpen}>
        <span className="pr-slot">
          {row.slots.map((s) => (
            <span key={s} className={row.clash.length > 0 ? 'pr-time is-clash' : 'pr-time'}>
              {s}
            </span>
          ))}
          <span className="pr-cr">
            {row.credits !== null ? (
              `${row.credits}単位`
            ) : (
              <>
                <span className="vh">単位は</span>
                記載
                <wbr />
                なし
              </>
            )}
          </span>
          {row.yearLong && <span className="pr-cr">通年</span>}
        </span>
        <span className="pr-body">
          <span className="pr-name">{row.name}</span>
          {row.clash.length > 0 && (
            <span className="pr-clash">
              <Icon name="warn" small />
              <span>{row.clash.join('、')}と重なる</span>
            </span>
          )}
          {row.why !== null && <span className="pr-why">{row.why}</span>}
        </span>
      </Link>
      <button
        className="pr-act"
        type="button"
        aria-label={placed ? `${row.name}をプランから外す` : `${row.name}をプランに入れる`}
        onClick={onAct}
      >
        {placed ? '外す' : '入れる'}
      </button>
    </li>
  )
}

interface CandidatesProps {
  rows: RowData[]
  onAct: (code: string) => void
}

/** その学期の系統図の科目でプランに無いもの（重ならない科目を先に、次に系統図の記載順） */
function Candidates({ rows, onAct }: CandidatesProps) {
  const { log } = useResearchLog()
  const [open, setOpen] = useState(false)
  const moreId = useId()
  const headingId = useId()
  if (rows.length === 0) return null
  const shown = open ? rows : rows.slice(0, CANDIDATES_SHOWN)
  const rest = rows.length - CANDIDATES_SHOWN
  return (
    <section className="pl-cands" aria-labelledby={headingId}>
      <h2 className="pl-label" id={headingId}>
        入れられる科目
      </h2>
      <ul className="pl-rows" id={moreId}>
        {shown.map((r, i) => (
          <PlanRow
            key={r.code}
            row={r}
            inPlan={false}
            onOpen={() => log('result_click', { syllabus_id: r.code, rank: i + 1, list: 'plan', candidate: true })}
            onAct={() => onAct(r.code)}
          />
        ))}
      </ul>
      {rest > 0 && (
        <button className="pl-more" type="button" aria-expanded={open} aria-controls={moreId} onClick={() => setOpen((o) => !o)}>
          <span>{open ? '閉じる' : `ほかに${rest}科目`}</span>
          <Icon name="down" small />
        </button>
      )}
    </section>
  )
}
