import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import '../../navi/plan.css'
import { atPlanTerm, findPlanCourse, planTermLabel } from '../../navi/diagnose'
import { sequenceOf } from '../../navi/graph'
import { useResearchLog, useSyllabusViewLog } from '../../navi/research'
import { courseHref, useNavi } from '../../navi/state'
import type { Origin, PaneState, TrailEntry } from '../../navi/state'
import { courseTermLabel, slotLong } from '../../navi/timetable'
import type { Course } from '../../navi/types'
import { useDiagnose } from '../../navi/useDiagnose'
import { useFlags } from '../../navi/variant'
import { clashText, detailWhy, isOtherTerm, leadText } from '../../navi/views'
import type { DetailWhy, ListContext } from '../../navi/views'
import Accordion from './Accordion'
import BackLink from './BackLink'
import Icon from './Icon'

/** 取る順は、前と後に3つずつまで出し、残りは「ほか N 科目」で開く */
const ORDER_SHOWN = 3
/** 授業でやることを3行で畳むのは、この字数より長いときだけ（狭い列の3行ほど） */
const LEARN_CLAMP_CHARS = 80

interface PlanCourseBodyProps {
  course: Course
  origin: Origin
  /** 詳細を開いた記録（syllabus_open）の from */
  from: string
  /** 作る場所の上の戻る先 */
  back: TrailEntry
}

/**
 * 診断の変種の科目の詳細（デザインのコンペの U-a。作る場所に出す）。シラバスの写しは減らし、プランの中でのその科目
 * （空きか・重なるか・入っているか・なぜ・取る順）を出す。授業でやることは3行で畳み、授業計画・教科書・区分は出さない
 * （原文へのリンクで読む）。成績のつけ方は畳んで残す（審査 J2 の指摘: スマホだけの人が原文へ移る手間）。
 * 時間割のマスの輪と破線は、確かめる場所（PlanLayout）が出す。
 */
export default function PlanCourseBody({ course, origin, from, back }: PlanCourseBodyProps) {
  const { dept, ask, track, shortlist, placement, focusTerm, assumedTerm, isKept, toggleKeep } = useNavi()
  const { working } = useDiagnose()
  const flags = useFlags()
  const { log } = useResearchLog()
  const titleId = useId()
  const learnId = useId()
  const [learnOpen, setLearnOpen] = useState(false)
  const [orderOpen, setOrderOpen] = useState(false)
  useSyllabusViewLog(course.code, from)

  const ctx: ListContext = { dept, shortlist, focusTerm, assumedTerm, flags, placement }
  const placed = isKept(course.code)
  const entry = working === null ? undefined : findPlanCourse(working, course.code)
  // 重なりと空きは、プランに入っていればプランの学年と学期で見る（詳細の学年は「１〜４年次」の最初の学年のため）
  const at = working === null ? course : atPlanTerm(working, course)
  const clash = course.slots.length > 0 ? clashText(ctx, at) : null
  const fit = clash ?? (placed || course.slots.length === 0 ? '' : `${isOtherTerm(at, focusTerm) ? `${courseTermLabel(at)}は` : ''}空き`)
  const lead = leadText(course)
  const clampable = !lead.missing && lead.text.length > LEARN_CLAMP_CHARS
  const why = planWhy(entry?.course, detailWhy(ctx, course, origin, ask))
  const showWhy = flags.graph === 'on' || why.ai
  const seq = sequenceOf(dept, course)
  const here = courseHref(course.code, origin)
  const step = (label: string, href: string): PaneState => ({ trail: [{ label: course.name, href: here }, { label, href }], tab: 'search' })
  const traverse = (to: Course, direction: 'before' | 'after') => {
    track({ type: 'traverse' })
    log('sequence_click', { from_syllabus_id: course.code, to_syllabus_id: to.code, direction })
  }
  const before = orderOpen ? seq.before : seq.before.slice(0, ORDER_SHOWN)
  const after = orderOpen ? seq.after : seq.after.slice(0, ORDER_SHOWN)
  const rest = seq.before.length + seq.after.length - before.length - after.length

  return (
    <article className="pd" data-role="detail" aria-labelledby={titleId}>
      <BackLink entry={back} />
      <h1 className="pl-title" id={titleId}>
        {course.name}
        {course.faculty !== null && <span className="pd-fac"> {course.faculty}</span>}
      </h1>
      <dl className="pd-facts">
        <dt>曜限</dt>
        <dd>
          {slotLong(course)}
          {fit !== '' && <span className={clash !== null ? 'pd-note is-clash' : 'pd-note'}>{fit}</span>}
        </dd>
        <dt>単位</dt>
        <dd>{course.credits ?? <span className="pd-note">記載なし</span>}</dd>
        <dt>対象</dt>
        <dd>
          {course.yearRange ?? `${course.year}年`} {course.term === '通年' ? '通年' : `${course.term}学期`}
        </dd>
        <dt>担当</dt>
        <dd>
          {course.teacher.status === 'known' ? (
            course.teacher.name
          ) : (
            <span className="pd-note">{course.teacher.status === 'notInSyllabus' ? 'シラバスに記載なし' : '準備中'}</span>
          )}
        </dd>
      </dl>
      {course.faculty !== null && <p className="pd-src">卒業の単位に数えられるかは、学部の決まりで変わります。</p>}

      {working !== null &&
        (placed ? (
          <div className="pd-in">
            <p className="pd-state">
              <Icon name="check" small />
              {entry === undefined ? 'プランに入っています' : `${planTermLabel(entry.term)}のプランに入っています`}
            </p>
            <button className="pl-line" type="button" onClick={() => toggleKeep(course.code, 'detail')}>
              プランから外す
            </button>
          </div>
        ) : (
          <div className="pd-in">
            <button className="pl-primary" type="button" onClick={() => toggleKeep(course.code, 'detail')}>
              <Icon name="plus" small />
              プランに入れる
            </button>
          </div>
        ))}

      <section className="pd-sec">
        <h2 className="pl-label">授業でやること</h2>
        <p id={learnId} className={lead.missing ? 'pd-learn is-missing' : clampable && !learnOpen ? 'pd-learn is-clamp' : 'pd-learn'}>
          {lead.text}
        </p>
        <div className="pd-links">
          {clampable && (
            <button className="pl-tbtn" type="button" aria-expanded={learnOpen} aria-controls={learnId} onClick={() => setLearnOpen((o) => !o)}>
              {learnOpen ? '閉じる' : '続きを読む'}
            </button>
          )}
          {course.syllabusUrl !== null && (
            <a
              className="pd-ext"
              href={course.syllabusUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => {
                track({ type: 'original' })
                log('original_open', { syllabus_id: course.code })
              }}
            >
              シラバスの原文
              <Icon name="ext" small />
              <span className="vh">（大学のサイトが新しいタブで開きます）</span>
            </a>
          )}
        </div>
        {!lead.missing && <p className="pd-src">{dept.syllabusYear}年度シラバスより</p>}
      </section>

      {showWhy && (
        <section className="pd-sec">
          <h2 className="pl-label">
            <Icon name="why" small />
            なぜ
          </h2>
          <p className="pd-text">{why.text}</p>
          <p className="pd-src">
            {why.source}
            {why.ai && ' 間違うことがあります。'}
          </p>
        </section>
      )}

      {flags.graph === 'on' && (
        <section className="pd-sec">
          <h2 className="pl-label">取る順</h2>
          {seq.before.length + seq.after.length === 0 ? (
            <p className="pd-text">前後の科目はありません。</p>
          ) : (
            <div className="pd-order">
              {before.length > 0 && <OrderList head="先に取る" list={before} fromCode={course.code} step={step} onTraverse={(c) => traverse(c, 'before')} />}
              {after.length > 0 && <OrderList head="あとに続く" list={after} fromCode={course.code} step={step} onTraverse={(c) => traverse(c, 'after')} />}
              {(rest > 0 || orderOpen) && (
                <button className="pl-tbtn" type="button" aria-expanded={orderOpen} onClick={() => setOrderOpen((o) => !o)}>
                  {orderOpen ? '閉じる' : `ほか${rest}科目`}
                </button>
              )}
            </div>
          )}
          <p className="pd-src">まとまりどうしの線です。直接の前提とは限りません。</p>
        </section>
      )}

      <div className="accs pd-accs">
        <Accordion label="成績のつけ方" hint={course.grading === null ? '記載なし' : ''}>
          <p className="pd-text">{course.grading ?? 'シラバスに書かれていません。'}</p>
        </Accordion>
      </div>
    </article>
  )
}

/** プランに入っている科目の「なぜ」。診断の理由はその文、AI の案と自分で足した科目は、その旨と系統図の事実 */
function planWhy(entry: { origin: string; reasons: { text: string }[] } | undefined, fallback: DetailWhy): DetailWhy {
  if (entry === undefined) return fallback
  if (entry.origin === 'diagnose' && entry.reasons.length > 0) {
    return { text: entry.reasons.map((r) => r.text).join('。'), source: '診断の答えから', ai: false }
  }
  if (entry.origin === 'refine') return { ...fallback, text: `AIの案で入れた科目です。${fallback.text}` }
  if (entry.origin === 'user') return { ...fallback, text: `自分で入れた科目です。${fallback.text}` }
  return fallback
}

interface OrderListProps {
  head: string
  list: Course[]
  /** いま見ている科目（たどった先の「なぜ」に使う） */
  fromCode: string
  step: (label: string, href: string) => PaneState
  onTraverse: (c: Course) => void
}

function OrderList({ head, list, fromCode, step, onTraverse }: OrderListProps) {
  return (
    <>
      <h3 className="pd-order-h">{head}</h3>
      <ul>
        {list.map((c) => {
          const href = courseHref(c.code, { kind: 'course', code: fromCode })
          return (
            <li key={c.code}>
              <Link to={href} state={step(c.name, href)} onClick={() => onTraverse(c)}>
                <span>{c.name}</span>
                <span className="pd-yr">{courseTermLabel(c)}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </>
  )
}
